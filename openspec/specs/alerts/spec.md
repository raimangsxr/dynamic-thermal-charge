## Purpose

Hacer visibles fuera del registro las condiciones degradadas que un operador
tiene que atender, sin que el aviso pueda detener el control.

## Requirements

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
reenvíe el aviso de una condición ya notificada. Un tipo desactivado o una
configuración de correo no operativa no abren episodio, así que habilitar
cualquiera de los dos más tarde sigue avisando de la siguiente ocurrencia.
La primera entrega y la apertura del episodio deben confirmarse en una sola
transacción, de modo que un fallo entre ambas no deje un mensaje duplicable.

#### Scenario: Condición sostenida

- **WHEN** la misma condición se detecta en dos ciclos consecutivos
- **THEN** se envía un único correo

#### Scenario: Reaparición tras resolverse

- **WHEN** la condición se resuelve y vuelve a ocurrir después
- **THEN** se envía un segundo correo

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
