# Design

## Approach
Before modifying the planner, serialize a small fixed corpus of `PlanningInput` cases and capture canonical output, objective scores, model counts, and phase timings from the base revision. A differential runner will execute the same corpus against the candidate revision and compare normalized results using the planner's existing tolerances.

Build the room-energy MILP from sparse per-heater index sets:

- Create shortfall and start-shortfall variables only where the target is active; materialization and objective construction use zero constants elsewhere.
- Compute the last slot that can influence a target or terminal guard. Beyond it, represent charge and emitted heat as zero constants and keep only the state recurrence needed to produce the existing traces.
- Sum global power and objective terms over variables that actually exist. Assertions in model construction record dense-versus-sparse counts and prove every omitted index belongs to an inactive or dominated region.

Describe each lexicographic phase with its expression and, only where mathematically known, a global lower bound. After a verified feasible incumbent, a phase whose value is already at that bound receives the same objective lock and score entry without launching CBC. All other phases continue through the current CBC invocation and deadline path.

Move preview lifecycle reporting to semantic steps. Coverage is marked after forecast coverage validation; resolution is entered once before the first solve. Phase callbacks collect timings in memory and check cancellation once at each boundary, but do not repeatedly complete and reopen the resolution database row. Final aggregate diagnostics are persisted with the result.

At preview submission, build the current request and exact input token, then look for the latest completed preview with the same token. Reuse is allowed only when its result has no `solver_time_limit`. A hit creates and completes a new durable job with copied immutable result data and cache-source diagnostics, preserving the observable request lifecycle without running CBC.

## Constraints
- The shared solver deadline includes every phase and remains the configured value.
- CBC remains single-threaded with the fixed seed and current feasibility verification.
- State variables initially remain dense so passive decay traces and downstream serialization do not require a second implementation.
- Deployment latency is measured outside CI; CI enforces equivalence, model reduction, cache behavior, and bounded synthetic benchmarks.

## Decisions
- Sparse index sets are derived once from normalized targets and guards, rather than inferred from generated constraints. This makes omission rules auditable and testable.
- Lower-bound short-circuiting is opt-in per objective. No phase is skipped based on heuristic closeness, elapsed time, or a bound reported by an interrupted solver.
- Cache identity remains the existing input token, which already covers aligned horizon, telemetry values, forecast points, planner settings, heaters, targets, and revisions. Crossing a slot boundary or changing any covered input causes a miss.
- A fully optimized comfort-degraded result may be reused because degradation alone is an output of the exact optimum; any result containing `solver_time_limit` may not.
- Cross-process locking and solver replacement remain follow-up options because scheduling contention and backend differences can change operational behavior even when the mathematical model is unchanged.

## Risks
- Incorrectly identifying a heater's last relevant slot could remove a decision that affects a later target, especially across midnight. Mitigation: explicit cross-midnight and terminal-guard fixtures plus construction assertions.
- A tolerance error in lower-bound detection could skip a non-optimal phase. Mitigation: use the same verification and lock tolerances as a normally solved phase and differential tests around the tolerance boundary.
- Reusing a result with incomplete token coverage would return stale output. Mitigation: retain the current token builder as the single cache key and add mutation tests for every token component.
- SQLite savings may be small compared with CBC time. Model and phase timings are kept separate so the deployment benchmark can attribute remaining latency before considering broader solver changes.
