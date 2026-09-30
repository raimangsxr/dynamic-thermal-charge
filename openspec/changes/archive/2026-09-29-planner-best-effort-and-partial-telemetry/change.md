# Planner resilience: best-effort activation and partial telemetry

Status: approved

## Goal
Keep the installation governed by the best available plan instead of switching every output off. A single heater without fresh telemetry, or a degraded comfort result without a valid alternative, shall each produce an explicit, activable, operator-explained plan and an alert, without weakening the safety guarantees of `VALID`/`CONVERGING` plans.

## Requirements
- R1: A `DEGRADED` plan shall be activable in `best_effort` mode only when no `VALID`/`CONVERGING` plan is active or the active one does not cover the next recalculation instant (`horizon_end <= now + next_refresh`). A `DEGRADED` candidate shall never replace a covering `VALID`/`CONVERGING` plan; a newer best-effort candidate replaces an older best-effort plan; a `VALID`/`CONVERGING` candidate always replaces a best-effort plan. The same rule applies to periodic, deviation-triggered and manual (API) activation.
- R2: A best-effort active plan drives relays and MQTT discharge like any active plan, survives a process restart, and is flagged `activation_mode: best_effort` in the planning API, status API, preview response, operational snapshot, Home Assistant attributes and panel.
- R3: A heater whose indoor temperature or SOC is missing, future or older than `indoor_max_age_minutes` shall be excluded from the plan (no charge decisions, no commanded discharge); the remaining heaters are planned normally; the plan records `excluded_heaters` with cause `missing_required_state` and an `excluded_heater` deficit; the physical status is classified on planned heaters only. When every enabled heater is excluded the result remains `INVALID` with zero slots.
- R4: The independent validator shall recompute the exclusion set from the request and reject a candidate whose exclusions, decisions or interval count differ. The input token shall carry a new model version so previews computed before this change cannot be activated.
- R5: New catalogue alerts `plan_best_effort_active` and `plan_heater_excluded` shall follow the one-per-episode rule, be queued where the condition is observed without blocking the control loop, and be rearmed when the condition ends. `plan_recalculation_degraded` remains for a candidate retained behind a covering plan and its message no longer states that outputs stay off.
- R6: `INVALID` and best-effort results shall carry operator-facing cause codes and a backend-provided `recommended_action` whose horizon text uses the configured `forecast_horizon_hours`; the panel translates every planner cause code, including `missing_temperature_schedule`, `invalid_temperature_schedule`, `infeasible_power_configuration`, `missing_guard_forecast_coverage`, `excluded_heater` and `safe_planning_input`, and no longer keeps its own copy of recommended actions.
- R7: A heater excluded from the active plan that regains fresh telemetry shall be evaluated by the deviation check and trigger an early recalculation when a comfort shortfall is projected.

## Acceptance
- A1: Runtime tests: without an active plan a `DEGRADED` candidate is persisted `active=True`, `activation_mode=best_effort`, the controller schedule follows it and `plan_best_effort_active` is queued once; with a covering `VALID` plan the same candidate is retained as diagnostic and `plan_recalculation_degraded` is queued; when the covering plan ends before the next refresh the candidate is activated; a later `VALID` plan replaces it and rearms the alerts; a restart keeps `activation_mode`.
- A2: API tests: `POST /planning/activate` with a `DEGRADED` token is rejected without `best_effort: true`, rejected while a covering plan governs, and accepted otherwise; status, planning, preview and operational responses expose `activation_mode`, `best_effort`, `best_effort_reasons`, `excluded_heaters`, and deficits carry `cause` and `recommended_action`.
- A3: Planner tests: one stale heater yields a plan whose slots never contain it, with `excluded_heaters` and an `excluded_heater` deficit, and whose status equals that of the same request without the heater; all-stale telemetry stays `INVALID` with zero slots; the validator rejects a mutated exclusion set; the token differs from the previous model version.
- A4: Alert tests: `plan_heater_excluded` is queued once while the active plan has exclusions and rearmed when a plan without exclusions is activated; message bodies name the heaters, cause and consequence.
- A5: Discharge tests: a best-effort active plan enables discharge inside active windows; an excluded heater receives `OFF`/`NULL`.
- A6: Deviation test: an excluded heater with fresh telemetry and a projected shortfall triggers `projected_deficit`.
- A7: Frontend specs cover the best-effort banner and chip, the excluded-heater list, the best-effort activation button with confirmation, and translated cause codes with backend recommended actions; `make check` passes.

## Decisions
- D1: Best-effort is an activation mode persisted per plan row (`inputs_json.activation_mode`), not a new physical status; `VALID`/`CONVERGING`/`DEGRADED`/`INVALID` semantics are unchanged.
- D2: Heater exclusion is orthogonal to the physical status; it never forces `DEGRADED`, so a covering `VALID` plan cannot block re-planning of healthy heaters. The panel derives `best_effort` from `activation_mode == best_effort` or a non-empty `excluded_heaters`.
- D3: Coverage for precedence compares `horizon_end` with the next refresh instant; `guaranteed_until` stays a comfort guarantee and remains `None` for `DEGRADED` plans.
- D4: Exclusion is decided inside the planner from the request so preview, activation, runtime and the validator agree; no request-side filtering.
- D5: Excluded heaters receive no commanded discharge, exactly as a heater without plan; enabling discharge without state knowledge is deferred.
- D6: Alerts stay email-only in this change. Forecast age limits, the standing-loss model, the panel alert list, telemetry history and onboarding are separate later changes.
