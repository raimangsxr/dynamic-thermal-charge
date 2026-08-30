#!/usr/bin/env bash
set -euo pipefail

action=${1:-}
shift || true
if [ -z "$action" ]; then
  echo "usage: angular.sh <setup|test|lint|check> [dirs...]" >&2
  exit 2
fi
if [ "$#" -eq 0 ]; then set -- .; fi

pm_for() {
  local dir=$1
  if [ -f "$dir/pnpm-lock.yaml" ]; then echo pnpm
  elif [ -f "$dir/yarn.lock" ]; then echo yarn
  else echo npm
  fi
}

require_pm() {
  local pm=$1
  command -v "$pm" >/dev/null 2>&1 || { echo "ERROR: package manager '$pm' is not installed" >&2; exit 2; }
}

has_script() {
  local dir=$1 script=$2
  (cd "$dir" && node -e 'const p=require("./package.json"); process.exit(p.scripts && p.scripts[process.argv[1]] ? 0 : 1)' "$script")
}

script_text() {
  local dir=$1 script=$2
  (cd "$dir" && node -e 'const p=require("./package.json"); process.stdout.write((p.scripts&&p.scripts[process.argv[1]])||"")' "$script")
}

run_script() {
  local dir=$1 pm=$2 script=$3; shift 3
  case "$pm" in
    npm) (cd "$dir" && npm run "$script" "$@") ;;
    pnpm) (cd "$dir" && pnpm run "$script" "$@") ;;
    yarn) (cd "$dir" && yarn run "$script" "$@") ;;
  esac
}

setup_one() {
  local dir=$1 pm
  pm=$(pm_for "$dir"); require_pm "$pm"
  echo "==> Angular setup: $dir ($pm)"
  case "$pm" in
    npm)
      if [ -f "$dir/package-lock.json" ]; then (cd "$dir" && npm ci); else (cd "$dir" && npm install); fi ;;
    pnpm) (cd "$dir" && pnpm install --frozen-lockfile) ;;
    yarn) (cd "$dir" && yarn install --immutable) || (cd "$dir" && yarn install --frozen-lockfile) ;;
  esac
}

test_one() {
  local dir=$1 pm text
  export CI=1
  pm=$(pm_for "$dir"); require_pm "$pm"
  echo "==> Angular tests: $dir"
  if has_script "$dir" test; then
    text=$(script_text "$dir" test)
    if printf '%s' "$text" | grep -Eq '(^|[[:space:]])ng[[:space:]]+test'; then
      run_script "$dir" "$pm" test -- --watch=false
    else
      run_script "$dir" "$pm" test
    fi
  else
    echo "INFO: no package.json test script detected in $dir"
  fi
}

lint_one() {
  local dir=$1 pm
  export CI=1
  pm=$(pm_for "$dir"); require_pm "$pm"
  echo "==> Angular lint: $dir"
  if has_script "$dir" lint; then
    run_script "$dir" "$pm" lint
  else
    echo "INFO: no package.json lint script detected in $dir; Angular build remains part of make check"
  fi
}

check_one() {
  local dir=$1 pm
  export CI=1
  pm=$(pm_for "$dir"); require_pm "$pm"
  echo "==> Angular build: $dir"
  if has_script "$dir" build; then
    run_script "$dir" "$pm" build
  elif [ -x "$dir/node_modules/.bin/ng" ]; then
    (cd "$dir" && CI=1 ./node_modules/.bin/ng build)
  else
    echo "ERROR: Angular component in $dir has no build script/local Angular CLI" >&2
    exit 2
  fi
}

for dir in "$@"; do
  [ -f "$dir/package.json" ] || { echo "ERROR: package.json not found in Angular component: $dir" >&2; exit 2; }
  case "$action" in
    setup) setup_one "$dir" ;;
    test) test_one "$dir" ;;
    lint) lint_one "$dir" ;;
    check) check_one "$dir" ;;
    *) echo "ERROR: unknown action: $action" >&2; exit 2 ;;
  esac
done
