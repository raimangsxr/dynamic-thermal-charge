# Model room comfort from stored energy and thermal losses

Status: approved

## Goal

Replace percentage-driven demand planning with an energy balance that projects, per room and per interval, both accumulator energy and indoor temperature. Configuration should expose only the physical room parameters needed by that model and temperature schedules should express the operator's comfort objective.

## Requirements

- R1: Each heater configuration shall expose a room thermal capacity `room_thermal_capacity_kwh_per_c` greater than zero and a room heat-loss coefficient `room_heat_loss_kw_per_c` greater than or equal to zero. Accumulator capacity shall remain derived as nominal input power multiplied by full-charge hours.
- R2: Each enabled heater shall have a weekly temperature-target schedule made of a room temperature in degrees Celsius, a local time, and one or more weekdays. A target remains active until the next scheduled target for that heater.
- R3: For every planning interval of `dt` hours, the planner shall use the forecast outdoor temperature and projected indoor temperature to calculate signed envelope exchange as `E_loss = K_room * (T_inside - T_outside) * dt`, and shall enforce `T_next = T_inside + (E_heater - E_loss) / C_room`.
- R4: Stored energy shall start from reported SOC times accumulator capacity and evolve as `E_store_next = E_store + E_charge - E_heater`, bounded between zero and accumulator capacity. `E_charge` shall equal nominal input power times `dt` only while the heater is scheduled ON; delivered room heat shall not exceed the energy available in that interval.
- R5: The optimiser shall prioritize minimizing temperature shortfall against each room's active target, using heater priority when contracted power cannot satisfy all rooms, and shall then minimize charged energy while preserving the existing electrical power limits and deterministic scheduling behavior.
- R6: Planning previews, active-plan timelines, explanations, persistence, and audit output shall report projected indoor temperature, target temperature, stored energy in kWh and SOC, heat delivered, thermal loss/exchange, and any temperature shortfall for every heater and interval. No displayed temperature may be derived directly from SOC.
- R7: Automatic planning shall require fresh indoor-temperature and stored-SOC telemetry per enabled heater. Accumulator-temperature and target-temperature telemetry shall no longer be planning inputs; the configured temperature schedule is the target source.
- R8: Percentage charge constraints and their editor/API/persistence shall be removed and replaced by temperature-target schedules. Existing percentage constraints shall be discarded during migration because they cannot be converted reliably into temperatures.
- R9: The superseded planning parameters `target_charge`, `reserve_percent`, `demand_factor`, global design indoor/outdoor temperatures, and `feedback_horizon_hours` shall be removed from configuration and calculation. The legacy thermal parameters `target_temperature_c`, per-room design outdoor temperature, `thermal_factor`, `min_charge`, `max_charge`, `thermal_loss_c_per_hour`, `room_inertia_hours`, `outdoor_loss_per_hour`, and `emission_c_per_hour` shall also be removed.
- R10: The configurable MQTT surface shall retain the indoor-temperature and stored-SOC topics needed by the planner and shall remove the accumulator-temperature, target-temperature, and target-charge command/discovery settings that no longer affect behavior.
- R11: Existing installations shall migrate each heater to `C_room = 2.5 kWh/°C`, `K_room = 0.12 kW/°C`, and an all-week 00:00 temperature target taken from its legacy thermal target when present, otherwise 21 °C. New heaters shall receive the same defaults, all persistent schema changes shall use a migration, and existing planning history shall remain readable.
- R12: Missing or stale required telemetry, a missing temperature schedule, invalid room coefficients, missing forecast coverage, or an infeasible electrical configuration shall produce an explicit invalid/degraded result without silently reverting to percentage-based planning.

## Acceptance

- A1: With a 2.8 kW heater charged for 8 hours, the planner represents 100% SOC as 22.4 kWh and 50% SOC as 11.2 kWh.
- A2: Given `C_room = 2.5 kWh/°C`, `K_room = 0.12 kW/°C`, a known indoor/outdoor temperature, target schedule, SOC, charge decision, and interval length, unit tests reproduce the equations in R3 and R4, including signed heat exchange when outdoors is warmer.
- A3: When available stored energy is sufficient, projected temperature reaches the scheduled target without charging unnecessary energy; when it is insufficient, the preview reports the resulting temperature shortfall and never makes stored energy negative.
- A4: Changing only the outdoor forecast changes both interval loss and required charge; changing only SOC changes energy availability but never directly maps to a room-temperature value.
- A5: API and frontend tests demonstrate editing the two room coefficients and weekly temperature targets, and show the energy/temperature projection without percentage-constraint controls or superseded parameters.
- A6: Migration tests prove deterministic defaults, removal of charge constraints, preservation of historical plan reads, and successful operation on SQLite and PostgreSQL-compatible schemas.
- A7: Runtime tests prove that only fresh indoor temperature and SOC are required and that the controller executes the generated ON/OFF plan under the existing power limits.
- A8: `make check` passes and README usage/configuration text describes the new model and parameters.

## Outcome

La planificación, persistencia, MQTT, API, runtime y panel ahora usan el
balance acoplado de energía almacenada y temperatura interior, con consignas
semanales y resultados físicos auditables. Las restricciones porcentuales y la
telemetría de objetivo térmico fueron retiradas de la configuración activa.
