# Design

## Approach
Split planning into three explicit layers.

First, build the sparse physical model once and solve only the comfort objectives, one stage per distinct heater priority. Each proven stage is locked as today. If a stage reaches the shared deadline with an incumbent, keep that incumbent instead of manufacturing a physical violation from the solver status.

Second, when comfort has been proven with time remaining, perform at most one polishing solve. Its bounded scalar objective combines electricity charged, avoidable terminal energy/heat, lateness, and a stable binary tie-break. This intentionally replaces the former seven exact secondary optima; their individual values remain diagnostics, not activation gates.

Third, pass every candidate through a solver-independent validator. Starting from the request telemetry, replay the persisted charge and heat decisions with the domain equations, compare the reconstructed states with the payload tolerance, verify per-slot/global power and storage bounds, and derive comfort violations and `VALID`/`CONVERGING`/`DEGRADED` from that replay. Treat missing/non-finite decisions or any hard-invariant mismatch as `INVALID`. Store solver quality beside, rather than inside, that physical classification.

Add a database-backed calculation record keyed by the exact input token. Automatic planning and preview jobs first reuse a completed verified record or attach to the current owner. A short renewable lease recovers work after process death and is renewed while a request waits for the installation lease. A global deployment-device lease serializes different-token CBC runs; automatic planning is queued ahead of a preview that has not started, while an active solve is not preempted. Each caller retains its own durable audit/job identity and copies the shared immutable result on completion.

Before changing the solver, capture real preview diagnostics from the deployment device and add a fixed corpus that includes the slow production shape. Compare the reduced CBC pipeline on that device with a HiGHS prototype only if an ARMv7-compatible production package can be built and maintained; backend replacement is not on the critical path.

## Constraints
- Production targets Raspberry Pi ARMv7. The current Debian CBC package is already supported; Python packages requiring unavailable platform wheels or an on-device compiler are not acceptable.
- The controller actuates binary charge decisions, while heat is a projected continuous decision. Validation must therefore replay both and must not trust CBC status or serialized state variables as proof.
- The deadline covers all solver work. Model construction, validation, persistence, and queue time are reported separately so an operator can distinguish computation from contention.
- Exact input identity must continue to include aligned horizon, telemetry, forecast, configuration, targets, and solver-affecting settings.

## Decisions
- Keep exact lexicographic optimization only for comfort priority tiers. Once a physically compliant plan has zero comfort shortfall, later quality proof cannot improve its safety classification.
- Replace the secondary hierarchy with a documented bounded cost whose coefficients are normalized from finite model bounds. The selected equivalent schedule may change, so tests assert invariants, priority, and cost properties rather than historical slot equality.
- The independent validator is the sole activation gate for a non-optimal incumbent. Solver-reported `Optimal` or `Feasible` is diagnostic evidence, never sufficient by itself.
- Persist `optimization_quality` and stage diagnostics on plans and preview results. Preserve legacy `solver_time_limit` only when reading historical records; do not emit it as a new physical deficit.
- Coordinate through the application database because the runtime planner and API preview worker are separate container processes and process-local locks cannot prevent contention.

## Risks
- Accepting a feasible incumbent changes the former promise that every activated plan has all tie-breakers proven. Mitigation: make quality explicit, retain exact comfort priority where proof completes, and gate activation on independent physical replay.
- A composite cost can select a different but physically equivalent schedule. Mitigation: bound every component, document the intended ordering, and compare operational metrics rather than byte-for-byte slots.
- A validator that shares solver construction helpers could repeat the same defect. Mitigation: implement replay from the existing domain step function and test it with deliberately corrupted solver payloads.
- A stale lease could delay urgent automatic planning. Mitigation: short expiry, renewal while queued, a solver-budget grace period, recovery on startup, and automatic priority before unstarted previews.
- Native multi-objective solvers may benchmark faster but add ARMv7 packaging risk. Mitigation: require an on-device bake-off and reproducible image build before any backend migration.
