# Replanificación por desviación del plan

Status: approved

## Goal

El plan se calcula suponiendo que la previsión AEMET se cumple y solo se
recalcula por reloj, cada `max(replan_minutes, slot_minutes)`. Cuando el
exterior es más frío de lo previsto, la estancia se enfría más de lo proyectado
y el acumulador llega a la consigna sin SOC suficiente, pero el sistema no lo
detecta hasta la siguiente replanificación periódica. Evaluar en cada límite de
slot si el plan vigente sigue sirviendo para las condiciones medidas y
recalcular en cuanto deje de servir.

## Requirements

- R1: En cada límite de slot, con un plan activo y control automático habilitado, el controlador reproyecta los intervalos restantes del plan partiendo de la temperatura interior y el SOC medidos de cada acumulador, conservando las decisiones de carga del plan vigente.
- R2: La reproyección usa el modelo físico de sala ya existente, sin resolver el MILP, de modo que la evaluación por slot no consume presupuesto de solver.
- R3: Si la reproyección revela un déficit de temperatura que el plan vigente no preveía, o lo agrava por encima de la tolerancia configurada, el controlador replanifica de inmediato en lugar de esperar la cadencia periódica.
- R4: Si la reproyección alcanza todas las consignas y deja un excedente de energía almacenada por encima de la tolerancia configurada respecto a la proyección del plan, el controlador también replanifica, para recortar carga que las condiciones reales han vuelto innecesaria.
- R5: Como máximo se produce una replanificación por desviación por slot, además de las periódicas y de las solicitadas por el operador.
- R6: Un acumulador sin telemetría reciente utilizable no se reproyecta y no dispara por sí mismo una replanificación; su ausencia de datos sigue tratándose por las reglas vigentes de entradas físicas frescas.
- R7: Una replanificación por desviación queda auditada con su motivo, el acumulador, el instante y los valores que la provocaron, distinguible de una periódica y de una solicitada por el operador.
- R8: Las tolerancias de déficit y de excedente se persisten en la configuración de Planificación con valores predeterminados y validación de rango.
- R9: Un recálculo disparado por desviación que devuelva `INVALID` conserva el plan activo anterior en lugar de desactivarlo, y registra el resultado inválido para auditoría sin activarlo.
- R10: Ese caso emite la alerta por email de replanificación imposible, con el motivo del resultado inválido, el instante y la advertencia de que se sigue ejecutando el plan anterior.
- R11: El resto del contrato no cambia: la cadencia periódica, el presupuesto del solver, la solicitud durable de recálculo del operador, el tratamiento de un recálculo periódico `INVALID` y el de un resultado `DEGRADED` conservan su comportamiento.

## Acceptance

- A1: Con un plan activo cuya proyección alcanzaba la consigna y una temperatura interior medida más baja, la reproyección revela un déficit y el ciclo replanifica sin esperar la cadencia periódica.
- A2: Con la temperatura interior medida igual a la proyectada, ningún ciclo dispara una replanificación por desviación.
- A3: Con una temperatura interior medida más alta y todas las consignas alcanzadas, un excedente de energía almacenada superior a la tolerancia dispara una replanificación.
- A4: Dos límites de slot consecutivos con desviación producen como máximo una replanificación por desviación cada uno, y una desviación sostenida dentro del mismo slot no produce una segunda.
- A5: Un acumulador sin SOC o sin temperatura interior recientes no dispara una replanificación por desviación, y otro acumulador del mismo ciclo con desviación sí la dispara.
- A6: El historial de auditoría del plan distingue una replanificación por desviación de una periódica y expone el acumulador y los valores que la provocaron.
- A7: Un recálculo por desviación que devuelve `INVALID` deja el plan anterior activo, guarda el resultado inválido sin activarlo y emite una única alerta por email.
- A8: Un recálculo periódico que devuelve `INVALID` sigue desactivando el plan activo, sin cambio de comportamiento.
- A9: La API persiste y devuelve ambas tolerancias, rechaza valores fuera de rango y conserva la validación de revisión de la configuración de Planificación; `make check` pasa.

## Decisions

- D1: La reproyección cubre todos los intervalos restantes del plan activo, no solo la ventana visible: un déficit que aparece más allá de la ventana también invalida las decisiones de carga que se están ejecutando ahora.
- D2: La reproyección usa `RoomEnergyDemandEstimator` con las decisiones de carga del plan y sin fijar el calor entregado, es decir, con el mismo controlador ideal de sala del modelo de planificación. Así el veredicto es coherente con el criterio con el que se construyó el plan.
- D3: La señal es el déficit reproyectado, no una desviación en grados respecto a la proyección. Una desviación pequeña que compromete una consigna dispara, y una desviación grande sin consecuencias para el confort no dispara.
- D4: El excedente de R4 se mide como energía almacenada proyectada al final del plan por encima de la del plan vigente. El optimizador ya minimiza la carga, así que un excedente solo puede venir de unas condiciones reales más favorables que las previstas.
- D5: Las tolerancias van en la configuración de Planificación por ser comportamiento de ejecución ajustable por el operador: déficit en grados, con 0,1 °C predeterminado, y excedente en puntos de SOC, con 5 puntos predeterminados.
- D6: La evaluación ocurre en el ciclo de control, en el límite de slot, y no en el proceso de replanificación: es la comprobación que decide si hay que replanificar antes de tiempo.
- D7: Un recálculo por desviación que devuelva `INVALID` conserva el plan anterior, al contrario que uno periódico, que lo desactiva. La asimetría se justifica porque el disparo por desviación es una comprobación adicional y oportunista: si no puede producir un plan mejor, dejar la instalación como estaba nunca es peor que no haber disparado. Un recálculo periódico sí expresa que las entradas vigentes ya no sostienen ningún plan, y su desactivación se conserva.
- D8: `save_plan` desactiva hoy el plan anterior siempre que el nuevo es `INVALID` (`persistence/planning.py:493`), así que hace falta una vía explícita para persistir un resultado inválido sin desactivar. Se añade como opción del guardado, usada solo por el disparo por desviación, en lugar de deducirla del motivo.
- D9: El sistema no mide la temperatura exterior, así que la previsión errónea no se corrige. La realimentación es el interior y el SOC medidos, que es suficiente para que el recálculo programe la carga adicional. Corregir un sesgo de previsión exigiría un sensor exterior y queda fuera de este cambio.
- D10: Este cambio depende de la capacidad de alertas por email del cambio `email-alerts`, que aporta la configuración, la cola duradera y la deduplicación por episodio. Aquí solo se añade el tipo de alerta al catálogo y su emisión.
- D11: La calidad de la señal mejora con `soc-dependent-emission-limit`, porque un SOC bajo pasará a reproyectar el déficit que hoy el modelo no ve. Los cambios son independientes en el código.

## Tasks

- [ ] T1: Añadir las dos tolerancias a la configuración de Planificación con migración Alembic, esquema, API y panel.
- [ ] T2: Añadir una función pura que, dado el plan activo, la telemetría vigente y el instante, devuelva si hay que replanificar y el motivo, el acumulador y los valores que lo justifican.
- [ ] T3: Conectarla al ciclo de control en el límite de slot, con el límite de una replanificación por desviación por slot.
- [ ] T4: Registrar el motivo y sus valores en la auditoría del plan, distinguible de `periodic` y de una activación del operador.
- [ ] T5: Añadir al guardado del plan la vía explícita para persistir un resultado `INVALID` sin desactivar el plan anterior, y usarla solo en el disparo por desviación.
- [ ] T6: Añadir el tipo de alerta de replanificación imposible al catálogo de `email-alerts` y emitirlo en ese caso.
- [ ] T7: Cubrir con tests el déficit reproyectado, el caso sin desviación, el excedente, el límite por slot, la telemetría no utilizable, la conservación del plan anterior con un `INVALID` por desviación, la desactivación con un `INVALID` periódico, la alerta y la auditoría.
- [ ] T8: Actualizar `openspec/specs/planning/spec.md` y la sección de replanificación de `README.md`.
- [ ] T9: Ejecutar `make check`.
