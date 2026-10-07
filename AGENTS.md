<!-- BEGIN AI-ENGINEERING-STANDARD v1 -->
## AI engineering workflow

### Behavior
- Inspect repository evidence before asking; if product behavior is still ambiguous, ask the user. Never choose among valid behaviors by assumption.
- Implement only current requirements. Prefer the simplest solution; avoid speculative abstractions, future-proofing, and unrelated cleanup.
- Use deterministic tools for verification. Read only files relevant to the current task; do not load archived changes by default.

### Change class
- **QUICK**: obvious/localized work where a spec would not reduce ambiguity. No SDD artifact; implement directly, then use `aes-verify-change` and `aes-create-pr` when useful.
- **STANDARD**: non-trivial behavior change. Use `aes-spec-change`; one `change.md`; get explicit user approval before implementation.
- **COMPLEX**: only when a prior technical design materially reduces risk. Use `aes-spec-change`; `change.md` + concise `design.md`; get explicit user approval.
- If a QUICK change exposes functional ambiguity, stop and reclassify.
- After approval, treat the active artifacts as the handoff; prefer a fresh/compacted context and load code on demand.

### Implementation and quality
- For approved STANDARD/COMPLEX work, use `aes-implement-change`, then `aes-verify-change`, `aes-finish-change`, and `aes-create-pr` as applicable.
- Tests must prove changed behavior where practical. `make check` is the single full repository quality gate and must pass after the final verification-relevant change before a PR. Do not rerun a successful full gate solely because a later workflow stage started; reuse it while no verification-relevant files have changed.
- Use `make setup`, `make dev`, `make test`, `make lint`, and `make check` as the project command contract.
- Persistent model/schema changes use migrations; SQLAlchemy projects use Alembic.
- Prefer database-backed configuration for runtime application behavior when reasonable. Keep secrets/bootstrap/environment concerns outside it. Ask if placement is ambiguous.
- Do not read README.md by default. Read/update only the relevant section when installation, configuration, usage, operation, or a relevant public interface changes. Do not create additional general documentation unless explicitly requested.

### Git
- Use GitHub Flow with short-lived `feature/*`, `fix/*`, `refactor/*`, or `chore/*` branches.
- Use Conventional Commits. Default to one coherent final commit after verification/consolidation; use checkpoint commits only when materially useful. Push and open a PR to `main` when ready.
- Never merge to `main`; the user always performs the merge.

## Orca coordinator guard

Before modifying repository files, determine the current Git branch.

If the current branch is `main`:

- Treat this session as coordinator-only.
- Never implement, edit, fix, refactor, format, or otherwise modify repository files, even for QUICK changes.
- For any user request requiring repository changes, invoke `$orca-coordinator` before doing task-specific work.
- Delegate all implementation and fix work through Orca using the model policy defined in `.orca/pilot.md`.
- Never fall back to implementing changes in the Coordinator session if orchestration cannot be initialized or a worker cannot be started. Report the blocker instead.
- Read-only investigation, planning, classification, coordination and reporting are allowed.
<!-- END AI-ENGINEERING-STANDARD v1 -->
