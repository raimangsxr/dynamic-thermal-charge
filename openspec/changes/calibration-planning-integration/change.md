# Integrar la calibración térmica con la planificación

Status: draft

## Goal
Que una calibración en curso no se presente como una degradación de la planificación. Hoy el acumulador calibrado se excluye con la causa `calibration_active` reutilizando el mecanismo de exclusión de mejor esfuerzo, lo que marca todos los planes como mejor esfuerzo, envía avisos falsos de telemetría ausente y provoca replanificaciones por desviación en cada slot. Además, el cuestionario de estimación de la estancia debe poder abrirse cuando el usuario lo decida.

Depende de `automatic-thermal-calibration` (rama `raimangsxr/thermal-calibration`): se implementa apilado sobre ella o después de su merge.

## Requirements
- R1: Una exclusión con causa `calibration_active` no convierte el plan en mejor esfuerzo: la activación automática y manual, `best_effort` y `best_effort_reasons` solo consideran exclusiones `missing_required_state` y los demás motivos existentes.
- R2: La alerta `plan_heater_excluded` solo se abre y se mantiene por acumuladores con causa `missing_required_state`; un acumulador en calibración no la abre ni impide su rearme.
- R3: La comprobación de desviación omite los acumuladores cuya calibración está activa en el instante evaluado, con la misma fuente de propiedad que usa el planificador; los demás acumuladores siguen pudiendo disparar un recálculo.
- R4: Planificación, Estado, snapshot operativo y Home Assistant distinguen un acumulador `en calibración` de uno excluido por telemetría, con etiqueta propia en español y sin mostrar acción recomendada de recuperar telemetría.
- R5: El cuestionario de estimación inicial se abre por acción explícita del usuario en cualquier estado de la estancia salvo con una sesión de calibración activa, que lo rechaza sin escrituras parciales; aplicar la estimación conserva el contrato existente (estado `estimated`, replanificación).
- R6: Al terminar una calibración por cualquier causa, el recálculo solicitado vuelve a incluir el acumulador en el plan sin intervención del usuario.

## Acceptance
- A1: Pruebas de planificación y runtime: con un acumulador en calibración y el resto con telemetría fresca, un plan `VALID` se activa en modo normal, `best_effort` es falso y no se encola `plan_best_effort_active` ni `plan_heater_excluded`.
- A2: Con un acumulador en calibración y otro sin telemetría, el plan es mejor esfuerzo solo por `missing_required_state` y la alerta de exclusión nombra únicamente al segundo.
- A3: Prueba de desviación: un acumulador en calibración con telemetría fresca y déficit proyectado no dispara `projected_deficit`; otro acumulador comprobable sí puede dispararlo.
- A4: Pruebas API/frontend/Home Assistant muestran la etiqueta `En calibración` y ninguna acción de telemetría para ese acumulador.
- A5: Pruebas API y Angular: el cuestionario se abre con estancia `approximate`, `calibrated`, `estimated`, `manually_adjusted`, `failed` y `cancelled`, y se rechaza durante una sesión activa.
- A6: Tras terminar una sesión, el siguiente plan contiene de nuevo decisiones para ese acumulador; `make check` pasa.

## Decisions
- D1: `calibration_active` sigue viajando en `excluded_heaters` para conservar la trazabilidad del plan; lo que cambia es qué causas cuentan como degradación.
- D2: La desviación consulta la propiedad de calibración vigente y no la causa guardada en el plan, para no depender de un plan que pudo calcularse antes del inicio de la sesión.

## Tasks
- [ ] T1: Filtrar `calibration_active` en el modo de activación, motivos de mejor esfuerzo y alerta de exclusión; pruebas.
- [ ] T2: Omitir acumuladores en calibración en la comprobación de desviación; pruebas.
- [ ] T3: Etiquetas y proyecciones en API, Angular, snapshot y Home Assistant; pruebas.
- [ ] T4: Abrir el cuestionario de estimación a demanda con rechazo durante sesión activa; pruebas API y Angular.
- [ ] T5: Actualizar specs vivas de planificación y alertas; `make check`.
