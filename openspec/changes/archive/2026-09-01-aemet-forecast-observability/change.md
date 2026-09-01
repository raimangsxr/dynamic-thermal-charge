# Observabilidad y consulta manual del forecast AEMET

Status: approved

## Goal
El panel debe hacer visible cuándo se volverá a consultar AEMET y qué ocurrió en la última consulta. Además, el usuario debe poder lanzar una consulta manual desde Sistema → weather y consultar el forecast horario gráficamente en Planificación.

## Requirements
- R1: El runtime debe persistir para la instalación la fecha/hora de la última consulta de forecast, su resultado (correcta o error), el detalle del error cuando exista y la próxima consulta automática prevista.
- R2: `GET /api/v1/planning` debe exponer la próxima consulta automática a AEMET y el forecast horario disponible para que el frontend pueda representarlo, aunque no haya un plan activo.
- R3: Planificación debe mostrar el forecast horario en un gráfico y, justo debajo, la fecha/hora de la próxima consulta automática a AEMET.
- R4: La respuesta de configuración del sistema debe incluir en `weather` el estado y la fecha/hora de la última consulta, además del detalle del error si la última consulta falló.
- R5: Sistema → weather debe mostrar un botón para lanzar inmediatamente una consulta contra AEMET; mientras se ejecuta debe evitar envíos duplicados y debe comunicar el resultado correcto o el error devuelto.
- R6: La consulta manual debe guardar el mismo estado/forecast que una consulta automática y no debe modificar la cadencia configurada de las consultas automáticas.
- R7: La configuración no debe exponer la clave API de AEMET en ninguna respuesta ni en el frontend.

## Acceptance
- A1: Una consulta automática correcta deja estado `success`, fecha/hora de consulta, próxima ejecución y forecast horario persistidos y visibles en Planificación y Sistema → weather.
- A2: Una consulta automática fallida deja estado `error` y su detalle visible en Sistema → weather, sin borrar el último forecast válido.
- A3: El gráfico de Planificación representa los puntos horarios recibidos y sigue mostrando una alternativa accesible cuando no hay datos de forecast o canvas.
- A4: Al pulsar el botón manual con AEMET configurado, se realiza una petición real, se actualiza el estado persistido y la respuesta de la UI refleja éxito o error sin filtrar secretos.
- A5: La consulta manual no cambia `refresh_minutes`/`retry_minutes` ni la próxima ejecución automática calculada por el ciclo.
- A6: Las pruebas backend y frontend cubren persistencia/lectura de estado, endpoint manual, errores y renderizado de la información solicitada.

## Outcome
Se añadió observabilidad persistida del ciclo AEMET, consulta manual protegida y visualización del forecast horario en Planificación. El parser acepta las variantes habituales de respuesta de AEMET (`estado` 1/200 y datos `periodo`/`dato`) y los errores expuestos son accionables sin filtrar secretos.
