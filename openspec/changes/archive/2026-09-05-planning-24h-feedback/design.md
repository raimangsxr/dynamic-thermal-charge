# Design

## Constraints

- The API handlers are synchronous and the solver is blocking; there is no safe
  interruption hook inside a running PuLP/CBC call, so cancellation is checked
  only at planner phase boundaries.
- Preview execution must remain read-only for active plans and constraints.
- Progress storage and jobs require an Alembic migration and retention handling.
- Dense 24-hour data must remain legible on mobile; the matrix and tables may
  scroll horizontally, while overview charts preserve sparse labels and full
  tooltips.

## Decisions

- Polling restores durable progress after reload with ordinary authenticated
  HTTP endpoints and avoids a long-lived connection on the deployment target.
- Cancellation is cooperative at planner phase boundaries because the blocking
  solver has no safe interruption hook.
- The preview is the primary chart data source after completion; the active plan
  remains the fallback context.

## Risks

- Detailed DEBUG records can be voluminous over 24 hours. They are intentionally
  limited to service logging, where normal deployment rotation applies.
- A background worker is process-local. Persisted interrupted jobs make an API
  restart visible and safe, while a later distributed worker can replace the
  runner without changing the job API.
