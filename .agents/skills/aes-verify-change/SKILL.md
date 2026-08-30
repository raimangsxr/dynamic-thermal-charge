---
name: aes-verify-change
description: Verify QUICK or specified work against its behavior contract, then run the deterministic project quality gate.
metadata:
  version: "1.0.0"
---

# Verify a change

This is requirement-focused verification, not a second broad architecture review.

## 1. Read the smallest behavior contract

Inspect the branch diff against `main` and tests relevant to changed behavior.

For **QUICK**, use the user's explicit request plus repository evidence as the contract. Do not create an SDD artifact just to verify the work. Confirm the requested outcome is present and no unrelated scope was introduced.

For **STANDARD/COMPLEX**, read `AGENTS.md`, active `change.md`, and `design.md` only if present. The change must still say `Status: approved`. Build a compact mental mapping:

- every `R*` requirement -> implementation evidence;
- every `A*` acceptance item -> test or explicit deterministic/manual evidence;
- every completed `T*` -> actual completed work.

Do not generate a separate verification document.

## 2. Resolve mismatches

If implementation is missing or contradicts the behavior contract, fix the implementation and tests.

For STANDARD/COMPLEX, if satisfying the requirement would require changing approved behavior, stop and ask the user rather than silently editing the contract. For QUICK, if verification exposes functional ambiguity, stop and reclassify instead of guessing.

Remove accidental scope and unnecessary complexity discovered in the diff when safe to do so.

## 3. Run deterministic checks

Run focused tests while fixing issues, then always run:

```bash
make check
```

Fix failures caused by the change. If a failure is unrelated/pre-existing and cannot safely be fixed within scope, report it clearly instead of hiding it.

Verify README is current when its documented installation/configuration/usage/operation changed.

## 4. Finish

Do not create the normal final commit yet; leave the verified worktree for consolidation and `aes-create-pr`. Use a checkpoint commit only when it materially reduces risk. Keep the final report compact: requested behavior/requirements satisfied, `make check` result, and only unresolved human-review points.

Normal next step is `aes-finish-change` for STANDARD/COMPLEX work, or `aes-create-pr` for QUICK work.
