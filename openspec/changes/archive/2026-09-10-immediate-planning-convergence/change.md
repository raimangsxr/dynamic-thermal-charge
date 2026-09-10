# Convergencia inmediata a una nueva planificación

Status: approved

## Goal

Evaluar siempre una nueva planificación desde el momento actual, activarla solo
si ya es válida o puede converger a corto plazo y, durante esa convergencia,
informar al operador con la hora de cumplimiento continuado proyectada por el
modelo.

## Requirements

- R1: Guardar y activar debe sustituir inmediatamente el conjunto de consignas
  vigente y calcular desde el siguiente límite de slot que no haya pasado. No
  debe existir selección de fecha ni planificación pendiente.
- R2: El resultado debe usar cuatro estados canónicos: `VALID` cuando cumple
  todas las consignas exigibles del horizonte desde el comienzo; `CONVERGING`
  cuando solo tiene un tramo inicial de incumplimiento y demuestra un instante
  posterior de cumplimiento continuado; `DEGRADED` cuando no demuestra esa
  convergencia; e `INVALID` cuando las entradas o el cálculo no son aptos.
- R3: Solo los resultados `VALID` y `CONVERGING` deben poder activarse. La API
  debe rechazar la activación de `DEGRADED` e `INVALID` aunque el cliente intente
  invocarla directamente, y el plan vigente debe permanecer intacto.
- R4: Mientras una consigna quede incumplida, reducir el déficit térmico debe
  prevalecer sobre ahorrar carga o energía. Con un único acumulador y potencia
  disponible, el plan debe cargar o entregar calor desde el primer slot en que
  ello permita acercarse al objetivo; con recursos compartidos se deben
  conservar los límites y prioridades configurados.
- R5: La interfaz debe presentar `CONVERGING` como un aviso no bloqueante que
  indica que el plan se aplicará de inmediato y necesita un periodo inicial de
  adaptación. `DEGRADED` debe presentarse como plan no activable.
- R6: Para clasificar un plan como `CONVERGING` debe existir, dentro del
  horizonte, un borde con consigna activa que ya se cumpla y tras el cual no
  vuelva a existir ningún déficit en ningún borde con consigna activa. Ese borde
  es la hora proyectada de cumplimiento continuado; el final de una ventana o
  un hueco sin consigna no pueden contarse por sí solos como convergencia.
- R7: Los déficits consecutivos de la misma ventana de consigna, acumulador y
  causa deben mostrarse como un solo aviso con intervalo afectado y déficit
  máximo. Un resultado `CONVERGING` debe mostrar la hora de cumplimiento de cada
  acumulador afectado y la hora global, igual a la última de ellas, junto con el
  final del horizonte hasta el que se garantiza.
- R8: El detalle técnico debe conservar todas las observaciones originales por
  borde e intervalo aunque la presentación para el operador las agrupe.
- R9: Las entradas ausentes u obsoletas, la configuración inválida, la falta de
  cobertura meteorológica y un solver sin solución verificable deben seguir
  produciendo `INVALID`, bloquear la activación y mostrarse como errores, no como
  avisos de adaptación.
- R10: `VALID` debe sustituir a `FEASIBLE` como nombre público y persistido del
  estado satisfactorio. Los planes históricos almacenados como `FEASIBLE` deben
  seguir siendo legibles y exponerse a los clientes como `VALID`.
- R11: Si una replanificación periódica de un horario ya activo produce
  `DEGRADED`, no debe activar ese candidato. Debe conservar el último plan
  `VALID` o `CONVERGING` mientras tenga slots vigentes, hacer visible la
  degradación y continuar recalculando con la cadencia configurada; agotado su
  horizonte sin sustituto activable, se aplica el comportamiento seguro
  existente de ausencia de plan vigente.
- R12: La entrada en ese estado debe encolar una alerta de email durable y
  deduplicada por episodio mediante el catálogo de alertas existente. Ciclos
  `DEGRADED` consecutivos no deben repetir el correo; un resultado posterior
  `VALID` o `CONVERGING` rearma la alerta para un episodio futuro.
- R13: El correo debe identificar la instalación, el instante, los acumuladores
  y consignas afectados, la causa y déficit máximo, el horizonte restante del
  plan conservado y la consecuencia de no disponer de un sustituto activable.
  Un fallo o desactivación del correo no debe afectar al plan ni al controlador.

## Acceptance

- A1: Dadas las 16:00, una temperatura insuficiente y una nueva consigna de
  25 °C entre las 17:00 y las 21:00, la preview propone carga o aporte de calor
  desde el primer slot útil y queda `CONVERGING` si demuestra que después podrá
  cumplir de forma continuada.
- A2: Al activar esa preview `CONVERGING`, las nuevas consignas y el plan
  sustituyen inmediatamente a los anteriores y la interfaz confirma la
  activación junto con la hora de cumplimiento continuado.
- A3: Los déficits consecutivos de esa ventana se muestran en un único aviso con
  el acumulador, 17:00–21:00, el déficit máximo y la hora de convergencia prevista
  o la ausencia de garantía dentro del horizonte.
- A4: Abrir el detalle del aviso permite consultar cada déficit de inicio y fin
  que produjo el plan, con sus instantes y temperaturas proyectadas.
- A5: Con un acumulador por debajo del objetivo y potencia disponible desde el
  primer slot, una alternativa que posponga carga para ahorrar energía no puede
  imponerse a otra que reduzca antes el déficit.
- A6: Si queda algún déficit después del supuesto instante de convergencia, no
  existe ningún borde activo posterior que demuestre recuperación o no puede
  mantenerse el objetivo, la preview queda `DEGRADED`, no puede activarse y el
  plan vigente no cambia.
- A7: Si falta telemetría reciente o cobertura AEMET continua, la preview queda
  `INVALID`, explica el error y no permite guardar ni activar.
- A8: Una planificación que ya puede cumplirse se activa inmediatamente como
  `VALID` y no muestra avisos de adaptación.
- A9: Un plan histórico persistido con estado `FEASIBLE` se consulta como
  `VALID` sin perder sus slots, explicaciones ni auditoría.
- A10: Si el plan activo era `CONVERGING` y el siguiente recálculo resulta
  `DEGRADED`, el candidato no se activa, el plan anterior continúa gobernando
  sus slots vigentes y el panel muestra el fallo de convergencia.
- A11: Dos recálculos `DEGRADED` consecutivos del mismo episodio producen un
  solo correo. Tras un recálculo `VALID` o `CONVERGING`, un nuevo episodio
  `DEGRADED` produce otro correo.
- A12: Si el último plan activable alcanza el final de su horizonte sin
  sustituto, deja de accionar salidas; el fallo de SMTP no altera ese resultado.
