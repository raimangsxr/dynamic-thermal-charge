---

description: "Task list for 002-config-api"
---

# Tasks: API HTTP de estado y configuración

**Input**: Design documents from `/specs/002-config-api/`

**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/`. La feature
`001-config-database` debe estar implementada: esta fase consume su repositorio, su histórico y
su puerta de esquema.

**Tests**: OBLIGATORIOS. El Principio V exige tests en el módulo espejo del código tocado y
cobertura explícita de los caminos de fallo del Principio I.

**Organization**: agrupadas por historia de usuario. Cada bloque es entregable y verificable por
separado.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: paralelizable — toca ficheros distintos y no depende de tareas incompletas
- **[Story]**: historia de usuario de `spec.md` (US1…US8)

## Path Conventions

Proyecto único: `src/dynamic_thermal_charge/`, `tests/` en la raíz. Toda la superficie HTTP vive
en `src/dynamic_thermal_charge/api/`, el único paquete autorizado a importar FastAPI, igual que
`persistence/` es el único que importa SQLAlchemy.

## Orden de las historias P1 y por qué

`spec.md` marca como P1 las historias 1, 2, 3, 4 y 5. El orden de implementación **no** es su
numeración, porque hay dependencias reales:

- **US4 (autenticación) va primero.** Si las rutas se escriben antes, existe una ventana en la
  que hay endpoints sin proteger, y añadir la protección después obliga a rehacer cada test.
- **US2 (señal de vida y vigencia) va antes de US1 (estado).** El endpoint de estado no puede
  escribirse sin saber si el dato que devuelve es vigente: la vigencia no es un adorno de la
  respuesta, es la que decide qué se puede afirmar en ella.
- **US5 (independencia de procesos) se verifica al final de las P1**, cuando ya hay una API y un
  controlador que se pueden arrancar y parar por separado.

El orden es por tanto **US4 → US2 → US1 → US3 → US5**, y después **US6 → US7 → US8**.

---

## Phase 1: Setup

**Purpose**: dependencias y estructura, sin tocar comportamiento.

- [X] T001 Declarar en `pyproject.toml` el extra `api` con `fastapi>=0.115,<1` y `uvicorn>=0.30,<1`, añadirlo al extra `dev`, y añadir `httpx2>=2.12` al extra `dev`. Incluir un comentario que **prohíba explícitamente** `uvicorn[standard]`: arrastra `uvloop` y `httptools`, sin wheel `armv7l`, que exigirían compilador en la Pi (research D1)
- [X] T002 Escribir `tests/test_deployment.py::test_forbidden_dependencies_never_return`: guardia que falle si `pyproject.toml` declara `uvicorn[standard]`, `uvloop`, `httptools` o `greenlet`. Ninguno tiene wheel `armv7l` y romperían el despliegue en la Pi sin que la suite lo notase; el comentario de T001 documenta la prohibición pero no la impide (FR-047, SC-011)
- [X] T003 Crear el esqueleto del paquete en `src/dynamic_thermal_charge/api/__init__.py` y el directorio `src/dynamic_thermal_charge/api/routes/`
- [X] T004 [P] Añadir a `tests/conftest.py` la utilidad que construye la aplicación y su cliente en proceso sobre el transporte ASGI, con token conocido y base de datos SQLite en `tmp_path`. **Ningún test abre un puerto**
- [X] T005 [P] Añadir a `tests/conftest.py` el doble de `HeartbeatPublisher`, configurable para fallar y para devolver latidos con instantes arbitrarios, sin importar FastAPI

---

## Phase 2: Foundational (prerrequisitos bloqueantes)

**Purpose**: la tabla del latido, su migración y los ajustes de entorno. Ninguna historia puede
empezar sin esta fase, y al terminarla no hay todavía ninguna ruta servida.

### Tabla del latido y migración

- [X] T006 Definir en `src/dynamic_thermal_charge/persistence/schema.py` la tabla `controller_heartbeat` según `data-model.md`: fila única por instalación con `installation_id` único, `updated_at`, `started_at`, `degraded`, `plan_id`, `poll_seconds`, `driver_kind` y `runner_id`, con sus `CHECK` portables
- [X] T007 Añadir en `schema.py` los mapeos de las restricciones nuevas a `CONSTRAINT_FIELDS`, y comprobar que la guardia existente `test_every_declared_constraint_maps_to_a_field` sigue pasando
- [X] T008 Dejar `controller_heartbeat` **fuera** de `RETAINED_TABLES` en `schema.py`: es una fila que se actualiza, no un histórico que crece, y documentarlo en el propio módulo
- [X] T009 Crear la migración `src/dynamic_thermal_charge/persistence/migrations/versions/0002_controller_heartbeat.py` que cree solo la tabla nueva, sin tocar ninguna existente
- [X] T010 Actualizar `KNOWN_REVISIONS` en `src/dynamic_thermal_charge/persistence/gate.py` a dos entradas, de forma que una base de datos de la fase 1 se detecte como `BEHIND` con la sugerencia de migrar, nunca como desconocida
- [X] T011 Añadir a `tests/test_persistence_seed.py` la comprobación de que `KNOWN_REVISIONS` sigue coincidiendo con las migraciones distribuidas, y a `tests/test_persistence_gate.py` el caso de una base de datos en `0001` detectada como `BEHIND`
- [X] T012 Escribir `tests/test_persistence_heartbeat.py::test_migrating_from_phase_one_preserves_data` (FR-048b): sembrar en la revisión `0001`, migrar a `0002` y comprobar que la configuración y el histórico sobreviven íntegros. Es la primera migración que se aplicará sobre datos reales del usuario

### Publicación y lectura del latido

- [X] T013 Declarar en `src/dynamic_thermal_charge/persistence/__init__.py` el `Protocol` `HeartbeatPublisher`, la dataclass `Heartbeat` y la enumeración `Liveness` con `LIVE`, `LIVE_DEGRADED`, `STALE` y `NEVER_SEEN`, según `contracts/heartbeat.md`
- [X] T014 Implementar `src/dynamic_thermal_charge/persistence/heartbeat.py` con `publish()` y `read()` sobre la tabla nueva, en una sola fila que se inserta la primera vez y se actualiza después
- [X] T015 Garantizar que **ningún** método de `heartbeat.py` propaga excepciones: un fallo de escritura se registra como error y el control continúa. Misma regla que `HistoryRecorder`
- [X] T016 Escribir en `tests/test_persistence_heartbeat.py` los casos de publicación y lectura: primera publicación, actualizaciones sucesivas sin crecer en filas, lectura sin latido previo, y todos los campos de ida y vuelta con instantes en UTC
- [X] T017 Añadir a `tests/test_persistence_heartbeat.py` la prueba de que un fallo de escritura del latido **no** propaga excepción y se registra como error

### Consultas paginadas de histórico

- [X] T018 Añadir a `src/dynamic_thermal_charge/persistence/history.py` las consultas paginadas de planes, previsiones y transiciones: filtro por rango, orden del más reciente al más antiguo, límite acotado, detección de si hay más resultados, y **cursor opaco sobre el par `(instante, id)`** según la definición de `data-model.md`. No un desplazamiento numérico: una inserción entre dos páginas provocaría elementos repetidos o saltados
- [X] T019 Añadir en `src/dynamic_thermal_charge/persistence/history.py` el filtro opcional por identificador de acumulador a la consulta de transiciones, resolviéndolo sobre la columna de texto para que siga devolviendo las de acumuladores ya eliminados
- [X] T020 Escribir en `tests/test_persistence_history.py` los casos de las consultas nuevas: orden, límite aplicado, `has_more`, rango vacío y filtro por acumulador eliminado

### Ajustes de entorno

- [X] T021 Implementar `src/dynamic_thermal_charge/api/settings.py` leyendo del entorno `DTC_API_TOKEN`, `DTC_API_HOST` (por defecto `127.0.0.1`), `DTC_API_PORT` (por defecto `8420`), `DTC_API_STALE_SECONDS` y `DTC_API_CORS_ORIGINS` (por defecto vacío), según `contracts/http-api.md`
- [X] T022 Hacer que `settings.py` **no** lea nada de la base de datos y documentar por qué: son los datos necesarios antes de poder leerla, y el token está excluido del almacén por el Principio III (research D11)
- [X] T023 Escribir `tests/test_api_security.py::test_settings_defaults_are_restrictive`: la dirección por defecto es solo local y la lista de orígenes admitidos está vacía

**Checkpoint**: existe el latido y la configuración de entorno. El programa se comporta igual
que antes salvo que el esquema tiene una tabla más.

---

## Phase 3: US4 — Impedir que un desconocido cambie la instalación (P1)

**Goal**: nada se ejecuta sin la credencial correcta, y la credencial no se filtra ni se puede
deducir.

**Independent Test**: se repite cada operación sin credencial, con una incorrecta y con la
correcta, comprobando qué se ejecuta en cada caso.

**Por qué va primera**: escribir rutas antes de la protección deja una ventana con endpoints sin
proteger y obliga a rehacer todos sus tests al añadirla.

- [X] T024 [US4] Implementar en `src/dynamic_thermal_charge/api/security.py` la validación del token con `secrets.compare_digest`, comparando los valores ya codificados para que la longitud no se filtre (research D5)
- [X] T025 [US4] Implementar en `security.py` el rechazo de credenciales triviales al arrancar: token ausente, vacío, de menos de 32 caracteres o igual al valor de ejemplo del fichero de entorno. La API **no** debe quedar escuchando en ese caso
- [X] T026 [US4] Hacer en `src/dynamic_thermal_charge/api/security.py` que un token ausente y un token incorrecto produzcan **la misma** respuesta, sin revelar en qué se diferencian ni si la instalación existe
- [X] T027 [US4] Registrar en `src/dynamic_thermal_charge/api/security.py` los intentos rechazados con la ruta y el origen, y **nunca** con el token ofrecido
- [X] T028 [US4] Implementar `src/dynamic_thermal_charge/api/errors.py` con el cuerpo de error uniforme y la traducción de los errores de dominio a códigos estables y códigos HTTP, según la tabla de `contracts/http-api.md`
- [X] T029 [US4] Implementar `create_app()` en `src/dynamic_thermal_charge/api/__init__.py`, con la dependencia de autenticación aplicada a todas las rutas salvo la de salud —**incluidas `/docs` y `/openapi.json`**, que enumeran la superficie de la API y nadie necesita sin autenticar (FR-007, FR-052)— y la política de orígenes admitidos tomada de los ajustes
- [X] T030 [US4] Implementar `src/dynamic_thermal_charge/api/routes/health.py` según FR-052: la única ruta sin credencial, deliberadamente muda, que no revela nada de la instalación, ni si la base de datos está accesible, ni la versión del esquema, ni si existe configuración
- [X] T031 [US4] Escribir en `tests/test_api_security.py` los casos de autenticación: sin cabecera, con esquema erróneo, con token incorrecto, con token correcto, y que las dos primeras respuestas sean indistinguibles
- [X] T032 [US4] Añadir a `tests/test_api_security.py` los casos de arranque rechazado: token ausente, vacío, corto y de ejemplo. En todos, la aplicación no se construye
- [X] T033 [US4] Añadir a `tests/test_api_security.py` la verificación **por inspección** de que la comparación del token pasa por `secrets.compare_digest`, sustituyéndolo por un doble que registre las llamadas. **No medir tiempos**: un test de tiempos sería no determinista, y el Principio V lo prohíbe. La propiedad se garantiza por construcción, no por medición
- [X] T034 [US4] Añadir a `tests/test_api_security.py` la prueba de que el token no aparece en ninguna respuesta ni en ningún registro, ni siquiera en el de un intento rechazado
- [X] T035 [US4] Añadir a `tests/test_api_security.py` la prueba de que la ruta de salud responde sin credencial y **no** revela el estado de la base de datos ni de la instalación, y la prueba de que `/docs` y `/openapi.json` **sí** exigen credencial
- [X] T036 [US4] Añadir a `tests/test_api_security.py` el caso **positivo** de origen admitido: con un origen declarado en los ajustes, la respuesta lleva las cabeceras que el navegador necesita, y con otro distinto no las lleva. Sin este caso solo se prueba que la puerta está cerrada, y de que se pueda abrir depende el frontend de la fase 3 (FR-044)

**Checkpoint**: la API está protegida antes de tener nada que proteger.

---

## Phase 4: US2 — No creerse un estado obsoleto (P1)

**Goal**: la API distingue siempre «esto está pasando ahora» de «esto es lo último que se supo».

**Independent Test**: con un reloj controlado se deja de publicar el latido y se comprueba que el
estado pasa a marcarse como no vigente sin alterar los datos históricos.

**Por qué va antes del endpoint de estado**: la vigencia decide qué se puede afirmar en la
respuesta de estado. No es un campo más, es la condición de toda la respuesta.

- [X] T037 [US2] Implementar `src/dynamic_thermal_charge/api/liveness.py` como lógica **pura**, sin FastAPI y sin acceso a datos: dados un latido, un instante y unos ajustes, devuelve la vigencia
- [X] T038 [US2] Implementar en `liveness.py` la tolerancia derivada `max(3 × poll_seconds, 30 s)`, sobrescribible por `DTC_API_STALE_SECONDS`, usando el `poll_seconds` que viaja **en el latido** y no el de la configuración, porque el controlador puede haber arrancado con otra
- [X] T039 [US2] Implementar en `liveness.py` el tratamiento del latido con instante futuro: más allá de un margen de reloj pequeño se resuelve a `STALE`, **nunca** a vigente. Si el reloj retrocede, una comparación ingenua daría «vigente para siempre», que es el fallo peligroso (research D4)
- [X] T040 [US2] Inyectar `HeartbeatPublisher` en `src/dynamic_thermal_charge/service.py` y publicar el latido **en cada iteración** del bucle, no solo al refrescar el plan: publicar solo en el refresco dejaría hasta `refresh_minutes` de silencio y un controlador muerto pasaría tres horas pareciendo vivo
- [X] T041 [US2] Hacer que el latido incluya el estado de degradación vigente del servicio, el plan en ejecución, el `poll_seconds` **real con el que el controlador está funcionando** —no el de la configuración, que puede ser posterior—, el tipo de driver, el `started_at` del proceso y un `runner_id` aleatorio generado al arrancar y estable mientras vive (FR-014)
- [X] T042 [US2] Inyectar el publicador desde `src/dynamic_thermal_charge/cli.py` en el modo controlador, sin cambiar la firma de `ChargeController` ni de los drivers
- [X] T043 [US2] Escribir `tests/test_api_liveness.py` con la tabla completa de vigencia: sin latido, latido reciente, latido justo en el límite, latido pasado de la tolerancia, latido con instante futuro dentro del margen, latido con instante futuro fuera del margen, y latido con degradación
- [X] T044 [US2] Añadir a `tests/test_api_liveness.py` el caso del salto de reloj hacia atrás, comprobando que **no** produce un estado permanentemente vigente, y el salto hacia adelante, comprobando que se corrige solo con el siguiente latido
- [X] T045 [US2] Añadir a `tests/test_api_liveness.py` la comprobación de que la tolerancia se deriva del `poll_seconds` del latido y no del de la configuración
- [X] T046 [US2] Añadir a `tests/test_service.py` la prueba de que el servicio publica un latido por iteración, con reloj y `wait` inyectados
- [X] T047 [US2] Añadir a `tests/test_service.py` la prueba de que un fallo al publicar el latido **no** interrumpe el bucle de control ni la conmutación de salidas
- [X] T048 [US2] Añadir a `tests/test_service.py` la prueba de que el latido refleja la degradación del servicio al entrar y al salir de ella
- [X] T049 [US2] Implementar en `src/dynamic_thermal_charge/api/liveness.py` la detección de más de un controlador (FR-053) según `contracts/heartbeat.md`: un `started_at` que retrocede, o un `runner_id` que alterna entre dos valores, indican dos procesos vivos. La API **solo señala**; no arbitra ni detiene a nadie
- [X] T050 [US2] Añadir a `tests/test_api_liveness.py` los casos de la detección: `runner_id` estable, reinicio limpio con `started_at` posterior, `started_at` que retrocede, y `runner_id` alternando. Dos controladores conmutando los mismos relés no puede verse igual que uno sano

**Checkpoint**: la vigencia es una función probada y el controlador ya publica su latido.

---

## Phase 5: US1 — Ver de un vistazo qué está pasando ahora (P1)

**Goal**: una sola consulta devuelve la fotografía completa del momento, con su vigencia.

**Independent Test**: con una instalación y un histórico conocidos se consulta el estado y cada
dato coincide con lo que el planificador y el controlador registraron.

- [X] T051 [US1] Implementar en `src/dynamic_thermal_charge/api/schemas.py` los modelos de respuesta de estado: `StatusResponse`, `ControllerHealth`, `HeaterState`, `PlanSummary`, `ForecastSummary` y `AllocationSummary`, explícitos y separados del dominio (research D7)
- [X] T052 [US1] Implementar `src/dynamic_thermal_charge/api/dependencies.py` con la apertura del almacén, la puerta de esquema, el reloj inyectable y los ajustes, todos como dependencias sustituibles en pruebas
- [X] T053 [US1] Implementar en `src/dynamic_thermal_charge/api/routes/status.py` la derivación del estado de las salidas a partir de la última transición por acumulador, tratando la ausencia de transiciones como apagado, que es el estado en que todo driver inicializa
- [X] T054 [US1] Implementar en `routes/status.py` el cálculo de la potencia instantánea y su porcentaje del límite, **solo** cuando la vigencia es `LIVE` o `LIVE_DEGRADED`
- [X] T055 [US1] Implementar en `routes/status.py` la selección del plan en curso como el que contiene el instante de la consulta, devolviendo `null` cuando no hay ninguno en lugar del último plan pasado
- [X] T056 [US1] Implementar en `routes/status.py` la presentación del estado no vigente: `state_is_current` a `false`, `power` a `null`, y el estado de cada acumulador como último estado conocido con su instante, **sin** afirmar que ninguno esté activo
- [X] T057 [US1] Servir `GET /api/v1/status` desde `create_app()`, con la previsión asociada al plan y su origen (`aemet`, `simulated` o `fallback`), y el reparto por acumulador con minutos solicitados, asignados y no atendidos
- [X] T058 [US1] Escribir en `tests/test_api_status.py` el caso del estado vigente: acumuladores activos, potencia y porcentaje, ventana del plan, previsión con su origen, y reparto por acumulador
- [X] T059 [US1] Añadir a `tests/test_api_status.py` los tres casos de controlador no sano: nunca visto, silencioso y degradado, comprobando en los dos primeros que `power` es `null` y que no se afirma ninguna salida activa
- [X] T060 [US1] Añadir a `tests/test_api_status.py` el caso de la previsión de reserva, comprobando que el origen se reporta como `fallback`
- [X] T061 [US1] Añadir a `tests/test_api_status.py` el caso de una instalación sin ningún plan y el de un plan que no cubre la carga solicitada, con los minutos no atendidos
- [X] T062 [US1] Añadir a `tests/test_api_status.py` el caso de la recuperación del controlador, comprobando que el estado vuelve a vigente sin reiniciar la API
- [X] T063 [US1] Añadir a `tests/test_api_status.py` el caso de una instalación sin ningún acumulador, comprobando que el estado sigue siendo consultable y no muestra ninguna salida activa

**Checkpoint**: el estado es consultable y honesto. Es el MVP de la fase.

---

## Phase 6: US3 — Editar la configuración desde un cliente (P1)

**Goal**: las mismas garantías que la línea de comandos, a través de HTTP.

**Independent Test**: se aplican cambios válidos e inválidos por la API y se comprueba, leyendo
después, qué quedó almacenado y qué se rechazó.

- [X] T064 [US3] Implementar en `src/dynamic_thermal_charge/api/schemas.py` los modelos de configuración: `ConfigResponse`, `HeaterResponse`, `SetFieldRequest`, `AddHeaterRequest` y `ChangeResponse`
- [X] T065 [US3] Garantizar en `schemas.py` que `ConfigResponse` **no** incluye la localización de la base de datos ni el valor de la clave del proveedor; del proveedor, solo el **nombre** de su variable de entorno
- [X] T066 [US3] Servir `GET /api/v1/config` y `GET /api/v1/config/heaters/{id}` desde `src/dynamic_thermal_charge/api/routes/config.py`, incluyendo la revisión de configuración y la de esquema
- [X] T067 [US3] Servir `PATCH /api/v1/config` y `PATCH /api/v1/config/heaters/{id}` en `routes/config.py`, **reutilizando** `ConfigRepository.set_field` sin reimplementar ni relajar ninguna validación
- [X] T068 [US3] Servir `POST /api/v1/config/heaters` y `DELETE /api/v1/config/heaters/{id}` en `routes/config.py`, reutilizando `add_heater` y `remove_heater`
- [X] T069 [US3] Hacer obligatoria la revisión en toda escritura y traducir `ConfigConflictError` a **409** con un mensaje que indique releer, en `routes/config.py`
- [X] T070 [US3] Enrutar en `routes/config.py` los campos hacia instalación, proveedor meteorológico o acumulador, y producir un **404** que enumere los nombres admitidos o los acumuladores existentes cuando el nombre no exista
- [X] T071 [US3] Escribir en `tests/test_api_config.py` los casos de lectura: configuración completa con su revisión, acumulador concreto, y acumulador inexistente con la lista de los existentes
- [X] T072 [US3] Añadir a `tests/test_api_config.py` los casos de edición correcta: campo de instalación y campo de acumulador, comprobando valor anterior, valor nuevo y revisión resultante, y que los demás acumuladores no cambian
- [X] T073 [US3] Añadir a `tests/test_api_config.py` el alta y la baja de acumuladores, comprobando que la baja arrastra salida y perfil térmico y **conserva** el histórico
- [X] T074 [US3] Añadir a `tests/test_api_config.py` los casos de rechazo con el almacén intacto: configuración resultante inválida (**422**), valor con aspecto de credencial (**422**), identificador ya en uso (**409**) y campo inexistente (**404**)
- [X] T075 [US3] Añadir a `tests/test_api_config.py` el caso de dos clientes sobre la misma revisión: el primero tiene éxito, el segundo recibe **409**, y ningún cambio se pierde en silencio
- [X] T076 [US3] Añadir a `tests/test_api_config.py` la prueba de que una edición no altera un plan ya construido y toma efecto en el siguiente recálculo
- [X] T077 [US3] Escribir en `tests/test_api_config.py` la guardia de fugas: ninguna respuesta contiene la cadena de conexión, el token ni el valor de la clave de AEMET
- [X] T078 [US3] Escribir en `tests/test_api_config.py` la guardia de campos nuevos: comparar los campos del dominio con los expuestos en `ConfigResponse` y **fallar** si aparece uno de dominio sin decidir explícitamente si se expone

**Checkpoint**: la configuración se gestiona por completo desde un cliente.

---

## Phase 7: US5 — Que la API no pueda romper la calefacción (P1)

**Goal**: los dos procesos son de verdad independientes, y ninguna operación de la API acciona
una salida.

**Independent Test**: se detiene y se arranca cada proceso por separado y se observa el efecto en
el otro y en el estado de las salidas.

- [X] T079 [US5] Escribir `tests/test_api_guards.py::test_no_api_module_imports_a_driver`: guardia estática de que ningún módulo de `api/` importa `drivers`, `gpio_driver` ni `controller`, y de que ninguno monta ficheros estáticos (FR-045). Es lo que hace verificable que **ninguna ruta puede accionar una salida** (Principio I)
- [X] T080 [US5] Añadir a `tests/test_api_guards.py` la guardia de que el núcleo se importa sin el extra `api` instalado: importar `scheduler`, `thermal`, `models` y `controller` no debe cargar `fastapi` ni `uvicorn`
- [X] T081 [US5] Añadir a `tests/test_api_guards.py` la guardia de que ningún módulo de `api/` importa la API asíncrona de SQLAlchemy ni `greenlet`
- [X] T082 [US5] Añadir a `tests/test_api_guards.py` la comprobación de que todos los manejadores son funciones síncronas: un `async def` que llamase al repositorio síncrono bloquearía el bucle de eventos esperando a una base de datos remota (research D6)
- [X] T083 [US5] Escribir `tests/test_api_errors.py` con el caso de base de datos inaccesible: **503** con código `store_unavailable`, sin traza, sin la cadena de conexión, y sin ningún dato de estado inventado
- [X] T084 [US5] Añadir a `tests/test_api_errors.py` los casos de esquema no utilizable: ausente, atrasado y desconocido, todos **503** con `schema_unusable`, y comprobar que **no** se sirve ninguna operación, ni de lectura
- [X] T085 [US5] Añadir a `tests/test_api_errors.py` el caso de configuración almacenada inválida, y la comprobación de que no se ofrece ninguna operación de escritura sobre datos que no se comprenden
- [X] T086 [US5] Añadir a `tests/test_api_errors.py` la comprobación de que ningún cuerpo de error contiene trazas, rutas del sistema de ficheros ni fragmentos de la cadena de conexión, recorriendo todos los códigos de error del contrato
- [X] T087 [US5] Añadir a `tests/test_api_errors.py` la prueba de que la API **no** migra el esquema: ninguna ruta lo altera, y con un esquema atrasado la respuesta remite a la CLI
- [X] T088 [US5] Configurar en `src/dynamic_thermal_charge/api/dependencies.py` los tiempos de espera del motor de base de datos para que ninguna petición quede bloqueada indefinidamente, y añadir su prueba a `tests/test_api_errors.py`
- [X] T089 [US5] Añadir a `tests/test_api_status.py` la prueba de que la API responde con el controlador ausente en lugar de bloquearse o fallar
- [X] T090 [US5] Añadir a `tests/test_service.py` la prueba de que el bucle de control funciona sin publicador de latido inyectado, de modo que la API es opcional para el controlador y no al revés
- [X] T091 [US5] Escribir `tests/test_api_guards.py::test_the_control_loop_runs_without_the_api_installed`: ejecutar el bucle de control en un subproceso que no importe nada de `api/` y comprobar que planifica y conmuta con normalidad. Es la mitad automatizable de SC-003; la otra mitad, detener la API con un plan en curso, es la manual de T112

**Checkpoint**: las P1 están completas. La API es utilizable y no puede dañar el control.

---

## Phase 8: US6 — Auditar el pasado desde un cliente (P2)

**Goal**: reconstruir cualquier noche del periodo retenido sin acceder al dispositivo.

**Independent Test**: con un histórico sembrado de varias noches se consulta con distintos rangos
y páginas y se comprueba qué se devuelve.

- [X] T092 [US6] Implementar en `src/dynamic_thermal_charge/api/schemas.py` los modelos de histórico: `Page`, `PlanHistoryItem`, `ForecastHistoryItem` y `TransitionHistoryItem`
- [X] T093 [US6] Servir `GET /api/v1/history/plans`, `/forecasts` y `/transitions` desde `src/dynamic_thermal_charge/api/routes/history.py`, con filtro por rango, orden del más reciente al más antiguo y paginación
- [X] T094 [US6] Aplicar en `routes/history.py` el tamaño de página por defecto de 50 y el máximo de 500, acotando un límite mayor y reflejándolo en `limit_applied`
- [X] T095 [US6] Rechazar en `routes/history.py` un rango con el inicio posterior al fin con **400**, y devolver una página vacía cuando el rango no tiene datos
- [X] T096 [US6] Exponer el parámetro `heater_id` en la ruta de transiciones de `src/dynamic_thermal_charge/api/routes/history.py`, delegando en el filtro del borde de datos añadido en T019 y validando que un identificador inexistente devuelve página vacía, no **404**: el acumulador pudo existir y haber sido eliminado
- [X] T097 [US6] Escribir en `tests/test_api_history.py` los casos de paginación: orden, límite por defecto, límite acotado al máximo, `has_more` y continuación por cursor
- [X] T098 [US6] Añadir a `tests/test_api_history.py` los casos de rango: rango parcial, rango vacío que devuelve página vacía, y rango invertido que devuelve **400**
- [X] T099 [US6] Añadir a `tests/test_api_history.py` el caso del acumulador eliminado, comprobando que su histórico sigue siendo consultable
- [X] T100 [US6] Añadir a `tests/test_api_history.py` la comprobación de que ninguna consulta devuelve el histórico completo, ni siquiera sin parámetros

**Checkpoint**: el histórico es consultable y siempre acotado.

---

## Phase 9: US7 — Descubrir la API sin leer el código (P2)

**Goal**: quien construya un cliente obtiene el contrato de la propia API.

**Independent Test**: se solicita la descripción y se comprueba que enumera todas las operaciones
realmente disponibles.

- [X] T101 [US7] Documentar en `create_app()` y en cada ruta los resúmenes, descripciones y respuestas de error, de modo que la descripción generada sea utilizable sin leer el código
- [X] T102 [US7] Escribir `tests/test_api_docs.py::test_the_description_matches_what_is_served`: comparar las operaciones descritas con las rutas realmente registradas y fallar si hay descritas que no existen o servidas sin describir
- [X] T103 [US7] Añadir a `tests/test_api_docs.py` la comprobación de que la descripción **no** contiene secretos ni valores reales de configuración
- [X] T104 [US7] Añadir a `tests/test_api_docs.py` la comprobación de que cada operación documenta los códigos de error que realmente puede devolver, según `contracts/http-api.md`

**Checkpoint**: el contrato vive en la API, no en la cabeza de quien la escribió.

---

## Phase 10: US8 — Mantener el histórico acotado desde un cliente (P3)

**Goal**: disparar la limpieza sin acceder por consola.

**Independent Test**: con un histórico que excede la retención se dispara la limpieza por la API y
se comprueba el recuento y qué sobrevive.

- [X] T105 [US8] Servir `POST /api/v1/history/prune` en `src/dynamic_thermal_charge/api/routes/history.py`, reutilizando `HistoryRecorder.prune` con la retención vigente
- [X] T106 [US8] Devolver en `src/dynamic_thermal_charge/api/routes/history.py` el recuento por tabla, e indicar explícitamente cuando la retención es ilimitada y no se ha eliminado nada
- [X] T107 [US8] Escribir en `tests/test_api_history.py` los casos de limpieza: con registros que exceden la retención, comprobando que la configuración y los planes vivos se conservan, y con retención ilimitada

---

## Phase 11: Despliegue y cierre

**Purpose**: dejar los dos servicios instalables y la documentación coherente.

- [X] T108 Implementar el subcomando `dtc api` en `src/dynamic_thermal_charge/cli.py`, que arranca el servidor con los ajustes del entorno y falla el arranque si el token no es válido
- [X] T109 Verificar con un test en `tests/test_api_guards.py` que el subcomando `api` **no** construye ningún driver de salida, igual que los subcomandos administrativos de la fase anterior
- [X] T110 [P] Añadir a `deploy/environment.example` la variable `DTC_API_TOKEN` con la instrucción de generarlo, y las de host, puerto, tolerancia y orígenes comentadas
- [X] T111 Crear `deploy/systemd/dynamic-thermal-charge-api.service`: mismo usuario y mismo fichero de entorno que el controlador, `TimeoutStartSec` holgado por el coste de arranque medido, sin `ExecStartPre` que duplique el arranque del intérprete, `ProtectSystem=strict` y `ReadWritePaths` sobre el directorio de la base de datos
- [X] T112 Añadir la opción `--with-api` a `scripts/install-service.sh`: instala el extra `api`, instala la segunda unidad, **no** la arranca ni la habilita, y avisa de que hay que generar el token
- [X] T113 Ampliar `tests/test_deployment.py` para verificar la segunda unidad: que no pasa fichero de configuración, que el instalador no la arranca ni la habilita, y que el fichero de entorno de ejemplo no contiene un token real
- [X] T114 Añadir a `README.md` la sección de la API: generar el token, arrancar los dos servicios, y la tabla de diagnóstico
- [X] T115 Añadir a `README.md` la advertencia explícita de exponer la API en la red: sirve en claro, el token viaja legible, quien lo tenga puede cambiar la potencia máxima y los pines, y publicarla en internet requiere un proxy inverso con cifrado que queda fuera de alcance
- [X] T116 Ejecutar `pytest` completo y comprobar que pasa sin red, sin PostgreSQL, sin hardware y **sin abrir ningún puerto**, y que las omisiones siguen siendo solo las de `tests/test_postgres_compat.py` más el par de driver ausente
- [ ] T117 **MANUAL, requiere hardware — diferida, fuera del criterio de fase completa.** Medir en la Raspberry Pi el arranque y la memoria residente del proceso de la API frente al presupuesto de <10 s y <120 MB, y anotar el resultado en `research.md` D2. Comprobar allí mismo que detener la API no altera el plan en ejecución

---

## Dependencies

```text
Phase 1 Setup
     ↓
Phase 2 Foundational   ← tabla del latido, migración, consultas paginadas, ajustes
     ↓
Phase 3 US4 (autenticación)   ← antes de que exista cualquier ruta que proteger
     ↓
Phase 4 US2 (vigencia y latido)   ← decide qué puede afirmar la respuesta de estado
     ↓
Phase 5 US1 (estado actual)   ← MVP de la fase
     ↓
Phase 6 US3 (edición)
     ↓
Phase 7 US5 (independencia)   ← se verifica cuando ya hay dos procesos que arrancar y parar
     ↓
Phase 8 US6 (histórico) → Phase 9 US7 (descripción) → Phase 10 US8 (limpieza)
     ↓
Phase 11 Despliegue y cierre
```

Dependencias que conviene no perder de vista:

- **T010 y T011 son un par.** Añadir la revisión `0002` sin actualizar las revisiones conocidas
  haría que la puerta de esquema tomase una base de datos ya migrada por **desconocida**, y el
  arranque se rechazaría. Es el modo de fallo que la fase 1 dejó armado a propósito.
- **T015 antes de T040.** El publicador debe ser incapaz de lanzar **antes** de inyectarlo en el
  bucle de control; al revés, un fallo de latido podría tumbar la calefacción.
- **T037 a T039 antes de T056.** La presentación del estado no vigente depende de que la
  vigencia ya esté decidida y probada como función pura.
- **T024 a T029 antes de cualquier ruta.** La dependencia de autenticación se aplica en
  `create_app()`; si las rutas llegan antes, existen sin proteger.
- **T065 y T078 son un par.** El modelo explícito y la guardia que detecta campos nuevos solo
  sirven juntos: el modelo evita la fuga hoy, la guardia la evita mañana.
- **T018 antes de la fase 8.** Las rutas de histórico no pueden paginar lo que el borde de datos
  no sabe paginar.
- **T002 desde el principio.** Es la guardia que protege el hallazgo más valioso de la
  investigación. Ponerla al final permitiría que alguien «arreglase» la instalación siguiendo la
  documentación de FastAPI y rompiese el despliegue en la Pi sin que nada fallase.
- **T039 antes de T049.** La detección de un segundo controlador necesita que el latido lleve ya
  `runner_id` y `started_at`.
- **T017 antes de T098.** El cursor debe estar implementado en el borde de datos antes de
  probarse en la ruta; en el desglose original se probaba algo que nadie construía.
- **US7 depende de que todas las rutas existan**: describir un contrato incompleto no sirve.

## Parallel Execution Examples

Dentro de la fase 1: T004 y T005 en paralelo.

Dentro de la fase 2: el bloque del latido (T013–T017) es paralelo al de consultas de histórico
(T018–T020) y al de ajustes (T021–T023), porque tocan ficheros distintos, siempre que T006–T012
estén hechos.

Dentro de la fase 5: T051 (`schemas.py`) es paralelo a T052 (`dependencies.py`).

Dentro de la fase 11: T110 en paralelo con el resto.

No paralelizar dentro de un mismo fichero: T006, T007 y T008 tocan `schema.py`; T037 a T039
tocan `liveness.py`; T064 y T065 tocan `schemas.py`; casi toda la fase 6 toca `routes/config.py`.

## Implementation Strategy

**MVP mínimo utilizable**: fases 1 a 5. Al terminarlas hay una API autenticada que informa del
estado con honestidad sobre su vigencia. Es lo que necesita el frontend de la fase 3 para
mostrar algo.

**Primer punto de despliegue razonable**: añadir las fases 6 y 7. Sin la 6 el frontend sería un
visor; sin la 7 no hay garantía verificable de que la API no pueda dañar el control, que es la
propiedad por la que se eligieron dos procesos.

**Completar la fase**: fases 8 a 11. La 11 es obligatoria antes de instalar en la Raspberry: sin
T115 el operador no tiene el aviso de que la API sirve en claro y de que el token equivale a la
llave del cuadro eléctrico.

**Fases posteriores del proyecto** (fuera de este `tasks.md`): frontend Angular e integración con
Home Assistant.

## Resumen

| Fase | Historia | Tareas | Prioridad |
| --- | --- | ---: | --- |
| 1 Setup | — | 5 (T001–T005) | — |
| 2 Foundational | — | 18 (T006–T023) | bloqueante |
| 3 | US4 autenticación | 13 (T024–T036) | P1 |
| 4 | US2 vigencia y latido | 14 (T037–T050) | P1 |
| 5 | US1 estado actual | 13 (T051–T063) | P1 |
| 6 | US3 edición | 15 (T064–T078) | P1 |
| 7 | US5 independencia | 13 (T079–T091) | P1 |
| 8 | US6 histórico | 9 (T092–T100) | P2 |
| 9 | US7 descripción | 4 (T101–T104) | P2 |
| 10 | US8 limpieza | 3 (T105–T107) | P3 |
| 11 Despliegue y cierre | — | 10 (T108–T117) | — |
| **Total** | | **117** | |

De las 117, **116 son ejecutables en máquina de desarrollo**. T117 requiere la Raspberry Pi,
está marcada como manual y queda fuera del criterio de fase completa.

Cobertura: los 54 requisitos funcionales y los 12 criterios de éxito de `spec.md` tienen al menos
una tarea asociada, tras cerrar en la revisión de `/speckit-analyze` los huecos de FR-044,
FR-045, FR-047, FR-052, FR-053, FR-048b, SC-003 y SC-011.

Los caminos de fallo del Principio I y IV están cubiertos por T017, T031–T036, T043–T045, T047,
T049–T050, T059, T074, T079–T091 y T109.

## Revisión de `/speckit-analyze`

Las cinco tareas siguientes se añadieron al cerrar los hallazgos del análisis de consistencia, y
son las únicas que no proceden del desglose original:

| Tarea | Hallazgo | Qué cerraba |
| --- | --- | --- |
| T002 | F2 (HIGH) | La viabilidad en ARMv7 dependía de que nunca reapareciese `uvicorn[standard]`, y solo lo impedía un comentario |
| T036 | F9 | Solo se probaba que la puerta de orígenes está cerrada, no que se pueda abrir; de eso depende el frontend de la fase 3 |
| T049, T050 | F8 | Dos controladores contra la misma base de datos se veían igual que uno sano. Riesgo eléctrico oculto |
| T091 | F10 | SC-003 solo se verificaba a mano en la Pi |

Los demás hallazgos se cerraron reformulando artefactos, sin añadir tareas: F1 (FR-007 decía
«toda operación» y el contrato eximía la ruta de salud; además `/docs` queda ahora autenticado),
F3 (el cursor se probaba en T098 sin estar definido ni implementado; ahora es un par
`(instante, id)` opaco, definido en `data-model.md` y exigido en T017), F4 (FR-014 no exigía el
`poll_seconds` del que depende toda la vigencia), F5 (T032 invitaba a un test de tiempos, que el
Principio V prohíbe), F6 (la ruta de salud no tenía requisito: ahora es FR-052), F7 (la migración
desde la fase 1 no tenía requisito: ahora es FR-048b), F11 (SC-011 no era medible), F12 (nota de
terminología credencial/token), F13 (la guardia de T075 cubre también el montaje de estáticos),
F14 y F15.
