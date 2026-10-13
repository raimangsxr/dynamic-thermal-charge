# Design

## Approach
Evolucionar `operator_notification` a la tabla de alertas de la aplicación en lugar de crear otra: se añaden `alert_type`, `severity`, `episode_id`, `opened_at`, `resolved_at` y se conserva `acknowledged_at`. El servicio de alertas actual pasa a escribir la fila de bandeja dentro de la misma transacción que abre el episodio y encola el correo, de modo que bandeja, episodio y cola nunca divergen. Resolver un episodio rellena `resolved_at`; acusar solo rellena `acknowledged_at`. El histórico se lee con el mismo cursor opaco que `/history/*`.

Web Push deja de colgar de la sesión de calibración: cada apertura crea un intento por suscripción con clave única `(alert_id, subscription_id)`, reutilizando el worker y los estados `denied`, `unsupported`, `expired` y `error` existentes.

## Constraints
- Hoy solo el controlador drena la cola de correo, en su ciclo. La API necesita entregar `controller_unresponsive` cuando el controlador está caído, así que la cola debe poder drenarse desde dos procesos sin duplicar envíos.
- `alert_delivery` y `alert_episode` no están en `RETAINED_TABLES` y crecen sin límite; entran en la retención con el histórico de alertas.
- La revisión Alembic se fija al implementar porque la calibración ocupa 0025.

## Decisions
- Reclamación de entregas por arrendamiento: una fila pendiente se reclama con `claimed_by` y `claimed_until` en una actualización condicional; el proceso que la reclama la envía y la marca. Así controlador y API drenan la misma cola sin coordinación adicional.
- El detector de `controller_unresponsive` es una tarea periódica del proceso API que reutiliza `api/liveness.py` con el mismo umbral que Estado, para que indicador y alerta nunca discrepen.
- `output_failure` se abre desde las transiciones que el controlador ya registra una vez por cambio, sin un sondeo nuevo.
- `alert_email_failed` nunca se envía por correo, para no entrar en bucle, y se considera resuelta con la siguiente entrega de correo correcta.
- El snapshot operativo añade un bloque `alerts` compacto; Home Assistant lo lee del mismo snapshot cada 30 segundos y no consulta un endpoint nuevo.

## Risks
- Dos procesos enviando avisos aumentan el riesgo de duplicados. Mitigación: claves únicas por episodio y canal, y el arrendamiento de reclamación.
- Migrar la bandeja de calibración cambia su comportamiento de borrado al acusar. Mitigación: la migración conserva los avisos existentes como acusados o activos según su estado.
- Un umbral de latido demasiado estricto generaría alertas en reinicios normales. Mitigación: reutilizar el umbral de liveness ya validado.
