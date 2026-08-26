# Implementation Plan: Integración con Home Assistant

**Branch**: `004-home-assistant` | **Date**: 2026-08-27 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/004-home-assistant/spec.md`

**Constitución aplicada**: 1.1.0 · **Depende de**: `001`, `002`, `003` (implementadas)

## Summary

Publicar la instalación en Home Assistant por mensajería, con descubrimiento automático, y aceptar
de vuelta **dos** órdenes: habilitar un acumulador y ajustar su carga objetivo. Además, cerrar el
lazo: consumir la temperatura interior real de cada estancia y usarla en el modelo térmico, con
reserva obligatoria al comportamiento anterior.

Dos cosas hacen esta fase distinta de las anteriores.

**La primera**: el broker puede estar al otro lado de un túnel. Eso convierte la resistencia a la
desconexión en un requisito de primer orden, y hace crítica la **última voluntad**: sin ella, un
túnel caído dejaría a Home Assistant mostrando el último valor conocido para siempre — el mismo
fallo que las tres fases anteriores se dedicaron a evitar, reapareciendo un metro más allá. La
respuesta es **disponibilidad en dos niveles**, porque hay dos formas distintas de perder la verdad:
que muera el publicador, y que muera el controlador con el publicador vivo.

**La segunda**: es la primera fase desde la 1 que **toca el núcleo**. El modelo térmico gana un
parámetro. Se mantiene puro —las medidas llegan como dato— y con la garantía escrita de que un
acumulador sin temperatura declarada calcula *exactamente* lo mismo que antes.

Enfoque técnico: **`paho-mqtt` sincrónico**, sin ninguna dependencia transitiva, en un servicio
propio. Migración `0003` con cuatro columnas nuevas y valores por defecto que no cambian nada.

Detalle y mediciones en [research.md](./research.md); columnas y proyecciones en
[data-model.md](./data-model.md); contratos en [contracts/](./contracts/).

## Technical Context

**Language/Version**: Python 3.12+ (sin cambio).

**Primary Dependencies**:

| Dependencia | Ámbito | Justificación (Principio VI) |
| --- | --- | --- |
| `paho-mqtt>=2.1,<3` | extra `mqtt` | Cliente de mensajería. Python puro y **sin ninguna dependencia**: verificado en entorno limpio |
| `amqtt` | **descartado** | Arrastra siete dependencias, y **reintroduciría `pyyaml`**, retirado deliberadamente en la fase 1 |
| `gmqtt` | **descartado** | Declara `codecov` y `coverage` como dependencias de runtime |
| API asíncrona | **prohibida** | El proyecto es síncrono de extremo a extremo desde la fase 1, para no reintroducir `greenlet` |

**Storage**: cuatro columnas nuevas y la migración `0003`. Ninguna tabla nueva.

**Testing**: `pytest`. El cliente de mensajería detrás de un `Protocol` con doble en memoria. Sin
broker, sin red, sin Home Assistant.

**Target Platform**: Raspberry Pi 2B con systemd, **cuarta unidad independiente**. El broker puede
ser local o alcanzable por túnel.

**Project Type**: librería con CLI, API HTTP, panel web y publicador de mensajería. Proyecto único
más `frontend/`.

**Performance Goals**: publicación cada 15 s por defecto. Lo que importa es la huella: **< 70 MB**
de RSS y arranque **< 5 s** en la Pi.

Medido: `import paho.mqtt.client` en 0,060–0,072 s; RSS 29,0 MB con `paho` sobre 8,7 MB de base;
**46,8 MB con `paho` + SQLAlchemy**, que es el proceso real. Sumado a los ~45 MB del controlador y
~65 MB de la API, el conjunto de los cuatro servicios ronda **155 MB de 1 GB**, en torno al 15 %.
Esa era la comprobación que faltaba antes de añadir un cuarto proceso.

**Constraints**:

- Ninguna operación del publicador acciona una salida ni construye el medio para hacerlo.
- Las órdenes se limitan a **dos** campos, por **lista blanca**.
- Sin vigencia del estado, las entidades afectadas quedan **no disponibles**, nunca «apagadas» ni a
  cero.
- La última voluntad se declara **antes** de conectar, con retención.
- Al reconectar, descubrimiento **antes** que estado.
- Los asuntos de mando **no** se retienen.
- La antigüedad de una medida se mide con el instante de recepción del dispositivo.
- Un acumulador sin temperatura declarada calcula exactamente lo mismo que antes.
- Ningún test usa broker, red, Home Assistant ni hardware.

**Scale/Scope**: una instalación, un Home Assistant, 4-10 acumuladores.

## Constitution Check

*GATE: superado antes de Phase 0 y revisado tras Phase 1.*

### I. Seguridad física primero (fail-safe) — PASA

| Regla | Cómo se cumple |
| --- | --- |
| Ninguna interfaz activa una salida sin pasar por el controlador fail-safe | El paquete del publicador **no importa** `drivers`, `gpio_driver` ni `controller`. Misma guardia estática que ya protege a `api/`. Las órdenes se aplican como configuración y pasan por el planificador |
| Home Assistant no puede tocar lo que importa | **Lista blanca de dos campos**. Potencia máxima, pin y nivel activo quedan fuera **por construcción**, no por comprobación. Una lista negra dejaría fuera un campo futuro por omisión; una blanca, por defecto |
| Ambigüedad hacia el estado seguro | Sin prueba, **no disponible**: ni «apagado» ni cero. Un binario en «apagado» engaña a una automatización; uno no disponible la detiene, que es lo correcto |
| Un fallo externo no puede alterar el control | El publicador es un proceso aparte, sin dependencia declarada del controlador. Detenerlo horas no produce ningún cambio observable (SC-010) |
| Nada oculta una situación peligrosa | La sospecha de dos controladores se publica como entidad apta para notificar (FR-012) |
| El planificador nunca se queda sin plan | Cualquier fallo de temperatura interior produce reserva y registro, nunca excepción (FR-027) |

### II. Núcleo puro, hardware y red en los bordes — PASA

- El publicador es un borde nuevo, confinado en su paquete, el único que importa `paho`.
- **El modelo térmico sigue sin I/O**: las medidas llegan como parámetro. Quien las recoge es el
  publicador. Es la diferencia entre ampliar el núcleo y contaminarlo.
- Consume el `ConfigRepository`, el `SchemaGate` y las lecturas de estado ya existentes, a través de
  sus `Protocol`. No reimplementa validación.
- El cliente de mensajería vive detrás de un `Protocol` inyectable: los tests no tocan un broker.
- Ninguna excepción de `paho` cruza hacia el dominio.

### III. Configuración validada y explícita — PASA

- La línea es la de todo el proyecto: **entorno** para lo que hace falta antes de leer el almacén
  y para los secretos; **base de datos** para lo que describe la instalación (research D9).
- Las credenciales del broker vienen del mecanismo protegido del despliegue y **no** se escriben en
  la base de datos, el repositorio ni los logs.
- El publicador **no necesita ninguna credencial de Home Assistant**: la temperatura llega por el
  mismo canal. Un secreto menos que gestionar.
- Toda orden se valida con el repositorio existente, sin relajar nada.
- Esquema versionado: la migración `0003` añade columnas con valores por defecto que **no cambian el
  comportamiento efectivo de nada**, que es lo que FR-023 exige.
- El publicador no migra el esquema, y sobre uno que no comprende no publica.

### IV. Continuidad y degradación observable — PASA

- **La disponibilidad en dos niveles es literalmente esta fase**: hacer observable desde fuera, y
  para una automatización, la diferencia entre «esto pasa» y «esto es lo último que se supo».
- Reconexión con espera creciente, sin terminar el proceso (FR-031, FR-032).
- Un rechazo de credenciales se trata **distinto** de un broker inalcanzable: no entra en el bucle
  apretado, porque llenaría registros y algunos brokers bloquean al cliente (FR-033).
- La entrada y salida de la reserva térmica se registran **una vez por transición**, misma
  disciplina que el watchdog meteorológico y la degradación por base de datos.
- Un valor implausible se registra como **error**, porque indica un sensor averiado y no una
  ausencia normal.

### V. Tests deterministas sin hardware — PASA

- Doble en memoria del cliente de mensajería. Ningún test abre un socket.
- El modelo térmico se prueba como función: la tabla completa de medida válida, ausente, vieja y
  absurda, sin ningún doble de red.
- Cobertura obligatoria en lo que miente si falla: los dos niveles de disponibilidad cruzados con
  publicador vivo y muerto, que la última voluntad se declare **antes** de conectar, el orden al
  reconectar, la lista blanca, y los cuatro caminos de reserva.
- **Y la garantía de FR-023 como test**, comparando la demanda antes y después con la misma entrada.

### VI. Simplicidad y stdlib primero — PASA

- **Una** dependencia nueva, en extra opcional, Python puro, **sin dependencias transitivas**. La
  elección se hizo comparando cuatro candidatos: dos quedaron fuera por lo que arrastran.
- El núcleo se importa y ejecuta sin ella.
- La reconexión con espera creciente es la de la librería, no una propia: verificada la firma
  `reconnect_delay_set(min_delay=1, max_delay=120)`.
- YAGNI: sin forzado manual, sin varias instalaciones por broker, sin control de acceso por
  entidad, sin componente propio de Home Assistant que empaquetar y mantener.

### Restricciones de plataforma — PASA

- Sin compilador: `paho` es Python puro.
- El dispositivo gana un cuarto proceso, medido: ~155 MB de 1 GB entre los cuatro.
- La constitución 1.1.0 ya prevé la integración domótica como borde; no hace falta enmienda.

**Resultado de la puerta: PASA.** Dos desviaciones, registradas abajo.

## Project Structure

### Documentation (this feature)

```text
specs/004-home-assistant/
├── plan.md, spec.md
├── research.md          # Phase 0: 12 decisiones, con paho medido
├── data-model.md        # Phase 1: cuatro columnas y las proyecciones
├── quickstart.md        # Phase 1: túnel, entidades, lazo cerrado, diagnóstico
├── contracts/
│   ├── mqtt.md          # Asuntos, retención, última voluntad, descubrimiento, órdenes
│   └── thermal.md       # El único cambio en el núcleo
├── checklists/requirements.md
└── tasks.md             # Phase 2 — lo crea /speckit-tasks
```

### Source Code (repository root)

```text
src/dynamic_thermal_charge/
├── thermal.py                       # + temperatura interior opcional. ÚNICO cambio del núcleo
├── models.py                        # + indoor_topic y los tres parámetros de la instalación
├── config.py                        # + validación del rango plausible
├── cli.py                           # + subcomando `mqtt`
├── scheduler.py, controller.py, drivers.py, service.py, state.py, weather.py   # SIN CAMBIOS
├── persistence/
│   ├── schema.py                    # + cuatro columnas
│   ├── mapping.py, repository.py    # + los campos nuevos
│   ├── gate.py                      # KNOWN_REVISIONS pasa a tres
│   └── migrations/versions/0003_indoor_temperature.py     # NUEVO
├── api/                             # SIN CAMBIOS
└── mqtt/                            # NUEVO — único paquete que importa paho
    ├── __init__.py                  # Protocol del cliente + errores de dominio
    ├── settings.py                  # entorno: broker, credenciales, cifrado, prefijos
    ├── client.py                    # paho detrás del Protocol; última voluntad y reconexión
    ├── topics.py                    # asuntos e identificadores ESTABLES
    ├── discovery.py                 # definiciones de entidad y disponibilidad en dos niveles
    ├── publisher.py                 # el bucle: leer, publicar, suscribirse
    ├── commands.py                  # LISTA BLANCA de dos campos
    └── indoor.py                    # medidas recibidas, con su antigüedad y plausibilidad

frontend/                            # SIN CAMBIOS
deploy/systemd/dynamic-thermal-charge-mqtt.service    # NUEVO
scripts/install-service.sh                            # + --with-mqtt
README.md                                             # + sección de Home Assistant

tests/
├── test_thermal.py                  # + la tabla de temperatura interior y FR-023
├── test_mqtt_settings.py, test_mqtt_topics.py, test_mqtt_discovery.py
├── test_mqtt_publisher.py           # disponibilidad, última voluntad, orden al reconectar
├── test_mqtt_commands.py            # lista blanca, conflicto, republicación
├── test_mqtt_indoor.py              # ausente, vieja, absurda, recuperación
├── test_mqtt_guards.py              # sin drivers; núcleo sin el extra
└── test_deployment.py               # + la cuarta unidad
```

**Structure Decision**: toda la mensajería en `mqtt/`, el único paquete autorizado a importar
`paho`, igual que `persistence/` con SQLAlchemy y `api/` con FastAPI. Esa concentración es lo que
hace verificable con un test estático que **ninguna ruta de mensajería puede accionar una salida**.

`mqtt/topics.py` merece existir aparte aunque sea pequeño: ahí viven los identificadores de entidad,
y si cambian, las automatizaciones que el operador ya escribió dejan de funcionar sin ningún aviso.
Concentrarlos hace que un cambio sea visible en cualquier revisión.

## Complexity Tracking

| Violación | Por qué es necesaria | Alternativa más simple rechazada porque |
| --- | --- | --- |
| Tocar el modelo térmico, que es el componente más delicado y que llevaba tres fases intacto | Es la mejora funcional con más valor real del proyecto: una estancia que ya está caliente deja de cargarse como si estuviera fría. Mitigado: el modelo sigue siendo una función sin I/O, las medidas llegan como parámetro, y **FR-023 exige por test que un acumulador sin temperatura declarada calcule exactamente lo mismo que antes** | Dejar el lazo abierto mantendría el núcleo intacto y desperdiciaría los sensores que el usuario ya tiene, siguiendo la instalación cargando a ciegas. El usuario lo pidió con reserva obligatoria, que es la forma correcta de pedirlo |
| Un cuarto proceso en un dispositivo con 1 GB | Es lo que mantiene la E/S de red hacia el exterior —a través de un túnel, la dependencia menos fiable del sistema— fuera del proceso cuyo fail-safe no es negociable. Medido: los cuatro juntos ~155 MB, el 15 % | Publicar desde el controlador ahorraría el proceso y metería reconexiones a un broker remoto en el bucle que conmuta relés. Publicar desde la API la convertiría en dos cosas y dejaría a Home Assistant sin datos al pararla. Ambas se ofrecieron al usuario y eligió la separación |
| Disponibilidad en dos niveles, en lugar de una sola | Hay **dos** formas distintas de perder la verdad, y una sola no cubre ambas: con solo la última voluntad, un controlador muerto y un publicador vivo publicaría «apagado» sin prueba; con solo el nivel del estado, un publicador muerto congelaría el último valor para siempre | Un nivel único es más corto de escribir y deja uno de los dos agujeros abierto, con la particularidad de que el dato falso no llega a un panel donde alguien lo lea con criterio, sino a una automatización que actúa |
