# Decouple planning validity from optimization completeness

Status: approved

## Goal
Make planning produce an activable result within a predictable interactive time on the deployment device. A solver deadline shall limit optimization quality, not turn a physically valid, independently verified schedule into a `DEGRADED` plan.

## Requirements
- R1: `VALID`, `CONVERGING`, `DEGRADED`, and `INVALID` shall describe the verified physical projection and input validity only; failure to prove a non-safety tie-breaker before the deadline shall not itself add a planning violation or change that classification.
- R2: A candidate returned without a complete optimality proof may be activable only after an independent deterministic validator replays its charge and heat decisions and verifies power, storage, temperature, horizon, and target-boundary invariants against the current inputs.
- R3: Planning shall expose optimization quality separately as `OPTIMAL`, `FEASIBLE_LIMIT`, or `NO_SOLUTION`, including elapsed time, completed objective stages, bound/gap data when available, and the reason optimization stopped.
- R4: Comfort and heater priority shall remain ahead of energy and timing preferences. Secondary preferences shall use at most one solver stage and shall never consume the entire budget merely to prove cosmetic deterministic tie-breakers.
- R5: Preview and automatic planning shall use the same classification, validation, and optimization-quality rules. A verified `FEASIBLE_LIMIT` result shall be persistable, activable according to its physical status, and reusable for an exact matching input token.
- R6: Concurrent automatic and preview calculations shall not duplicate an exact input or compete without coordination on the deployment device; exact in-flight or completed work shall be joined or reused durably.
- R7: Invalid inputs, absence of a verified candidate, or failure of the independent validator shall remain non-activable and shall never replace an active plan.
- R8: The configured deadline, cancellation, durable preview lifecycle, exact-token invalidation, forecast coverage, slot resolution, and physical model shall remain observable and enforceable.

## Acceptance
- A1: Forced deadlines after a verified physically compliant candidate yield `VALID` or `CONVERGING` plus `FEASIBLE_LIMIT`, without a `solver_time_limit` physical violation; a candidate with a real non-converging comfort deficit remains `DEGRADED`.
- A2: Mutation tests show that the independent validator rejects excess power, broken storage balance, invalid charge decisions, missing intervals, and temperature or target-boundary violations even when the solver reports feasibility.
- A3: A representative corpus proves unchanged physical safety and priority ordering while allowing secondary slot choices to differ from the former nine-phase exact hierarchy.
- A4: Production-shaped four-heater previews on the deployment device complete within the agreed interactive latency target and no longer become `DEGRADED` solely because optimization reached its deadline.
- A5: Concurrent equal-token requests execute one optimization and receive the same durable result; different-token requests are coordinated without losing cancellation or freshness checks.
- A6: Existing planner and preview suites, new timeout/validator/concurrency tests, and `make check` pass.

## Decisions
- D1: Physical validity and solver optimality become separate public concepts; exact proof of all historical tie-breakers is no longer an activation requirement.
- D2: The current seven secondary lexicographic phases are replaced by one bounded operational-quality objective; stable serialization is preserved without requiring an exact schedule match between equivalent optima.
- D3: CBC remains the initial deployment backend because the supported Raspberry Pi ARMv7 image already provides it; a backend replacement is accepted only after an on-device bake-off with equivalent validation and packaging support.

## Outcome
The physical status is now independent from secondary solver proof. `FEASIBLE_LIMIT`
incumbents are replay-validated, reusable and activable when physically
`VALID`/`CONVERGING`; durable token single-flight and an installation lease avoid
duplicate CBC work. `make check` passes. The Raspberry Pi benchmark remains a
deployment-time measurement and is documented in the README.
