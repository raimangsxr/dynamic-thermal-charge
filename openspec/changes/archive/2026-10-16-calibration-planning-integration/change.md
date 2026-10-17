# Integrar la calibración térmica con la planificación

Status: approved

## Goal
Que una calibración en curso no se presente como una degradación de la
planificación ni provoque replanificaciones falsas, y que el cuestionario de
estimación de la estancia pueda abrirse cuando el usuario lo decida.

## Requirements
- R1: `calibration_active` se conserva en `excluded_heaters` para mantener la
  trazabilidad, pero no cuenta como degradación: la activación, `best_effort`,
  `best_effort_reasons` y las alertas solo consideran `missing_required_state`
  y los demás motivos degradantes.
- R2: La desviación consulta la propiedad viva de calibración, omite los
  acumuladores activos y permite que otro acumulador comprobable solicite un
  recálculo.
- R3: Planning, Status, snapshot operativo y Home Assistant proyectan de
  inmediato una sesión activa aunque el plan persistido aún no se haya
  recalculado; muestran `En calibración` y no recomiendan recuperar telemetría.
- R4: Al terminar una calibración por cualquier causa, el recálculo solicitado
  vuelve a incluir el acumulador sin intervención adicional del usuario.
- R5: El cuestionario de estimación inicial se abre por acción explícita en
  cualquier estado de la estancia, salvo durante una sesión activa, que lo
  rechaza sin escrituras parciales; aplicar la estimación conserva el estado
  `estimated` y solicita planificación.
