# Restaurar el ciclo AEMET y la integridad del solver

Status: approved

## Goal

La planificación automática dejó de refrescar la previsión AEMET: `refresh_plan` retorna
antes de obtenerla cuando existen constraints o un plan activo, así que al agotarse la
cobertura horaria almacenada el plan pasa a `INVALID` y todas las salidas quedan
apagadas indefinidamente. Además el optimizador puede presentar como óptimo un plan que
el solver no resolvió. Este cambio devuelve al sistema previsión vigente en todo momento
y garantiza que nunca se publique como válido un plan que no lo es, sin alterar el modelo
de demanda ni la formulación del MILP.

## Requirements

- R1: La obtención y persistencia de la previsión ocurre en cada replanificación,
  con independencia del motor que construya el plan. La planificación automática usa la
  previsión almacenada más reciente y ya no depende de una consulta manual.
- R2: La consulta diaria a AEMET se gobierna por `aemet_query_hour` en la zona horaria de
  la instalación, con un intento y exactamente cinco reintentos horarios. Su estado es
  durable y sobrevive a un reinicio sin reiniciar el contador de intentos.
- R3: Agotados los reintentos se conserva la última previsión válida marcada obsoleta y
  se sigue planificando con ella; nunca se sustituye por valores simulados, y una
  previsión simulada o de respaldo continúa sin autorizar carga automática.
- R4: Un fallo al obtener la previsión no aborta la replanificación: el plan se recalcula
  con la última previsión almacenada utilizable.
- R5: La cadencia de replanificación se gobierna por `replan_minutes`, alineada a
  frontera de intervalo y con un intervalo como cota inferior.
- R6: El plan solo se declara `FEASIBLE` cuando todas las fases del solver alcanzaron el
  óptimo. Un valor de variable ausente es un fallo del solver, nunca un cero.
- R7: Si el solver agota su límite de tiempo, el resultado es `DEGRADED` con una
  violación tipada `solver_time_limit` cuando existe una solución factible verificada, y
  `INVALID` cuando no existe. El desempate entre soluciones equivalentes vuelve a ser
  determinista.
- R8: El controlador rechaza arrancar con salidas GPIO cuando la telemetría no proviene
  de MQTT real, es decir cuando MQTT está deshabilitado o la simulación de acumuladores
  está activa, informando la causa como evento crítico.
- R9: Persistir un plan `INVALID` desactiva el plan activo anterior, de modo que la
  consulta del plan nunca muestra un plan distinto del que se está ejecutando.
- R10: El déficit informado por acumulador agrega todas sus violaciones en lugar de
  conservar solo la última.
- R11: El optimizador respeta simultáneamente la potencia contratada y la potencia máxima
  de acumuladores, y admite una carga base de la vivienda que se descuenta de la
  contratada, con valor cero por defecto.
- R12: Las tablas de planificación automática y de previsión horaria se recortan por
  antigüedad igual que el resto del histórico.

## Acceptance

- A1: Un test de integración prueba que una replanificación con constraints activas
  registra una previsión nueva y un ciclo de previsión, y que el plan resultante usa esa
  previsión. Este test falla con el código actual.
- A2: Tests prueban el ciclo diario: se consulta a `aemet_query_hour`, un fallo programa
  el reintento a la hora siguiente, el sexto fallo marca el ciclo obsoleto y completado,
  y el estado restaurado desde persistencia no reinicia el contador.
- A3: Un test prueba que, con previsión obsoleta conservada, el plan se sigue calculando
  y que una previsión de respaldo produce `INVALID` con motivo `forecast_not_eligible`.
- A4: Tests prueban que la cadencia de replanificación respeta `replan_minutes` alineada
  a intervalo y nunca baja de un intervalo.
- A5: Tests con un solver simulado prueban que un estado no óptimo y un valor de variable
  ausente nunca producen `FEASIBLE`, y que el límite de tiempo produce `DEGRADED` con
  `solver_time_limit` o `INVALID`, jamás un plan con todos los intervalos apagados
  presentado como óptimo.
- A6: Un test prueba que dos ejecuciones con la misma entrada producen el mismo
  `input_token`, los mismos acumuladores activos por intervalo y el mismo `score`.
- A7: Un test prueba que el arranque con GPIO y telemetría no real se rechaza con la
  causa registrada.
- A8: Tests prueban que un plan `INVALID` deja sin plan activo, que el déficit agrega
  varias violaciones del mismo acumulador y que ambos límites de potencia y la carga base
  restringen el plan.
- A9: Un test prueba que las tablas de planificación automática y previsión horaria se
  recortan por `retention_days`.
- A10: `make check` pasa y `README.md` describe la cadencia de previsión y
  replanificación vigente y la restricción de arranque con GPIO.

## Outcome

El ciclo AEMET, la cadencia de replanificación y las garantías de publicación
del solver quedan restaurados; la configuración de carga base se migra con un
valor por defecto de cero.
