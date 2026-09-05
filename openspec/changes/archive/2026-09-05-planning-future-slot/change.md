# Ventana y horizonte desde el siguiente slot no pasado

Status: approved

## Goal

Evitar que la planificación automática incluya intervalos ya iniciados cuando
se recalcula entre límites de slot. La ventana visible y el horizonte completo
deben empezar en el primer límite de slot que no haya quedado atrás.

## Requirements

- R1: El planner automático debe alinear el inicio al primer límite de
  `slot_minutes` mayor o igual que el instante de cálculo; si el instante cae
  dentro de un slot, debe avanzar al límite siguiente.
- R2: `horizon_start`, `window_start`, sus finales, los slots y la
  materialización de constraints deben derivarse del mismo inicio alineado y
  conservar exactamente las duraciones configuradas.
- R3: La generación del `input_token` debe usar la misma alineación futura que
  el planner, manteniendo la compatibilidad entre preview y activación.
- R4: La especificación viva y las pruebas deben describir y verificar que el
  inicio nunca es anterior al instante de cálculo.

## Acceptance

- A1: Con `slot_minutes=15` y cálculo a las 23:25, el plan empieza a las
  23:30; una hora exactamente alineada conserva ese límite y una hora con
  segundos posteriores avanza al siguiente.
- A2: Si el redondeo avanza a medianoche, el horizonte conserva el número de
  slots y termina exactamente tras la duración configurada.
- A3: Preview y activación calculan el mismo token para las mismas entradas y
  no aparece ningún slot anterior al instante de cálculo.
- A4: La suite determinista del proyecto (`make check`) continúa pasando.
