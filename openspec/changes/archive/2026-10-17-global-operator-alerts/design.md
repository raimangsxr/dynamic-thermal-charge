# Design

## Durable approach
Evolucionar `operator_notification` a la tabla de alertas de la aplicación en
lugar de crear otra: la fila de bandeja, el episodio y la cola de correo se
confirman en una misma transacción. Resolver rellena `resolved_at` y acusar
solo `acknowledged_at`; el histórico usa el mismo cursor opaco que
`/history/*`.

Cada apertura crea un intento Web Push por suscripción con clave única
`(alert_id, subscription_id)`, reutilizando el worker y sus estados de entrega.

## Constraints
La cola de correo debe poder drenarse desde el controlador y la API sin
duplicar envíos. Las filas de entregas y episodios participan en la misma
retención que el histórico de alertas.

## Durable decisions
- Reclamación de entregas por arrendamiento: una fila pendiente se reclama con `claimed_by` y `claimed_until` en una actualización condicional; el proceso que la reclama la envía y la marca. Así controlador y API drenan la misma cola sin coordinación adicional.
- El detector de `controller_unresponsive` es una tarea periódica del proceso API que reutiliza `api/liveness.py` con el mismo umbral que Estado, para que indicador y alerta nunca discrepen.
- `output_failure` se abre desde las transiciones que el controlador ya registra una vez por cambio, sin un sondeo nuevo.
- `alert_email_failed` nunca se envía por correo, para no entrar en bucle, y se considera resuelta con la siguiente entrega de correo correcta.
- Las alertas `info` se conservan en la bandeja y el snapshot de Home Assistant, se intentan por Web Push y no crean filas de correo.
- El snapshot operativo añade un bloque `alerts` compacto; Home Assistant lo lee del mismo snapshot cada 30 segundos y no consulta un endpoint nuevo.

## Risks addressed
- Dos procesos enviando avisos aumentan el riesgo de duplicados. Mitigación: claves únicas por episodio y canal, y el arrendamiento de reclamación.
- Migrar la bandeja de calibración cambia su comportamiento de borrado al acusar. Mitigación: la migración conserva los avisos existentes como acusados o activos según su estado.
- Un umbral de latido demasiado estricto generaría alertas en reinicios normales. Mitigación: reutilizar el umbral de liveness ya validado.
