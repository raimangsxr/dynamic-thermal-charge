# Configure the room thermal model per storage heater

Status: approved

## Goal

Expose the existing per-heater room model in two clear conceptual UI groups
while preserving the current API, persistence, defaults, and planner behavior.
The thermal-model group is collapsible, its coefficients retain clear unit and
planning help, and the UI warns when multiple heaters still use both defaults.

## Requirements

- R1: The heater editor presents exactly two conceptual groups: `Datos del acumulador`, containing the existing power, capacity, charge/discharge behavior, static emission, and other physical device properties; and `Modelo térmico de la estancia`, containing both named thermal fields with unit-bearing labels. The thermal-model group is collapsible, with no prescribed initial state.
- R2: The room thermal capacity input has UI `min=0.0001`, `step=0.1`, and no configured maximum; the room heat loss input has UI `min=0`, `step=0.01`, and no configured maximum.
- R3: Help for each coefficient states its physical meaning and includes an illustrative example of how changing it affects planning; exact example wording is implementation-level.
- R4: When two or more heaters each retain exactly both defaults—2.5 kWh/°C for `room_thermal_capacity_kwh_per_c` and 0.12 kW/°C for `room_heat_loss_kw_per_c`—the configuration UI shows a visible warning; presentation and copy are implementation-level.
- R5: Each value remains persisted per heater in the existing thermal-profile representation and round-trips through configuration reads, single-field edits, and add/replace requests; no zone or room entity is introduced.
- R6: Missing or legacy values resolve to 2.5 kWh/°C and 0.12 kW/°C, respectively, while valid non-default values remain unchanged through migration, reload, and API exposure.
- R7: Capacity remains finite and positive and heat loss finite and non-negative at domain/API/storage boundaries; rejected writes leave the prior configuration and revision unchanged.
- R8: Room-energy planning consumes the per-heater values with `E_loss = K_room * (T_inside - T_outside) * dt` and `T_next = T_inside + (E_heater - E_loss) / C_room`; planner code changes only when verification proves current consumption incorrect.
- R9: Form, API/persistence, and planner tests cover both fields, the selected UI constraints, warning condition, help content, non-default round trips, validation/default compatibility, and coefficient-sensitive room-energy calculations.

## Acceptance

- A1: A heater create/edit flow presents exactly the two conceptual groups, with the thermal group collapsible and both fields submitted and reloaded independently.
- A2: The rendered capacity control exposes min 0.0001 and step 0.1 without a configured max, and the rendered heat-loss control exposes min 0 and step 0.01 without a configured max.
- A3: Help for both fields includes each coefficient's physical meaning and an illustrative planning-impact example understandable without implementation details.
- A4: With at least two heaters having both default coefficients, the UI visibly displays a warning based on saved per-heater values.
- A5: GET, PATCH, and PUT expose and persist both fields per heater; old records receive the specified defaults and remain writable without data loss, while non-default values round-trip unchanged.
- A6: Invalid capacity/loss values, including non-finite values and values outside backend constraints, are rejected with no partial write or revision advance; UI constraints remain those in A2.
- A7: Planner tests demonstrate that non-default coefficients alter the documented room balance while default-valued plans preserve current results; no zone-level behavior is present.
- A8: Relevant frontend form, backend API/persistence, and backend room-energy planner tests pass, including default and existing-record compatibility coverage.

## Outcome

The verified change preserves the existing planner equations and adds the
per-heater configuration contract to the planning living spec.
