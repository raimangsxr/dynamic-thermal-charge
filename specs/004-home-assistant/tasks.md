---

description: "Task list for 004-home-assistant"
---

# Tasks: Integración con Home Assistant

**Input**: Design documents from `/specs/004-home-assistant/`

**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/`. Las features
`001-config-database`, `002-config-api` y `003-web-panel` están implementadas.

**Tests**: OBLIGATORIOS. El Principio V y FR-042–FR-044 exigen tests deterministas sin broker,
red, Home Assistant, base de datos remota ni hardware.

**Organization**: tareas agrupadas por historia. Las historias P1 se ordenan por dependencia y
riesgo: US2 (honestidad) → US1 (publicación) → US3 (órdenes) → US5 (conexión real) → US6
(despliegue). US4, P2, cierra después el lazo térmico sobre la infraestructura ya probada.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: paralelizable; toca ficheros distintos y no depende de otra tarea incompleta.
- **[Story]**: historia de usuario de `spec.md` (`US1`…`US6`).
- Cada tarea indica los ficheros exactos que debe tocar.

---

## Phase 1: Setup

**Purpose**: declarar el borde opcional y preparar dobles compartidos sin cambiar comportamiento.

- [X] T001 Añadir `paho-mqtt>=2.1,<3` al extra opcional `mqtt` y al extra `dev`, conservando vacío el runtime base, en `pyproject.toml`
- [X] T002 Crear el paquete `src/dynamic_thermal_charge/mqtt/` y definir en `src/dynamic_thermal_charge/mqtt/__init__.py` el `MqttClient` `Protocol` y errores de dominio sin importar `paho`
- [X] T003 [P] Añadir a `tests/conftest.py` un cliente MQTT en memoria que registre en orden voluntad, conexión, publicaciones, suscripciones y mensajes inyectados, sin abrir sockets

---

## Phase 2: Foundational (prerrequisitos bloqueantes)

**Purpose**: modelo, migración, repositorios y nombres estables compartidos por todas las historias.

**CRITICAL**: ninguna historia empieza antes de completar esta fase.

### Tests primero

- [X] T004 [P] Escribir en `tests/test_models.py`, `tests/test_config.py` y `tests/test_cli_config_commands.py` los casos de `indoor_topic` opcional y vacío normalizado a nulo, tolerancia positiva, rango plausible ordenado y defaults compatibles
- [X] T005 [P] Escribir en `tests/test_persistence_schema.py` las aserciones de la revisión `0003`: cuatro columnas nuevas, `indoor_reading.heater_pk` entero como PK/FK a `heater.id`, borrado en cascada y migración sin alterar datos existentes
- [X] T006 [P] Crear `tests/test_persistence_indoor.py` con reemplazo atómico por acumulador, lectura coherente de todas las medidas, invalidación, cascada al borrar un acumulador y paridad SQLite/PostgreSQL mediante los dobles existentes
- [X] T007 [P] Crear `tests/test_mqtt_topics.py` con asuntos propios y de descubrimiento, segmento fijo `installation`, ids derivados solo de ese segmento y del id de dominio, e independencia del nombre visible, prefijo, PK y orden

### Implementación fundacional

- [X] T008 Añadir `indoor_topic` a `Heater`, la política interior a `SiteConfig` y `IndoorReading` inmutable con `received_at` local en `src/dynamic_thermal_charge/models.py`
- [X] T009 Añadir validación completa y mensajes accionables para tolerancia y rango plausible en `src/dynamic_thermal_charge/config.py`
- [X] T010 Implementar columnas, tabla y relaciones de `indoor_reading` en `src/dynamic_thermal_charge/persistence/schema.py`
- [X] T011 Crear `src/dynamic_thermal_charge/persistence/migrations/versions/0003_indoor_temperature.py` y añadir `0003` a `src/dynamic_thermal_charge/persistence/gate.py`, con upgrade y downgrade conservadores
- [X] T012 Incorporar los cuatro campos a las conversiones y listas permitidas de `src/dynamic_thermal_charge/persistence/mapping.py` y `src/dynamic_thermal_charge/persistence/repository.py`
- [X] T013 Implementar en `src/dynamic_thermal_charge/persistence/repository.py` el protocolo y repositorio de últimas medidas con `upsert`, `invalidate` y `read_all`, traduciendo excepciones SQLAlchemy a errores de dominio
- [X] T014 Implementar en `src/dynamic_thermal_charge/mqtt/topics.py` constructores puros de asuntos con segmento `installation` e ids de dispositivo y `unique_id` que no dependan del nombre visible ni del prefijo

**Checkpoint**: el esquema `0003` y las fronteras compartidas están listos; aún no hay conexión MQTT.

---

## Phase 3: US2 — Que Home Assistant tampoco mienta (Priority: P1)

**Goal**: representar ausencia de prueba como `unavailable`, cubriendo por separado la muerte del
publicador y la falta de vigencia del controlador.

**Independent Test**: con el cliente en memoria, cruzar publicador conectado/desconectado con las
cuatro situaciones del controlador y verificar valores y disponibilidad publicados.

### Tests primero

- [X] T015 [P] [US2] Crear `tests/test_mqtt_discovery.py` con la matriz de disponibilidad: salida y potencia exigen `availability` y `state_available`; configuración, salud y sospecha múltiple exigen solo `availability`
- [X] T016 [P] [US2] Crear `tests/test_mqtt_publisher.py` con controlador sano, degradado, silencioso y nunca visto, comprobando que estado no vigente no publica salida apagada ni potencia cero
- [X] T017 [US2] Añadir a `tests/test_mqtt_publisher.py` la última voluntad `offline`, QoS 1 y retenida, y comprobar que se declara antes de cualquier intento de conexión
- [X] T018 [US2] Añadir a `tests/test_mqtt_publisher.py` base de datos inaccesible y esquema pendiente, futuro o inválido: todo queda no disponible, se registra una vez por transición y no se inventa estado
- [X] T019 [P] [US2] Añadir a `tests/test_mqtt_discovery.py` la entidad de sospecha de más de un controlador y los cuatro valores exactos de salud aptos para automatizaciones

### Implementación

- [X] T020 [US2] Implementar los bloques de disponibilidad de uno y dos niveles y las entidades de salud en `src/dynamic_thermal_charge/mqtt/discovery.py`
- [X] T021 [US2] Implementar en `src/dynamic_thermal_charge/mqtt/publisher.py` la proyección honesta del estado, sin convertir `None` en `false` ni publicar potencia cuando la vigencia falta
- [X] T022 [US2] Implementar en `src/dynamic_thermal_charge/mqtt/service.py` la preparación de última voluntad antes de conectar y las transiciones retenidas de `availability` y `state_available`
- [X] T023 [US2] Añadir a `src/dynamic_thermal_charge/mqtt/publisher.py` la degradación por base de datos o esquema, con registro solo al entrar y salir y recuperación automática

**Checkpoint**: el mecanismo que impide mentir existe y está probado antes de publicar el catálogo completo.

---

## Phase 4: US1 — Ver la instalación sin configurar nada (Priority: P1) 🎯 MVP observable

**Goal**: descubrir automáticamente un dispositivo por instalación y uno por acumulador, con
estado completo, ids estables y retirada de huérfanos.

**Independent Test**: arrancar contra el cliente en memoria con cuatro acumuladores y comprobar
todos los mensajes de descubrimiento y estado, su retención y los cambios al añadir o eliminar uno.

### Tests primero

- [X] T024 [P] [US1] Completar `tests/test_mqtt_discovery.py` con todas las entidades de instalación y acumulador de FR-003/FR-004, agrupación `via_device`, plantillas, unidades y estabilidad de `unique_id` al renombrar la instalación o cambiar el prefijo
- [X] T025 [P] [US1] Añadir a `tests/test_mqtt_publisher.py` el estado retenido de instalación y acumuladores: salida, potencia y porcentaje, límite, ventana, previsión y origen, y minutos solicitados, asignados y no atendidos
- [X] T026 [US1] Añadir a `tests/test_mqtt_publisher.py` alta dinámica de acumulador y baja con payload vacío retenido para cada asunto de descubrimiento retirado
- [X] T027 [US1] Añadir a `tests/test_mqtt_publisher.py` reinicio de Home Assistant simulado, comprobando que descubrimiento, disponibilidad y último estado se publican con QoS 1 y retención
- [X] T028 [US1] Añadir a `tests/test_mqtt_publisher.py` la cadencia por defecto de 15 s con reloj y espera inyectados, sin dormir en tiempo real

### Implementación

- [X] T029 [US1] Construir en `src/dynamic_thermal_charge/mqtt/discovery.py` las definiciones completas de dispositivos y entidades según `contracts/mqtt.md`
- [X] T030 [US1] Implementar en `src/dynamic_thermal_charge/mqtt/publisher.py` las cargas JSON deterministas de instalación y acumulador a partir de configuración, latido, plan y previsión existentes
- [X] T031 [US1] Componer en `src/dynamic_thermal_charge/mqtt/publisher.py` los lectores de configuración, salud, último plan y previsión sin importar FastAPI ni duplicar sus reglas de vigencia
- [X] T032 [US1] Implementar en `src/dynamic_thermal_charge/mqtt/publisher.py` el inventario anterior, descubrimiento de altas y tombstones retenidos de bajas
- [X] T033 [US1] Implementar en `src/dynamic_thermal_charge/mqtt/service.py` el ciclo periódico con reloj y espera inyectables, conservando el proceso ante fallos transitorios
- [X] T034 [US1] Suscribir los asuntos de mando e interiores declarados después del descubrimiento en `src/dynamic_thermal_charge/mqtt/service.py`, sin aplicar todavía sus cargas

**Checkpoint**: el catálogo completo aparece y se mantiene con un cliente MQTT falso.

---

## Phase 5: US3 — Automatizar la carga desde Home Assistant (Priority: P1)

**Goal**: aceptar solo `enabled` y `target_charge`, mediante configuración validada y sin acceso a
ninguna salida.

**Independent Test**: inyectar órdenes válidas, inválidas, prohibidas, concurrentes y dirigidas a
un acumulador inexistente; verificar configuración, registros y republicación del valor real.

### Tests primero

- [X] T035 [P] [US3] Crear `tests/test_mqtt_commands.py` con `ON`/`OFF`, carga objetivo entre 0 y 1, payload vacío/no numérico/fuera de rango y acumulador inexistente
- [X] T036 [US3] Añadir a `tests/test_mqtt_commands.py` la lista blanca estructural: `power`, `pin`, `active_high` y cualquier campo futuro se rechazan y no crean ni modifican nada
- [X] T037 [US3] Añadir a `tests/test_mqtt_commands.py` conflicto de revisión: releer y reintentar exactamente una vez; un segundo conflicto se rechaza sin bucle
- [X] T038 [US3] Añadir a `tests/test_mqtt_commands.py` órdenes contradictorias en orden, rechazo previo de toda orden con `retain=true`, republicación QoS 1 retenida del valor almacenado y una integración que demuestre que el cambio aceptado aparece en el siguiente plan

### Implementación

- [X] T039 [US3] Implementar en `src/dynamic_thermal_charge/mqtt/commands.py` rechazo y registro del indicador `retain` antes del parseo, seguido del parseo estricto de asuntos y payloads con lista blanca inmutable
- [X] T040 [US3] Aplicar órdenes mediante `ConfigRepository.set_field` y su validación existente en `src/dynamic_thermal_charge/mqtt/commands.py`, sin importar controlador ni drivers
- [X] T041 [US3] Implementar el único reintento por conflicto de revisión y los registros accionables sin secretos en `src/dynamic_thermal_charge/mqtt/commands.py`
- [X] T042 [US3] Integrar la cola ordenada de mensajes de mando en `src/dynamic_thermal_charge/mqtt/service.py`
- [X] T043 [US3] Republicar desde `src/dynamic_thermal_charge/mqtt/publisher.py` con QoS 1 y retención el estado real del acumulador tras toda orden aplicada, rechazada o recibida como retenida

**Checkpoint**: Home Assistant modifica configuración, nunca salidas, y nunca conserva un valor ordenado pero rechazado.

---

## Phase 6: US5 — Conectar con un Home Assistant remoto (Priority: P1)

**Goal**: conectar por red local o túnel, soportar TLS, caída y recuperación, y tratar credenciales
rechazadas con una espera fija de cinco minutos.

**Independent Test**: simular broker inaccesible, desconexión y rechazo de credenciales en el
adaptador falso, verificando esperas y orden de recuperación sin red real.

### Tests primero

- [X] T044 [P] [US5] Crear `tests/test_mqtt_settings.py` con variables obligatorias, defaults, rangos, TLS, usuario sin contraseña, contraseña no mostrada en `repr` ni errores y cadencia configurable
- [X] T045 [P] [US5] Crear `tests/test_mqtt_client.py` comprobando MQTT v5, `connect_async`, `loop_start`, TLS, autenticación, QoS 1, `reconnect_delay_set(1, 120)` y PUBACK aceptado o rechazado por permisos mediante un doble de `paho`
- [X] T046 [US5] Añadir a `tests/test_mqtt_client.py` rechazo de credenciales: un registro al entrar, reintentos exactamente cada 300 s con espera inyectada y un registro al recuperarse
- [X] T047 [US5] Añadir a `tests/test_mqtt_publisher.py` reconexión con orden exacto `availability online` → todo el descubrimiento → estado, incluidas suscripciones renovadas

### Implementación

- [X] T048 [US5] Implementar carga y validación del entorno en `src/dynamic_thermal_charge/mqtt/settings.py`, manteniendo credenciales fuera de base de datos y registros
- [X] T049 [US5] Implementar en `src/dynamic_thermal_charge/mqtt/client.py` el adaptador `paho` síncrono MQTT v5 y traducir callbacks, excepciones y PUBACK fallido a errores de dominio sin registrar payloads ni secretos
- [X] T050 [US5] Configurar reconexión exponencial para inalcanzabilidad y espera fija de credenciales con reloj/espera inyectables en `src/dynamic_thermal_charge/mqtt/client.py`
- [X] T051 [US5] Implementar el orden completo de conexión y reconexión en `src/dynamic_thermal_charge/mqtt/service.py`
- [X] T052 [US5] Añadir el subcomando `dtc mqtt` y su composición perezosa de extras, repositorios y servicio en `src/dynamic_thermal_charge/cli.py`

**Checkpoint**: una caída del túnel se recupera sola y unas credenciales incorrectas no crean un bucle apretado.

---

## Phase 7: US6 — Desplegarlo sin tocar lo que ya funciona (Priority: P1)

**Goal**: instalar un cuarto servicio independiente, sin grupo GPIO, compilador, arranque ni
habilitación automáticos.

**Independent Test**: inspeccionar y probar el instalador y la unidad, y demostrar estáticamente
que el paquete MQTT no puede construir un camino hacia el hardware.

### Tests primero

- [X] T053 [P] [US6] Crear `tests/test_mqtt_guards.py` que falle si `mqtt/` importa `controller`, `drivers` o `gpio_driver`, si módulos ajenos importan `paho`, o si el núcleo deja de importarse sin el extra `mqtt`
- [X] T054 [P] [US6] Ampliar `tests/test_deployment.py` con la cuarta unidad: usuario restringido, sin grupo `gpio`, sin dependencia de controlador/API/panel y `ExecStart` mediante `dtc mqtt`
- [X] T055 [US6] Añadir a `tests/test_deployment.py` la opción `--with-mqtt`: instala el extra y la unidad pero no ejecuta compilador, no migra, no arranca ni habilita ningún servicio

### Implementación

- [X] T056 [US6] Crear `deploy/systemd/dynamic-thermal-charge-mqtt.service` con endurecimiento coherente con las unidades existentes y sin acceso a GPIO
- [X] T057 [US6] Añadir las variables MQTT, comentarios de secretos y ejemplo TLS a `deploy/environment.example`
- [X] T058 [US6] Añadir `--with-mqtt` y la instalación del extra puro Python a `deploy/install-service.sh`, sin cambiar el comportamiento de las opciones existentes
- [X] T059 [US6] Verificar aislamiento de ciclos de vida y manejo de parada limpia en `tests/test_mqtt_publisher.py` y `src/dynamic_thermal_charge/mqtt/service.py`

**Checkpoint**: el publicador se instala y se detiene de forma independiente y no puede alcanzar el hardware.

---

## Phase 8: US4 — Cerrar el lazo con la temperatura real (Priority: P2)

**Goal**: llevar la última medida desde MQTT a la base de datos y desde allí al recálculo del
controlador, con selección pura y reserva obligatoria.

**Independent Test**: calcular con medida válida, ausente, vieja e inválida, y comprobar demanda,
invalidación persistida y registros únicos de entrada y recuperación de reserva.

### Tests primero

- [X] T060 [P] [US4] Crear `tests/test_mqtt_indoor.py` con alta, cambio y eliminación dinámica de `indoor_topic`, baja de la suscripción anterior, reloj local, payload válido y reemplazo de la fila anterior
- [X] T061 [US4] Añadir a `tests/test_mqtt_indoor.py` payload vacío, no numérico e implausible: registro apropiado e invalidación atómica inmediata de cualquier lectura anterior
- [X] T062 [P] [US4] Ampliar `tests/test_thermal.py` con selección de medida ausente, justo en el límite de antigüedad, vieja y fuera del rango vigente, usando `at` explícito y sin leer reloj
- [X] T063 [US4] Añadir a `tests/test_thermal.py` el cálculo con medida válida bajo objetivo, en objetivo y sobre objetivo; este último queda en `min_charge`, no en cero
- [X] T064 [US4] Añadir a `tests/test_thermal.py` la regresión fuerte de FR-023: sin `indoor_topic` ni mapa interior, cada demanda coincide exactamente con el comportamiento anterior
- [X] T065 [P] [US4] Crear `tests/test_cli_indoor.py` que compruebe que cada recálculo lee `IndoorReadingRepository`, pasa datos al modelo y continúa con reserva si la lectura falla o falta
- [X] T066 [US4] Añadir a `tests/test_cli_indoor.py` registros una sola vez al entrar en reserva, silencio durante repeticiones y un solo registro al recuperar medida real
- [X] T067 [P] [US4] Ampliar `tests/test_api_config.py` según `specs/004-home-assistant/contracts/config.md`: lectura y escritura de los cuatro campos, `indoor_topic` vacío convertido a nulo, rechazos y revisión optimista
- [X] T068 [P] [US4] Ampliar `frontend/src/app/config/config.spec.ts` con visualización y edición de los cuatro parámetros, eliminación de `indoor_topic` al vaciarlo, errores por campo y conservación del formulario ante rechazo

### Implementación

- [X] T069 [US4] Implementar recepción, validación, `upsert` e invalidación en `src/dynamic_thermal_charge/mqtt/indoor.py` y reconciliar altas, cambios, bajas y `unsubscribe` en `src/dynamic_thermal_charge/mqtt/service.py`
- [X] T070 [US4] Implementar en `src/dynamic_thermal_charge/thermal.py` la selección pura de lecturas por `at`, tolerancia y rango, devolviendo temperatura utilizable y motivo de reserva
- [X] T071 [US4] Ampliar `ThermalDemandEngine.calculate` en `src/dynamic_thermal_charge/thermal.py` con el mapa opcional de grados interiores, preservando denominador, factor, límites y ruta anterior
- [X] T072 [US4] Leer las medidas al inicio de cada recálculo, registrar transiciones de reserva y pasarlas a `_build_plan` en `src/dynamic_thermal_charge/cli.py`
- [X] T073 [US4] Implementar `specs/004-home-assistant/contracts/config.md` en `src/dynamic_thermal_charge/api/schemas.py`, `src/dynamic_thermal_charge/api/routes/config.py`, `frontend/src/app/core/api.types.ts` y `frontend/src/app/config/config.html`

**Checkpoint**: el lazo se cierra entre procesos sin introducir MQTT ni I/O en el modelo térmico.

---

## Phase 9: Documentación y cierre

- [X] T074 Añadir a `README.md` instalación, variables, identidad estable, entidades, órdenes permitidas y retenidas rechazadas, túnel/TLS, temperaturas interiores, reserva y diagnóstico de `specs/004-home-assistant/quickstart.md`
- [X] T075 [P] Añadir a `README.md` permisos mínimos del broker, MQTT v5/QoS 1, diagnóstico de PUBACK rechazado, órdenes nunca retenidas y credenciales protegidas
- [X] T076 Ejecutar la suite Python completa con `pytest` y corregir únicamente regresiones de la feature en `src/` y `tests/` hasta cumplir FR-042–FR-044
- [X] T077 Ejecutar `npm test` y `npm run build` desde `frontend/`, verificando que el panel anterior sigue pasando y que los campos nuevos respetan el presupuesto existente
- [ ] T078 **MANUAL, requiere dispositivo y Home Assistant.** Seguir `specs/004-home-assistant/quickstart.md` en una Raspberry Pi: comprobar descubrimiento, muerte y caída del túnel, mantener el publicador detenido 2 horas verificando que plan y salidas no cambian, órdenes —incluida una retenida rechazada— y efecto de orden y temperatura sobre el siguiente plan
- [ ] T079 **MANUAL, requiere Raspberry Pi 2B.** Medir y registrar en `specs/004-home-assistant/research.md` el arranque y RSS terminados: publicador <5 s y <70 MB, y cuatro servicios juntos <250 MB, incluyendo comandos, fecha y versiones del entorno

---

## Dependencies

```text
Phase 1 Setup
     ↓
Phase 2 Foundational
     ↓
Phase 3 US2 honestidad
     ↓
Phase 4 US1 descubrimiento/publicación
     ↓
Phase 5 US3 órdenes
     ↓
Phase 6 US5 conexión y reconexión
     ↓
Phase 7 US6 despliegue
     ↓
Phase 8 US4 lazo térmico (P2)
     ↓
Phase 9 documentación y cierre
```

Dependencias internas importantes:

- T008–T013 preceden cualquier publicación: configuración y medida deben tener una única forma de dominio y persistencia.
- T014 precede T020 y T029: disponibilidad y descubrimiento deben usar ids y asuntos estables ya probados.
- T020–T023 preceden T029–T034: primero se define cuándo una entidad puede afirmar un valor; después se amplía el catálogo.
- T029–T034 preceden T039–T043: las órdenes necesitan suscripciones y republicación ya operativas.
- T048–T051 implementan el adaptador real después de que toda la semántica esté probada contra el `Protocol` falso.
- T060–T071 preceden T072: el controlador no compone persistencia y modelo hasta que invalidación, selección y cálculo sean puros y estén probados.
- T067 y T068 preceden T073: los contratos de API y panel se fijan por test antes de exponer los campos.

## Parallel Execution Examples

- En Phase 2, T004–T007 pueden escribirse en paralelo; después T010/T011, T012/T013 y T014 tocan áreas distintas.
- En US2, T015, T016 y T019 son paralelizables antes de la implementación.
- En US1, T024 y T025 son paralelizables; T026–T028 comparten `test_mqtt_publisher.py` y van en serie.
- En US5, T044 y T045 son paralelizables.
- En US6, T053 y T054 son paralelizables; unidad e instalador pueden implementarse en paralelo tras sus tests.
- En US4, los bloques MQTT (T060–T061), térmico (T062–T064), controlador (T065–T066), API (T067) y panel (T068) pueden arrancar en paralelo.

No paralelizar tareas que modifican el mismo fichero, aunque sus requisitos parezcan independientes.

## Implementation Strategy

**MVP observable**: completar Setup, Foundational, US2 y US1. Contra el cliente en memoria ya queda
demostrado que Home Assistant descubriría todo sin mentir sobre la vigencia.

**Primer incremento operable**: añadir US3 y US5. El publicador se conecta a un broker real,
recupera caídas y acepta las dos órdenes permitidas.

**Primer incremento desplegable**: añadir US6. La cuarta unidad llega al dispositivo sin tocar el
controlador ni requerir compilador.

**Feature completa**: añadir US4 y Phase 9. La temperatura cruza entre procesos por la base de
datos y modifica el siguiente plan con reserva probada. T078 valida el comportamiento real y T079
valida los límites de plataforma; ambas quedan marcadas como manuales porque requieren la Pi.

## Resumen

| Fase | Historia | Tareas | Prioridad |
| --- | --- | ---: | --- |
| 1 Setup | — | 3 | — |
| 2 Foundational | — | 11 | bloqueante |
| 3 | US2 honestidad | 9 | P1 |
| 4 | US1 publicación | 11 | P1 |
| 5 | US3 órdenes | 9 | P1 |
| 6 | US5 conexión | 9 | P1 |
| 7 | US6 despliegue | 7 | P1 |
| 8 | US4 temperatura | 14 | P2 |
| 9 cierre | — | 6 | — |
| **Total** | | **79** | |

De las 79 tareas, 77 son ejecutables en desarrollo; T078 y T079 requieren dispositivo.
Cada historia declara un test independiente y todas las tareas usan checkbox, id secuencial,
etiqueta de historia cuando corresponde y ruta de fichero.
