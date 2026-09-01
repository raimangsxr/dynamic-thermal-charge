# Planificación optimizada por forecast AEMET

Status: approved

## Goal

Sustituir el modelo de carga automática actual por una planificación rolling-horizon, determinista y explicable que use el forecast horario AEMET y el estado MQTT real para cubrir confort y constraints con la mínima carga posible, sin superar nunca la potencia disponible ni el 100 % de ningún acumulador.

## Requirements

- R1: La configuración persistente global incluye potencia contratada, potencia máxima de acumuladores (por defecto igual a la contratada), horizonte de hasta 48 h, slot divisor de una hora, temperaturas de diseño con interior mayor que exterior y horizonte positivo de feedback; cada acumulador valida potencia y tiempo de carga positivos, prioridad entera, `demand_factor > 0` y reserva no negativa, y expone `capacity_kwh = charge_power_kw × full_charge_time_hours`.
- R2: El proveedor meteorológico permanece desacoplado del core y normaliza puntos horarios AEMET; el horizonte empieza en un límite de slot y termina en el menor entre la configuración y la cobertura AEMET continua disponible. Sin cobertura AEMET utilizable el resultado es `INVALID`; el fallback simulado no autoriza carga automática de producción.
- R3: Un `DemandEstimator` puro `degree_hours_v1` calcula kWh por slot con `design_delta_c = design_indoor_temperature_c - design_outdoor_temperature_c` y `thermal_coefficient = capacity_kwh / (24 × design_delta_c)`, usando temperatura objetivo MQTT, feedback lineal de temperatura real hasta su horizonte, `demand_factor` y finalmente reserva multiplicativa; nunca genera demanda negativa ni usa `thermal_loss_rate`.
- R4: Un `ChargePlanner` puro recibe demanda, SOC MQTT actual, acumuladores, constraints materializadas y potencia global, y modela por slot carga ON/OFF a potencia nominal, balance energético en kWh y SOC entre 0 y 100 %, sin carga que exceda la capacidad ni combinación que exceda la potencia global.
- R5: Las constraints recurrentes se materializan con la timezone del sistema para todas las fechas del horizonte, solo aceptan porcentajes 0..100 y horas alineadas al slot, y exigen `SOC >= minimum` en el límite temporal indicado, antes de consumir la demanda del slot que comienza entonces.
- R6: El planificador optimiza lexicográficamente: restricciones físicas; menor shortfall de constraints por niveles de prioridad descendente; menor demanda forecast no servida por niveles de prioridad descendente; menor kWh cargado; perfil de carga más tardío; y desempate determinista. La prioridad nunca crea demanda ni carga adicional.
- R7: Si no puede satisfacerse todo, devuelve el mejor plan físicamente válido como `DEGRADED` y violations tipadas con requisito, valor alcanzable, shortfall, instante y motivo; potencia individual superior al límite, estado imprescindible ausente y configuración inválida también producen violations explícitas y, cuando impiden planificar con seguridad, estado `INVALID` sin activaciones ON.
- R8: El resultado usa estados `FEASIBLE`, `DEGRADED` o `INVALID` e incluye timestamps del horizonte y generación, potencia y estado por acumulador en cada slot, SOC esperado inicial/final, demanda estimada, violations y explicación por acumulador (SOC real, demanda, factor, reserva, próxima constraint y periodos de carga).
- R9: `PlanningService` obtiene en cada ejecución el forecast y las últimas muestras MQTT, estima, materializa constraints, planifica y persiste/publica el resultado sin que el core conozca HTTP, MQTT, base de datos, topics ni reloj real; nunca usa como SOC inicial la proyección del plan anterior.
- R10: Se replantea al arrancar, al comenzar cada slot, tras un forecast nuevo y tras cambios de objetivo, configuración global/de acumulador o constraints; las actualizaciones de temperatura/SOC pueden coalescerse, pero sus últimos valores conocidos se leen al planificar.
- R11: La configuración, migraciones, API, persistencia, ejecución del controlador y documentación pública se adaptan al nuevo dominio, retirando de V1 `thermal_loss_rate` y la semántica heredada de reserva como puntos extra de SOC, sin introducir precios, aprendizaje ni modelado térmico adicional.

## Acceptance

- A1: Tests unitarios prueban capacidad, degree-hours, feedback que se desvanece, reserva multiplicativa, `demand_factor`, cero demanda en condiciones cálidas y forecast horario/truncamiento del horizonte.
- A2: Tests puros del planner prueban límites global y de capacidad, combinaciones simultáneas válidas, ON/OFF/ON, constraints y weekdays, prioridades, plan imposible degradado, JIT y determinismo.
- A3: Tests prueban que un SOC MQTT 0 % es válido, que una replanificación usa el nuevo SOC real, que estado/forecast imprescindible ausente produce `INVALID` y que potencia individual excesiva se informa sin violar el límite.
- A4: Tests de integración prueban migración, lectura/escritura de configuración, API de preview/activación, persistencia de plan/violations/explicación y eventos de replanificación sin broker, AEMET real, reloj real ni base externa.
- A5: `make check` pasa y README describe la configuración y semántica públicas vigentes.

## Decisions

- D1: Ante varias constraints o demandas de igual prioridad se minimiza la suma de shortfall energético del nivel; prioridades distintas se resuelven en optimizaciones sucesivas, sin pesos arbitrarios.
- D2: La falta de cualquiera de las tres muestras MQTT requeridas para un acumulador habilitado invalida el plan completo; es la opción segura porque no existe un estado inicial fiable para accionar salidas.
- D3: La cobertura meteorológica debe ser horaria y continua desde el inicio del horizonte; no se inventan temperaturas ni se amplía el último punto. Los puntos AEMET normalizados pueden repetirse en los subslots que cubre su hora.

## Tasks

- [x] T1: Migrar y mapear la configuración y los modelos de dominio V1, eliminando los campos térmicos excluidos.
- [x] T2: Implementar y probar proveedor normalizado, estimador `degree_hours_v1` y materialización de constraints.
- [x] T3: Implementar y probar la optimización lexicográfica, resultados, violations y explicabilidad.
- [x] T4: Integrar rolling horizon con persistencia, API, MQTT/controlador y eventos de replanificación.
- [x] T5: Actualizar compatibilidad visible y README, y ejecutar la puerta de calidad completa.
