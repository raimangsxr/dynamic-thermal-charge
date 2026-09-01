# Design

## Approach

Introducir tres núcleos puros: `DegreeHoursDemandEstimator`, materializador de constraints y `MilpChargePlanner`. `PlanningService` construirá un snapshot inmutable de configuración, forecast, telemetría y hora inyectada; el resultado completo seguirá siendo un value object que las capas API, persistencia y controlador adaptan.

`degree_hours_v1` obtiene para cada acumulador `design_delta_c = design_indoor_temperature_c - design_outdoor_temperature_c` y exige que sea positivo. Su coeficiente nominal es `capacity_kwh / (24 × design_delta_c)`, expresado conceptualmente en kWh/(h×°C). En cada slot usa `target_mqtt - outdoor + (target_mqtt - real_temperature) × max(0, 1 - elapsed_hours / feedback_horizon_hours)` y limita solo este resultado final a un mínimo de cero; por tanto el feedback aumenta demanda si la estancia está fría y la reduce si está por encima del objetivo.

El planner formulará un MILP con una variable binaria ON/OFF y variables continuas de energía/shortfall por acumulador y slot. Se resolverá con PuLP y CBC en fases sucesivas: cada óptimo se fija antes de resolver el siguiente nivel de prioridad; después se fija la carga total y se minimiza, slot a slot desde el principio, la energía situada temprano. Variables e inputs se crean siempre en orden canónico y CBC se ejecuta con un hilo y parámetros deterministas.

## Constraints

- El despliegue objetivo es Raspberry Pi/ARMv7: PuLP es Python puro y CBC se instalará como paquete Debian del contenedor, evitando wheels nativos no disponibles en esa plataforma.
- Toda la aritmética de dominio usa kW, kWh y horas; los W/minutos de interfaces heredadas se convierten solo en los bordes.
- El balance representa demanda no servida con slack: `energy_next = energy + charge - demand + unmet`. Así la energía física nunca es negativa y el shortfall de confort queda cuantificado sin falsear SOC.
- Los tests del core usan un solver local y fijan hora, timezone e inputs; las pruebas HTTP de AEMET siguen usando transporte inyectado.

## Decisions

- La migración mueve el `thermal_factor` vigente a `demand_factor`, mueve la reserva sin reinterpretarla y crea configuración global con `contracted_power = max_heating_power` existente y diseño 21/0. Los campos de inercia, emisión, pérdida y límites térmicos dejan de formar parte del modelo/API activo.
- La reserva se incorpora a cada demanda de slot antes de optimizar, por lo que también queda reflejada en violations y explicaciones y nunca permite SOC superior a capacidad.
- Una constraint coincide con un estado de frontera `energy[t]`; si coincide con `horizon_start`, solo puede cumplirla el SOC real inicial. Las constraints en el extremo `horizon_end` también se evalúan.
- Un plan `DEGRADED` es activable porque conserva todas las restricciones físicas y es precisamente el mejor plan ejecutable. Un plan `INVALID` nunca se activa y se materializa con slots OFF para mantener una salida segura y explicable.
- Forecast y demanda se conservan en el snapshot explicativo persistido; las tablas de slots guardan energía/SOC de inicio y fin, no solo el porcentaje posterior heredado.

## Risks

- Resolver varias fases MILP en cada replanificación puede ser costoso en una Pi 2B. Se mitiga reutilizando un solo modelo, fijando cada óptimo, limitando el horizonte a cobertura real y midiendo un caso de 48 h/15 min en tests; un fallo o terminación sin optimalidad produce `INVALID`, nunca un plan presentado como óptimo.
- Los cambios de esquema atraviesan bases de configuración y aplicación. Una revisión Alembic única transforma datos existentes y los tests ejercitan upgrade tanto SQLite como la compatibilidad PostgreSQL.
- La semántica nueva invalida planes activos antiguos. Durante la migración se desactivan; el arranque genera un snapshot nuevo desde telemetría real antes de accionar salidas.
