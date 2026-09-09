# Satisfy temperature targets from interval start

Status: approved

## Goal

Make weekly temperature targets mean that the requested temperature is already satisfied when an active interval begins and remains satisfied through its end. Present the resulting discrete plan without visually shifting end-of-interval state or interpolating relay power.

## Requirements

- R1: For every heater and slot with an active temperature target, projected indoor temperature at both the slot start and slot end must be at least that target, subject to explicit feasibility reporting.
- R2: The optimizer may deliver heat in earlier untargeted slots when needed to preheat for a later target; electrical charging remains governed by the existing power, storage, horizon, and planning constraints.
- R3: If the target cannot be satisfied at either boundary, the plan must not report that interval as fulfilled; its deficit must identify the violated boundary time and projected shortfall.
- R4: Temperature, stored-charge charts, and detail tables must associate start-state values with slot starts and end-state values with slot ends, without presenting an end-state as if it existed at the start.
- R5: Per-heater and aggregate electrical power must be rendered as discrete slot occupancy, not as ramps or curves between samples.
- R6: The temperature chart must use a data-derived vertical range rather than forcing zero when zero is outside the relevant temperature range.
- R7: The active-plan stored-charge chart must express each heater's stored energy as a percentage of that heater's configured total storage capacity, on a common 0–100% scale; its detail must retain the corresponding kWh values for physical auditability.

## Acceptance

- A1: Given a target that starts at 08:00 and an indoor temperature below target before 08:00, a feasible plan preheats so the 08:00 projected start temperature is at or above target and remains so at 08:30.
- A2: Given insufficient stored energy or electrical capacity to preheat, the result is `DEGRADED` or `INVALID` as required by the existing safety contract and reports a deficit at 08:00; it is not shown as fulfilled at that time.
- A3: A target ending at 18:00 is enforced through the end boundary of the final active slot and is no longer required after 18:00 unless another target applies.
- A4: A target active at the planning horizon start uses the measured initial temperature as its start boundary; if that measurement is below target, the plan reports the unavoidable initial deficit.
- A5: Deterministic tests cover target start, target end, cross-midnight targets, horizon-start deficits, preheating, energy balance, and power limits.
- A6: In the planning UI, a 2.4 kW relay interval is displayed as 2.4 kW for the whole slot, and thermal/storage values are labeled at their actual boundary times.
- A7: Existing full-horizon projection and visible-window semantics remain unchanged.
- A8: Accumulators with different kWh capacities but the same relative stored charge are plotted at the same percentage, the chart axis and legend use `%`, and the detail remains able to report stored energy in kWh.

## Decisions

- D1: “Maintained through the interval” is evaluated at every modeled slot boundary. With the existing constant per-slot energy balance, satisfying both boundaries prevents a modeled intra-slot dip.
- D2: No new configuration or database migration is introduced; the corrected semantics apply to existing weekly targets.
