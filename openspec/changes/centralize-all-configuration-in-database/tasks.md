## 1. Baseline e inventario de configuración

- [x] 1.1 Crear un inventario versionado de cada lectura runtime de entorno/fichero y clasificarla como configuración persistente, constante interna o argumento operativo; verificar con un test basado en `rg`/AST que no quedan accesos sin clasificar.
- [x] 1.2 Añadir pruebas de caracterización para los valores actuales de API, MQTT, AEMET, logging, relay test, retención y base de datos antes de moverlos; verificar que la suite conserva defaults y validaciones existentes.
- [x] 1.3 Introducir un resolvedor único del directorio de estado de producción y su inyección explícita en tests; verificar rutas deterministas y que ninguna variable de entorno pueda cambiar el backend runtime.
- [x] 1.4 Definir errores y estados compartidos de topología (`bootstrap`, `normal`, `fallback`, `migrating`, incompatible); verificar serialización sanitizada y clasificación de indisponibilidad frente a corrupción/validación.

## 2. Almacenes SQLite de bootstrap y fallback

- [x] 2.1 Crear metadata y migraciones independientes de `bootstrap.db` para estado de onboarding, locator estructurado, revisión compare-and-swap, digest local y lease de migración; verificar creación, upgrade y rechazo de versión futura.
- [x] 2.2 Implementar el repositorio de bootstrap con inicialización atómica, permisos `0700/0600` y generación única de credencial de onboarding; verificar que el secreto solo se devuelve en la creación y nunca se persiste en claro.
- [x] 2.3 Modelar el locator SQLite/PostgreSQL por campos allow-list con redacción centralizada y validación TLS; verificar URLs inválidas, drivers no soportados y ausencia de credenciales en `repr`, logs y errores.
- [x] 2.4 Crear metadata y migraciones independientes de `fallback.db` para snapshot, plan, digest administrativo, outbox y reconciliación; verificar que no contiene tablas de configuración editable ni histórico completo.
- [x] 2.5 Implementar lectura/escritura atómica de snapshots con revisión, timestamps y checksum; verificar detección de corrupción, reemplazo completo y conservación de la snapshot anterior ante fallo.
- [x] 2.6 Añadir un comando de diagnóstico/recuperación de bootstrap que nunca autocorrija datos ambiguos; verificar estado seguro y mensajes accionables con bootstrap incompatible o corrupto.

## 3. Separación de configuración y aplicación

- [x] 3.1 Clasificar todas las tablas actuales entre configuración y aplicación y separar metadata/migraciones Alembic sin cambiar semántica; verificar que cada almacén tiene revisión propia y solo sus tablas esperadas.
- [x] 3.2 Adaptar los repositorios de configuración funcional para usar exclusivamente el engine de configuración; verificar CRUD, locking optimista y validación en SQLite y PostgreSQL.
- [x] 3.3 Adaptar histórico, forecast, planes, heartbeat, logs de controller y relay tests al engine de aplicación; verificar la suite de persistencia contra los dos drivers.
- [x] 3.4 Configurar los schemas PostgreSQL `dtc_config` y `dtc_app` y los ficheros SQLite `configuration.db`/`application.db`; verificar aislamiento, migraciones independientes y equivalencia de consultas.
- [x] 3.5 Eliminar dependencias transaccionales entre objetos de ambos almacenes y definir compensación donde una operación abarque los dos; verificar que un fallo del segundo commit no corrompe el primero ni activa outputs.

## 4. Modelo y repositorio de configuración de sistema

- [x] 4.1 Crear modelos tipados para database, API/security, MQTT, weather/keys, output, logging y operations con defaults y validaciones cruzadas; verificar todos los rangos, combinaciones obligatorias y semánticas `hot`/`next_cycle`/`restart`.
- [x] 4.2 Crear tablas/migraciones de snapshot global, documentos de dominio, secretos, revisión y auditoría en el almacén de configuración; verificar rollback atómico y evolución de formato.
- [x] 4.3 Implementar lectura y actualización por sección construyendo y validando una configuración candidata completa; verificar éxito, error global y conflicto de revisión sin escrituras parciales.
- [x] 4.4 Implementar secretos `keep`/`replace`/`clear`, digest no reversible para autenticación y almacenamiento recuperable solo para integraciones; verificar rotación, campos obligatorios y que lecturas nunca devuelven valores.
- [x] 4.5 Implementar DTOs/catálogo allow-list con metadatos de activación y estado configurado de secretos; verificar que añadir un campo persistente nuevo obliga a decidir explícitamente su exposición.
- [x] 4.6 Añadir auditoría sanitizada de onboarding, cambios, rotaciones, pruebas y migraciones; verificar actor, campos, revisiones y resultado sin valores sensibles.

## 5. Contexto de almacenamiento y adopción por procesos

- [x] 5.1 Implementar `StorageContext` para abrir bootstrap y construir una generación coherente de repositorios de configuración/aplicación; verificar SQLite y PostgreSQL sin `DTC_DATABASE_URL`.
- [x] 5.2 Implementar sustitución y retirada segura de generaciones al cambiar locator; verificar que operaciones en vuelo terminan sobre su generación y las nuevas usan la siguiente.
- [x] 5.3 Añadir seguimiento de revisión aplicada por API, controller y MQTT, incluido `pending_apply`/`pending_restart`; verificar convergencia y diagnóstico cuando un proceso queda atrás.
- [x] 5.4 Mover API host/port/CORS/token/staleness al repositorio y arrancar onboarding con defaults seguros; verificar API configurada/no configurada y aplicación tras reinicio.
- [x] 5.5 Mover MQTT y credenciales al repositorio, con recarga/reconexión controlada; verificar rotación, combinaciones username/password y que una configuración ausente no afecta al controller.
- [x] 5.6 Mover API key meteorológica, output real/simulado, GPIO, logging, retención, heartbeat y relay-test al repositorio; verificar que cada consumidor respeta su política de activación.
- [x] 5.7 Eliminar las lecturas runtime de configuración desde `os.environ`, ficheros y URLs de CLI; verificar mediante la guardia del inventario y tests que valores externos contradictorios se ignoran.

## 6. Fallback y reconciliación

- [x] 6.1 Implementar refresco del fallback después de cada configuración/plan canónico confirmado; verificar revisión, checksum, frescura y reemplazo atómico.
- [x] 6.2 Implementar routing por política de operación y entrada en fallback solo ante indisponibilidad clasificada; verificar que validación/esquema incompatible no se tratan como corte de red.
- [x] 6.3 Hacer que el controller ejecute el plan fallback válido y apague outputs cuando falta, caduca o está corrupto; verificar transiciones, continuidad y safe-off con reloj controlado.
- [x] 6.4 Implementar outbox durable con UUID, tipo/versionado, aggregate, orden y revisión de configuración; verificar recuperación tras reinicio local y límites de espacio.
- [x] 6.5 Añadir adaptadores idempotentes para planes, forecasts, heartbeats, eventos de output y logs esenciales; verificar replays repetidos sin duplicados ni relaciones rotas.
- [x] 6.6 Implementar reconciliador por lotes con ACK, backoff y reanudación, seguido de recarga canónica y refresco local; verificar caída a mitad, configuración remota más reciente y retorno a normal solo al converger.
- [x] 6.7 Exponer métricas/estado de fallback, edad, última sincronización y pendientes sin credenciales; verificar respuestas de health y logs durante entrada, permanencia y recuperación.

## 7. Saga de cambio de driver

- [x] 7.1 Implementar preflight efímero para SQLite/PostgreSQL con timeout, TLS, permisos, espacio y versiones; verificar fallos sanitizados y que ninguna prueba persiste candidatos.
- [x] 7.2 Implementar lease exclusivo y máquina de estados reanudable de migración en bootstrap; verificar exclusión concurrente, expiración segura y recuperación tras reinicio.
- [x] 7.3 Implementar preparación del destino y copia consistente por lotes de configuración y aplicación preservando IDs/revisiones; verificar migración de una base poblada sin bloquear el plan activo.
- [x] 7.4 Implementar verificaciones de schemas, recuentos, relaciones y checksums antes del commit; verificar que una discrepancia conserva el locator/origen y marca el destino fallido.
- [x] 7.5 Implementar compare-and-swap del locator, apertura end-to-end del destino, replay de outbox y retirada no destructiva del origen; verificar el punto de commit y los dos caminos de rollback del diseño.
- [x] 7.6 Añadir soporte y pruebas completas SQLite→PostgreSQL y cobertura del camino PostgreSQL→SQLite definido por la misma saga; verificar que el driver final es la única autoridad y los almacenes retirados no reciben escrituras.

## 8. Onboarding y API administrativa

- [x] 8.1 Añadir endpoints públicos mínimos de health/estado de onboarding y finalización con credencial de un solo uso, rate limit e invalidación; verificar éxito, expiración, intentos erróneos y reutilización rechazada.
- [x] 8.2 Adaptar autenticación para resolver el digest administrativo desde canónico/fallback y rotarlo en caliente; verificar acceso normal/degradado, comparación segura y ausencia de ventana anónima.
- [x] 8.3 Añadir endpoints autenticados de topología, catálogo y lectura/`PATCH` por sección con `expected_revision`; verificar validación, conflicto, semántica de secreto y reinicio pendiente.
- [x] 8.4 Añadir endpoints de prueba para PostgreSQL, MQTT y weather con timeout y redacción; verificar éxito/error sin persistencia, logs o respuestas sensibles.
- [x] 8.5 Añadir endpoints para iniciar y seguir migraciones con confirmación explícita; verificar fases, operación concurrente rechazada y resultado que identifica el backend aún activo.
- [x] 8.6 Aplicar modo solo lectura durante fallback/migrating y añadir errores `degraded_mode`, `operation_in_progress` y `connection_test_failed`; verificar códigos reintentables y que la snapshot nunca se modifica.
- [x] 8.7 Ampliar OpenAPI y guardias de fuga para todas las superficies nuevas; verificar que schema, ejemplos, errores, health y auditoría no contienen secretos ni URLs credencializadas.

## 9. Frontend de Configuración del sistema

- [x] 9.1 Añadir tipos/clientes para onboarding, configuración por secciones, secretos, topología, pruebas y migraciones; verificar tests de contrato y manejo uniforme de errores.
- [x] 9.2 Crear ruta/asistente de onboarding que bloquee vistas operativas hasta completar mínimos; verificar credencial inválida, navegación por pasos, finalización e invalidación.
- [x] 9.3 Crear `/configuracion-sistema`, entrada de navegación y resumen por secciones separado de acumuladores; verificar rutas, guards y responsive layout.
- [x] 9.4 Implementar formularios tipados con revisión global, validación y política de activación; verificar guardado válido, error global, conflicto que conserva edición y aviso de reinicio.
- [x] 9.5 Implementar controles de secreto write-only que nunca rehidratan ni persisten valores en navegador; verificar `keep`/`replace`/`clear`, cancelación y ausencia en DOM/logs después de completar.
- [x] 9.6 Implementar selección/prueba de driver, revisión del alcance, confirmación y progreso de saga; verificar éxito, fallo, salida/retorno a la vista y prohibición de doble migración.
- [x] 9.7 Añadir banner global de modo degradado/migrando y deshabilitar mutaciones con explicación; verificar edad de snapshot, pendientes y recuperación a normal.
- [x] 9.8 Añadir confirmaciones específicas para autenticación, secretos, driver y output real, y cubrir teclado/foco/anuncios/contraste; verificar pruebas de componente y auditoría de accesibilidad.

## 10. Migración legada y despliegue sin ficheros

- [x] 10.1 Implementar el comando aislado de import legado con dry-run para leer una vez entorno y DB antigua, mapear todos los valores y producir informe sanitizado; verificar instalaciones SQLite/PostgreSQL, ausencias y repetición idempotente.
- [x] 10.2 Añadir verificación post-import de secretos presentes, revisiones, recuentos, relaciones y snapshot fallback; verificar que un fallo deja intactos la DB y el fichero anteriores.
- [x] 10.3 Actualizar instalador para crear el directorio protegido, inicializar bootstrap y mostrar una sola vez el token de onboarding; verificar permisos, instalación nueva y upgrade sin pérdida.
- [x] 10.4 Eliminar `EnvironmentFile` y valores `DTC_*` de las unidades systemd y ejemplo de despliegue; verificar que API, controller y MQTT arrancan exclusivamente desde bootstrap/configuración.
- [x] 10.5 Actualizar CLI para init/doctor/import/recovery sin aceptar ficheros o URLs en comandos runtime; verificar mensajes deprecados accionables y que `run`, `api` y `mqtt` comparten `StorageContext`.
- [x] 10.6 Actualizar README y documentación operativa con onboarding, topología, migración, fallback, TLS, backups y rollback; verificar que no se instruye a mantener configuración runtime en ficheros.

## 11. Verificación integral y endurecimiento

- [x] 11.1 Añadir tests de integración multiproceso sobre SQLite para API/controller/MQTT compartiendo bootstrap pero schemas separados; verificar revisión aplicada, cambios hot/next-cycle/restart y ausencia de dependencias de entorno.
- [x] 11.2 Añadir tests PostgreSQL reales para namespaces, migración, autoridad canónica y deduplicación; verificar con el marcador existente de PostgreSQL y documentar cómo ejecutarlos.
- [x] 11.3 Ejecutar escenarios de corte antes/durante/después de migración, reinicio durante replay, disco lleno y bootstrap corrupto; verificar safe-off, conservación de origen y recuperación reanudable.
- [x] 11.4 Añadir pruebas exhaustivas de no fuga de tokens, API keys, passwords y locators en API, OpenAPI, CLI, logs, excepciones, auditoría y frontend; verificar cadenas centinela en todas las salidas capturadas.
- [x] 11.5 Ejecutar suite backend, tests frontend, build de producción y validación OpenSpec estricta; verificar que todo pasa y registrar cualquier test PostgreSQL omitido por falta de servidor.
