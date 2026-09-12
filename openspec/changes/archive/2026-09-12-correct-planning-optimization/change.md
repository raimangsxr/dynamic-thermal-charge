# Corregir las garantías de la optimización térmica

Status: approved

## Goal

Garantizar que el planificador respeta el orden de optimización aprobado también
con el tamaño habitual de la instalación y que no vacía al final del horizonte
un acumulador cuya consigna continúa activa.

## Requirements

- R1: El confort se optimiza y bloquea por nivel de prioridad antes de evaluar
  consumo, estado terminal, calor fuera de consigna o momento de carga, con
  independencia del número de acumuladores y slots.
- R2: Solo un plan que haya alcanzado el óptimo de todas las fases puede ser
  `VALID`; agotar el presupuesto conserva únicamente una solución factible
  verificada como `DEGRADED` con `solver_time_limit`.
- R3: Tras fijar el confort, el optimizador minimiza en este orden la energía
  cargada, el excedente terminal no necesario, el calor entregado, el calor
  fuera de consigna y la anticipación de la carga, seguido de desempates
  deterministas que no alteran fases anteriores.
- R4: Si una consigna está activa en el borde final y continúa en el siguiente
  slot, el excedente terminal solo penaliza energía por encima de la reserva
  física mínima necesaria para atravesar ese slot de guarda sin déficit.
- R5: El slot de guarda usa el mismo balance térmico, capacidad de emisión y
  previsión exterior que el horizonte, pero no se publica como decisión del
  plan. Si no existe cobertura meteorológica para calcularlo, el resultado es
  explícitamente `INVALID` por cobertura insuficiente.
- R6: Si ninguna consigna continúa después del horizonte, no se introduce
  reserva terminal nueva y se mantiene la minimización vigente del excedente.

## Acceptance

- A1: Un escenario con más de 96 decisiones binarias y contención eléctrica no
  empeora ningún déficit de prioridad superior para mejorar una prioridad
  inferior, reducir carga o desplazarla en el tiempo.
- A2: En ese mismo tamaño, dos soluciones con igual confort y energía cargada
  eligen los últimos slots físicamente viables de forma reproducible.
- A3: Con una consigna que cruza el final del horizonte y SOC inicial bajo, el
  plan termina con la reserva mínima que permite cumplir los dos bordes del slot
  de guarda sin carga adicional ni déficit.
- A4: La misma entrada, pero con la consigna terminada en el borde final, no
  conserva una reserva implícita.
- A5: Si cualquier fase no demuestra optimalidad dentro del presupuesto total,
  el resultado es `DEGRADED` con `solver_time_limit` y no se puede activar.
