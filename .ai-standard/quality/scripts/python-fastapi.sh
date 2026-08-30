#!/usr/bin/env bash
set -euo pipefail

action=${1:-}
shift || true
if [ -z "$action" ]; then
  echo "usage: python-fastapi.sh <setup|test|lint|check> [dirs...]" >&2
  exit 2
fi
if [ "$#" -eq 0 ]; then set -- .; fi

prefix_for() {
  local dir=$1
  PREFIX=()
  if [ -f "$dir/uv.lock" ]; then
    command -v uv >/dev/null 2>&1 || { echo "ERROR: uv.lock found in $dir but uv is not installed" >&2; exit 2; }
    PREFIX=(uv run)
  elif [ -f "$dir/poetry.lock" ]; then
    command -v poetry >/dev/null 2>&1 || { echo "ERROR: poetry.lock found in $dir but poetry is not installed" >&2; exit 2; }
    PREFIX=(poetry run)
  elif [ -x "$dir/.venv/bin/python" ]; then
    PREFIX=(.venv/bin)
  fi
}

run_python() {
  local dir=$1; shift
  prefix_for "$dir"
  if [ "${#PREFIX[@]}" -eq 0 ]; then
    (cd "$dir" && python3 "$@")
  elif [ "${PREFIX[0]}" = ".venv/bin" ]; then
    (cd "$dir" && .venv/bin/python "$@")
  else
    (cd "$dir" && "${PREFIX[@]}" python "$@")
  fi
}

run_tool() {
  local dir=$1 tool=$2; shift 2
  prefix_for "$dir"
  if [ "${#PREFIX[@]}" -eq 0 ]; then
    (cd "$dir" && "$tool" "$@")
  elif [ "${PREFIX[0]}" = ".venv/bin" ]; then
    (cd "$dir" && ".venv/bin/$tool" "$@")
  else
    (cd "$dir" && "${PREFIX[@]}" "$tool" "$@")
  fi
}

has_tool() {
  local dir=$1 tool=$2
  prefix_for "$dir"
  if [ "${#PREFIX[@]}" -eq 0 ]; then
    (cd "$dir" && command -v "$tool" >/dev/null 2>&1)
  elif [ "${PREFIX[0]}" = ".venv/bin" ]; then
    [ -x "$dir/.venv/bin/$tool" ]
  else
    (cd "$dir" && "${PREFIX[@]}" "$tool" --version >/dev/null 2>&1)
  fi
}

configured() {
  local dir=$1 pattern=$2
  [ -f "$dir/pyproject.toml" ] && grep -Eiq "$pattern" "$dir/pyproject.toml"
}

setup_one() {
  local dir=$1
  echo "==> Python setup: $dir"
  if [ -f "$dir/uv.lock" ]; then
    command -v uv >/dev/null 2>&1 || { echo "ERROR: install uv for $dir" >&2; exit 2; }
    (cd "$dir" && uv sync)
  elif [ -f "$dir/poetry.lock" ]; then
    command -v poetry >/dev/null 2>&1 || { echo "ERROR: install poetry for $dir" >&2; exit 2; }
    (cd "$dir" && poetry install)
  else
    if [ ! -x "$dir/.venv/bin/python" ]; then
      (cd "$dir" && python3 -m venv .venv)
    fi
    if [ -f "$dir/requirements-dev.txt" ]; then
      (cd "$dir" && .venv/bin/python -m pip install -r requirements-dev.txt)
    elif [ -f "$dir/requirements.txt" ]; then
      (cd "$dir" && .venv/bin/python -m pip install -r requirements.txt)
    elif [ -f "$dir/pyproject.toml" ]; then
      (cd "$dir" && .venv/bin/python -m pip install -e '.[dev]') || \
        (cd "$dir" && .venv/bin/python -m pip install -e .)
    else
      echo "WARN: no Python dependency manifest found in $dir" >&2
    fi
  fi
}

test_one() {
  local dir=$1
  echo "==> Python tests: $dir"
  if [ -d "$dir/tests" ] || configured "$dir" 'pytest|tool\.pytest'; then
    if has_tool "$dir" pytest; then
      run_python "$dir" -m pytest
    else
      echo "ERROR: tests/ or pytest config found in $dir but pytest is unavailable" >&2
      exit 2
    fi
  else
    echo "INFO: no pytest suite detected in $dir"
  fi
}

lint_one() {
  local dir=$1 ran=0
  echo "==> Python static checks: $dir"
  if configured "$dir" 'ruff|tool\.ruff'; then
    has_tool "$dir" ruff || { echo "ERROR: ruff is configured in $dir but unavailable" >&2; exit 2; }
    run_tool "$dir" ruff check .
    run_tool "$dir" ruff format --check .
    ran=1
  fi
  if configured "$dir" 'mypy|tool\.mypy'; then
    has_tool "$dir" mypy || { echo "ERROR: mypy is configured in $dir but unavailable" >&2; exit 2; }
    run_tool "$dir" mypy .
    ran=1
  fi
  if [ -f "$dir/pyrightconfig.json" ] || configured "$dir" 'pyright'; then
    if has_tool "$dir" pyright; then
      run_tool "$dir" pyright
      ran=1
    else
      echo "WARN: pyright is configured in $dir but no project-local executable was detected" >&2
    fi
  fi
  # Dependency-free syntax baseline even when no linter is configured.
  run_python "$dir" -m compileall -q -x '(^|/)(\.venv|venv|node_modules|\.git|build|dist)(/|$)' .
  if [ "$ran" -eq 0 ]; then
    echo "INFO: no Python linter/type checker configured; compileall is the static baseline"
  fi
}

check_one() {
  local dir=$1
  if [ -f "$dir/alembic.ini" ] || [ -d "$dir/alembic" ]; then
    if has_tool "$dir" alembic; then
      echo "==> Alembic migration graph: $dir"
      run_tool "$dir" alembic heads >/dev/null
    else
      echo "ERROR: Alembic structure found in $dir but alembic is unavailable" >&2
      exit 2
    fi
  fi
}

for dir in "$@"; do
  [ -d "$dir" ] || { echo "ERROR: Python component directory not found: $dir" >&2; exit 2; }
  case "$action" in
    setup) setup_one "$dir" ;;
    test) test_one "$dir" ;;
    lint) lint_one "$dir" ;;
    check) check_one "$dir" ;;
    *) echo "ERROR: unknown action: $action" >&2; exit 2 ;;
  esac
done
