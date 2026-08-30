---
name: aes-finish-change
description: Consolidate only durable behavior from a verified change, compact its history, and archive it outside normal agent context.
metadata:
  version: "1.0.0"
---

# Finish and archive a verified change

Use after `aes-verify-change` succeeds and before opening the PR.

## 1. Decide whether a living spec adds value

Read the verified `change.md` and existing `openspec/specs/` only for affected capabilities.

Preserve behavior in a living spec only if it is stable, non-obvious, externally observable/contractual, or an important constraint future changes could accidentally violate. Do not create living specs merely because a STANDARD change existed.

Do not preserve implementation details, task lists, class/file names, or facts cheaply discoverable from code.

When a living spec is justified, update the smallest capability file under:

```text
openspec/specs/<capability>/spec.md
```

Use compact OpenSpec-compatible structure:

```markdown
## Purpose
<short purpose>

## Requirements
### Requirement: <name>
<normative behavior>

#### Scenario: <name>
- **WHEN** ...
- **THEN** ...
```

Merge with existing requirements instead of duplicating them.

## 2. Compact the change history

Before archiving, compact `change.md` while preserving useful history:

- keep `Status: approved`;
- keep Goal;
- keep the final Requirements;
- keep Acceptance only when useful to understand the contract;
- remove transient Decisions that are now obvious from code/living spec;
- retain only a very short `## Outcome` if it adds useful historical context;
- **keep the completed Tasks checklist until the archive helper runs**.

The helper verifies that at least one task was completed and none remain unchecked, then removes the Tasks section from the archived copy automatically. Never delete Tasks to make a change appear complete.

For COMPLEX work, compact `design.md` to only decisions/risk information that remains useful historically; delete it if nothing durable remains.

Do not create a summary document.

## 3. Archive deterministically

Use the project helper; do not use native `openspec archive` for this AES workflow because native sync expects OpenSpec delta-spec artifacts that AES intentionally does not create.

```bash
python3 .ai-standard/tools/archive_change.py <change-name>
```

The helper refuses to archive while task checkboxes are still incomplete and moves the folder to `openspec/changes/archive/YYYY-MM-DD-<name>/`.

## 4. Leave a coherent final worktree

Keep living-spec/README/archive changes together with the verified implementation for the final commit. Do not create a separate documentation/archive commit unless a checkpoint is materially useful.

Normal next step is `aes-create-pr`.
