# Design

## Durable design

- El controlador usa un horizonte móvil discretizado por `slot_minutes`, toma una instantánea inmutable de entradas y conserva los slots ya ejecutados.
- El planificador es Python puro y determinista: nunca supera el límite eléctrico, aplica poda y declara `best_effort` si alcanza el límite de exploración.
- Los instantes persistidos siguen en UTC; las reglas recurrentes se evalúan en la zona horaria de la instalación, incluidos cambios DST.
- La telemetría MQTT es la fuente de verdad del estado almacenado. La caducidad se evalúa por magnitud y cualquier magnitud requerida caducada apaga y excluye solo ese acumulador.
- Preview nunca publica al driver. Activar valida de nuevo el token y persiste constraints y plan en una única transacción.
- El ciclo AEMET conserva la última previsión válida, registra antigüedad y realiza como máximo cinco reintentos horarios tras el intento inicial.
