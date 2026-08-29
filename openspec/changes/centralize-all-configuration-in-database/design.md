## Context

La persistencia actual usa un único esquema SQL compatible con SQLite/PostgreSQL para configuración funcional e histórico, descubierto mediante `DTC_DATABASE_URL`. API, MQTT, AEMET y varios límites operativos aún leen el entorno directamente; la API incluso necesita el token antes de abrir el almacén. El controlador, API y publicador MQTT son procesos separados que coordinan por base de datos, y el controlador ya conserva el plan en memoria ante una caída, pero no existe una réplica local duradera ni reconciliación.

La solución debe arrancar siempre en una Raspberry Pi con SQLite disponible, soportar PostgreSQL mediante `pg8000`, conservar el estado seguro de las salidas y mantener el comportamiento equivalente entre drivers. Véanse las cuatro specs de este cambio para el contrato observable.

## Goals / Non-Goals

**Goals:**

- Dar a todos los procesos una única ruta de resolución: bootstrap local → backend canónico → fallback local cuando corresponda.
- Separar ciclos de vida y migraciones de bootstrap, continuidad, configuración y aplicación.
- Hacer que el cambio de driver sea verificable, recuperable y sin estado canónico dividido.
- Permitir onboarding y administración completa desde la web sin una dependencia circular de autenticación.
- Clasificar exhaustivamente los valores actuales para que ningún ajuste runtime permanezca accidentalmente en entorno.
- Mantener la operación segura durante cortes y conservar los eventos esenciales hasta poder sincronizarlos.

**Non-Goals:**

- Alta disponibilidad multi-nodo, elección de líder o edición administrativa offline.
- Replicación general de PostgreSQL, copia local de todo el histórico o recuperación ante pérdida total del host local.
- Cifrado de secretos a nivel de aplicación sin una raíz externa; añadir SQLCipher, TPM, keyring o un secret manager sería otro cambio.
- Cambio automático de driver por fallo: fallback es un modo de continuidad, no una promoción canónica.
- Ejecutar migraciones destructivas sin operación administrativa explícita ni convertir el frontend en gestor de PostgreSQL.

## Decisions

### 1. Cuatro almacenes lógicos con materialización distinta por driver

Se define un directorio de estado de producción fijo y propiedad del usuario de servicio. El código recibe el directorio por inyección en tests, no por una variable runtime. Contendrá:

| Almacén lógico | SQLite | PostgreSQL activo | Contenido |
|---|---|---|---|
| Bootstrap | `bootstrap.db` | No aplica | Estado de onboarding, locator estructurado, digest de acceso local, lock/estado de migración y revisiones mínimas |
| Fallback | `fallback.db` | No aplica | Snapshot de continuidad, plan vigente, frescura, outbox y estado de reconciliación |
| Configuración | `configuration.db` | schema `dtc_config` | Toda configuración funcional/de sistema, secretos, revisiones y auditoría |
| Aplicación | `application.db` | schema `dtc_app` | Planes, forecasts, históricos, heartbeat, eventos de output, relay tests y demás runtime |

SQLite no tiene schemas equivalentes a PostgreSQL. Usar ficheros independientes preserva el aislamiento y permite backup/migración por dominio. Se descarta simular namespaces con prefijos en un único fichero porque mantendría acopladas las migraciones y ampliaría el daño de corrupción. También se descarta depender permanentemente de `ATTACH`: los repositorios deben operar con engines explícitos y no asumir transacciones atómicas entre ficheros.

Cada almacén tendrá su propia tabla de revisión de esquema y cadena de migraciones. Una capa `StorageContext` compondrá repositorios de configuración y aplicación y publicará un estado de topología inmutable por generación; al conmutar se construye una generación nueva y se retira la anterior después de vaciar operaciones activas.

### 2. Bootstrap mínimo como única raíz local de descubrimiento

Todos los entrypoints abren primero `bootstrap.db`; desaparece `resolve_location(environ)`. El locator guarda campos estructurados (`driver`, host, puerto, database, usuario, secreto, TLS y opciones permitidas), nunca una URL opaca. Para SQLite guarda la identidad de los ficheros canónicos, cuya ruta se deriva del directorio fijo y no es editable desde el frontend.

Bootstrap es una excepción necesaria a «todo reside en PostgreSQL»: cuando PostgreSQL es canónico conserva una copia mínima de sus datos de conexión porque sin ella no puede descubrirse. La configuración completa y su copia canónica de esos campos viven en `dtc_config`; cada cambio confirmado actualiza primero el backend canónico y después el locator local mediante un protocolo versionado. Si falla la segunda fase, se conserva el locator anterior y se reporta `restart_pending` en vez de dejar un locator parcialmente escrito.

Se descarta guardar solo un puntero a una URL en un fichero porque reintroduce el problema original, y guardar el locator únicamente en PostgreSQL porque es circular.

### 3. Onboarding con credencial local de un solo uso

Al crear bootstrap se genera un secreto aleatorio de alta entropía, se guarda solo su digest con expiración/contador de intentos y se imprime una única vez en consola/journal de la operación de instalación. En estado `unconfigured`, la API escucha con defaults compilados conservadores y solo expone health, estado de onboarding y finalización autenticada. La finalización crea el digest del token administrativo en configuración y fallback, invalida el bootstrap token y cambia el estado atómicamente.

El token administrativo se almacena únicamente como digest. Los secretos que deben recuperarse para conectar (PostgreSQL, MQTT, AEMET) se guardan reversiblemente en columnas marcadas como secretas; la capa de DTO y logging aplica deny-by-default. El fichero SQLite y sus backups usan permisos `0600`, el directorio `0700` y PostgreSQL usa roles con acceso limitado a ambos schemas.

Se descarta onboarding anónimo limitado a loopback: detrás de nginx no es fiable inferir el cliente real y un error de proxy podría abrir el sistema. También se descarta almacenar cifrado de campo con una clave en la misma base de datos porque añade complejidad sin mejorar el modelo de amenaza.

### 4. Catálogo tipado, snapshots completos y revisiones

La configuración de sistema se modelará por dominios tipados, no como pares clave/valor sin esquema: API/security, database, MQTT, weather credentials, output, logging y operations. Los campos escalares con evolución frecuente pueden almacenarse como un documento JSON versionado por dominio, pero cada snapshot se valida contra modelos estrictos antes de persistir. La configuración funcional existente de instalación/acumuladores conserva su modelo relacional.

Una tabla raíz `system_configuration` mantiene revisión global, versión del formato y timestamps. Las actualizaciones construyen una configuración candidata completa, validan dependencias cruzadas y confirman snapshot, secretos/auditoría y revisión en una transacción del almacén de configuración. Cada campo declara política de activación (`hot`, `next_cycle`, `restart`) en un catálogo de servidor que también alimenta la API.

Se descarta reutilizar variables de entorno como override de emergencia: haría imposible conocer la configuración efectiva y rompería el requisito central. Las constantes no administrables —nombres de tablas, rutas productivas, timeouts defensivos máximos— permanecen en código; los flags que solicitan una acción puntual no sustituyen valores persistentes.

### 5. Routing normal/fallback con política explícita por operación

El router clasifica operaciones:

- Lecturas/configuración administrativa: solo backend canónico; durante fallback se permite una vista sanitizada de la snapshot, marcada como stale.
- Escrituras administrativas: solo canónico y rechazadas en fallback.
- Lecturas de control: canónico en normal, snapshot local en fallback.
- Escrituras runtime esenciales: canónico en normal; outbox local cuando el remoto falla o durante migración.
- Históricos no esenciales: best-effort según la política de retención, pero cualquier evento necesario para reconstruir outputs/planes entra en outbox.

El paso a fallback exige un error clasificado como indisponibilidad, no errores de validación o versión. Usa la última snapshot confirmada y comprueba revisión, checksum, ventana del plan y antigüedad máxima. Sin evidencia segura, el controller fuerza outputs apagados. Los demás procesos permanecen vivos y reportan degradación.

La snapshot se escribe en una transacción SQLite y lleva checksum del payload, revisión canónica y timestamps. No se permite editarla. Se descarta intentar merges bidireccionales porque no hay una autoridad fiable para resolver secretos, pines o límites eléctricos divergentes.

### 6. Outbox idempotente para reconciliar runtime

Cada evento offline recibe UUID, tipo, versión de payload, aggregate id, orden por aggregate, instante de origen, revisión de configuración y estado de entrega. Las tablas canónicas incorporan el UUID como clave idempotente o una tabla de deduplicación en `dtc_app`. El reconciliador toma lotes pequeños, respeta dependencias (plan antes de transiciones asociadas), confirma remotamente y marca localmente; el borrado físico se hace posteriormente por retención.

La recuperación sigue: validar schemas remotos → drenar outbox → recargar configuración → refrescar snapshot/plan → publicar heartbeat sano. Si cae a mitad, los ACKs remotos y UUIDs permiten continuar sin duplicar. Se usan backoff con jitter y límites persistidos, mientras los límites defensivos máximos permanecen en código.

Se descarta replicar todas las tablas de aplicación mediante SQL genérico: las diferencias SQLite/PostgreSQL y las relaciones harían frágil la reconciliación. La outbox contiene eventos de dominio versionados y adaptadores explícitos.

### 7. Cambio de driver como saga local, no transacción distribuida

Una migración adquiere un lock de bootstrap con lease y operation id. La API pasa a modo `migrating`: bloquea mutaciones, el controlador sigue el plan actual y envía nuevas escrituras a la outbox. Las fases persistidas son:

1. Preflight de driver, TLS, credenciales, permisos, espacio y versiones.
2. Creación/migración de `dtc_config` y `dtc_app` en staging lógico.
3. Snapshot consistente del origen y copia por lotes con IDs preservados.
4. Verificación de versiones, recuentos, relaciones, revisiones y checksums seleccionados.
5. Marcado del destino como preparado.
6. Compare-and-swap del locator de bootstrap.
7. Apertura de nueva generación, replay de outbox y verificación end-to-end.
8. Marcado del origen como retirado, sin borrarlo automáticamente.

Hasta la fase 6 el rollback consiste en abandonar el destino y seguir en el origen. Después de conmutar, un fallo de apertura revierte el locator con la versión anterior si todavía no hubo escrituras canónicas exclusivas; en caso contrario se queda en fallback y exige recuperación explícita para no perder datos. La misma saga soporta volver a SQLite, aunque la primera entrega priorizará SQLite → PostgreSQL.

Se descarta una transacción entre SQLite y PostgreSQL porque no existe una frontera atómica común. El locator local es el punto de commit y las fases persistidas hacen reanudable la operación.

### 8. API administrativa separada por secciones y operaciones

Se añadirán endpoints versionados para:

- estado/topología y catálogo de campos;
- onboarding;
- lectura y `PATCH` por sección con `expected_revision`;
- mutaciones write-only de secretos (`keep`, `replace`, `clear`);
- pruebas efímeras de PostgreSQL, MQTT y weather;
- creación y seguimiento de migraciones.

Las respuestas se construyen con DTOs explícitos. No se serializan modelos de persistencia. Los errores conservan las categorías actuales y añaden `degraded_mode`, `operation_in_progress` y `connection_test_failed`. Health público no incluye configuración. La auditoría registra nombres de campos y revisiones, nunca valores secretos.

La API no reinicia systemd. Los procesos sondean la revisión a una cadencia corta y aplican ajustes `hot`/`next_cycle`; para `restart`, registran su revisión aplicada y la UI muestra la diferencia. Host y puerto de la propia API son el caso de bootstrap operacional: la primera escucha usa defaults seguros; un cambio persistido se activa tras reinicio y el launcher consulta bootstrap/config antes de crear el servidor.

### 9. Frontend con onboarding y configuración de sistema

Se incorporan rutas públicas limitadas de onboarding y una ruta autenticada `/configuracion-sistema`, manteniendo `/configuracion` para instalación/acumuladores. Un servicio de estado de topología alimenta el banner global y deshabilita mutaciones en fallback/migrating.

Cada sección usa formularios tipados y carga independiente, pero guarda contra una revisión global para validar relaciones cruzadas. Los secretos no se rehidratan: el estado conserva solo `configured`, la acción elegida y el valor nuevo en memoria hasta completar/cancelar. La migración se presenta como una operación larga consultada periódicamente; salir de la vista no cancela la saga.

### 10. Migración del despliegue existente en dos pasos

Se añade una herramienta de transición explícita y de un solo uso que puede leer el fichero de entorno legado y la base indicada por `DTC_DATABASE_URL`, crear los cuatro almacenes, importar todos los valores conocidos, generar los campos ausentes y verificar el resultado. Esta lectura queda confinada al comando de migración y no se comparte con ningún entrypoint runtime.

El instalador nuevo crea directorio y bootstrap, imprime el token de onboarding e instala unidades sin `EnvironmentFile`. Los servicios no arrancan contra una instalación antigua hasta que el import haya terminado. Tras verificar el nuevo arranque se retira el fichero de entorno; la herramienta deja un informe sanitizado y no lo borra automáticamente.

## Risks / Trade-offs

- [Bootstrap contiene credenciales recuperables de PostgreSQL] → permisos mínimos, redacción centralizada, backups protegidos y documentación clara del modelo de amenaza; no duplicar otros secretos allí.
- [Guardar credenciales reversibles en DB amplía el impacto de una lectura de DB] → roles mínimos, TLS remoto, DTOs allow-list y pruebas de no fuga; no prometer cifrado sin raíz independiente.
- [Cuatro almacenes elevan complejidad de migración y diagnóstico] → revisiones independientes, `StorageContext`, estado de topología único y comandos de doctor que validen cada frontera.
- [Una caída durante el cambio de locator puede dejar intención ambigua] → compare-and-swap versionado, fases persistidas, destino preparado y origen conservado hasta verificación posterior.
- [La outbox puede crecer durante una caída larga] → límites y alertas por espacio, lotes/retención, prioridad a eventos esenciales y apagado seguro antes de agotar disco.
- [Un plan fallback puede ejecutar una intención ya modificada remotamente] → snapshot con revisión/frescura y ventana estricta; PostgreSQL inaccesible implica priorizar continuidad del plan confirmado, nunca recalcular con datos parciales.
- [Procesos separados pueden aplicar revisiones a distinta velocidad] → cada proceso publica revisión aplicada y la UI mantiene `pending_restart`/`pending_apply` hasta convergencia.
- [El import legado es una excepción temporal al principio “sin ficheros”] → binario/comando aislado, nunca invocado por runtime, cubierto por tests y documentado para retirarse tras el periodo de migración.

## Migration Plan

1. Introducir modelos/migraciones de bootstrap y fallback sin cambiar todavía la ruta runtime; añadir inventario automatizado de todas las lecturas de entorno.
2. Separar el esquema actual en configuración/aplicación y adaptar repositorios con compatibilidad temporal sobre SQLite.
3. Añadir el importador legado y ejecutar un dry-run que compare configuración, secretos presentes, recuentos e históricos sin mostrar valores.
4. Detener los tres procesos, importar a los cuatro almacenes y conservar intactos la base y el fichero de entorno anteriores.
5. Instalar unidades sin `EnvironmentFile`, arrancar API en modo onboarding o autenticado según import y verificar controller/MQTT/API, revisiones y snapshot fallback.
6. Habilitar UI/API de sistema y, opcionalmente, ejecutar la saga a PostgreSQL desde el backend SQLite ya migrado.
7. Simular caída y recuperación de PostgreSQL, verificar continuidad, outbox y deduplicación; después retirar el fichero de entorno legado.

Rollback antes de seleccionar el nuevo runtime: restaurar las unidades anteriores y reutilizar DB/fichero intactos. Rollback después de activar la nueva topología: detener procesos, seleccionar mediante el comando de recuperación el locator anterior verificado y reiniciar; nunca copiar datos hacia atrás implícitamente ni borrar el destino fallido.
