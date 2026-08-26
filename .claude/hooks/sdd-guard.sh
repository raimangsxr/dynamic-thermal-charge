#!/usr/bin/env bash
# UserPromptSubmit hook: recuerda en cada turno que este repo trabaja en SDD (SpecKit).
# Ver CLAUDE.md > "Gobernanza SDD".
set -euo pipefail

read -r -d '' CONTEXT <<'TXT' || true
[SDD guard] Este repositorio trabaja SIEMPRE en Spec-Driven Development con SpecKit.
Antes de escribir codigo de produccion para una feature, bug o refactor:
1. /speckit-specify -> spec.md (y /speckit-clarify si hay ambiguedad)
2. /speckit-plan -> plan.md + artefactos de diseno
3. /speckit-tasks -> tasks.md
4. /speckit-implement -> ejecutar tasks.md
Excepciones permitidas sin ciclo SDD: preguntas, lectura/analisis, comandos git,
formato/typos, y la propia configuracion de tooling. Si el usuario pide codigo
directamente y no hay spec para ese trabajo, propon el paso SDD que falta antes
de editar src/. No saltes fases ni las ejecutes fuera de orden.
TXT

jq -nc --arg ctx "$CONTEXT" \
  '{hookSpecificOutput:{hookEventName:"UserPromptSubmit",additionalContext:$ctx}}'
