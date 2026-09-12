# Harden planning integrity and diagnostics

Status: approved

## Goal

Make a downloaded diagnostic for a past plan self-contained enough to reproduce weather-related edge cases. Correct the telemetry freshness, slot-boundary deviation and target-alignment defects that can otherwise invalidate or misrepresent an operational plan.

## Requirements

- R1: The downloadable diagnostic for both automatic and legacy plans includes a `forecast` section sourced only from the plan's persisted `forecast_id`; it never substitutes the latest forecast or performs a new AEMET request.
- R2: The forecast section identifies the persisted snapshot with its id, source, municipality, forecast date, retrieval time and summary temperatures, and includes hourly timestamp, temperature and interpolation fields.
- R3: Hourly points are limited to the inclusive context interval from 12 hours before the plan start through 12 hours after the plan end. All persisted points inside that interval are included in chronological order; missing leading or trailing hours do not prevent the diagnostic download.
- R4: The forecast section records the requested interval, the actual available interval, and whether leading or trailing context is incomplete. If the plan has no surviving linked forecast, the diagnostic explicitly reports it as unavailable without reconstructing data.
- R5: Retention preserves a forecast while any retained automatic or legacy plan references it, so the diagnostic remains reproducible for the same lifetime as the plan.
- R6: The diagnostic remains secret-free and the existing plan explanation response is unchanged.
- R7: Automatic planning and deviation evaluation use the installation's `indoor_max_age_minutes` as the maximum age for both required indoor-temperature and stored-SOC readings. Planning status views use the same threshold, including rejection of future-dated readings.
- R8: A deviation check performed by the controller's first poll after a slot boundary evaluates that boundary once and includes the slot that began there, preserving its charge decision and physical evolution before evaluating later slots. Polling delay must not cause the current slot to be skipped or make current telemetry appear to be the state at the next slot.
- R9: Every enabled temperature target's start and end must align with the configured `slot_minutes`; midnight expressed as `00:00` or `24:00` is aligned. Preview/activation input containing a non-aligned target is rejected without persisting partial target changes.
- R10: A non-aligned target already present in persisted configuration makes automatic planning explicitly `INVALID` with the affected heater and schedule identified; it is never rounded, extended or shortened silently.

## Acceptance

- A1: Downloading an automatic-plan diagnostic returns the exact linked forecast metadata and only linked hourly points between `horizon_start - 12h` and `horizon_end + 12h`, including both bounds when points exist there.
- A2: Downloading a legacy-plan diagnostic applies the same behavior using `window_start` and `window_end`.
- A3: A linked snapshot with only partial surrounding coverage is downloaded successfully and marks the corresponding leading or trailing coverage as incomplete.
- A4: A plan with a null or previously removed forecast reference is downloaded successfully with an explicit unavailable forecast section and no current forecast data.
- A5: Retention does not delete a forecast referenced by a surviving plan, and deletes it once no retained plan references it and its own retention limit has expired.
- A6: Diagnostic regression coverage verifies that credentials remain absent and that the forecast source and interpolation markers are preserved.
- A7: With `indoor_max_age_minutes = 30`, readings aged 16 minutes remain usable by preview, periodic planning and deviation checks, while readings older than 30 minutes or dated in the future are rejected consistently.
- A8: When the first controller poll occurs seconds after a boundary, deviation reprojection includes the newly active slot exactly once and accounts for its retained charge decision before comparing every later physical boundary.
- A9: With 30-minute slots, `10:00–11:30` and a midnight endpoint are accepted, while `10:15–11:15` is rejected by preview/activation and cannot partially replace the persisted schedule.
- A10: Runtime planning encountering an already-persisted `10:15–11:15` target with 30-minute slots returns an identified `INVALID` result rather than treating it as `10:30–11:30`.

## Decisions

- D1: “12 hours afterwards” means 12 hours after the plan end, not after its start.
- D2: The actual linked snapshot is included even when its recorded source is `fallback` or `simulated`; the source field makes that fact explicit instead of labeling non-AEMET data as AEMET.
- D3: The additive diagnostic payload uses format identifier `dynamic-thermal-charge-plan-diagnostic-v2`; no forecast data is added to the normal explanation endpoint or rendered in the UI.
- D4: Non-aligned temperature targets are rejected rather than modeled with partial slots.
- D5: The configured indoor freshness limit governs both physical readings required by the coupled planner because neither temperature nor SOC may be assumed independently.
