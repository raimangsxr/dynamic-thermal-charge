## Why

La aplicación todavía necesita un fichero de entorno para descubrir la base de datos y para configurar la API, MQTT, credenciales y parámetros operativos. Esto impide administrar el sistema íntegramente desde el frontend y deja el despliegue dividido entre la base de datos y ficheros externos, especialmente cuando se usa PostgreSQL remoto.

## What Changes

- **BREAKING**: eliminar la lectura de ficheros y variables de entorno de configuración en runtime, incluidos `DTC_DATABASE_URL`, credenciales de API/AEMET/MQTT, ajustes HTTP, MQTT, relés de prueba, logging y límites operativos; los argumentos puramente operativos de CLI y las constantes internas no pasan a ser configuración.
- Introducir un SQLite local obligatorio y de ubicación estable con dos almacenes lógicos: bootstrap, con lo imprescindible para iniciar y localizar el backend activo, y fallback, con una réplica mínima y una cola duradera para continuar durante una pérdida de conectividad.
- Separar en el driver activo —SQLite local o PostgreSQL remoto— la configuración de sistema de los datos de aplicación/runtime, con migraciones y repositorios independientes aunque SQLite materialice la separación mediante bases de datos locales en vez de namespaces SQL.
- Añadir un asistente de primera puesta en marcha que permita entrar al frontend, establecer la credencial administrativa y completar la configuración sin editar ficheros.
- Añadir una sección de «Configuración del sistema» para administrar base de datos, API, MQTT, proveedor meteorológico y sus secretos, driver de salida real/simulado, logging y parámetros de servicio; los secretos serán escribibles y rotables, pero nunca retornados en claro.
- Permitir cambiar de SQLite a PostgreSQL remoto mediante una operación validada que prepara el destino, copia configuración y datos de aplicación, verifica integridad y solo entonces conmuta el backend activo.
- Hacer que PostgreSQL sea la fuente canónica cuando se selecciona: el SQLite local conserva únicamente el locator de bootstrap, la réplica mínima de continuidad, metadatos de sincronización y escrituras pendientes, no una segunda configuración editable.
- Mantener el controlador funcionando durante cortes de red con la última configuración y plan seguros; acumular eventos runtime idempotentes en local y reconciliarlos al recuperar PostgreSQL, mientras las mutaciones administrativas quedan deshabilitadas en modo fallback para evitar conflictos.
- Actualizar API, CLI, unidades systemd, instalador, documentación y pruebas para el arranque sin fichero de configuración y para hacer visible el estado normal/degradado, la procedencia de los datos y la sincronización pendiente.

## Capabilities

### New Capabilities

- `database-resident-system-configuration`: Persistencia, validación, protección y consumo de toda la configuración y los secretos desde el almacén de configuración del driver activo.
- `resilient-storage-topology`: Bootstrap SQLite, separación de almacenes, selección/migración del driver, fallback local y reconciliación tras recuperar PostgreSQL.
- `system-configuration-api`: Contrato administrativo y de onboarding para consultar, validar y cambiar configuración del sistema y exponer el estado del backend sin revelar secretos.
- `system-configuration-ui`: Nueva experiencia frontend de primera configuración y administración del sistema, incluida la migración a PostgreSQL y la visualización del modo degradado.

### Modified Capabilities

_Ninguna: el repositorio todavía no contiene especificaciones principales OpenSpec; estas capacidades formalizan y sustituyen comportamientos descritos en especificaciones históricas fuera de `openspec/specs`._

## Impact

- Persistencia y migraciones: nuevos almacenes/modelos de bootstrap, fallback, configuración y aplicación; routing dinámico y sincronización offline.
- Backend: arranque, repositorios, API/security, MQTT, weather, controlador, logging, relay test, CLI y gestión del ciclo de vida de procesos.
- Frontend: rutas, navegación, cliente API, onboarding y formularios de configuración de sistema con tratamiento especial de secretos y operaciones largas.
- Despliegue: eliminación de `/etc/dynamic-thermal-charge/environment` como fuente de configuración, rutas SQLite estables, permisos de los almacenes locales y migración de instalaciones existentes.
- Compatibilidad: requiere una migración única desde los valores existentes en entorno; el cambio de backend y el nuevo onboarding modifican el procedimiento de instalación y recuperación.
- Seguridad: secretos almacenados en base de datos y excluidos de respuestas/logs; la protección en reposo dependerá de permisos del SQLite y controles/TLS del PostgreSQL, salvo que se incorpore posteriormente una raíz de cifrado externa.
