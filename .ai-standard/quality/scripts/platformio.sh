#!/usr/bin/env bash
set -euo pipefail

action=${1:-}
shift || true
if [ -z "$action" ]; then
  echo "usage: platformio.sh <setup|test|lint|check> [dirs...]" >&2
  exit 2
fi
if [ "$#" -eq 0 ]; then set -- .; fi

require_pio() {
  command -v pio >/dev/null 2>&1 || command -v platformio >/dev/null 2>&1 || {
    echo "ERROR: PlatformIO CLI (pio/platformio) is not installed" >&2
    exit 2
  }
}

pio_cmd() {
  if command -v pio >/dev/null 2>&1; then pio "$@"; else platformio "$@"; fi
}

has_tests() {
  local dir=$1
  [ -d "$dir/test" ] && [ -n "$(find "$dir/test" -type f -print -quit 2>/dev/null)" ]
}

for dir in "$@"; do
  [ -f "$dir/platformio.ini" ] || { echo "ERROR: platformio.ini not found: $dir" >&2; exit 2; }
  require_pio
  case "$action" in
    setup)
      echo "==> PlatformIO dependencies: $dir"
      (cd "$dir" && pio_cmd pkg install)
      ;;
    test)
      if has_tests "$dir"; then
        echo "==> PlatformIO tests: $dir"
        (cd "$dir" && pio_cmd test)
      else
        echo "INFO: no PlatformIO test suite detected in $dir"
      fi
      ;;
    lint)
      echo "INFO: no additional PlatformIO static analyzer configured by default for $dir"
      ;;
    check)
      echo "==> PlatformIO build: $dir"
      (cd "$dir" && pio_cmd run)
      ;;
    *) echo "ERROR: unknown action: $action" >&2; exit 2 ;;
  esac
done
