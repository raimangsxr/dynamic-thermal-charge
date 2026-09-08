# Coherencia de datos y operación del frontend en tiempo real

Status: approved

## Goal

Hacer que las vistas operativas presenten una misma realidad de planificación,
previsión y estado del controlador, y eliminar etiquetas técnicas, fechas
ambiguas y datos corruptos que dificultan la operación.

## Requirements

- R1: Estado y Planificación deben usar el plan automático activo y la previsión vigente como fuentes coherentes, distinguiendo claramente ventana visible, horizonte y ausencia de plan.
- R2: Los estados `FEASIBLE`, `DEGRADED` e `INVALID` deben normalizarse y mostrarse con etiquetas operativas en todas las vistas, sin depender de la capitalización recibida.
- R3: Histórico > Planes debe incluir las planificaciones automáticas activadas y conservar legibles los registros legacy, sin omisiones ni duplicados silenciosos.
- R4: Los nombres meteorológicos y cualquier texto con caracteres no ASCII deben conservarse correctamente desde el proveedor hasta el navegador; debe existir una regresión para `A Coruña`.
- R5: Las fechas de Configuración, Planificación e Histórico deben mostrarse en la zona horaria de la instalación, indicando la zona cuando pueda afectar a la operación; la hora diaria de AEMET, los reintentos y la próxima actualización deben distinguirse.
- R6: Las tablas y resúmenes operatorios deben usar nombres de acumulador, eventos y motivos traducidos; los identificadores y JSON crudos solo aparecerán como detalle técnico secundario. El resumen debe decir “intervalos de 30 minutos”.
- R7: El frontend debe distinguir previsión real, fallback y último error de proveedor, y no presentar como actual una previsión que solo fue fallback; los avisos de plan inválido y salidas apagadas deben quedar contextualizados.
- R8: Configuración debe mostrar el driver efectivo de salidas y explicar cuando el modo global simulado prevalece sobre una salida GPIO configurada; Histórico > Transiciones debe distinguir ausencia de eventos de indisponibilidad de datos.
- R9: La pantalla de prueba de relés debe conservar las garantías de sesión, lease, confirmación y apagado seguro; la verificación añadida no debe activar salidas reales de forma automática.

## Acceptance

- A1: Con los datos actuales, Estado y Planificación muestran el mismo plan automático, estado, previsión y origen, con ventana e horizonte explicados sin contradicciones.
- A2: Ninguna vista operatoria muestra `FEASIBLE`, `activated`, `periodic` ni JSON de auditoría sin una representación localizada equivalente.
- A3: El histórico incluye la activación automática observada y permite diferenciarla de planes legacy.
- A4: `Noia, A Coruña` aparece correctamente en el detalle de previsión y en las respuestas de prueba.
- A5: Las fechas se presentan de forma consistente en `Europe/Madrid` y la siguiente consulta explica si es consulta diaria, retry o refresh.
- A6: Un escenario AEMET 429 muestra fallback y próximo intento sin ocultar el último dato válido; un plan inválido explica por qué las salidas permanecen apagadas.
- A7: Los nombres amigables, el texto de intervalos, el driver efectivo y el estado vacío de transiciones son consistentes en Chrome desktop y responsive.
- A8: Existen pruebas de contrato API, persistencia y frontend para la divergencia legacy/automática, mayúsculas de estado, Unicode, fallback, zona horaria y transiciones; `make check` pasa.
- A9: La prueba de relés mantiene confirmación física, propiedad de pestaña, lease y apagado seguro, y no se ejecuta durante la verificación automática.
