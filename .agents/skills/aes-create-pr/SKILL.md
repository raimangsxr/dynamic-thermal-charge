---
name: aes-create-pr
description: Finalize a verified task branch, reuse valid verification evidence, push it, and open a concise GitHub PR without ever merging main.
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

## 2. Verification preflight

Confirm that `aes-verify-change` completed successfully and its final `make check` passed.

Do not rerun `make check` merely because the PR stage has started.

Reuse the successful verification result when no implementation, tests, dependency manifests, migrations, build configuration, deployment configuration, or other verification-relevant files changed afterwards.

Changes limited to OpenSpec archival/consolidation, living specs, README or other documentation do not invalidate the existing quality-gate result.

If verification evidence is missing or verification-relevant files changed after the last successful gate, stop and return the change to `aes-verify-change` rather than performing verification inside this skill.

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
