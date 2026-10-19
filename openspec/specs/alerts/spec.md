## Purpose

Hacer visibles fuera del registro las condiciones degradadas que un operador
tiene que atender, sin que el aviso pueda detener el control.

## Requirements

### Requirement: Bandeja global y ciclo de vida de alertas

Cada tipo del catálogo se persiste como un aviso de operador con tipo, título,
severidad (`critical`, `warning` o `info`), mensaje, instante de apertura,
resolución opcional y acuse opcional. La API expone las vistas `active`,
`history` y `all` con cursor opaco y permite acusar un aviso sin borrarlo; el
histórico conserva los avisos y sus entregas conforme a `retention_days`.
Las alertas de condición se resuelven al desaparecer la condición y las de
evento nacen resueltas.

#### Scenario: Acuse conservado en histórico

- **WHEN** el operador acusa una alerta activa
- **THEN** desaparece de `active`, conserva su apertura y acuse en `history`,
  y sigue sujeta a la retención configurada

#### Scenario: Apertura idempotente tras reinicio

- **WHEN** dos procesos detectan el mismo episodio
- **THEN** la persistencia confirma una sola alerta y una sola entrega por
  suscripción

### Requirement: Canales independientes y alertas informativas

Cada apertura intenta de forma independiente correo y Web Push por cada
suscripción activa mediante filas duraderas reclamables con una concesión
entre procesos. Un fallo o agotamiento de un canal no modifica el aviso ni
bloquea el control. Las alertas `info` siempre permanecen en la bandeja, se
proyectan en la aplicación y Home Assistant y se intentan por Web Push, pero
no generan correo. Desactivar un tipo suprime sus filas de correo y Push, pero
no elimina el aviso de la bandeja.

#### Scenario: Info sin correo

- **WHEN** se abre una alerta `info` con una suscripción Web Push activa
- **THEN** se persiste en la bandeja y se crea una tentativa Push sin crear una
  entrega de correo

#### Scenario: Reclamación exclusiva

- **WHEN** dos procesos reclaman la misma entrega pendiente
- **THEN** solo el proceso que obtiene la concesión puede marcarla enviada o
  fallida

### Requirement: Detección de controlador y nuevas transiciones

El proceso API detecta `controller_unresponsive` por un latido obsoleto o por
varios controladores sospechados y lo resuelve cuando el latido vuelve a estar
vigente. El runtime abre y resuelve `output_failure` por transición de rechazo
de una salida o bloqueo de seguridad del relé, y abre `plan_deviation_replan`
cuando una medida solicita recálculo; estas detecciones no alteran la física de
planificación.

#### Scenario: Controlador recuperado

- **WHEN** la API observa un latido obsoleto y después uno vigente
- **THEN** abre una alerta crítica en el primer sondeo y resuelve el mismo
  episodio en el segundo

### Requirement: Calibration notification channels

Cada terminación de calibración crea un aviso duradero en la bandeja de la
aplicación. El backend intenta correo por la cola existente de forma
independiente y crea una tentativa Web Push por cada suscripción activa; cada
pareja sesión/navegador se deduplica. La interfaz registra la suscripción con
las APIs estándar de Notification, Web Push y service worker, y separa el
navegador o contexto no apto, el permiso, la configuración VAPID y los errores
de suscripción o registro. En el backend, la falta de VAPID, permiso,
suscripción o entrega marca `unsupported`, `denied`, `expired` o `error`; la
interfaz traduce esos estados a mensajes localizados y accionables sin mostrar
el literal técnico `unsupported`. Ningún fallo cambia el resultado de
calibración, que sigue visible en la bandeja.

#### Scenario: Activación Web Push compatible

- **WHEN** el navegador está en un contexto seguro, expone Notification, Web Push y service worker, y el operador concede permiso
- **THEN** la interfaz obtiene la clave pública VAPID, registra el service worker, crea o reutiliza la suscripción y la registra sin clasificar la plataforma como incompatible

#### Scenario: Degradación de activación accionable

- **WHEN** el navegador, el contexto, el permiso, la configuración VAPID o la suscripción impiden activar avisos
- **THEN** la interfaz muestra un estado localizado y accionable que explica el siguiente paso y no expone el literal técnico `unsupported`

#### Scenario: Push endpoint expired

- **WHEN** el proveedor devuelve que un endpoint ha caducado o fue revocado
- **THEN** la suscripción pasa a `expired`, no vuelve a intentarse y la
  aplicación conserva el aviso terminal

#### Scenario: Browser permission denied

- **WHEN** el navegador no concede permiso o no soporta Push
- **THEN** no se registra una suscripción y el aviso in-app sigue disponible

### Requirement: Configuración de correo residente en base de datos

La configuración de sistema debe incluir una sección de correo con activación,
servidor, puerto, modo de cifrado, remitente, destinatarios y tiempo de espera,
administrada con la misma revisión y auditoría que el resto de secciones. El
usuario y la contraseña SMTP deben guardarse en el catálogo de secretos: la API
permite establecerlos, rotarlos y borrarlos, informa de si están configurados y
nunca devuelve su valor. No debe introducirse ninguna variable de entorno nueva.

Activar el envío exige servidor, remitente y al menos un destinatario, de modo
que la configuración no pueda quedar habilitada a medias. Las credenciales son
opcionales, porque un relé sin autenticación es legítimo, pero media pareja de
credenciales se rechaza.

#### Scenario: Alta de la configuración de correo

- **WHEN** se guarda la sección de correo con una revisión vigente
- **THEN** se persiste, se devuelve en la configuración pública y su revisión
  avanza

#### Scenario: Activación incompleta

- **WHEN** se intenta activar el envío sin servidor, sin remitente o sin
  destinatarios
- **THEN** el cambio se rechaza y la configuración vigente se conserva

#### Scenario: Rotación de credenciales SMTP

- **WHEN** se establece, rota o borra el usuario o la contraseña SMTP
- **THEN** la respuesta informa de que están configurados sin incluir su valor

### Requirement: Catálogo de alertas con activación por tipo

Debe existir un catálogo de tipos de alerta con clave estable, título y
descripción, y una activación por tipo persistida. Un tipo recién incorporado
está activo sin necesidad de configurarlo, porque el almacén solo registra las
desviaciones respecto al catálogo del código. Un tipo desconocido se rechaza.

#### Scenario: Silenciar un tipo de alerta

- **WHEN** el operador desactiva un tipo del catálogo
- **THEN** ese tipo deja de generar avisos y el resto los conserva

#### Scenario: Tipo desconocido

- **WHEN** se intenta activar o desactivar un tipo que no existe en el catálogo
- **THEN** la petición se rechaza y no se guarda nada

### Requirement: Cola duradera y entrega con reintentos

Al detectar una condición de alerta debe encolarse un mensaje duradero con su
tipo, su instante y su contenido; la detección nunca envía correo de forma
sincrónica. El envío ocurre en un paso del ciclo de control, con reintentos y
espera creciente hasta un máximo de intentos; agotados, la alerta queda
registrada como fallida y no se reintenta indefinidamente. El cuerpo se
construye al encolar, de modo que conserve los valores que provocaron el aviso
aunque se entregue más tarde.

Un fallo de correo, una configuración incompleta o unas alertas deshabilitadas
no pueden interrumpir el ciclo de control ni el accionamiento de las salidas, y
se registran una vez por transición.

#### Scenario: Entrega tras un fallo transitorio

- **WHEN** un intento de envío falla
- **THEN** la alerta sigue pendiente, su contador de intentos avanza y el
  siguiente intento espera más que el anterior

#### Scenario: Intentos agotados

- **WHEN** se agotan los intentos de una alerta
- **THEN** queda marcada como fallida, se registra el motivo y no vuelve a
  intentarse

#### Scenario: Fallo de correo durante el control

- **WHEN** la entrega de alertas falla o su almacén no está disponible
- **THEN** el ciclo de control termina completo, las salidas conservan su
  accionamiento y el fallo se registra una vez por transición

#### Scenario: Reinicio con alertas pendientes

- **WHEN** el proceso se reinicia con una alerta encolada
- **THEN** el siguiente ciclo la entrega, sin haberla perdido

### Requirement: Un aviso por episodio

Mientras una condición siga activa no debe encolarse otra alerta de su tipo.
Cuando la condición se resuelve, ese tipo se rearma y una ocurrencia nueva
vuelve a avisar. El estado de rearme se persiste, de modo que un reinicio no
reenvíe el aviso de una condición ya notificada. Una configuración de correo
no operativa no impide abrir el aviso en la bandeja; un tipo desactivado
conserva el aviso, pero suprime sus entregas de correo y Push.
La primera entrega y la apertura del episodio deben confirmarse en una sola
transacción, de modo que un fallo entre ambas no deje un mensaje duplicable.

#### Scenario: Condición sostenida

- **WHEN** la misma condición se detecta en dos ciclos consecutivos
- **THEN** se envía un único correo

#### Scenario: Reaparición tras resolverse

- **WHEN** la condición se resuelve y vuelve a ocurrir después
- **THEN** se envía un segundo correo

### Requirement: Alertas de mejor esfuerzo y telemetría excluida

El catálogo debe incluir `plan_best_effort_active` y
`plan_heater_excluded`. La primera identifica que el controlador gobierna las
salidas con un plan físicamente validado que no alcanzó convergencia completa;
la segunda identifica los acumuladores, la causa y la consecuencia de no
ordenar carga ni descarga mientras falte estado requerido. Ambas se encolan de
forma no bloqueante y respetan el episodio único por tipo; al activar un plan
normal o recuperar la telemetría se limpian y quedan rearmadas. La alerta
`plan_recalculation_degraded` se conserva para un candidato degradado retenido
como diagnóstico y no afirma que las salidas permanecerán apagadas si existe
un best-effort activable cuando expire la cobertura.

#### Scenario: Best-effort activo

- **WHEN** se activa un plan `DEGRADED` como `best_effort`
- **THEN** se encola una sola alerta de `plan_best_effort_active` con la causa y
  se mantienen las salidas gobernadas por el plan

#### Scenario: Acumulador excluido

- **WHEN** la planificación activa excluye uno o más acumuladores por falta de
  temperatura interior o SOC recientes
- **THEN** se encola una sola alerta `plan_heater_excluded` que nombra los
  acumuladores, la causa y que no se ordena carga ni descarga para ellos

#### Scenario: Acumulador en calibración

- **WHEN** la planificación activa conserva un acumulador excluido con causa
  `calibration_active`
- **THEN** no se abre ni se mantiene `plan_heater_excluded` ni
  `plan_best_effort_active` por ese acumulador, y las proyecciones lo muestran
  como `En calibración` sin acción para recuperar telemetría

#### Scenario: Resolución de las alertas nuevas

- **WHEN** un plan posterior ya no usa best-effort ni contiene exclusiones
- **THEN** ambas alertas se rearman y una ocurrencia futura puede volver a
  encolarlas

### Requirement: Aviso de previsión obsoleta

El catálogo debe incluir `forecast_stale`. Se abre cuando se activa un plan
que lleva el aviso de entrada `stale_forecast` y se rearma cuando se activa un
plan cuya previsión está dentro de `forecast_max_age_hours`. El mensaje conserva
la hora de obtención de la previsión, su edad, el límite configurado, el último
error de AEMET y el próximo reintento horario. La alerta no modifica el estado
físico del plan, la precedencia de activación ni el accionamiento.

#### Scenario: Previsión antigua activada

- **WHEN** se activa como mejor esfuerzo un plan con `stale_forecast`
- **THEN** se encola una sola alerta `forecast_stale` con la hora de obtención,
  edad, límite, último error y próximo reintento

#### Scenario: Previsión recuperada

- **WHEN** se activa un plan posterior con previsión dentro del límite
- **THEN** `forecast_stale` se rearma sin encolar otro aviso

### Requirement: Aviso de replanificación imposible

Debe avisarse cuando un recálculo devuelve `INVALID`. El correo identifica la
instalación, el instante, la causa del resultado inválido y su consecuencia:
que la instalación se queda sin plan activo cuando el recálculo periódico lo
desactiva, o que se conserva el plan anterior cuando no ha podido reemplazarse.

#### Scenario: Recálculo periódico inválido

- **WHEN** un recálculo periódico devuelve `INVALID` y desactiva el plan activo
- **THEN** se encola la alerta con la causa y la consecuencia de quedarse sin
  plan activo

#### Scenario: Recálculo válido posterior

- **WHEN** un recálculo posterior produce un plan
- **THEN** la alerta se rearma sin enviar nada

### Requirement: Envío de prueba

La API debe ofrecer un envío de prueba que valide la configuración de correo
vigente, devuelva el fallo de forma explicable y no encole ni registre una
alerta del catálogo. Sin configuración operativa, la prueba se rechaza
explícitamente.

#### Scenario: Prueba correcta

- **WHEN** se solicita el envío de prueba con una configuración operativa
- **THEN** se entrega un mensaje y el catálogo de alertas no cambia

#### Scenario: Prueba fallida

- **WHEN** el servidor de correo es inalcanzable
- **THEN** la respuesta explica el fallo y no deja rastro en el catálogo
