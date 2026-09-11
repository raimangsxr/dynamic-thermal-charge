# Explicabilidad y diagnóstico de la planificación

Status: approved

## Goal
Permitir que un operador entienda con evidencia conservada por qué se generó y
activó un plan, qué cambió en una replanificación y qué actuación resultó, sin
tener que reconstruirlo desde logs ni conocer el optimizador.

## Requirements
- R1: Cada nuevo cálculo automático debe conservar un snapshot inmutable con su
  motivo, instante, revisiones, límites de potencia, consignas, telemetría con
  marcas de tiempo y validez, referencia y estado de la previsión, resultado del
  solver, déficits y magnitudes físicas por intervalo. Ningún secreto debe formar
  parte del snapshot.
- R2: La API debe exponer el detalle explicable de un plan activo o histórico por
  su identificador. En planes antiguos, cualquier evidencia no conservada debe
  figurar como no disponible, sin reconstruirse desde el estado actual.
- R3: El panel debe ofrecer desde la planificación activa una explicación breve
  y determinista por acumulador: estado inicial, objetivo relevante, demanda,
  carga asignada, evolución térmica, restricciones o déficits y motivo del
  cálculo.
- R4: El operador debe poder desplegar una línea temporal por acumulador y abrir
  cada intervalo para ver energía inicial, carga, calor entregado, pérdidas,
  energía final, temperatura proyectada, objetivo y potencia agregada frente a
  sus límites.
- R5: Una replanificación debe mostrar la causa registrada y comparar el nuevo
  resultado con el plan activo al que reemplaza: cambios relevantes de entradas,
  intervalos de carga añadidos o eliminados, energía/SOC final, temperatura
  prevista y déficits. Si el candidato no reemplaza al plan activo, debe indicarlo
  expresamente.
- R6: El panel debe mostrar un historial reciente de cálculos desde el que se
  pueda abrir la explicación conservada y reconocer planes activos, reemplazados
  y candidatos no activados.
- R7: El operador debe poder descargar un informe de diagnóstico legible por
  máquina con la evidencia del plan seleccionado, su comparación, eventos de
  auditoría y transiciones relacionadas, excluyendo secretos y credenciales.
- R8: Las explicaciones deben derivarse exclusivamente de campos estructurados y
  reglas deterministas; los logs pueden adjuntarse como evidencia, pero no ser la
  fuente de una conclusión.

## Acceptance
- A1: Dado un cálculo nuevo, cambiar después la configuración, telemetría o
  previsión no altera su explicación ni el informe descargado.
- A2: Desde el plan activo se puede identificar visualmente qué datos entraron,
  el balance de cualquier intervalo y qué restricciones o déficits condicionaron
  el resultado.
- A3: Tras una replanificación por desviación se muestran los valores planificados
  y medidos que la dispararon, el plan anterior y las diferencias del nuevo plan.
- A4: Un cálculo periódico o manual sin desviación se etiqueta con su motivo real
  y no presenta una causa inventada.
- A5: Un candidato `INVALID` o `DEGRADED` conservado sin activar explica el fallo y
  deja claro qué plan continúa gobernando las salidas.
- A6: Un plan anterior a esta funcionalidad sigue siendo consultable y marca la
  evidencia ausente como no disponible.
- A7: El informe descargado permite relacionar el plan con su auditoría y
  transiciones, y una prueba automática verifica que no contiene secretos.

## Outcome

La planificación conserva y expone evidencia estructurada, ofrece explicaciones
operativas e intervalos detallados en el panel y genera diagnósticos descargables
sin alterar el comportamiento del optimizador.
