# Planificación de 24 horas con progreso explicable

Status: approved

## Goal

Hacer que toda planificación automática y su vista previa describan una situación
continua y completa de las próximas 24 horas. Durante una vista previa, el
operador debe poder seguir, reanudar tras recargar y cancelar el cálculo, y
recibir un resultado comprensible y visualmente explicable en lugar de métricas
internas del solver.

## Requirements

- R1: La planificación automática y la vista previa planifican exactamente las
  24 horas continuas desde el siguiente límite de intervalo configurado.
- R2: Si no existe cobertura AEMET horaria continua para las 24 horas, no se
  genera un plan parcial y el resultado explica que falta cobertura.
- R3: Iniciar una vista previa crea un trabajo persistente, no modificador del
  plan activo, con estados recuperables tras recargar o volver a la pantalla.
- R4: El panel muestra y actualiza los checks de validación de inputs,
  telemetría, cobertura AEMET, estimación de demanda, materialización de
  constraints, resolución, validación de seguridad y resumen final.
- R5: El operador puede solicitar la cancelación de una vista previa. El panel
  muestra que está cancelando; el cálculo termina de forma segura al concluir
  la fase activa del solver y no puede activarse su resultado.
- R6: Con nivel `DEBUG`, el servicio registra las entradas, comprobaciones,
  estimaciones, fases del solver, decisiones por acumulador e intervalo, y el
  motivo de cada déficit, error o cancelación.
- R7: El resultado de la vista previa usa lenguaje de operador: ventana,
  previsión usada, carga prevista por acumulador, cumplimiento de constraints,
  avisos agrupados por causa y acción recomendada. No muestra la puntuación
  interna del solver como mensaje principal.
- R8: Los gráficos de Planificación muestran la vista previa de 24 horas cuando
  existe, y el plan activo en su ausencia; comparten el mismo eje temporal y
  distinguen claramente ambos contextos.
- R9: La visualización explica por cada acumulador cuándo carga, a qué potencia,
  cuánta energía aporta y qué porcentaje de su capacidad representa; muestra la
  evolución del SOC y las constraints aplicables.
- R10: La visualización muestra la temperatura estimada de cada estancia con la
  previsión exterior AEMET superpuesta, la potencia total frente a los límites
  disponibles y la previsión horaria usada para las próximas 24 horas.
- R11: Cada gráfico tiene una alternativa textual o tabular accesible con los
  mismos valores y unidades esenciales.

## Acceptance

- A1: Tests prueban que la planificación contiene 24 horas completas y que una
  cobertura AEMET de menos de 24 horas devuelve un resultado explícitamente no
  planificable, sin intervalos parciales.
- A2: Un test de integración inicia una vista previa, recarga su estado por su
  identificador y recibe todos los checks con sus estados finales.
- A3: Tests prueban que la cancelación pasa por el estado visible
  `cancelando`, termina tras una fase del solver y no permite activar el job.
- A4: Tests de logs `DEBUG` prueban que quedan trazas de cada etapa y que el
  resultado relaciona los avisos con su causa.
- A5: Tests del panel prueban estados pendiente, en curso, completado, error y
  cancelado; el resultado no muestra la puntuación técnica y sí un resumen y
  acciones comprensibles.
- A6: Tests del panel prueban que una preview de 24 horas alimenta la matriz de
  carga, el SOC, temperaturas interiores con forecast, potencia total y
  previsión; cada visualización identifica unidades, acumuladores y ventana.
- A7: Tests prueban que las representaciones textuales o tabulares contienen los
  datos esenciales de cada gráfico sin requerir canvas.

## Decisions

- D1: Las 24 horas son obligatorias tanto para el controlador como para la
  vista previa; el horizonte ya no admite resultados parciales.
- D2: El progreso se persiste para sobrevivir a recargas o navegación y la
  cancelación es cooperativa al finalizar la fase actual del solver.
- D3: El detalle `DEBUG` se registra inicialmente en los logs del servicio,
  no en el visor de logs del panel.
