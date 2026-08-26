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

- [ ] T001 Declarar en `pyproject.toml` el extra `api` con `fastapi>=0.115,<1` y `uvicorn>=0.30,<1`, añadirlo al extra `dev`, y añadir `httpx2>=2.12` al extra `dev`. Incluir un comentario que **prohíba explícitamente** `uvicorn[standard]`: arrastra `uvloop` y `httptools`, sin wheel `armv7l`, que exigirían compilador en la Pi (research D1)
- [ ] T002 Crear el esqueleto del paquete en `src/dynamic_thermal_charge/api/__init__.py` y el directorio `src/dynamic_thermal_charge/api/routes/`
- [ ] T003 [P] Añadir a `tests/conftest.py` la utilidad que construye la aplicación y su cliente en proceso sobre el transporte ASGI, con token conocido y base de datos SQLite en `tmp_path`. **Ningún test abre un puerto**
- [ ] T004 [P] Añadir a `tests/conftest.py` el doble de `HeartbeatPublisher`, configurable para fallar y para devolver latidos con instantes arbitrarios, sin importar FastAPI

---

## Phase 2: Foundational (prerrequisitos bloqueantes)

**Purpose**: la tabla del latido, su migración y los ajustes de entorno. Ninguna historia puede
empezar sin esta fase, y al terminarla no hay todavía ninguna ruta servida.

### Tabla del latido y migración

- [ ] T005 Definir en `src/dynamic_thermal_charge/persistence/schema.py` la tabla `controller_heartbeat` según `data-model.md`: fila única por instalación con `installation_id` único, `updated_at`, `started_at`, `degraded`, `plan_id`, `poll_seconds` y `driver_kind`, con sus `CHECK` portables
- [ ] T006 Añadir en `schema.py` los mapeos de las restricciones nuevas a `CONSTRAINT_FIELDS`, y comprobar que la guardia existente `test_every_declared_constraint_maps_to_a_field` sigue pasando
- [ ] T007 Dejar `controller_heartbeat` **fuera** de `RETAINED_TABLES` en `schema.py`: es una fila que se actualiza, no un histórico que crece, y documentarlo en el propio módulo
- [ ] T008 Crear la migración `src/dynamic_thermal_charge/persistence/migrations/versions/0002_controller_heartbeat.py` que cree solo la tabla nueva, sin tocar ninguna existente
- [ ] T009 Actualizar `KNOWN_REVISIONS` en `src/dynamic_thermal_charge/persistence/gate.py` a dos entradas, de forma que una base de datos de la fase 1 se detecte como `BEHIND` con la sugerencia de migrar, nunca como desconocida
- [ ] T010 Añadir a `tests/test_persistence_seed.py` la comprobación de que `KNOWN_REVISIONS` sigue coincidiendo con las migraciones distribuidas, y a `tests/test_persistence_gate.py` el caso de una base de datos en `0001` detectada como `BEHIND`
- [ ] T011 Escribir `tests/test_persistence_heartbeat.py::test_migrating_from_phase_one_preserves_data`: sembrar en la revisión `0001`, migrar a `0002` y comprobar que la configuración y el histórico sobreviven

### Publicación y lectura del latido

- [ ] T012 Declarar en `src/dynamic_thermal_charge/persistence/__init__.py` el `Protocol` `HeartbeatPublisher`, la dataclass `Heartbeat` y la enumeración `Liveness` con `LIVE`, `LIVE_DEGRADED`, `STALE` y `NEVER_SEEN`, según `contracts/heartbeat.md`
- [ ] T013 Implementar `src/dynamic_thermal_charge/persistence/heartbeat.py` con `publish()` y `read()` sobre la tabla nueva, en una sola fila que se inserta la primera vez y se actualiza después
- [ ] T014 Garantizar que **ningún** método de `heartbeat.py` propaga excepciones: un fallo de escritura se registra como error y el control continúa. Misma regla que `HistoryRecorder`
- [ ] T015 Escribir en `tests/test_persistence_heartbeat.py` los casos de publicación y lectura: primera publicación, actualizaciones sucesivas sin crecer en filas, lectura sin latido previo, y todos los campos de ida y vuelta con instantes en UTC
- [ ] T016 Añadir a `tests/test_persistence_heartbeat.py` la prueba de que un fallo de escritura del latido **no** propaga excepción y se registra como error

### Consultas paginadas de histórico

- [ ] T017 Añadir a `src/dynamic_thermal_charge/persistence/history.py` las consultas paginadas de planes, previsiones y transiciones: filtro por rango, orden del más reciente al más antiguo, límite acotado y detección de si hay más resultados
- [ ] T018 Añadir en `src/dynamic_thermal_charge/persistence/history.py` el filtro opcional por identificador de acumulador a la consulta de transiciones, resolviéndolo sobre la columna de texto para que siga devolviendo las de acumuladores ya eliminados
- [ ] T019 Escribir en `tests/test_persistence_history.py` los casos de las consultas nuevas: orden, límite aplicado, `has_more`, rango vacío y filtro por acumulador eliminado

### Ajustes de entorno

- [ ] T020 Implementar `src/dynamic_thermal_charge/api/settings.py` leyendo del entorno `DTC_API_TOKEN`, `DTC_API_HOST` (por defecto `127.0.0.1`), `DTC_API_PORT` (por defecto `8420`), `DTC_API_STALE_SECONDS` y `DTC_API_CORS_ORIGINS` (por defecto vacío), según `contracts/http-api.md`
- [ ] T021 Hacer que `settings.py` **no** lea nada de la base de datos y documentar por qué: son los datos necesarios antes de poder leerla, y el token está excluido del almacén por el Principio III (research D11)
- [ ] T022 Escribir `tests/test_api_security.py::test_settings_defaults_are_restrictive`: la dirección por defecto es solo local y la lista de orígenes admitidos está vacía

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

- [ ] T023 [US4] Implementar en `src/dynamic_thermal_charge/api/security.py` la validación del token con `secrets.compare_digest`, comparando los valores ya codificados para que la longitud no se filtre (research D5)
- [ ] T024 [US4] Implementar en `security.py` el rechazo de credenciales triviales al arrancar: token ausente, vacío, de menos de 32 caracteres o igual al valor de ejemplo del fichero de entorno. La API **no** debe quedar escuchando en ese caso
- [ ] T025 [US4] Hacer en `src/dynamic_thermal_charge/api/security.py` que un token ausente y un token incorrecto produzcan **la misma** respuesta, sin revelar en qué se diferencian ni si la instalación existe
- [ ] T026 [US4] Registrar en `src/dynamic_thermal_charge/api/security.py` los intentos rechazados con la ruta y el origen, y **nunca** con el token ofrecido
- [ ] T027 [US4] Implementar `src/dynamic_thermal_charge/api/errors.py` con el cuerpo de error uniforme y la traducción de los errores de dominio a códigos estables y códigos HTTP, según la tabla de `contracts/http-api.md`
- [ ] T028 [US4] Implementar `create_app()` en `src/dynamic_thermal_charge/api/__init__.py`, con la dependencia de autenticación aplicada a todas las rutas salvo la de salud, y la política de orígenes admitidos tomada de los ajustes
- [ ] T029 [US4] Implementar `src/dynamic_thermal_charge/api/routes/health.py`: la única ruta sin credencial, deliberadamente muda, que no revela nada de la instalación ni de la base de datos
- [ ] T030 [US4] Escribir en `tests/test_api_security.py` los casos de autenticación: sin cabecera, con esquema erróneo, con token incorrecto, con token correcto, y que las dos primeras respuestas sean indistinguibles
- [ ] T031 [US4] Añadir a `tests/test_api_security.py` los casos de arranque rechazado: token ausente, vacío, corto y de ejemplo. En todos, la aplicación no se construye
- [ ] T032 [US4] Añadir a `tests/test_api_security.py` la prueba de que la comparación del token usa `secrets.compare_digest`, y no una comparación que salga antes en el primer byte distinto
- [ ] T033 [US4] Añadir a `tests/test_api_security.py` la prueba de que el token no aparece en ninguna respuesta ni en ningún registro, ni siquiera en el de un intento rechazado
- [ ] T034 [US4] Añadir a `tests/test_api_security.py` la prueba de que la ruta de salud responde sin credencial y **no** revela el estado de la base de datos ni de la instalación

**Checkpoint**: la API está protegida antes de tener nada que proteger.

---

## Phase 4: US2 — No creerse un estado obsoleto (P1)

**Goal**: la API distingue siempre «esto está pasando ahora» de «esto es lo último que se supo».

**Independent Test**: con un reloj controlado se deja de publicar el latido y se comprueba que el
estado pasa a marcarse como no vigente sin alterar los datos históricos.

**Por qué va antes del endpoint de estado**: la vigencia decide qué se puede afirmar en la
respuesta de estado. No es un campo más, es la condición de toda la respuesta.

- [ ] T035 [US2] Implementar `src/dynamic_thermal_charge/api/liveness.py` como lógica **pura**, sin FastAPI y sin acceso a datos: dados un latido, un instante y unos ajustes, devuelve la vigencia
- [ ] T036 [US2] Implementar en `liveness.py` la tolerancia derivada `max(3 × poll_seconds, 30 s)`, sobrescribible por `DTC_API_STALE_SECONDS`, usando el `poll_seconds` que viaja **en el latido** y no el de la configuración, porque el controlador puede haber arrancado con otra
- [ ] T037 [US2] Implementar en `liveness.py` el tratamiento del latido con instante futuro: más allá de un margen de reloj pequeño se resuelve a `STALE`, **nunca** a vigente. Si el reloj retrocede, una comparación ingenua daría «vigente para siempre», que es el fallo peligroso (research D4)
- [ ] T038 [US2] Inyectar `HeartbeatPublisher` en `src/dynamic_thermal_charge/service.py` y publicar el latido **en cada iteración** del bucle, no solo al refrescar el plan: publicar solo en el refresco dejaría hasta `refresh_minutes` de silencio y un controlador muerto pasaría tres horas pareciendo vivo
- [ ] T039 [US2] Hacer que el latido incluya el estado de degradación vigente del servicio, el plan en ejecución, el `poll_seconds` real y el tipo de driver con el que arrancó
- [ ] T040 [US2] Inyectar el publicador desde `src/dynamic_thermal_charge/cli.py` en el modo controlador, sin cambiar la firma de `ChargeController` ni de los drivers
- [ ] T041 [US2] Escribir `tests/test_api_liveness.py` con la tabla completa de vigencia: sin latido, latido reciente, latido justo en el límite, latido pasado de la tolerancia, latido con instante futuro dentro del margen, latido con instante futuro fuera del margen, y latido con degradación
- [ ] T042 [US2] Añadir a `tests/test_api_liveness.py` el caso del salto de reloj hacia atrás, comprobando que **no** produce un estado permanentemente vigente, y el salto hacia adelante, comprobando que se corrige solo con el siguiente latido
- [ ] T043 [US2] Añadir a `tests/test_api_liveness.py` la comprobación de que la tolerancia se deriva del `poll_seconds` del latido y no del de la configuración
- [ ] T044 [US2] Añadir a `tests/test_service.py` la prueba de que el servicio publica un latido por iteración, con reloj y `wait` inyectados
- [ ] T045 [US2] Añadir a `tests/test_service.py` la prueba de que un fallo al publicar el latido **no** interrumpe el bucle de control ni la conmutación de salidas
- [ ] T046 [US2] Añadir a `tests/test_service.py` la prueba de que el latido refleja la degradación del servicio al entrar y al salir de ella

**Checkpoint**: la vigencia es una función probada y el controlador ya publica su latido.

---

## Phase 5: US1 — Ver de un vistazo qué está pasando ahora (P1)

**Goal**: una sola consulta devuelve la fotografía completa del momento, con su vigencia.

**Independent Test**: con una instalación y un histórico conocidos se consulta el estado y cada
dato coincide con lo que el planificador y el controlador registraron.

- [ ] T047 [US1] Implementar en `src/dynamic_thermal_charge/api/schemas.py` los modelos de respuesta de estado: `StatusResponse`, `ControllerHealth`, `HeaterState`, `PlanSummary`, `ForecastSummary` y `AllocationSummary`, explícitos y separados del dominio (research D7)
- [ ] T048 [US1] Implementar `src/dynamic_thermal_charge/api/dependencies.py` con la apertura del almacén, la puerta de esquema, el reloj inyectable y los ajustes, todos como dependencias sustituibles en pruebas
- [ ] T049 [US1] Implementar en `src/dynamic_thermal_charge/api/routes/status.py` la derivación del estado de las salidas a partir de la última transición por acumulador, tratando la ausencia de transiciones como apagado, que es el estado en que todo driver inicializa
- [ ] T050 [US1] Implementar en `routes/status.py` el cálculo de la potencia instantánea y su porcentaje del límite, **solo** cuando la vigencia es `LIVE` o `LIVE_DEGRADED`
- [ ] T051 [US1] Implementar en `routes/status.py` la selección del plan en curso como el que contiene el instante de la consulta, devolviendo `null` cuando no hay ninguno en lugar del último plan pasado
- [ ] T052 [US1] Implementar en `routes/status.py` la presentación del estado no vigente: `state_is_current` a `false`, `power` a `null`, y el estado de cada acumulador como último estado conocido con su instante, **sin** afirmar que ninguno esté activo
- [ ] T053 [US1] Servir `GET /api/v1/status` desde `create_app()`, con la previsión asociada al plan y su origen (`aemet`, `simulated` o `fallback`), y el reparto por acumulador con minutos solicitados, asignados y no atendidos
- [ ] T054 [US1] Escribir en `tests/test_api_status.py` el caso del estado vigente: acumuladores activos, potencia y porcentaje, ventana del plan, previsión con su origen, y reparto por acumulador
- [ ] T055 [US1] Añadir a `tests/test_api_status.py` los tres casos de controlador no sano: nunca visto, silencioso y degradado, comprobando en los dos primeros que `power` es `null` y que no se afirma ninguna salida activa
- [ ] T056 [US1] Añadir a `tests/test_api_status.py` el caso de la previsión de reserva, comprobando que el origen se reporta como `fallback`
- [ ] T057 [US1] Añadir a `tests/test_api_status.py` el caso de una instalación sin ningún plan y el de un plan que no cubre la carga solicitada, con los minutos no atendidos
- [ ] T058 [US1] Añadir a `tests/test_api_status.py` el caso de la recuperación del controlador, comprobando que el estado vuelve a vigente sin reiniciar la API
- [ ] T059 [US1] Añadir a `tests/test_api_status.py` el caso de una instalación sin ningún acumulador, comprobando que el estado sigue siendo consultable y no muestra ninguna salida activa

**Checkpoint**: el estado es consultable y honesto. Es el MVP de la fase.

---

## Phase 6: US3 — Editar la configuración desde un cliente (P1)

**Goal**: las mismas garantías que la línea de comandos, a través de HTTP.

**Independent Test**: se aplican cambios válidos e inválidos por la API y se comprueba, leyendo
después, qué quedó almacenado y qué se rechazó.

- [ ] T060 [US3] Implementar en `src/dynamic_thermal_charge/api/schemas.py` los modelos de configuración: `ConfigResponse`, `HeaterResponse`, `SetFieldRequest`, `AddHeaterRequest` y `ChangeResponse`
- [ ] T061 [US3] Garantizar en `schemas.py` que `ConfigResponse` **no** incluye la localización de la base de datos ni el valor de la clave del proveedor; del proveedor, solo el **nombre** de su variable de entorno
- [ ] T062 [US3] Servir `GET /api/v1/config` y `GET /api/v1/config/heaters/{id}` desde `src/dynamic_thermal_charge/api/routes/config.py`, incluyendo la revisión de configuración y la de esquema
- [ ] T063 [US3] Servir `PATCH /api/v1/config` y `PATCH /api/v1/config/heaters/{id}` en `routes/config.py`, **reutilizando** `ConfigRepository.set_field` sin reimplementar ni relajar ninguna validación
- [ ] T064 [US3] Servir `POST /api/v1/config/heaters` y `DELETE /api/v1/config/heaters/{id}` en `routes/config.py`, reutilizando `add_heater` y `remove_heater`
- [ ] T065 [US3] Hacer obligatoria la revisión en toda escritura y traducir `ConfigConflictError` a **409** con un mensaje que indique releer, en `routes/config.py`
- [ ] T066 [US3] Enrutar en `routes/config.py` los campos hacia instalación, proveedor meteorológico o acumulador, y producir un **404** que enumere los nombres admitidos o los acumuladores existentes cuando el nombre no exista
- [ ] T067 [US3] Escribir en `tests/test_api_config.py` los casos de lectura: configuración completa con su revisión, acumulador concreto, y acumulador inexistente con la lista de los existentes
- [ ] T068 [US3] Añadir a `tests/test_api_config.py` los casos de edición correcta: campo de instalación y campo de acumulador, comprobando valor anterior, valor nuevo y revisión resultante, y que los demás acumuladores no cambian
- [ ] T069 [US3] Añadir a `tests/test_api_config.py` el alta y la baja de acumuladores, comprobando que la baja arrastra salida y perfil térmico y **conserva** el histórico
- [ ] T070 [US3] Añadir a `tests/test_api_config.py` los casos de rechazo con el almacén intacto: configuración resultante inválida (**422**), valor con aspecto de credencial (**422**), identificador ya en uso (**409**) y campo inexistente (**404**)
- [ ] T071 [US3] Añadir a `tests/test_api_config.py` el caso de dos clientes sobre la misma revisión: el primero tiene éxito, el segundo recibe **409**, y ningún cambio se pierde en silencio
- [ ] T072 [US3] Añadir a `tests/test_api_config.py` la prueba de que una edición no altera un plan ya construido y toma efecto en el siguiente recálculo
- [ ] T073 [US3] Escribir en `tests/test_api_config.py` la guardia de fugas: ninguna respuesta contiene la cadena de conexión, el token ni el valor de la clave de AEMET
- [ ] T074 [US3] Escribir en `tests/test_api_config.py` la guardia de campos nuevos: comparar los campos del dominio con los expuestos en `ConfigResponse` y **fallar** si aparece uno de dominio sin decidir explícitamente si se expone

**Checkpoint**: la configuración se gestiona por completo desde un cliente.

---

## Phase 7: US5 — Que la API no pueda romper la calefacción (P1)

**Goal**: los dos procesos son de verdad independientes, y ninguna operación de la API acciona
una salida.

**Independent Test**: se detiene y se arranca cada proceso por separado y se observa el efecto en
el otro y en el estado de las salidas.

- [ ] T075 [US5] Escribir `tests/test_api_guards.py::test_no_api_module_imports_a_driver`: guardia estática de que ningún módulo de `api/` importa `drivers`, `gpio_driver` ni `controller`. Es lo que hace verificable que **ninguna ruta puede accionar una salida** (Principio I)
- [ ] T076 [US5] Añadir a `tests/test_api_guards.py` la guardia de que el núcleo se importa sin el extra `api` instalado: importar `scheduler`, `thermal`, `models` y `controller` no debe cargar `fastapi` ni `uvicorn`
- [ ] T077 [US5] Añadir a `tests/test_api_guards.py` la guardia de que ningún módulo de `api/` importa la API asíncrona de SQLAlchemy ni `greenlet`
- [ ] T078 [US5] Añadir a `tests/test_api_guards.py` la comprobación de que todos los manejadores son funciones síncronas: un `async def` que llamase al repositorio síncrono bloquearía el bucle de eventos esperando a una base de datos remota (research D6)
- [ ] T079 [US5] Escribir `tests/test_api_errors.py` con el caso de base de datos inaccesible: **503** con código `store_unavailable`, sin traza, sin la cadena de conexión, y sin ningún dato de estado inventado
- [ ] T080 [US5] Añadir a `tests/test_api_errors.py` los casos de esquema no utilizable: ausente, atrasado y desconocido, todos **503** con `schema_unusable`, y comprobar que **no** se sirve ninguna operación, ni de lectura
- [ ] T081 [US5] Añadir a `tests/test_api_errors.py` el caso de configuración almacenada inválida, y la comprobación de que no se ofrece ninguna operación de escritura sobre datos que no se comprenden
- [ ] T082 [US5] Añadir a `tests/test_api_errors.py` la comprobación de que ningún cuerpo de error contiene trazas, rutas del sistema de ficheros ni fragmentos de la cadena de conexión, recorriendo todos los códigos de error del contrato
- [ ] T083 [US5] Añadir a `tests/test_api_errors.py` la prueba de que la API **no** migra el esquema: ninguna ruta lo altera, y con un esquema atrasado la respuesta remite a la CLI
- [ ] T084 [US5] Configurar en `src/dynamic_thermal_charge/api/dependencies.py` los tiempos de espera del motor de base de datos para que ninguna petición quede bloqueada indefinidamente, y añadir su prueba a `tests/test_api_errors.py`
- [ ] T085 [US5] Añadir a `tests/test_api_status.py` la prueba de que la API responde con el controlador ausente en lugar de bloquearse o fallar
- [ ] T086 [US5] Añadir a `tests/test_service.py` la prueba de que el bucle de control funciona sin publicador de latido inyectado, de modo que la API es opcional para el controlador y no al revés

**Checkpoint**: las P1 están completas. La API es utilizable y no puede dañar el control.

---

## Phase 8: US6 — Auditar el pasado desde un cliente (P2)

**Goal**: reconstruir cualquier noche del periodo retenido sin acceder al dispositivo.

**Independent Test**: con un histórico sembrado de varias noches se consulta con distintos rangos
y páginas y se comprueba qué se devuelve.

- [ ] T087 [US6] Implementar en `src/dynamic_thermal_charge/api/schemas.py` los modelos de histórico: `Page`, `PlanHistoryItem`, `ForecastHistoryItem` y `TransitionHistoryItem`
- [ ] T088 [US6] Servir `GET /api/v1/history/plans`, `/forecasts` y `/transitions` desde `src/dynamic_thermal_charge/api/routes/history.py`, con filtro por rango, orden del más reciente al más antiguo y paginación
- [ ] T089 [US6] Aplicar en `routes/history.py` el tamaño de página por defecto de 50 y el máximo de 500, acotando un límite mayor y reflejándolo en `limit_applied`
- [ ] T090 [US6] Rechazar en `routes/history.py` un rango con el inicio posterior al fin con **400**, y devolver una página vacía cuando el rango no tiene datos
- [ ] T091 [US6] Exponer el parámetro `heater_id` en la ruta de transiciones de `src/dynamic_thermal_charge/api/routes/history.py`, delegando en el filtro del borde de datos añadido en T018 y validando que un identificador inexistente devuelve página vacía, no **404**: el acumulador pudo existir y haber sido eliminado
- [ ] T092 [US6] Escribir en `tests/test_api_history.py` los casos de paginación: orden, límite por defecto, límite acotado al máximo, `has_more` y continuación por cursor
- [ ] T093 [US6] Añadir a `tests/test_api_history.py` los casos de rango: rango parcial, rango vacío que devuelve página vacía, y rango invertido que devuelve **400**
- [ ] T094 [US6] Añadir a `tests/test_api_history.py` el caso del acumulador eliminado, comprobando que su histórico sigue siendo consultable
- [ ] T095 [US6] Añadir a `tests/test_api_history.py` la comprobación de que ninguna consulta devuelve el histórico completo, ni siquiera sin parámetros

**Checkpoint**: el histórico es consultable y siempre acotado.

---

## Phase 9: US7 — Descubrir la API sin leer el código (P2)

**Goal**: quien construya un cliente obtiene el contrato de la propia API.

**Independent Test**: se solicita la descripción y se comprueba que enumera todas las operaciones
realmente disponibles.

- [ ] T096 [US7] Documentar en `create_app()` y en cada ruta los resúmenes, descripciones y respuestas de error, de modo que la descripción generada sea utilizable sin leer el código
- [ ] T097 [US7] Escribir `tests/test_api_docs.py::test_the_description_matches_what_is_served`: comparar las operaciones descritas con las rutas realmente registradas y fallar si hay descritas que no existen o servidas sin describir
- [ ] T098 [US7] Añadir a `tests/test_api_docs.py` la comprobación de que la descripción **no** contiene secretos ni valores reales de configuración
- [ ] T099 [US7] Añadir a `tests/test_api_docs.py` la comprobación de que cada operación documenta los códigos de error que realmente puede devolver, según `contracts/http-api.md`

**Checkpoint**: el contrato vive en la API, no en la cabeza de quien la escribió.

---

## Phase 10: US8 — Mantener el histórico acotado desde un cliente (P3)

**Goal**: disparar la limpieza sin acceder por consola.

**Independent Test**: con un histórico que excede la retención se dispara la limpieza por la API y
se comprueba el recuento y qué sobrevive.

- [ ] T100 [US8] Servir `POST /api/v1/history/prune` en `src/dynamic_thermal_charge/api/routes/history.py`, reutilizando `HistoryRecorder.prune` con la retención vigente
- [ ] T101 [US8] Devolver en `src/dynamic_thermal_charge/api/routes/history.py` el recuento por tabla, e indicar explícitamente cuando la retención es ilimitada y no se ha eliminado nada
- [ ] T102 [US8] Escribir en `tests/test_api_history.py` los casos de limpieza: con registros que exceden la retención, comprobando que la configuración y los planes vivos se conservan, y con retención ilimitada

---

## Phase 11: Despliegue y cierre

**Purpose**: dejar los dos servicios instalables y la documentación coherente.

- [ ] T103 Implementar el subcomando `dtc api` en `src/dynamic_thermal_charge/cli.py`, que arranca el servidor con los ajustes del entorno y falla el arranque si el token no es válido
- [ ] T104 Verificar con un test en `tests/test_api_guards.py` que el subcomando `api` **no** construye ningún driver de salida, igual que los subcomandos administrativos de la fase anterior
- [ ] T105 [P] Añadir a `deploy/environment.example` la variable `DTC_API_TOKEN` con la instrucción de generarlo, y las de host, puerto, tolerancia y orígenes comentadas
- [ ] T106 Crear `deploy/systemd/dynamic-thermal-charge-api.service`: mismo usuario y mismo fichero de entorno que el controlador, `TimeoutStartSec` holgado por el coste de arranque medido, sin `ExecStartPre` que duplique el arranque del intérprete, `ProtectSystem=strict` y `ReadWritePaths` sobre el directorio de la base de datos
- [ ] T107 Añadir la opción `--with-api` a `scripts/install-service.sh`: instala el extra `api`, instala la segunda unidad, **no** la arranca ni la habilita, y avisa de que hay que generar el token
- [ ] T108 Ampliar `tests/test_deployment.py` para verificar la segunda unidad: que no pasa fichero de configuración, que el instalador no la arranca ni la habilita, y que el fichero de entorno de ejemplo no contiene un token real
- [ ] T109 Añadir a `README.md` la sección de la API: generar el token, arrancar los dos servicios, y la tabla de diagnóstico
- [ ] T110 Añadir a `README.md` la advertencia explícita de exponer la API en la red: sirve en claro, el token viaja legible, quien lo tenga puede cambiar la potencia máxima y los pines, y publicarla en internet requiere un proxy inverso con cifrado que queda fuera de alcance
- [ ] T111 Ejecutar `pytest` completo y comprobar que pasa sin red, sin PostgreSQL, sin hardware y **sin abrir ningún puerto**, y que las omisiones siguen siendo solo las de `tests/test_postgres_compat.py` más el par de driver ausente
- [ ] T112 **MANUAL, requiere hardware — diferida, fuera del criterio de fase completa.** Medir en la Raspberry Pi el arranque y la memoria residente del proceso de la API frente al presupuesto de <10 s y <120 MB, y anotar el resultado en `research.md` D2. Comprobar allí mismo que detener la API no altera el plan en ejecución

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

- **T009 y T010 son un par.** Añadir la revisión `0002` sin actualizar las revisiones conocidas
  haría que la puerta de esquema tomase una base de datos ya migrada por **desconocida**, y el
  arranque se rechazaría. Es el modo de fallo que la fase 1 dejó armado a propósito.
- **T014 antes de T038.** El publicador debe ser incapaz de lanzar **antes** de inyectarlo en el
  bucle de control; al revés, un fallo de latido podría tumbar la calefacción.
- **T035 a T037 antes de T052.** La presentación del estado no vigente depende de que la
  vigencia ya esté decidida y probada como función pura.
- **T023 a T028 antes de cualquier ruta.** La dependencia de autenticación se aplica en
  `create_app()`; si las rutas llegan antes, existen sin proteger.
- **T061 y T074 son un par.** El modelo explícito y la guardia que detecta campos nuevos solo
  sirven juntos: el modelo evita la fuga hoy, la guardia la evita mañana.
- **T017 antes de la fase 8.** Las rutas de histórico no pueden paginar lo que el borde de datos
  no sabe paginar.
- **US7 depende de que todas las rutas existan**: describir un contrato incompleto no sirve.

## Parallel Execution Examples

Dentro de la fase 1: T003 y T004 en paralelo.

Dentro de la fase 2: el bloque del latido (T012–T016) es paralelo al de consultas de histórico
(T017–T019) y al de ajustes (T020–T022), porque tocan ficheros distintos, siempre que T005–T011
estén hechos.

Dentro de la fase 5: T047 (`schemas.py`) es paralelo a T048 (`dependencies.py`).

Dentro de la fase 11: T105 en paralelo con el resto.

No paralelizar dentro de un mismo fichero: T005, T006 y T007 tocan `schema.py`; T035 a T037
tocan `liveness.py`; T060 y T061 tocan `schemas.py`; casi toda la fase 6 toca `routes/config.py`.

## Implementation Strategy

**MVP mínimo utilizable**: fases 1 a 5. Al terminarlas hay una API autenticada que informa del
estado con honestidad sobre su vigencia. Es lo que necesita el frontend de la fase 3 para
mostrar algo.

**Primer punto de despliegue razonable**: añadir las fases 6 y 7. Sin la 6 el frontend sería un
visor; sin la 7 no hay garantía verificable de que la API no pueda dañar el control, que es la
propiedad por la que se eligieron dos procesos.

**Completar la fase**: fases 8 a 11. La 11 es obligatoria antes de instalar en la Raspberry: sin
T110 el operador no tiene el aviso de que la API sirve en claro y de que el token equivale a la
llave del cuadro eléctrico.

**Fases posteriores del proyecto** (fuera de este `tasks.md`): frontend Angular e integración con
Home Assistant.

## Resumen

| Fase | Historia | Tareas | Prioridad |
| --- | --- | ---: | --- |
| 1 Setup | — | 4 (T001–T004) | — |
| 2 Foundational | — | 18 (T005–T022) | bloqueante |
| 3 | US4 autenticación | 12 (T023–T034) | P1 |
| 4 | US2 vigencia y latido | 12 (T035–T046) | P1 |
| 5 | US1 estado actual | 13 (T047–T059) | P1 |
| 6 | US3 edición | 15 (T060–T074) | P1 |
| 7 | US5 independencia | 12 (T075–T086) | P1 |
| 8 | US6 histórico | 9 (T087–T095) | P2 |
| 9 | US7 descripción | 4 (T096–T099) | P2 |
| 10 | US8 limpieza | 3 (T100–T102) | P3 |
| 11 Despliegue y cierre | — | 10 (T103–T112) | — |
| **Total** | | **112** | |

De las 112, **111 son ejecutables en máquina de desarrollo**. T112 requiere la Raspberry Pi,
está marcada como manual y queda fuera del criterio de fase completa.

Cobertura: los 51 requisitos funcionales y los 12 criterios de éxito de `spec.md` tienen al menos
una tarea asociada.

Los caminos de fallo del Principio I y IV están cubiertos por T016, T030–T034, T041–T043, T045,
T055, T070, T075–T086 y T104.
