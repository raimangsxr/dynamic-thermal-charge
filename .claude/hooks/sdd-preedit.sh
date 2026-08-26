#!/usr/bin/env bash
# PreToolUse (Write|Edit) hook: no se toca codigo de produccion sin ciclo SDD.
# Si no hay tasks.md para la feature activa, la edicion pasa a confirmacion manual.
set -uo pipefail

payload=$(cat)
fp=$(printf '%s' "$payload" | jq -r '.tool_input.file_path // empty')
[ -n "$fp" ] || exit 0

root=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
rel=${fp#"$root"/}

# Solo vigila codigo de produccion.
case "$rel" in
  src/*) ;;
  *) exit 0 ;;
esac

branch=$(git -C "$root" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")

feature_dir=""
if [ -f "$root/.specify/feature.json" ]; then
  feature_dir=$(jq -r '.feature_directory // empty' "$root/.specify/feature.json" 2>/dev/null || echo "")
fi
if [ -z "$feature_dir" ] && [ -n "$branch" ]; then
  feature_dir=$(ls -d "$root/specs/${branch%%-*}"-* 2>/dev/null | head -1)
fi
case "$feature_dir" in
  /*) ;;
  ?*) feature_dir="$root/$feature_dir" ;;
esac

if [ -n "$feature_dir" ] && [ -f "$feature_dir/tasks.md" ]; then
  exit 0
fi

reason="SDD guard: no hay tasks.md para la feature activa (rama '${branch:-?}'), asi que esta edicion de $rel esta fuera del ciclo SpecKit. Ejecuta /speckit-specify -> /speckit-plan -> /speckit-tasks antes de implementar, o aprueba si es un cambio exento (tooling, typo, hotfix consciente)."

jq -nc --arg r "$reason" \
  '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"ask",permissionDecisionReason:$r}}'
