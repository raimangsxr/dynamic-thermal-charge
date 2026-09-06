# Prueba de relés: coordinación segura y experiencia operativa

Status: approved

## Goal

Revisar y refactorizar el módulo de prueba de relés para que la operación sea segura,
observable y fácil de entender, con una experiencia visual coherente con Configuración.

## Requirements

- R1: La API solo permite iniciar una sesión cuando el controlador tiene un heartbeat vigente, no se detectan varios controladores y hay acumuladores habilitados; la sesión no puede activarse si esas condiciones, el lease o la revisión cambian.
- R2: La vista distingue sesión en preparación, activa, finalizando, terminada y fallida, además de recuperación de seguridad, controlador no actual y auditoría degradada, sin afirmar nunca un estado físico no confirmado.
- R3: El panel usa las cadencias configuradas por Operación para refresco de estado y renovación de lease, mantiene ambos ciclos independientes, evita peticiones duplicadas y se detiene/reanuda correctamente con la visibilidad de la pestaña.
- R4: Solo el propietario puede ordenar o finalizar; las órdenes pendientes bloquean la tarjeta correspondiente hasta recibir confirmación o rechazo, y el panel muestra el motivo accionable de los errores conocidos.
- R5: Una sesión terminada o fallida queda consultable como resultado histórico, pero ofrece iniciar una nueva prueba y no deja bloqueada la navegación ni marca como activa una sesión terminal.
- R6: La pantalla adopta el lenguaje visual de Configuración: cabecera de página, banners accionables, paneles, tarjetas de resumen, estados textuales accesibles, diseño responsive y acciones con estados de carga.
- R7: El header de credencial específico del módulo funciona también cuando el panel se sirve con CORS configurado, sin exponer la credencial en URLs, texto visible o logs.

## Acceptance

- A1: Las pruebas backend cubren heartbeat ausente/obsoleto, múltiples controladores, lease o revisión inválidos, cadencias configuradas y la transición segura de preparación a activa.
- A2: Las pruebas frontend cubren carga/refresh, sesiones externas, estados terminales, latch, controlador no actual, doble clic, órdenes pendientes, errores de potencia y renovación/sondeo con los intervalos recibidos.
- A3: En una vista activa, el operador puede saber qué está pasando, qué salida está confirmada, qué orden está pendiente y por qué una acción está deshabilitada sin interpretar códigos internos ni depender solo del color.
- A4: `npm test`, `npm run build` y la quality gate del proyecto pasan sin regresiones.

## Outcome

La coordinación quedó alineada con el heartbeat y la configuración persistida; el
panel presenta estados seguros y terminales con una experiencia coherente con
Configuración. El controlador mantiene la autoridad exclusiva sobre GPIO y la
recuperación de seguridad sigue siendo local al dispositivo.
