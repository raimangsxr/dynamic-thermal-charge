---
name: aes-create-pr
description: Finalize a task branch, rerun the quality gate, push it, and open a concise GitHub PR without ever merging main.
metadata:
  version: "1.0.0"
---

# Create the Pull Request

## 1. Preflight

Read `AGENTS.md`. Confirm:

- current branch is not `main`;
- working tree changes are expected;
- STANDARD/COMPLEX changes have been verified and archived;
- README is current when required.

Do not discard or rewrite unrelated user work.

## 2. Final quality gate

Run:

```bash
make check
```

Do not create the PR if the quality gate fails. Fix in-scope failures first; surface unrelated blockers clearly.

Stage the expected final files. If anything remains uncommitted, create one coherent Conventional Commit for the change. Preserve any intentional checkpoint commits; do not squash or rewrite them unless the user asks.

## 3. Push and open PR

Push the current branch and set upstream if necessary. Use GitHub CLI when available.

Create a concise PR to `main`. The body should contain only:

- **What**: short summary of the behavior/change;
- **Why**: one short reason;
- **Validation**: `make check` plus any important targeted validation;
- **Review notes**: only points that genuinely need human attention; omit if none.

Avoid generated implementation diaries, exhaustive file lists, or repeated spec text.

## 4. Stop at PR

Report the PR reference/link and any review note. Never merge, auto-merge, or push directly to `main`. The user always performs the merge.
