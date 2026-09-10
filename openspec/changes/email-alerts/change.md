# Alertas por email

Status: approved

## Goal

Las condiciones degradadas del controlador solo se ven en el registro, así que
una instalación que se queda sin plan activo puede pasar inadvertida hasta que
la vivienda se enfría. Añadir el envío de alertas por email como capacidad
reutilizable, con su configuración residente en base de datos y una cola
duradera, y usarla en su primera alerta: un recálculo periódico `INVALID` que
deja la instalación sin plan activo.

## Requirements

- R1: La configuración de sistema incluye una sección de correo con servidor, puerto, modo de cifrado, remitente y destinatarios, administrada por la API de sistema con revisión y auditoría como el resto de secciones.
- R2: El usuario y la contraseña SMTP se guardan como secretos del catálogo existente. La API permite establecerlos, rotarlos y borrarlos, informa de si están configurados y nunca devuelve su valor.
- R3: Existe un catálogo persistente de tipos de alerta con clave estable y activación por tipo, además del interruptor global de alertas. Añadir una alerta futura consiste en añadir una entrada al catálogo.
- R4: Al detectar una condición de alerta, el proceso la encola de forma duradera con su tipo, su instante y su contenido. La detección nunca envía el correo de forma sincrónica.
- R5: El envío ocurre en un paso del ciclo de control, con reintentos y espera creciente hasta un máximo de intentos. Agotados los intentos, la alerta queda registrada como fallida y no se reintenta indefinidamente.
- R6: Mientras la condición siga activa no se encola otra alerta del mismo tipo; cuando se resuelve, ese tipo se rearma y un episodio nuevo vuelve a avisar.
- R7: Un fallo de SMTP, una configuración de correo incompleta o unas alertas deshabilitadas no interrumpen el ciclo de control ni el accionamiento de las salidas, y se registran una vez por transición.
- R8: La primera alerta del catálogo se emite cuando un recálculo periódico devuelve `INVALID` y deja la instalación sin plan activo. El correo identifica la instalación, el instante, la causa del resultado inválido y la consecuencia.
- R9: La API ofrece un envío de prueba que valida la configuración de correo vigente y devuelve el fallo de forma explicable, sin encolar una alerta del catálogo.
- R10: El panel edita la sección de correo, la rotación de sus secretos y la activación por tipo, y ofrece el envío de prueba.
- R11: El resto del contrato no cambia: la cadencia de replanificación, el tratamiento de un plan `INVALID` y el accionamiento de salidas conservan su comportamiento.

## Acceptance

- A1: La configuración de correo se guarda y se devuelve por la API de sistema con su revisión, y un intento con revisión obsoleta se rechaza sin aplicar cambios.
- A2: La respuesta de la API informa de que el usuario y la contraseña SMTP están configurados sin incluir sus valores, y permite rotarlos y borrarlos.
- A3: Un recálculo periódico `INVALID` encola una alerta con su tipo, la causa y el instante, y el paso de envío la entrega una sola vez.
- A4: Un recálculo periódico `INVALID` en dos ciclos consecutivos produce un único correo mientras la condición no se resuelva; tras un recálculo válido y otro `INVALID` posterior, se produce un segundo correo.
- A5: Un fallo de SMTP deja la alerta encolada, incrementa su contador de intentos, no interrumpe el ciclo y, agotados los intentos, la marca como fallida.
- A6: Con las alertas deshabilitadas globalmente, con el tipo desactivado o sin configuración de correo completa, no se encola ni se envía nada y la condición se registra una vez.
- A7: El envío de prueba devuelve éxito con una configuración válida y un error explicable con un servidor inalcanzable, sin dejar rastro en el catálogo de alertas.
- A8: `npm test`, `npm run build` y `make check` pasan.

## Decisions

- D1: La configuración vive en la configuración de sistema residente en base de datos y los secretos en `SECRET_KINDS` y `system_secret`, siguiendo el patrón ya establecido para la clave de AEMET y las credenciales MQTT. No se añade ninguna variable de entorno nueva, en coherencia con la migración declarada en `runtime_configuration_inventory.py`.
- D2: La cola es una tabla nueva con el tipo, el contenido, el estado, el número de intentos y el próximo intento. Persistirla es lo que permite que una alerta sobreviva a un reinicio y quede auditada, que es justo lo que se necesita cuando el sistema está degradado.
- D3: El envío se hace desde el ciclo de control y no desde un proceso nuevo: el controlador ya es el proceso que observa las condiciones y publica latidos, y añadir un servicio aparte solo para el correo no aporta nada hoy.
- D4: La deduplicación es por episodio y por tipo, con el mismo criterio de transición que el controlador ya usa para los fallos de relé y de publicación MQTT: se avisa al entrar en la condición y se rearma al salir.
- D5: El estado de rearme por tipo se persiste junto al catálogo, para que un reinicio del controlador no vuelva a enviar un correo de una condición que ya había avisado.
- D6: El cuerpo del correo es texto plano y se construye en el momento de encolar, de modo que la alerta conserva los valores que la provocaron aunque se envíe más tarde.
- D7: El envío de prueba de R9 existe porque una configuración de correo mal puesta se descubriría, si no, la primera vez que hiciera falta la alerta.

## Tasks

- [x] T1: Añadir la sección de correo a la configuración de sistema y sus dos secretos al catálogo, con su validación.
- [x] T2: Añadir la tabla de cola de alertas y la de catálogo con su estado de rearme, con migración Alembic y esquema.
- [x] T3: Añadir un módulo de alertas con el encolado, la deduplicación por episodio y el envío SMTP con reintentos y espera creciente.
- [x] T4: Conectar el paso de envío al ciclo de control, tolerando cualquier fallo de correo sin afectar al accionamiento.
- [x] T5: Emitir la alerta de R8 en el recálculo periódico `INVALID` que deja la instalación sin plan activo.
- [x] T6: Exponer en la API la sección de correo, la rotación de secretos, la activación por tipo y el envío de prueba.
- [x] T7: Editar todo lo anterior en el panel, con sus tipos, su texto de ayuda y sus pruebas.
- [x] T8: Cubrir con tests la configuración y sus secretos, el encolado, la deduplicación por episodio, los reintentos y el agotamiento, la tolerancia a fallos y el envío de prueba.
- [x] T9: Actualizar `openspec/specs/planning/spec.md` si procede y las secciones de configuración y operación de `README.md`.
- [x] T10: Ejecutar `make check`.
