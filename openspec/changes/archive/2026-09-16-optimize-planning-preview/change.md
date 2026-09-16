# Optimize exact planning previews

Status: approved

## Goal
Reduce the latency of initial and repeated planning previews on the deployment device without changing the selected plan, its physical traces, or its classification. Preserve the current exact lexicographic optimization contract while removing mathematically redundant solver and persistence work.

## Requirements
- R1: For the same planning input, the optimized path shall preserve status, slot decisions, power values, convergence assessment, violations, objective score sequence, and public physical traces within the numeric tolerances already used by the planner.
- R2: The room-energy model shall omit only variables and constraints that are provably fixed, inactive, or dominated for the corresponding heater and slot.
- R3: A lexicographic phase may be skipped only when a verified feasible incumbent has reached that phase's proven global lower bound; the skipped optimum shall still be locked and represented in the score sequence.
- R4: Preview progress shall expose coverage and resolution accurately, remain durably observable, and honor cancellation at solver phase boundaries without repeatedly transitioning or writing the same resolution step for every phase.
- R5: An exact repeated preview may reuse a completed result only when its input token matches and the source calculation completed optimization without `solver_time_limit`; timed-out results shall never be reused.
- R6: Horizon length, slot duration, solver budget, objective hierarchy, CBC single-thread determinism, feasibility checks, and degradation rules shall remain unchanged.
- R7: The planner shall emit sufficient aggregate timing and model-size diagnostics to distinguish model construction, solver phases, preview persistence, and cache reuse without logging per-variable data.

## Acceptance
- A1: A differential corpus covering warm, cold, day/night, cross-midnight, terminal guard, and degraded-comfort cases produces equivalent observable plans before and after the change under the existing tolerances.
- A2: For the current production-shaped four-heater scenario, the sparse formulation removes at least 230 inactive shortfall variables and constraints and 24 dominated binary charge decisions while preserving the result.
- A3: On the deployment device, the production-shaped first calculation completes in at most 30 seconds and an exact repeated preview completes in at most 1 second; hardware measurements are reported separately from deterministic CI checks.
- A4: Forced-budget tests retain the existing `solver_time_limit` and `DEGRADED` behavior whenever all required lexicographic phases cannot be proven within the configured deadline.
- A5: Preview job tests prove durable completion, correct coverage/resolution progress, cancellation at phase boundaries, safe cache hits, and rejection of stale, mismatched, or timed-out cached results.
- A6: Existing planner and preview test suites plus the project quality gate pass.

## Decisions
- D1: Exact successive lexicographic solves remain the reference semantics; weighted objectives, relaxed MIP gaps, coarser slots, shorter horizons, and nondeterministic parallel CBC are excluded.
- D2: Cache reuse is an optimization of a newly requested durable preview and shall not make a previous job appear to be the new request.
- D3: Replacing CBC or coordinating solver priority across processes is excluded from this change; both can be evaluated later if exact formulation and preview-path improvements do not meet the target.

## Outcome

The exact room-energy model now uses auditable sparse decision sets, skips only
verified zero lower-bound phases, persists semantic preview progress, and safely
reuses complete exact-token results. Deployment-device latency remains a manual
operator measurement using the repository benchmark script.
