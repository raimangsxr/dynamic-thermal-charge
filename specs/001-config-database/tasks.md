---

description: "Task list for 001-config-database"
---

# Tasks: Configuración y histórico en base de datos

**Input**: Design documents from `/specs/001-config-database/`

**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/`

**Tests**: OBLIGATORIOS. El Principio V de la constitución exige que toda feature entre con
tests en el módulo espejo del código tocado, y que los caminos de fallo del Principio I
tengan cobertura explícita. No es una opción de este desglose.

**Organization**: agrupadas por historia de usuario. Cada bloque es entregable y verificable
por separado.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: paralelizable — toca ficheros distintos y no depende de tareas incompletas
- **[Story]**: historia de usuario de `spec.md` (US1…US6)

## Path Conventions

Proyecto único: `src/dynamic_thermal_charge/`, `tests/` en la raíz del repositorio.
Todo el código de persistencia vive en `src/dynamic_thermal_charge/persistence/`, el único
lugar autorizado a importar SQLAlchemy.

## Orden de las historias P1 y por qué

`spec.md` marca como P1 las historias 1, 2, 3 y 6. El orden de implementación **no** es su
orden de numeración, porque hay una dependencia real: la historia 1 (arrancar leyendo la
base de datos) necesita una base de datos que exista, y crearla es la historia 2. El orden
es por tanto **US2 → US1 → US6 → US3**, y después las P2 **US4 → US5**.

---

## Phase 1: Setup

**Purpose**: preparar dependencias y estructura sin tocar comportamiento.

- [ ] T001 Declarar en `pyproject.toml` los extras `db` (`SQLAlchemy>=2,<3`, `Alembic>=1.13`) y `postgres` (`pg8000>=1.31`), añadir `db` al extra `dev`, y declarar en `[project.scripts]` el alias `dtc` apuntando al mismo punto de entrada que `dynamic-thermal-charge`. NO retirar todavía `PyYAML` de `dependencies`: `config.py` aún lo importa y se retira en T050
- [ ] T002 Crear el esqueleto del subpaquete en `src/dynamic_thermal_charge/persistence/__init__.py` y el directorio `src/dynamic_thermal_charge/persistence/migrations/versions/`
- [ ] T003 [P] Registrar en `pyproject.toml` el marcador `postgres` de pytest y configurarlo para que se omita salvo que exista `DTC_TEST_POSTGRES_URL`, según `research.md` D12
- [ ] T004 [P] Crear `tests/conftest.py` con las utilidades compartidas: factoría de URL SQLite sobre `tmp_path`, reloj controlado y `wait` controlado reutilizables. Ningún test puede dormir en tiempo real
- [ ] T005 [P] Añadir `var/*.db`, `var/*.db-wal` y `var/*.db-shm` a `.gitignore`

---

## Phase 2: Foundational (prerrequisitos bloqueantes)

**Purpose**: la frontera de persistencia completa. Ninguna historia puede empezar sin esta
fase. Al terminarla no hay todavía ningún cambio de comportamiento visible para el usuario.

### Errores de dominio y URL

- [ ] T006 Definir la jerarquía de errores de dominio (`ConfigStoreError`, `ConfigStoreUnavailableError`, `ConfigStoreEmptyError`, `SchemaVersionError`, `ConfigValidationError`, `ConfigConflictError`) en `src/dynamic_thermal_charge/persistence/__init__.py`, con campo y acumulador en `ConfigValidationError`, según `contracts/repository.md`
- [ ] T007 Implementar el parseo de `DTC_DATABASE_URL` en `src/dynamic_thermal_charge/persistence/url.py`: motores admitidos `sqlite` y `postgresql+pg8000`, y una función `describe()` que devuelva motor, host y nombre de base de datos por separado
- [ ] T008 Escribir `tests/test_persistence_url.py` cubriendo: variable ausente, variable vacía, motor no admitido (mensaje que enumere los admitidos), URL SQLite absoluta, URL PostgreSQL con credenciales, y URL malformada
- [ ] T009 Añadir a `tests/test_persistence_url.py` la prueba de redacción de credenciales: `describe()` NUNCA devuelve la URL completa ni la contraseña, ni siquiera enmascarada, y el mensaje de arranque se construye campo a campo (`research.md` D11)

### Engine y PRAGMAs

- [ ] T010 Implementar la creación del engine en `src/dynamic_thermal_charge/persistence/engine.py`, usando exclusivamente la API síncrona de SQLAlchemy. Prohibido cualquier uso de la API asíncrona: reintroduciría `greenlet`, que exige compilador en la Pi (`research.md` D3)
- [ ] T011 Añadir en `engine.py` el listener del evento `connect` que fije en cada conexión SQLite `PRAGMA foreign_keys=ON`, `journal_mode=WAL`, `synchronous=FULL` y `busy_timeout=5000` (`research.md` D6)
- [ ] T012 Escribir `tests/test_persistence_schema.py::test_sqlite_pragmas` que abra una base de datos SQLite real en `tmp_path` a través del engine y compruebe **cada** PRAGMA por separado. `foreign_keys` viene desactivado por defecto en SQLite: sin esta comprobación las claves ajenas del modelo serían decorativas
- [ ] T013 Añadir en `engine.py` la traducción de excepciones en la frontera: ninguna excepción de SQLAlchemy, `pg8000` o `sqlite3` cruza hacia el dominio; se convierte en el error de dominio correspondiente
- [ ] T014 Escribir en `tests/test_persistence_failures.py` la prueba de que la traducción de T013 no deja escapar ninguna excepción de librería, inyectando fallos de conexión y de ejecución

### Esquema

- [ ] T015 Definir en `src/dynamic_thermal_charge/persistence/schema.py` el `MetaData` y las tablas de configuración `installation`, `weather_config`, `heater`, `output_config` y `thermal_profile`, con tipos, `NOT NULL`, claves ajenas con su `ON DELETE` y restricciones únicas según `data-model.md`
- [ ] T016 Añadir en `schema.py` las tablas de histórico `forecast`, `plan`, `plan_slot`, `plan_allocation`, `output_transition` y `config_change`, con sus índices de retención. `plan_slot.heater_id`, `plan_allocation.heater_id` y `output_transition.heater_id` son **texto y no claves ajenas**, para que el histórico sobreviva al borrado de un acumulador
- [ ] T017 Restringir los `CHECK` del esquema al subconjunto que se expresa idénticamente en SQLite y PostgreSQL; documentar en el propio módulo qué invariantes se delegan al dominio y por qué (`data-model.md`, sección de validación por capas)
- [ ] T018 Añadir en `tests/test_persistence_schema.py` la comprobación de que las claves ajenas se aplican de verdad sobre SQLite: borrar una instalación arrastra sus acumuladores, e insertar un `output_config` huérfano falla

### Modelo de dominio y conversión

- [ ] T019 [P] Añadir el campo de retención a `AppConfig` en `src/dynamic_thermal_charge/models.py`, con validación en `__post_init__` (positivo o `None` para ilimitada). Es el **único** cambio autorizado en este fichero
- [ ] T020 [P] Crear `tests/test_models.py` con la prueba del nuevo campo de retención de `AppConfig`: valores válidos, `None` como ilimitada y valores rechazados. No va en `tests/test_thermal.py`, que cubre el modelo térmico y no los invariantes de configuración
- [ ] T021 Implementar en `src/dynamic_thermal_charge/persistence/mapping.py` la conversión fila → dataclass para toda la configuración, construyendo los `dataclass(frozen=True)` existentes sin modificarlos, de modo que sus `__post_init__` sigan siendo la última línea de defensa
- [ ] T022 Implementar en `mapping.py` la conversión inversa dataclass → parámetros de escritura
- [ ] T023 Implementar en `mapping.py` los ayudantes de frontera temporal: todo instante se escribe en UTC y se lee como `datetime` consciente de zona; los horarios `start_time` y `end_time` se almacenan como texto `HH:MM` porque son reglas, no instantes (`research.md` D8)
- [ ] T024 Escribir en `tests/test_persistence_schema.py` la prueba de ida y vuelta de instantes: un instante con zona sobrevive al viaje sin perder ni inventar zona, y un `datetime` ingenuo nunca sale de la capa de persistencia

### Validación de configuración completa

- [ ] T025 Extraer a `src/dynamic_thermal_charge/config.py` el validador de configuración completa, independiente del origen: alineación de horario con `slot_minutes`, unicidad de pines entre salidas `gpio`, y exigencia de proveedor meteorológico cuando existe algún perfil térmico. Debe lanzar `ConfigValidationError` con campo y acumulador
- [ ] T026 Ampliar `tests/test_config.py` con la cobertura del validador de T025 —cada invariante de FR-009, con su campo y acumulador en el mensaje— **sin** retirar todavía los casos de carga YAML, que siguen siendo válidos hasta T049

### Migraciones y puerta de versión

- [ ] T027 Crear el andamiaje de Alembic en `src/dynamic_thermal_charge/persistence/migrations/env.py` y `script.py.mako`, con `render_as_batch=True` para que las alteraciones de tabla funcionen en SQLite
- [ ] T028 Crear la revisión inicial en `src/dynamic_thermal_charge/persistence/migrations/versions/` que construya todas las tablas de T015 y T016
- [ ] T029 Implementar `src/dynamic_thermal_charge/persistence/gate.py`: lee `alembic_version` con Core y devuelve `ok`, `missing`, `behind` o `unknown` comparando con la constante de revisiones conocidas. **No importa Alembic** (`research.md` D4, D5)
- [ ] T030 Escribir `tests/test_persistence_gate.py` con los cuatro estados, incluido el caso `unknown` que debe rechazar el arranque, y comprobando que el módulo no importa Alembic

### Semilla

- [ ] T031 Implementar `src/dynamic_thermal_charge/persistence/seed.py` con la instalación de ejemplo completa y válida, equivalente a `examples/raspberry-pi.yaml`, y estrictamente idempotente: si ya existe configuración, no toca nada
- [ ] T032 Escribir `tests/test_persistence_seed.py`: siembra sobre base de datos vacía, segunda siembra que no modifica nada, y siembra que no sobrescribe una configuración editada

### Guardias arquitectónicas

- [ ] T033 Escribir `tests/test_persistence_failures.py::test_nucleo_no_importa_sqlalchemy` que verifique que ningún módulo fuera de `persistence/` importa `sqlalchemy`, recorriendo el árbol de `src/` de forma estática
- [ ] T034 Añadir la prueba de que `import dynamic_thermal_charge` y la importación de `scheduler`, `thermal` y `models` **no** cargan `sqlalchemy` en `sys.modules`, garantizando la importación perezosa y el presupuesto de arranque de `research.md` D13

**Checkpoint**: la frontera de persistencia existe y está probada. El comportamiento visible
del programa sigue siendo el actual.

---

## Phase 3: US2 — Inicializar una instalación nueva desde cero (P1)

**Goal**: pasar de base de datos vacía a base de datos lista para arrancar, con un comando.

**Independent Test**: sobre una base de datos vacía, `db init` seguido de `config show`
muestra una instalación completa y válida.

- [ ] T035 [US2] Implementar en `src/dynamic_thermal_charge/persistence/repository.py` la operación de inicialización: aplica migraciones pendientes, siembra si no hay configuración, y conserva intactos los datos existentes
- [ ] T036 [US2] Implementar `dtc db init` en `src/dynamic_thermal_charge/cli.py`, informando de qué se ha creado, qué se ha migrado y qué se ha omitido, y devolviendo la revisión de esquema resultante
- [ ] T037 [US2] Implementar `dtc db upgrade` en `cli.py`: solo migra, nunca siembra
- [ ] T038 [US2] Implementar `ConfigRepository.current()` en `repository.py`, devolviendo configuración validada y revisión, o lanzando. Nunca devuelve configuración parcialmente válida
- [ ] T039 [US2] Implementar `dtc config show [--heater <id>]` en `cli.py`, mostrando la configuración completa, la revisión de configuración y la revisión de esquema, sin credenciales ni cadena de conexión
- [ ] T040 [US2] Escribir en `tests/test_cli_config_commands.py` los casos de `db init` (base vacía, repetición idempotente, base con configuración propia), `db upgrade` y `config show` (completo, filtrado por acumulador, acumulador inexistente enumerando los existentes)
- [ ] T041 [US2] Añadir a `tests/test_cli_config_commands.py` la comprobación de que `config show` no emite jamás la cadena de conexión ni la clave de AEMET, y que de AEMET solo aparece el **nombre** de la variable de entorno
- [ ] T042 [US2] Verificar con un test que `db init`, `db upgrade` y `config show` **no construyen ningún driver de salida**. Principio I: ninguna ruta administrativa puede conmutar hardware
- [ ] T043 [US2] Cubrir los códigos de salida del contrato para estos comandos: `0`, `1` base de datos inalcanzable, `2` revisión de esquema desconocida, `3` sin configuración, `4` acumulador inexistente (`contracts/cli.md`)

**Checkpoint**: existe una base de datos utilizable e inspeccionable. El servicio sigue
arrancando con YAML.

---

## Phase 4: US1 — Arrancar el servicio con la configuración en base de datos (P1)

**Goal**: la base de datos es la única fuente de configuración. Desaparece el YAML del
runtime.

**Independent Test**: con una base de datos sembrada, el plan generado es idéntico al que
producía la configuración equivalente en fichero.

- [ ] T044 [US1] Definir el `Protocol` `ConfigRepository` en `src/dynamic_thermal_charge/persistence/__init__.py` según `contracts/repository.md`, e inyectarlo en lugar de la carga de fichero
- [ ] T045 [US1] Reestructurar `src/dynamic_thermal_charge/cli.py` en subcomandos (`db`, `config`, `history`, `run`, `gpio-self-test`) según `contracts/cli.md`, retirando el argumento posicional de ruta de configuración
- [ ] T046 [US1] Implementar `dtc run [--controller | --watch-weather] [--driver …] [--start …] [--log-level …]` leyendo la configuración de la base de datos, conservando **sin cambios** la semántica de planificación, watchdog, controlador y selección de driver
- [ ] T047 [US1] Hacer que un argumento posicional con aspecto de ruta produzca un error que explique el cambio y remita a `dtc db init`, en lugar de un error genérico de argumentos
- [ ] T048 [US1] Registrar al arrancar el origen efectivo de la configuración usando `describe()`: motor, modo local o remoto, host y nombre de base de datos. Nunca la URL
- [ ] T049 [US1] Eliminar `load_config` y todo el código de carga y validación de fichero YAML de `src/dynamic_thermal_charge/config.py`, conservando únicamente el validador de configuración completa de T025, y retirar de `tests/test_config.py` los casos de carga de fichero que quedan huérfanos sin relajar la cobertura de invariantes de T026
- [ ] T050 [US1] Retirar `PyYAML` de `dependencies` en `pyproject.toml`, ahora que ningún módulo del runtime lo importa
- [ ] T051 [US1] Adaptar `src/dynamic_thermal_charge/service.py` para recibir la configuración del repositorio inyectado, sin cambiar la firma de `ChargeController` ni de los drivers
- [ ] T052 [US1] Aplicar la puerta de versión de esquema de T029 en el arranque de `run`: `missing` sugiere `db init`, `behind` sugiere `db upgrade`, `unknown` rechaza el arranque
- [ ] T053 [US1] Escribir en `tests/test_persistence_repository.py` la equivalencia de plan: la misma instalación cargada desde base de datos produce exactamente el mismo plan que producía la configuración en fichero, usando como referencia los casos de `tests/test_scheduler.py`
- [ ] T054 [US1] Añadir a `tests/test_cli_config_commands.py` los casos de arranque: variable de entorno ausente, motor no admitido, esquema ausente, migración pendiente, esquema desconocido, base de datos sin configuración y configuración almacenada inválida. En **todos** ellos, ninguna salida se activa
- [ ] T055 [US1] Añadir la cabecera a `examples/home.yaml` y `examples/raspberry-pi.yaml` indicando que el runtime ya no los lee y que se conservan como documentación y referencia de la semilla
- [ ] T056 [US1] Actualizar `tests/test_service.py` y `tests/test_watchdog.py` al repositorio inyectado, sin relajar ninguna aserción existente
- [ ] T057 [US1] Escribir la guardia simétrica a T033 en `tests/test_persistence_failures.py`: ningún módulo de `src/` importa `yaml`, ni lee una ruta de fichero de configuración, ni importa un servidor HTTP. Cubre SC-001 y FR-015, que hasta ahora solo estaban garantizados por la ausencia de código
- [ ] T058 [US1] Añadir a `tests/test_state.py` la regresión de durabilidad del plan activo con el repositorio inyectado (FR-020, hasta ahora sin ninguna tarea): escritura atómica, recuperación tras reinicio simulado, y plan ilegible o de versión desconocida tratado como ausencia de plan

**Checkpoint**: no queda configuración en fichero. `PyYAML` fuera del runtime.

---

## Phase 5: US6 — Sobrevivir a una base de datos que falla (P1)

**Goal**: una base de datos remota que se cae no apaga el servicio ni deja salidas
indeterminadas.

**Independent Test**: inyectando un repositorio que falla de forma controlada, se observa la
continuidad del proceso y el estado de las salidas.

- [ ] T059 [US6] Implementar en `src/dynamic_thermal_charge/service.py` el tratamiento de `ConfigStoreUnavailableError` como **única** excepción transitoria: conserva el plan en ejecución y reintenta con la cadencia configurada, sin terminar el proceso
- [ ] T060 [US6] Registrar la entrada y la salida del estado degradado una sola vez por transición, nunca en cada iteración del bucle de control, en `src/dynamic_thermal_charge/service.py`
- [ ] T061 [US6] Recalcular el plan con la configuración vigente al recuperarse el acceso, registrando la recuperación, en `src/dynamic_thermal_charge/service.py`
- [ ] T062 [US6] Confirmar que las demás excepciones de dominio (`ConfigStoreEmptyError`, `SchemaVersionError`, `ConfigValidationError`) son terminales para la operación en curso y nunca activan una salida
- [ ] T063 [US6] Crear los dobles de prueba de los tres `Protocol` en `tests/conftest.py`, configurables para fallar de forma determinista, sin importar SQLAlchemy
- [ ] T064 [US6] Escribir en `tests/test_persistence_failures.py` los casos: caída en caliente con plan válido en curso, recuperación posterior, arranque sin plan válido con todas las salidas apagadas, y ausencia de registro repetido de la degradación. Reloj y `wait` inyectados
- [ ] T065 [US6] Añadir a `tests/test_persistence_failures.py` el caso de base de datos que se llena durante una escritura: el plan activo y el estado de las salidas no se corrompen
- [ ] T066 [US6] Escribir en `tests/test_state.py` el caso de dos escritores concurrentes de la copia local del plan activo: ningún lector observa un plan truncado ni mezclado, y la última escritura gana. Cubre el edge case corregido de `spec.md`

**Checkpoint**: el modo de fallo que introduce PostgreSQL remoto está cubierto.

---

## Phase 6: US3 — Editar la configuración sin salir de la línea de comandos (P1)

**Goal**: llevar la instalación sembrada a la instalación real sin escribir SQL.

**Independent Test**: aplicar cambios válidos e inválidos y comprobar con `config show` qué
quedó almacenado y qué se rechazó.

- [ ] T067 [US3] Implementar `ConfigRepository.set_field()` en `repository.py` con bloqueo optimista por revisión: lee la revisión, valida la configuración completa resultante dentro de la transacción y escribe con `WHERE revision = <leída>` incrementándola (`research.md` D9)
- [ ] T068 [US3] Implementar `add_heater()` y `remove_heater()` en `repository.py`. La baja arrastra salida y perfil térmico y **conserva el histórico**
- [ ] T069 [US3] Registrar cada edición aplicada en `config_change` con revisión anterior y posterior, entidad, campo, valor anterior, valor nuevo, acción e instante
- [ ] T070 [US3] Implementar el rechazo de valores con aspecto de credencial o de cadena de conexión en cualquier campo de configuración, en `src/dynamic_thermal_charge/persistence/repository.py`, indicando que los secretos se sirven por variable de entorno
- [ ] T071 [US3] Implementar `dtc config set <campo> <valor> [--heater <id>]` en `cli.py`, informando del campo, su valor anterior y el nuevo
- [ ] T072 [US3] Implementar `dtc config add-heater` en `cli.py` con las opciones de nombre, modelo, prioridad, carga objetivo, habilitación, tipo de salida, pin, nivel activo y campos del perfil térmico
- [ ] T073 [US3] Implementar `dtc config remove-heater` en `cli.py`, exigiendo confirmación explícita salvo `--yes`
- [ ] T074 [US3] Hacer en `src/dynamic_thermal_charge/cli.py` que un campo o un acumulador inexistente produzca un error que enumere los campos admitidos o los acumuladores existentes, sin modificar nada
- [ ] T075 [US3] Escribir en `tests/test_persistence_repository.py` los casos de edición: campo de instalación, campo de acumulador que no toca a los demás, alta, baja con histórico conservado, y baja del último acumulador dejando una configuración válida con plan vacío
- [ ] T076 [US3] Añadir a `tests/test_persistence_repository.py` los casos de rechazo: resolución de intervalo que desalinearía el horario ya configurado, pin ya usado por otro acumulador, identificador de acumulador duplicado, y valor que parece un secreto. En todos, el almacén queda **exactamente** como estaba
- [ ] T077 [US3] Añadir a `tests/test_persistence_repository.py` la prueba de atomicidad: una interrupción a mitad de la edición deja la configuración anterior íntegra
- [ ] T078 [US3] Añadir la prueba de conflicto concurrente: dos ediciones sobre la misma revisión, la segunda se rechaza con `ConfigConflictError` y no pierde silenciosamente la primera
- [ ] T079 [US3] Añadir a `tests/test_persistence_repository.py` la prueba de que una edición no altera el plan en curso y toma efecto en el siguiente recálculo
- [ ] T080 [US3] Cubrir en `tests/test_cli_config_commands.py` los códigos de salida `4`, `5`, `6`, `7` y `8` del contrato, y verificar que ningún comando de edición construye un driver de salida

**Checkpoint**: la instalación real se configura sin tocar la base de datos a mano.

---

## Phase 7: US4 — Auditar qué pasó una noche concreta (P2)

**Goal**: reconstruir una noche completa a partir solo del histórico.

**Independent Test**: ejecutar el controlador contra un plan conocido con reloj controlado y
consultar el histórico resultante.

- [ ] T081 [US4] Definir el `Protocol` `HistoryRecorder` en `persistence/__init__.py` según `contracts/repository.md`
- [ ] T082 [US4] Implementar `record_forecast()` en `src/dynamic_thermal_charge/persistence/history.py`, guardando fecha, temperaturas, municipio cuando lo haya y el origen `aemet`, `simulated` o `fallback`
- [ ] T083 [US4] Exponer en `src/dynamic_thermal_charge/weather.py` el origen efectivo de la previsión para que `record_forecast` distinga proveedor real de valor de reserva, sin añadir I/O al núcleo
- [ ] T084 [US4] Implementar `record_plan()` en `history.py`, guardando el plan con su ventana, la revisión de configuración con la que se generó, la previsión asociada, sus intervalos y los minutos solicitados, asignados y no atendidos por acumulador
- [ ] T085 [US4] Implementar `record_transition()` en `history.py`, insertando solo cuando el estado cambia y nunca para el estado inicial `OFF` del arranque
- [ ] T086 [US4] Garantizar que **ningún** método de `HistoryRecorder` propaga excepciones: un fallo de escritura se registra como `ERROR` y devuelve un resultado nulo o vacío
- [ ] T087 [US4] Inyectar `HistoryRecorder` en `service.py` y en `src/dynamic_thermal_charge/controller.py` sin cambiar su firma pública ni la de los drivers
- [ ] T088 [US4] Escribir `tests/test_persistence_history.py`: plan registrado con su previsión y sus minutos no atendidos, previsión de reserva marcada como tal, transiciones registradas solo al cambiar, y estado inicial no registrado
- [ ] T089 [US4] Añadir en `tests/test_persistence_failures.py` la prueba de que un fallo de escritura de histórico se registra como error y **no** interrumpe la planificación ni la conmutación de salidas
- [ ] T090 [US4] Añadir a `tests/test_persistence_history.py` la prueba de reconstrucción completa: a partir solo del histórico se determina por qué cada acumulador cargó o no en una ventana concreta (SC-004)

**Checkpoint**: el histórico es auditable y no puede tumbar el control.

---

## Phase 8: US5 — Evitar que el histórico agote el almacenamiento (P2)

**Goal**: retención acotada y automática sin intervención manual.

**Independent Test**: con un histórico sembrado que abarca más que la retención y un reloj
controlado, disparar la limpieza y comprobar qué sobrevive.

- [ ] T091 [US5] Implementar `prune()` en `history.py` siguiendo la tabla «Alcance de la retención, por tabla» de `data-model.md`: elimina de `plan` (con `plan_slot` y `plan_allocation` en cascada), `forecast` y `output_transition`, **excluye `config_change`**, y devuelve el recuento por tabla
- [ ] T092 [US5] Garantizar que `prune()` nunca elimina la configuración de la instalación ni ningún plan con `window_end > now`, según la regla de identificación del plan activo de `data-model.md`. Protege también los planes futuros ya calculados, no solo el más reciente
- [ ] T093 [US5] Tratar la retención ilimitada como no eliminar nada, en `src/dynamic_thermal_charge/persistence/history.py`
- [ ] T094 [US5] Invocar la limpieza en la inicialización y después de cada refresco de plan, sin temporizador dedicado (`research.md` D10), registrando cuántos registros se han eliminado
- [ ] T095 [US5] Implementar `dtc history prune` en `cli.py`, informando del recuento eliminado
- [ ] T096 [US5] Escribir `tests/test_persistence_retention.py`: eliminación por antigüedad con reloj controlado, conservación del plan activo y de la configuración, retención ilimitada, y reducción drástica de la retención que elimina un volumen grande sin bloquear la planificación
- [ ] T097 [US5] Escribir en `tests/test_persistence_retention.py` la comprobación de volumen de SC-005, que hasta ahora no tenía ninguna tarea. Sembrar un año sintético de histórico para la instalación de referencia de cuatro acumuladores y comprobar que el tamaño del fichero SQLite resultante no supera el límite declarado en `research.md` D10

**Checkpoint**: el histórico está acotado. La feature es funcionalmente completa.

---

## Phase 9: Migración del despliegue y cierre

**Purpose**: dejar utilizable la Raspberry Pi ya desplegada y la documentación coherente.

- [ ] T098 [P] Añadir `DTC_DATABASE_URL` a `deploy/environment.example` con ejemplos de ambos motores y el recordatorio del modo `0600`
- [ ] T099 Actualizar `deploy/systemd/dynamic-thermal-charge.service`: `ExecStart` sin ruta de configuración, `ExecStartPre` que valide configuración y esquema, y `ReadWritePaths` que cubra el directorio de la base de datos
- [ ] T100 Actualizar `scripts/install-service.sh` conforme al FR-030 corregido: instalar el extra `db`, crear `/var/lib/dynamic-thermal-charge` con el propietario correcto, imprimir al terminar el único comando de inicialización que el operador debe ejecutar, y **no** ejecutar `db init` automáticamente si detecta un `config.yaml` previo, para no interponer datos de ejemplo entre el operador y la configuración real que va a reintroducir
- [ ] T101 Ampliar `tests/test_deployment.py` para verificar la unidad y el instalador nuevos, incluida la ausencia de ruta de configuración en `ExecStart`
- [ ] T102 Reescribir la sección de configuración de `README.md`: origen en base de datos, ambos motores, `DTC_DATABASE_URL`, y los comandos `db`, `config` y `history`
- [ ] T103 Añadir a `README.md` el procedimiento de actualización desde una versión con YAML, con el aviso **explícito** de que la configuración debe reintroducirse a mano porque no existe importación automática, y el énfasis en verificar pines BCM, `active_high` y potencia máxima antes de conectar hardware (FR-031)
- [ ] T104 [P] Enlazar la constitución desde `README.md`, resolviendo el punto que quedó pendiente en su Sync Impact Report. **No mapea a ningún requisito de esta feature**: es deuda de documentación heredada, y su omisión no afecta a la definición de fase completa
- [ ] T105 Escribir `tests/test_postgres_compat.py` con el marcador `postgres`, omitida salvo que exista `DTC_TEST_POSTGRES_URL`: mismo esquema, misma semilla y mismo plan que en SQLite
- [ ] T106 Escribir en `tests/test_persistence_schema.py` la comprobación de equivalencia entre dialectos que **corre siempre y sin servidor**: compilar el mismo conjunto de sentencias del esquema y de las consultas del repositorio contra los dialectos de SQLite y de PostgreSQL y verificar que ambas compilan y son equivalentes. Es la mitad de SC-002 que no dependía de un servidor y que faltaba
- [ ] T107 **MANUAL, requiere hardware — diferida, fuera del criterio de fase completa.** Medir en la Raspberry Pi el coste de arranque y la memoria residente frente al presupuesto declarado de <5 s y <80 MB, y anotar el resultado real en `research.md` D13. No es un test y no forma parte de la suite: el Principio V prohíbe tests que requieran Raspberry Pi. `/speckit-implement` debe dejarla sin marcar
- [ ] T108 Ejecutar `pytest` completo y confirmar que pasa sin red, sin PostgreSQL y sin hardware

---

## Dependencies

```text
Phase 1 Setup
     ↓
Phase 2 Foundational  ← bloquea todo lo demás
     ↓
Phase 3 US2 (inicializar)   ← crea la base de datos
     ↓
Phase 4 US1 (arrancar desde BD)   ← necesita que la BD exista
     ↓
Phase 5 US6 (fallo de BD)   ← necesita la ruta de arranque de US1
     ↓
Phase 6 US3 (editar)   ← necesita current() de US2 y el validador de T025
     ↓
Phase 7 US4 (auditar)   ← independiente de US3; necesita el esquema de histórico
     ↓
Phase 8 US5 (retención)   ← necesita el histórico de US4
     ↓
Phase 9 Despliegue y cierre
```

Dependencias que conviene no perder de vista:

- **T012 antes de cualquier test de integración**: sin el listener de PRAGMAs, los tests de
  claves ajenas darían falsos positivos.
- **T026 y T049 son un par**: la cobertura del validador nuevo entra antes de retirar la del
  cargador viejo, para que en ningún commit intermedio baje la cobertura de FR-009.
- **T025 antes de T067**: la edición valida con el mismo validador que la carga; si se
  duplicase la lógica, una edición podría aceptar lo que el arranque rechaza.
- **T049 y T050 después de T046**: no se puede retirar la carga YAML ni `PyYAML` antes de que
  exista la ruta de arranque que la sustituye.
- **T029 antes de T052**: la puerta de versión debe existir antes de aplicarse en el arranque.
- **T086 antes de T087**: el recorder debe ser incapaz de lanzar antes de inyectarlo en el
  bucle de control, o un fallo de auditoría podría tumbar el servicio.
- **T057 después de T049 y T050**: la guardia de que nadie importa `yaml` solo tiene sentido
  cuando ya se ha retirado la carga de fichero y la dependencia.
- **T097 después de T088**: medir el volumen sin la retención implementada mediría el caso
  que precisamente se quiere evitar.
- **US4 no depende de US3**: se pueden solapar si interesa.

## Parallel Execution Examples

Dentro de la fase 1: T003, T004 y T005 en paralelo.

Dentro de la fase 2: T019 y T020 en paralelo con el bloque de esquema (T015–T018), porque
`models.py` y `schema.py` son ficheros distintos. El bloque de URL (T007–T009) es paralelo al
de engine (T010–T014) siempre que T006 esté hecho.

Dentro de la fase 9: T098 y T104 en paralelo con el resto.

No paralelizar dentro de un mismo fichero: T015, T016 y T017 tocan `schema.py`; T021, T022 y
T023 tocan `mapping.py`; casi toda la fase 6 toca `cli.py` y `repository.py`.

## Implementation Strategy

**MVP mínimo utilizable**: fases 1, 2, 3 y 4. Al terminarlas el servicio arranca y planifica
desde base de datos, y se puede inspeccionar la configuración. Es el punto en el que ya no
hay YAML.

**Primer punto de despliegue razonable**: añadir la fase 5. Sin ella, un corte de red con
PostgreSQL remoto es un modo de fallo no cubierto y no debería llegar a una instalación real.

**Completar la fase**: fases 6, 7, 8 y 9. La 9 es obligatoria antes de actualizar la
Raspberry ya desplegada: sin T103 el operador no tiene el aviso de que su configuración no se
migra sola.

**Fases posteriores del proyecto** (fuera de este `tasks.md`): backend FastAPI, frontend
Angular e integración con Home Assistant.

## Resumen

| Fase | Historia | Tareas | Prioridad |
| --- | --- | ---: | --- |
| 1 Setup | — | 5 (T001–T005) | — |
| 2 Foundational | — | 29 (T006–T034) | bloqueante |
| 3 | US2 inicializar | 9 (T035–T043) | P1 |
| 4 | US1 arrancar desde BD | 15 (T044–T058) | P1 |
| 5 | US6 fallo de BD | 8 (T059–T066) | P1 |
| 6 | US3 editar por CLI | 14 (T067–T080) | P1 |
| 7 | US4 auditar | 10 (T081–T090) | P2 |
| 8 | US5 retención | 7 (T091–T097) | P2 |
| 9 Despliegue y cierre | — | 11 (T098–T108) | — |
| **Total** | | **108** | |

De las 108, **107 son ejecutables en máquina de desarrollo**. T107 requiere la Raspberry Pi,
está marcada como manual y queda fuera del criterio de fase completa.

Cobertura de requisitos: los 40 requisitos funcionales y los 12 criterios de éxito de
`spec.md` tienen al menos una tarea asociada, tras cerrar en la revisión de
`/speckit-analyze` los huecos de FR-015, FR-020, SC-001, SC-002 y SC-005.

Los caminos de fallo del Principio I y IV están cubiertos por T014, T042, T054, T057, T064,
T065, T066, T076, T080 y T089.

## Revisión de `/speckit-analyze`

Las cinco tareas siguientes se añadieron al cerrar los hallazgos del análisis de
consistencia, y son las únicas que no proceden del desglose original:

| Tarea | Hallazgo | Qué cerraba |
| --- | --- | --- |
| T057 | F6, F15 | SC-001 y FR-015 solo estaban garantizados por la ausencia de código, sin guardia |
| T058 | F3 | FR-020 no tenía **ninguna** tarea asociada |
| T066 | F9 | el edge case de dos escritores del plan activo no estaba cubierto, y prometía una serialización que no existe |
| T097 | F5 | SC-005 no tenía ninguna tarea: nadie medía el volumen del histórico |
| T106 | F7 | SC-002 solo se verificaba en una suite omitida por defecto |

Los demás hallazgos se cerraron reformulando artefactos, sin añadir tareas: F1 (FR-030
contradecía a T096), F2 (el plan activo no era identificable, así que T089 no era
implementable), F4 (alcance de la retención por tabla), F8 (`dtc` pasa a alias real
declarado en T001), F10 (T020 tenía destino ambiguo), F11 (T107 marcada como manual), F12
(formato de `weekdays`), F13 (nota de orden de los FR) y F14 (T100 anotada como deuda de
documentación).
