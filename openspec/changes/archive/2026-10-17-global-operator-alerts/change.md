# Alertas globales del operador: panel, Push y Home Assistant

Status: approved

## Goal
Que el usuario vea y atienda todas las situaciones límite desde un único sitio, aunque no tenga correo configurado y aunque el controlador haya dejado de responder. Hoy las alertas solo llegan por correo y la bandeja con acuse y Web Push existe únicamente para la calibración. El cambio generaliza esa bandeja a todos los tipos, añade los tipos que faltan y expone las alertas en Home Assistant.

Depende de `automatic-thermal-calibration` (bandeja `operator_notification`, suscripciones y entrega Web Push).

## Requirements
- R1: Cada tipo del catálogo produce una alerta en la aplicación con tipo, título, severidad `critical`, `warning` o `info`, mensaje, apertura, resolución y acuse. Las alertas de condición se resuelven solas al desaparecer la condición; las de evento, como la terminación de una calibración, quedan resueltas al crearse.
- R2: Acusar retira la alerta de la lista activa sin borrarla. Las alertas acusadas o resueltas forman un histórico consultable y paginado, sujeto a `retention_days`, igual que la cola de correo.
- R3: Cada apertura intenta, de forma independiente, correo y Web Push a cada suscripción vigente, con el mismo episodio y deduplicación; ningún fallo de canal cambia la alerta ni bloquea el control.
- R4: Nuevos tipos: `controller_unresponsive` (latido obsoleto o varios controladores sospechados), `output_failure` (una salida rechaza su orden o queda el bloqueo de seguridad de la prueba de relés), `alert_email_failed` (una entrega de correo agota sus intentos), `plan_deviation_replan` (recálculo por desviación medida, `info`) y `forecast_stale` si existe. Los tipos actuales y el de calibración se migran a la bandeja.
- R5: `controller_unresponsive` la detecta y entrega el proceso API, sin depender del controlador; su resolución ocurre cuando el latido vuelve a estar vigente.
- R6: El panel muestra en la barra superior un indicador con el número de alertas activas y su máxima severidad, y una página `Avisos` con activas, histórico y acuse. La página de calibración enlaza a ella en lugar de mantener su bandeja propia.
- R7: Home Assistant expone un `binary_sensor` `Alertas activas` en el dispositivo controlador, con número, tipos, severidad máxima y mensajes en atributos; el discovery MQTT publica una entidad equivalente.
- R8: El catálogo conserva la activación por tipo; desactivar un tipo suprime su correo y su Push, pero la alerta sigue en la bandeja.

## Acceptance
- A1: Pruebas de persistencia y API: abrir, resolver, acusar y paginar el histórico; retención de alertas y entregas; deduplicación por episodio tras reinicio.
- A2: Pruebas de canales: correo y Push se intentan por separado; un fallo de correo agotado abre `alert_email_failed` sin intentar enviarse por correo.
- A3: Prueba de API: con latido obsoleto y controlador detenido, la API abre `controller_unresponsive`, entrega correo y Push y lo resuelve al volver el latido.
- A4: Pruebas de controlador: un rechazo de salida abre `output_failure` una vez por transición y la recuperación lo resuelve.
- A5: Prueba de runtime: un recálculo por desviación crea `plan_deviation_replan` sin correo y con Push.
- A6: Pruebas de Angular: indicador, lista, histórico, acuse y enlace desde calibración; pruebas de Home Assistant y MQTT del sensor y sus atributos; `make check` pasa.

## Outcome
La implementación y la verificación terminaron correctamente; la revisión final confirmó la corrección de reconciliación del correo de terminación de calibración.
