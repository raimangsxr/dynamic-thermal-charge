#!/usr/bin/env bash
set -euo pipefail

action=${1:-}
shift || true
if [ -z "$action" ]; then
  echo "usage: esphome.sh <setup|test|lint|check> [dirs...]" >&2
  exit 2
fi
if [ "$#" -eq 0 ]; then set -- .; fi

configs_in() {
  local dir=$1 f
  find "$dir" \
    \( -name .git -o -name .ai-standard -o -name node_modules -o -name .venv -o -name venv -o -name archive -o -name dist -o -name build \) -prune -o \
    \( -name '*.yaml' -o -name '*.yml' \) -type f -print 2>/dev/null | while IFS= read -r f; do
      if grep -Eq '^[[:space:]]*esphome:[[:space:]]*$' "$f"; then printf '%s\n' "$f"; fi
    done
}

setup_one() {
  local dir=$1
  if [ -n "$(configs_in "$dir")" ]; then
    command -v esphome >/dev/null 2>&1 || { echo "ERROR: ESPHome config detected but esphome is not installed" >&2; exit 2; }
  fi
}

test_one() {
  echo "INFO: ESPHome profile has no runtime tests by default"
}

validate_one() {
  local dir=$1 found=0 f
  command -v esphome >/dev/null 2>&1 || { echo "ERROR: esphome is not installed" >&2; exit 2; }
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    found=1
    echo "==> esphome config: $f"
    esphome config "$f" >/dev/null
  done < <(configs_in "$dir")
  if [ "$found" -eq 0 ]; then echo "INFO: no ESPHome configuration detected under $dir"; fi
}

for dir in "$@"; do
  [ -d "$dir" ] || { echo "ERROR: ESPHome directory not found: $dir" >&2; exit 2; }
  case "$action" in
    setup) setup_one "$dir" ;;
    test) test_one "$dir" ;;
    lint) validate_one "$dir" ;;
    check) : ;;
    *) echo "ERROR: unknown action: $action" >&2; exit 2 ;;
  esac
done
