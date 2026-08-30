---
name: aes-implement-change
description: Implement an approved STANDARD or COMPLEX change exactly, using its contract as the handoff and loading code on demand.
metadata:
  version: "1.0.0"
---

# Implement an approved change

Use only after the user has approved the active STANDARD/COMPLEX artifacts.

## 1. Establish authoritative context

Read `AGENTS.md`. Identify the active change and run:

```bash
openspec status --change <name> --json
openspec instructions apply --change <name> --json
```

Read the returned context files (`change.md`, and `design.md` for COMPLEX). Require `Status: approved` in `change.md`; otherwise stop before modifying functional code and ask for approval. Treat the approved artifacts as the implementation handoff. Do not depend on planning-chat history and do not load archived changes.

Inspect only code/tests/configuration needed for the next task.

If the contract is missing, not approved, contradictory, or exposes a product ambiguity that could change behavior, stop and ask the user. Technical implementation choices that do not affect requested behavior may be resolved using existing repository patterns and the simplest adequate approach.

## 2. Implement to the contract

Work through the `Tasks` list in dependency order. Keep scope limited to the approved Requirements and necessary supporting changes.

For each task:

1. inspect the smallest relevant area;
2. implement the simplest solution consistent with existing patterns;
3. add/update focused tests when behavior changed;
4. mark the corresponding `T*` checkbox complete only when the task is actually done.

Do not add speculative extensibility, unrelated refactors, optional features, or documentation beyond what the contract requires.

Persistent SQLAlchemy model changes use Alembic migrations. Never replace a required migration with manual schema edits.

When adding runtime application configuration, prefer database persistence when reasonable under project rules; ask the user if placement is a product/operational decision.

## 3. README

Update `README.md` only when the implementation changes installation, required configuration, usage, operation, or a relevant public interface. Do not create additional general documentation unless explicitly requested.

## 4. Git state

Stay on the task branch and keep the worktree coherent. Do not commit by default yet: the normal final Conventional Commit is created by `aes-create-pr` after verification and consolidation. Use a checkpoint commit only when long or risky work materially benefits from one; never commit broken intermediate states when avoidable. Never merge `main`.

Do not open the PR yet unless the user explicitly skips the remaining workflow. Normal next step is `aes-verify-change`.
