# Implementation Plan: Integración con Home Assistant

**Branch**: `004-home-assistant` | **Date**: 2026-08-27 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/004-home-assistant/spec.md`

**Constitución aplicada**: 1.1.0 · **Depende de**: `001`, `002`, `003` (implementadas)

## Summary

Publicar la instalación en Home Assistant por MQTT Discovery y aceptar únicamente dos órdenes:
habilitar un acumulador y ajustar su carga objetivo. El publicador será un cuarto servicio,
independiente y sin acceso al hardware, con disponibilidad en dos niveles, última voluntad y
reconexión automática.

La temperatura interior llega por MQTT al publicador, pero el plan se calcula en el controlador.
La aclaración del 27 de agosto fija la base de datos compartida como frontera entre procesos: el
publicador valida y reemplaza atómicamente la última medida por acumulador; el controlador la lee
solo al recalcular el plan y la pasa como dato al modelo térmico. Una entrada inválida elimina la
medida anterior para que el siguiente cálculo use la reserva. MQTT nunca entra en el controlador.

Enfoque técnico: `paho-mqtt` 2.x sincrónico sobre MQTT v5 y QoS 1 en el extra opcional `mqtt`,
migración `0003` con cuatro columnas de configuración y una tabla de últimas medidas, repositorios
inyectables y tests sin broker, red, base de datos remota ni hardware.

## Technical Context

**Language/Version**: Python 3.12+.

**Primary Dependencies**:

| Dependencia | Ámbito | Justificación |
| --- | --- | --- |
| `paho-mqtt>=2.1,<3` | extra opcional `mqtt` | Cliente MQTT Python puro, sin dependencias transitivas |
| SQLAlchemy/Alembic existentes | extra `db` | Canal persistente y atómico entre los dos procesos ya separados |

**Storage**: SQLite local o PostgreSQL remoto. Migración `0003`: cuatro columnas de configuración
y tabla `indoor_reading` con una fila como máximo por acumulador.

**Testing**: `pytest`; cliente MQTT detrás de `Protocol`, dobles en memoria, relojes y esperas
inyectados. Ningún test abre sockets ni necesita Home Assistant.

**Target Platform**: Raspberry Pi 2B ARMv7, 1 GB, systemd; cuarto servicio independiente.

**Project Type**: paquete Python con CLI, controlador, API, panel web y publicador MQTT.

**Performance Goals**: publicación cada 15 s; publicador < 70 MB RSS y arranque < 5 s; los cuatro
servicios juntos < 250 MB RSS en la Pi 2B.

**Constraints**:

- El publicador no importa drivers, GPIO ni controlador y nunca acciona salidas.
- El controlador no importa `paho` ni se conecta al broker.
- Las órdenes usan lista blanca de `enabled` y `target_charge`.
- Las órdenes entrantes retenidas se rechazan antes de interpretar el payload.
- Los ids usan `installation` fijo y el id de dominio; no dependen de nombres, prefijos ni PK.
- Última voluntad antes de conectar; descubrimiento antes de estado al reconectar.
- Mensajes de mando nunca retenidos; descubrimiento, disponibilidad y estado sí retenidos.
- Publicaciones de descubrimiento, disponibilidad y estado con MQTT v5/QoS 1; un PUBACK rechazado
  se registra y no cuenta como éxito.
- Rechazo de credenciales: un registro por transición y reintento cada 300 s.
- Una entrada térmica inválida borra atómicamente la anterior; la antigüedad usa `received_at` local.
- El modelo térmico y el planificador siguen siendo deterministas y sin I/O.
- Un acumulador sin `indoor_topic` calcula exactamente lo mismo que antes.
- El publicador no migra el esquema y no publica datos si no lo comprende.

**Scale/Scope**: una instalación, un Home Assistant y 4-10 acumuladores.

## Constitution Check

*GATE: superado antes de Phase 0 y revisado tras Phase 1.*

### I. Seguridad física primero — PASA

- El paquete `mqtt/` no puede importar `drivers`, `gpio_driver` ni `controller`; una guardia
  estática lo verifica.
- Home Assistant solo modifica dos campos de configuración mediante el repositorio existente.
- Un valor desconocido se representa como no disponible, nunca como apagado o cero.
- Una entrada térmica ausente, vieja o inválida provoca reserva y nunca interrumpe el plan.

### II. Núcleo puro, hardware y red en los bordes — PASA

- `paho` queda confinado al adaptador MQTT del publicador.
- La base de datos es la frontera explícita entre procesos; el controlador lee medidas mediante un
  repositorio inyectado al recalcular, igual que lee configuración.
- La selección de medidas utilizables y el cálculo térmico reciben `at` y lecturas como datos; no
  leen reloj, broker ni base de datos.
- Ninguna excepción de `paho` o SQLAlchemy cruza al dominio.

### III. Configuración validada y explícita — PASA

- Credenciales, dirección, TLS y prefijos del broker proceden del entorno y nunca se registran.
- `indoor_topic`, tolerancia y rango plausible viven en la configuración versionada.
- La migración `0003` conserva datos y no cambia el cálculo efectivo hasta declarar un asunto.
- Las órdenes reutilizan validación, atomicidad y revisión optimista del repositorio.
- `indoor_topic` vacío se normaliza a nulo en CLI, API y panel para restaurar la ruta anterior.

### IV. Continuidad y degradación observable — PASA

- Broker o túnel inaccesible provoca reconexión exponencial sin terminar el proceso.
- Credenciales rechazadas se registran una vez y se reintentan cada cinco minutos; la recuperación
  se registra una vez.
- La última voluntad cubre la muerte del publicador y `state_available` la del controlador.
- La reserva térmica se registra solo al entrar o salir; una medida implausible se registra como
  error e invalida la anterior.

### V. Tests deterministas sin hardware — PASA

- Tests de contrato y unidad usan un cliente MQTT en memoria, repositorios temporales y reloj
  controlado.
- Cobertura explícita para última voluntad previa a conexión, retención, orden de reconexión,
  disponibilidad en dos niveles, rechazo de órdenes retenidas, PUBACK sin permisos, lista blanca,
  conflicto, invalidación atómica y cuatro caminos de reserva.
- La suite completa sigue funcionando sin instalar el extra `mqtt`.

### VI. Simplicidad y stdlib primero — PASA

- Se añade una sola dependencia, Python puro y sin transitivas, en un extra opcional.
- La tabla de una fila por acumulador reutiliza el almacén compartido ya obligatorio; evita añadir
  MQTT al controlador o diseñar un protocolo IPC nuevo.
- No hay componente personalizado de Home Assistant, forzado manual ni varias instalaciones.

### Restricciones de plataforma — PASA

- `paho-mqtt` no necesita compilador y el proceso medido con SQLAlchemy queda dentro del presupuesto.
- La cuarta unidad no pertenece al grupo `gpio` y no depende de las otras unidades.
- El frontend no cambia y no se construye nada en la Raspberry Pi.

**Resultado de la puerta: PASA.** Las dos complejidades deliberadas se justifican abajo.

## Project Structure

### Documentation (this feature)

```text
specs/004-home-assistant/
├── plan.md
├── spec.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── mqtt.md
│   ├── thermal.md
│   └── config.md
├── checklists/requirements.md
└── tasks.md
```

### Source Code (repository root)

```text
src/dynamic_thermal_charge/
├── models.py, config.py, thermal.py, cli.py
├── persistence/
│   ├── schema.py, mapping.py, repository.py, gate.py
│   └── migrations/versions/0003_indoor_temperature.py
├── api/schemas.py, api/routes/config.py
├── mqtt/
│   ├── __init__.py, settings.py, client.py, topics.py
│   ├── discovery.py, publisher.py, commands.py, indoor.py
│   └── service.py
└── controller.py, drivers.py, gpio_driver.py   # sin cambios

tests/
├── test_thermal.py
├── test_api_config.py
├── test_mqtt_settings.py, test_mqtt_topics.py, test_mqtt_discovery.py
├── test_mqtt_publisher.py, test_mqtt_commands.py, test_mqtt_indoor.py
├── test_mqtt_guards.py, test_persistence_indoor.py
└── test_deployment.py

deploy/systemd/dynamic-thermal-charge-mqtt.service
deploy/environment.example
scripts/install-service.sh
README.md

frontend/src/app/core/api.types.ts
frontend/src/app/config/config.html
frontend/src/app/config/config.spec.ts
```

**Structure Decision**: MQTT queda en un paquete nuevo y es el único que puede importar `paho`.
La persistencia de lecturas se añade al borde `persistence/`; el CLI del controlador compone ese
repositorio con el modelo durante el recálculo. No se toca `controller.py` ni los drivers de
salida. La API y el formulario web amplían sus contratos explícitos para que
los cuatro parámetros puedan declararse por las interfaces existentes, tal como promete el
`quickstart`; no añaden ningún canal ni comportamiento de control.

Los asuntos usan el segmento lógico fijo `installation`. El nombre visible y el prefijo de
despliegue pueden cambiar sin modificar ids de dispositivo ni `unique_id`. La tabla
`indoor_reading` referencia la PK entera de `heater`, que el repositorio traduce al id de dominio.

## Complexity Tracking

| Violación | Por qué es necesaria | Alternativa más simple rechazada porque |
| --- | --- | --- |
| Cuarto proceso en una Pi de 1 GB | Mantiene una dependencia de red remota fuera del proceso que conmuta relés; la huella conjunta estimada es ~155 MB | Publicar desde controlador o API mezcla ciclos de vida y permite que una caída externa afecte al control o a la API |
| Tabla `indoor_reading` como canal entre procesos | El publicador recibe la medida y el controlador genera el plan; ambos deben seguir independientes | Suscribir el controlador a MQTT viola el aislamiento; un socket/archivo IPC añade un protocolo, permisos y recuperación propios sin ventaja frente a la base de datos ya compartida |
