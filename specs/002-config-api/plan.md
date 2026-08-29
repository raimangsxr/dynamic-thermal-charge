# Implementation Plan: API HTTP de estado y configuración

**Branch**: `002-config-api` | **Date**: 2026-08-26 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/002-config-api/spec.md`

**Constitución aplicada**: 1.1.0 · **Depende de**: `001-config-database` (implementada)

## Summary

Exponer el estado y la configuración de la instalación por HTTP, como **servicio independiente**
del controlador, comunicándose solo a través de la base de datos. Autenticación por token
compartido en variable de entorno. Sin control manual de salidas: la API no puede accionar nada.

El problema central no es servir HTTP, es la **honestidad del estado**. Con dos procesos
separados, la API deduce el estado de las salidas del histórico de transiciones, y con el
controlador muerto lo presentaría como actual. Se resuelve con una señal de vida que el
controlador publica en cada iteración de su bucle, y con una distinción explícita, en cada
respuesta, entre «esto está pasando ahora» y «esto es lo último que se supo».

Enfoque técnico: **FastAPI con manejadores síncronos** sobre el `ConfigRepository` ya existente,
modelos de Pydantic explícitos y separados del dominio, y `uvicorn` **pelado**. Una tabla nueva
(`controller_heartbeat`) y una migración (`0002`). El planificador, el modelo térmico y el
controlador no cambian de firma; el controlador solo gana la publicación del latido, inyectada.

Detalle y mediciones en [research.md](./research.md); tabla nueva y estado derivado en
[data-model.md](./data-model.md); contratos en [contracts/](./contracts/).

## Technical Context

**Language/Version**: Python 3.12+ (sin cambio)

**Primary Dependencies**:

| Dependencia | Ámbito | Justificación (Principio VI) |
| --- | --- | --- |
| `fastapi>=0.115,<1` | extra `api` | Enrutado, validación y descripción autodescriptiva. Python puro |
| `uvicorn>=0.30,<1` | extra `api` | Servidor ASGI. **PELADO**. Python puro; solo arrastra `click` y `h11` |
| `httpx2>=2.12` | extra `dev` | Cliente del test en proceso. Starlette 1.6 deprecia `httpx` y pide este |
| `uvicorn[standard]` | **PROHIBIDO** | Arrastra `uvloop` y `httptools`, **sin wheel `armv7l`**: exigirían compilador en la Pi |
| API asíncrona de SQLAlchemy | **PROHIBIDA** | Reintroduce `greenlet`, la otra dependencia sin wheel `armv7l` |

`pydantic-core`, la única pieza no-Python de la cadena, **sí publica wheels `armv7l`**
(cp310–cp315). Es lo que hace viable FastAPI en el objetivo de despliegue. Verificado además que
todas las transitivas son Python puro.

**Storage**: la de la fase 1. Una tabla nueva, `controller_heartbeat`, de una fila que se
actualiza y no crece; queda fuera de la retención.

**Testing**: `pytest`. Unitarios de la lógica de vigencia sin FastAPI; integración en proceso
sobre el transporte ASGI, **sin abrir ningún puerto**; guardias arquitectónicas.

**Target Platform**: Raspberry Pi 2B (ARMv7 32 bits, ~1 GB RAM) con systemd, **dos unidades
independientes**. Desarrollo en macOS y Linux.

**Project Type**: librería con CLI y API HTTP, proyecto único. Sin frontend en esta fase.

**Performance Goals**: un cliente consultando cada pocos segundos. Lo que importa es el
arranque y la memoria: **< 10 s** de arranque en la Pi y **< 120 MB** de RSS.

Medido en la máquina de desarrollo: importación completa de la pila 0,33 s en caliente y 2,06 s
en frío; RSS 52,7 MB con FastAPI, Uvicorn y SQLAlchemy cargados; 0,256 s desde construir la
aplicación hasta servir la primera respuesta. Sumado al controlador (~45 MB de la fase 1), el
conjunto ronda 100 MB de 1 GB.

**Constraints**:

- Ninguna ruta de la API construye un driver de salida.
- El token nunca aparece en respuestas ni en logs, y se compara en tiempo constante.
- El arranque se rechaza con token ausente, vacío, corto o de ejemplo.
- Con esquema desconocido o atrasado no se sirve ninguna operación, ni de lectura.
- La API nunca migra el esquema.
- Escucha en `127.0.0.1` por defecto; exponerla es un acto explícito.
- Orígenes externos admitidos: ninguno por defecto.
- Ningún test abre un puerto, usa red, PostgreSQL o hardware.

**Scale/Scope**: una instalación, un operador, un cliente habitual. ~17 000 actualizaciones
diarias del latido sobre la misma fila.

## Constitution Check

*GATE: superado antes de Phase 0 y revisado tras Phase 1.*

### I. Seguridad física primero (fail-safe) — PASA

| Regla | Cómo se cumple |
| --- | --- |
| Ninguna interfaz activa una salida sin pasar por el controlador fail-safe | **Ninguna ruta de la API importa ni construye un driver.** Verificable con la misma guardia estática que ya cubre `sqlalchemy`: ningún módulo de `api/` puede importar `drivers`, `gpio_driver` ni `controller` |
| Sin control manual | No hay boost ni override en esta fase (FR-005). El planificador es el único que decide |
| Ambigüedad hacia el estado seguro | Sin latido reciente, la API **no afirma** que ningún acumulador esté activo y **no publica** potencia. Dice «no lo sé», que es la respuesta segura |
| Esquema desconocido | No se sirve ninguna operación, ni de lectura (research D8). No se reinterpreta una columna para decidir qué mostrar como potencia máxima |
| La API no puede romper el control | Procesos y unidades separados; detenerla o hacerla fallar no toca el controlador (FR-002) |

### II. Núcleo puro, hardware y red en los bordes — PASA

- La API es un borde nuevo, confinado en `api/`, el único paquete que importa FastAPI.
- Consume el `ConfigRepository`, el `HistoryRecorder` y el `SchemaGate` ya existentes a través
  de sus `Protocol`. **No reimplementa validación** (FR-025).
- `HeartbeatPublisher` es un `Protocol` nuevo, inyectado en el controlador; `controller.py`,
  `scheduler.py`, `thermal.py` y `models.py` no cambian.
- Ninguna excepción de FastAPI, Starlette o Pydantic escapa hacia el dominio, y ninguna
  excepción de dominio llega cruda al cliente: se traducen a un cuerpo de error uniforme.

### III. Configuración validada y explícita — PASA

- La configuración de la API (dirección, puerto, token, tolerancia, orígenes) viene del
  **entorno**, no de la base de datos: son datos necesarios antes de poder leerla, y el token
  está explícitamente excluido del almacén (research D11).
- El token nunca se escribe en la base de datos, el repositorio ni los logs (FR-008).
- La API **no devuelve** la cadena de conexión ni el valor de la clave del proveedor; solo el
  nombre de su variable. Garantizado estructuralmente por usar modelos de respuesta explícitos
  en lugar de serializar el dominio (research D7), con un test que falla si aparece un campo
  nuevo sin decidir si se expone.
- La puerta de versión de esquema se aplica igual que en la CLI.
- Toda escritura valida la configuración completa resultante reutilizando el validador existente.

### IV. Continuidad y degradación observable — PASA

- La señal de vida es el mecanismo por el que la degradación se vuelve observable **desde
  fuera** del proceso degradado, que es lo que la fase 1 no podía ofrecer.
- La API distingue vivo, vivo-degradado, no-visto-nunca y silencioso (FR-017).
- **Publicar el latido no puede parar el control**: no propaga excepciones, misma regla que el
  `HistoryRecorder`. Un fallo se traduce en «no vigente» en la API, que es lo honesto.
- Una base de datos inaccesible produce un error acotado en el tiempo, no un cuelgue (FR-041),
  mediante los tiempos de espera del motor, no un temporizador que no aplicaría a un hilo
  bloqueado (research D6).

### V. Tests deterministas sin hardware — PASA

- Tres niveles (research D9). **Ningún test abre un puerto**: verificado que el cliente en
  proceso sirve la primera respuesta en 0,256 s sobre el transporte ASGI.
- Caminos de fallo con cobertura explícita: sin token, token incorrecto, token trivial al
  arrancar, base de datos inaccesible, esquema desconocido y atrasado, configuración inválida,
  controlador nunca visto, controlador silencioso, controlador degradado, latido del futuro,
  revisión obsoleta, y paginación fuera de rango.
- Reloj inyectado en toda la lógica de vigencia. Ningún test duerme en tiempo real.

### VI. Simplicidad y stdlib primero — PASA con desviación justificada

- Dos dependencias de runtime nuevas, ambas en el extra `api`, ambas Python puro. Ninguna en el
  runtime base, que sigue sin dependencias obligatorias.
- La comparación en tiempo constante usa `secrets` de la biblioteca estándar, no una dependencia
  de criptografía.
- Manejadores síncronos: evita `greenlet` y evita reescribir el acceso a datos.
- YAGNI respetado: sin WebSocket, sin SSE, sin usuarios ni roles, sin agregaciones de series
  temporales, sin servir ficheros estáticos, sin migración desde HTTP.
- La desviación —añadir un servidor web a un proyecto de dependencias mínimas— se registra en
  Complexity Tracking.

### Restricciones de plataforma — PASA

- La constitución 1.1.0 ya prevé API HTTP como borde, sin necesidad de enmienda.
- La instalación no requiere compilador: comprobada la disponibilidad de wheels para toda la
  cadena, con `uvicorn[standard]` explícitamente prohibido.
- Sin artefactos de frontend en esta fase.

**Resultado de la puerta: PASA.** Una desviación, registrada abajo.

## Project Structure

### Documentation (this feature)

```text
specs/002-config-api/
├── plan.md              # Este fichero
├── spec.md
├── research.md          # Phase 0: 12 decisiones con mediciones
├── data-model.md        # Phase 1: la tabla nueva y el estado derivado
├── quickstart.md        # Phase 1: puesta en marcha, despliegue y diagnóstico
├── contracts/
│   ├── http-api.md      # Contrato externo: rutas, códigos, errores
│   └── heartbeat.md     # Contrato interno: la señal de vida
├── checklists/
│   └── requirements.md
└── tasks.md             # Phase 2 — lo crea /speckit-tasks
```

### Source Code (repository root)

```text
src/dynamic_thermal_charge/
├── models.py, scheduler.py, thermal.py        # SIN CAMBIOS
├── controller.py, drivers.py, gpio_driver.py  # SIN CAMBIOS
├── weather.py, watchdog.py, state.py          # SIN CAMBIOS
├── config.py                                  # SIN CAMBIOS
├── service.py                                 # publica el latido cada iteración
├── cli.py                                      # gana el subcomando `api`
├── persistence/
│   ├── __init__.py                             # + HeartbeatPublisher, Heartbeat, Liveness
│   ├── schema.py                               # + tabla controller_heartbeat
│   ├── heartbeat.py                            # NUEVO — publicar y leer el latido
│   ├── history.py                              # + consultas paginadas de histórico
│   ├── gate.py                                 # KNOWN_REVISIONS pasa a dos entradas
│   └── migrations/versions/0002_controller_heartbeat.py   # NUEVO
└── api/                                        # NUEVO — único paquete que importa FastAPI
    ├── __init__.py                             # create_app()
    ├── settings.py                             # entorno: host, puerto, token, tolerancia, orígenes
    ├── security.py                             # token en tiempo constante; rechazo de triviales
    ├── liveness.py                             # vigencia; PURO, sin FastAPI ni base de datos
    ├── errors.py                               # dominio -> cuerpo de error uniforme
    ├── schemas.py                              # modelos de petición y respuesta explícitos
    ├── dependencies.py                         # apertura del almacén, puerta de esquema, reloj
    └── routes/
        ├── status.py, config.py, history.py, health.py

tests/
├── test_api_liveness.py          # vigencia: tolerancia, saltos de reloj, nunca visto
├── test_api_security.py          # sin token, incorrecto, trivial, tiempo constante, logs
├── test_api_status.py            # estado vigente y no vigente, potencia, plan, previsión
├── test_api_config.py            # lectura, edición, conflicto, secretos, nombres desconocidos
├── test_api_history.py           # paginación, rangos, orden, acumulador eliminado
├── test_api_errors.py            # BD caída, esquema desconocido, sin fugas ni trazas
├── test_api_guards.py            # sin drivers en api/, núcleo sin el extra api
├── test_persistence_heartbeat.py # publicar, leer, no propagar excepciones
└── test_deployment.py            # + la segunda unidad systemd

deploy/systemd/dynamic-thermal-charge-api.service   # NUEVO
deploy/install-service.sh                           # + opción --with-api
README.md                                           # + sección de la API
```

**Structure Decision**: proyecto único. Toda la superficie HTTP se concentra en
`src/dynamic_thermal_charge/api/`, el único paquete autorizado a importar FastAPI, igual que
`persistence/` es el único que importa SQLAlchemy. Esa concentración es lo que hace verificable
con un test estático que **ninguna ruta de la API puede accionar una salida**: basta comprobar
que ningún módulo de `api/` importa `drivers`, `gpio_driver` ni `controller`.

`api/liveness.py` se mantiene deliberadamente puro —sin FastAPI y sin acceso a datos— porque es
la lógica que decide si la API dice la verdad, y merece probarse como una función, no a través
de una petición HTTP.

## Migración del despliegue

| Artefacto | Cambio |
| --- | --- |
| `deploy/systemd/dynamic-thermal-charge-api.service` | **Nuevo**. Mismo usuario y mismo fichero de entorno; `TimeoutStartSec` holgado por el coste de arranque medido; sin `ExecStartPre` que duplique el arranque del intérprete; `ProtectSystem=strict` y `ReadWritePaths` sobre el directorio de la base de datos |
| `deploy/environment.example` | Añade `DTC_API_TOKEN` con instrucción de generarlo, y las variables de host, puerto, tolerancia y orígenes comentadas |
| `deploy/install-service.sh` | Opción `--with-api`: instala el extra `api`, instala la segunda unidad, **no** la arranca ni la habilita, y avisa de que hay que generar el token |
| `README.md` | Sección de la API: token, arranque, exposición en red con su advertencia explícita, y tabla de diagnóstico |
| `tests/test_deployment.py` | Verifica la segunda unidad, que no pasa fichero de configuración, y que el instalador no arranca nada |

Actualización desde la fase 1: `dtc db upgrade` aplica la revisión `0002`. Una base de datos de
la fase 1 se detecta como atrasada con la sugerencia de migrar, no como desconocida.

## Complexity Tracking

| Violación | Por qué es necesaria | Alternativa más simple rechazada porque |
| --- | --- | --- |
| Añadir un servidor web y un framework a un proyecto cuyo runtime base no tiene dependencias (Principio VI) | La feature es, por definición, una superficie HTTP. Mitigado: ambas dependencias en el extra `api`, ambas Python puro, el runtime base sigue sin dependencias, y el núcleo se importa sin ellas | Un servidor propio sobre `http.server` evitaría las dependencias, pero reimplementar enrutado, validación de entrada, negociación de contenido y documentación es mucho más código propio y mucha más superficie de error que dos dependencias maduras. Para una interfaz de red, ese es exactamente el sitio donde no conviene el código artesanal |
| Una tabla nueva y una migración solo para saber si el otro proceso está vivo | Es el coste de haber separado los procesos, que es lo que protege al controlador. Sin ella la API mentiría sobre el estado, y una mentira sobre qué relé está cerrado es peor que un «no lo sé» | Fichero de latido: no cruza a otra máquina, y con PostgreSQL remoto los dos procesos pueden estar separados. Consultar systemd: acopla al gestor de servicios y no distingue un proceso colgado de uno sano. Deducirlo del último plan o de la última transición: hasta tres horas de silencio normal, indistinguible de la muerte. Detalle en research.md D3 |
| Modelos de respuesta duplicados respecto al dominio | Es lo que hace que un campo nuevo en el dominio **no** aparezca solo en la superficie de red. Serializar el dominio convertiría cada campo futuro en una fuga por defecto, y ya hay dos secretos en juego | Serializar las dataclasses directamente: más corto, pero hace del modelo de dominio un contrato público y de FR-022 una promesa que nadie sostiene. Mitigado con un test que falla cuando aparece un campo de dominio sin decidir si se expone |
