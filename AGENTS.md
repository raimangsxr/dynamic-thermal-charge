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
- Tests must prove changed behavior where practical. Before a PR, `make check` must pass.
- Use `make setup`, `make dev`, `make test`, `make lint`, and `make check` as the project command contract.
- Persistent model/schema changes use migrations; SQLAlchemy projects use Alembic.
- Prefer database-backed configuration for runtime application behavior when reasonable. Keep secrets/bootstrap/environment concerns outside it. Ask if placement is ambiguous.
- `README.md` is the only mandatory general documentation; update it only when installation, configuration, usage, operation, or a relevant public interface changes.

### Git
- Use GitHub Flow with short-lived `feature/*`, `fix/*`, `refactor/*`, or `chore/*` branches.
- Use Conventional Commits. Default to one coherent final commit after verification/consolidation; use checkpoint commits only when materially useful. Push and open a PR to `main` when ready.
- Never merge to `main`; the user always performs the merge.
<!-- END AI-ENGINEERING-STANDARD v1 -->
