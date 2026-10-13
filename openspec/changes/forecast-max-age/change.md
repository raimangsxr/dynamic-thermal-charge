# Antigüedad máxima de la previsión y reintentos AEMET continuos

Status: draft

## Goal
Que la instalación autónoma deje de planificar en silencio con una previsión antigua. Hoy, tras cinco reintentos fallidos, el ciclo AEMET se da por completado hasta el día siguiente y el planificador acepta cualquier previsión que cubra el horizonte sin mirar su antigüedad. El sistema debe seguir planificando con la última previsión válida, marcar el plan como mejor esfuerzo, avisar y seguir reintentando.

## Requirements
- R1: La configuración de planificación expone y persiste `forecast_max_age_hours`, entero entre 1 y 168 con valor predeterminado 30, con ayuda contextual en el panel y validación en la API.
- R2: En cada cálculo la edad de la previsión es `horizon_start − retrieved_at` de la previsión AEMET apta usada. Si supera el límite, el plan conserva su estado físico, añade el aviso de entrada `stale_forecast` y expone `forecast_age_hours` y `forecast_max_age_hours`.
- R3: Un plan con `stale_forecast` se activa en modo mejor esfuerzo con las mismas reglas de precedencia que un plan con exclusiones, y `stale_forecast` aparece en `best_effort_reasons`.
- R4: El ciclo AEMET reintenta cada hora sin límite de intentos mientras no obtenga una previsión, incluso al cambiar de día local; el número de intentos y el próximo reintento son observables en Estado.
- R5: Nueva alerta de catálogo `forecast_stale`, abierta cuando un plan activado lleva `stale_forecast` y rearmada cuando se activa un plan con previsión dentro del límite; el mensaje incluye la hora de obtención, la edad, el límite, el último error y el próximo reintento.
- R6: La temperatura exterior medida nunca sustituye ni corrige la previsión en la planificación.
- R7: El paso Comprobar, Estado, la pestaña de previsión de `Análisis y datos` y Home Assistant muestran la previsión obsoleta con su edad y el límite.

## Acceptance
- A1: Pruebas de planificación: con una previsión de edad mayor que el límite el estado físico no cambia, aparecen `stale_forecast`, `forecast_age_hours` y el plan se activa en mejor esfuerzo; con edad igual o menor no aparece.
- A2: El token de entrada incluye el indicador de obsolescencia y el límite, no la edad exacta, de modo que un preview sigue siendo activable dentro del mismo slot.
- A3: Pruebas del ciclo AEMET: tras seis fallos el estado sigue `stale`, no completado y con reintento a una hora; un nuevo día tras un día fallido reintenta sin esperar a la hora de consulta.
- A4: Pruebas de alertas: `forecast_stale` se encola una vez por episodio y se rearma con una previsión fresca.
- A5: El parámetro recorre migración, repositorio, API y panel con validación de rango y sin escrituras parciales.
- A6: Pruebas de frontend y Home Assistant cubren el aviso y los valores mostrados; `make check` pasa.

## Decisions
- D1: La obsolescencia es un aviso de entrada ortogonal al estado físico, igual que las exclusiones del cambio de mejor esfuerzo.
- D2: 30 horas cubren el ciclo diario de AEMET con margen para algunos reintentos antes de avisar.
- D3: Los reintentos horarios indefinidos sustituyen al tope de cinco; el requisito vivo "Ciclo de previsión AEMET durable" se modifica en consecuencia.

## Tasks
- [ ] T1: Columna `forecast_max_age_hours` con migración Alembic, repositorio, esquema API y evidencia del plan; pruebas.
- [ ] T2: Edad de la previsión, aviso `stale_forecast`, token y modo de activación en el planificador y la activación; pruebas.
- [ ] T3: Reintentos AEMET sin tope y continuidad entre días; exposición del número de intentos; pruebas.
- [ ] T4: Alerta `forecast_stale` y sus mensajes; pruebas.
- [ ] T5: Panel, Estado, `Análisis y datos` y atributos de Home Assistant; campo de configuración y ayuda; pruebas.
- [ ] T6: Actualizar specs vivas de planificación y alertas; `make check`.
