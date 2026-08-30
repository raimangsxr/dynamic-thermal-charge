---
name: aes-spec-change
description: Classify and specify non-trivial code changes with the minimum SDD context; ask before ambiguous product decisions.
metadata:
  version: "1.0.0"
---

# Specify a change

Use this skill before implementation when the requested work may change non-trivial behavior.

## 1. Investigate narrowly

Read `AGENTS.md` first. Inspect only repository files needed to understand the request: nearby code/tests, relevant existing living specs, and configuration that can objectively answer questions. Do not read archives or broad documentation by default.

Distinguish:

- **Known**: explicitly stated by the user/current contract.
- **Discoverable**: answer from repository evidence; inspect it.
- **Ambiguous/product decision**: more than one valid behavior remains; ask the user.

Batch related questions. Do not create a "reasonable assumption" for behavior.

## 2. Classify

Choose the lightest safe class:

- **QUICK**: specification would not materially reduce implementation ambiguity/risk. No OpenSpec change.
- **STANDARD**: non-trivial behavior should be agreed before coding. One `change.md`.
- **COMPLEX**: a technical design must be decided before coding to reduce material risk. `change.md` plus `design.md`.

File count/line count alone never makes a change COMPLEX. If uncertain between STANDARD and COMPLEX, prefer STANDARD.

For QUICK, state briefly why no spec is useful and proceed only if the user requested implementation. If ambiguity exists, it is not QUICK.

## 3. Prepare Git branch

Before writing change artifacts, inspect `git status` and current branch. Do not discard unrelated work. If on `main` with a clean working tree, create a short-lived branch using the appropriate prefix: `feature/`, `fix/`, `refactor/`, or `chore/` plus a kebab-case name. If unrelated uncommitted work makes isolation unsafe, ask the user.

## 4. Create OpenSpec change

Pick a short kebab-case change name.

STANDARD:

```bash
openspec new change <name> --schema aes-standard
openspec instructions change --change <name> --json
```

COMPLEX:

```bash
openspec new change <name> --schema aes-complex
openspec instructions change --change <name> --json
```

Use the returned template/instructions; do not invent extra artifacts.

Write `change.md` with `Status: draft`, then:

- a short Goal;
- atomic observable Requirements (`R1...`);
- verifiable Acceptance items (`A1...`) without checkboxes;
- only ambiguity-removing Decisions (`D1...`), deleting the section if empty;
- a short Tasks checklist (`T1...`). These must be the only checkboxes in the file.

Normal target size: about 300-800 model tokens. Completeness beats the target.

For COMPLEX, after `change.md` exists:

```bash
openspec instructions design --change <name> --json
```

Create `design.md` containing only the non-obvious approach/constraints/decisions/risks required before coding. Do not restate requirements.

## 5. Approval gate

Show the user the compact contract and any design, then request explicit approval. Do **not** implement STANDARD/COMPLEX behavior before approval.

After explicit approval, change the line to `Status: approved`. This tiny persisted gate is the handoff proof for a fresh context. Do not mark it approved before the user approves the complete STANDARD contract or complete COMPLEX contract+design.

Then recommend implementation from a fresh or compacted context using only `AGENTS.md`, active change artifacts, relevant living specs, and code discovered on demand.
