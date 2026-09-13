# Unificar topics MQTT y eliminar simulaciones

Status: approved

## Goal

Establecer un único esquema MQTT coherente para la aplicación y eliminar toda fuente de datos sintética de acumuladores, MQTT y meteorología.

## Requirements

### R1. Esquema MQTT único

Todos los topics MQTT propios de la aplicación usarán `mqtt.prefix`, cuyo valor por defecto será `telemetria`. La excepción será `mqtt.discovery_prefix`, reservado exclusivamente para la convención de descubrimiento de Home Assistant.

### R2. Topics estándar

Con el prefijo por defecto, el controlador usará `telemetria/installation/{availability,state_available,state}`, `telemetria/installation/heater/<id-normalizado>/state` y `telemetria/installation/heater/<id-normalizado>/set/enabled`. Cada acumulador usará `telemetria/acumuladores/<id-normalizado>/{telemetry,discharge,setpoint}`.

### R3. Corte directo sin compatibilidad

La aplicación dejará de publicar, suscribirse o mostrar topics `dtc/...` y dejará de leer o aceptar `telemetry_topic`, `damper_topic` y `setpoint_topic` como overrides. No habrá publicación ni suscripción dual durante la transición.

### R4. Retirar simulación MQTT de acumuladores

Se eliminarán el simulador MQTT de acumuladores, su supervisor, sus suscripciones, sus publicaciones y toda la configuración y persistencia `mqtt_simulation_*`.

### R5. Sin valores MQTT fijos

Se eliminarán `fixed_indoor_temperature_c` y `fixed_stored_soc_percent`. Si MQTT está desactivado o falta telemetría fresca, la planificación será inválida y no fabricará temperatura, SOC ni otros valores; las salidas deberán permanecer en estado seguro. La prueba de relés y el driver de salida simulado no forman parte de este cambio.

### R6. Meteorología exclusivamente real

Se eliminarán el proveedor meteorológico simulado y los valores de fallback/simulación. AEMET será el único proveedor; si no existe una previsión AEMET válida que cubra el horizonte requerido, la planificación será inválida y no generará temperaturas sintéticas.

### R7. Configuración, interfaz y documentación

La migración de persistencia, API, frontend, especificaciones, pruebas y `README.md` reflejará el esquema nuevo y eliminará los campos retirados. El descubrimiento de Home Assistant seguirá usando su prefijo externo, pero sus payloads apuntarán únicamente a los nuevos topics de estado y mando.

## Acceptance

- Los tests verifican el esquema estándar y que no existen rutas de runtime `dtc/...` ni topics legacy.
- Publisher, suscriptor, comandos, telemetría agrupada y descubrimiento usan únicamente los topics estándar.
- La API, la configuración persistida y la interfaz no exponen overrides ni campos de simulación/fijos retirados.
- No se inicia un segundo cliente MQTT de simulación y no se publican valores sintéticos de acumuladores.
- MQTT desactivado, telemetría ausente/obsoleta o previsión AEMET no válida producen planificación inválida sin valores inventados.
- La migración desde el esquema actual deja `mqtt.prefix=telemetria` y elimina los datos/campos de compatibilidad y simulación.
- `README.md` documenta el esquema final y `make check` pasa.
