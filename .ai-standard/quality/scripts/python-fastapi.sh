#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${AI_PYTHON_BIN:-python3}"

action=${1:-}
shift || true
if [ -z "$action" ]; then
  echo "usage: python-fastapi.sh <setup|test|lint|check> [dirs...]" >&2
  exit 2
fi
if [ "$#" -eq 0 ]; then set -- .; fi

environment_error() {
  local dir=$1
  echo "ERROR: Python environment for $dir is unavailable or broken; run '$0 setup $dir'. If $dir/.venv is stale, remove it and rerun setup to recreate it." >&2
  exit 2
}

prefix_for() {
  local dir=$1
  PREFIX=()
  if [ -f "$dir/uv.lock" ]; then
    command -v uv >/dev/null 2>&1 || { echo "ERROR: uv.lock found in $dir but uv is not installed" >&2; exit 2; }
    PREFIX=(uv run)
  elif [ -f "$dir/poetry.lock" ]; then
    command -v poetry >/dev/null 2>&1 || { echo "ERROR: poetry.lock found in $dir but poetry is not installed" >&2; exit 2; }
    PREFIX=(poetry run)
  elif [ -e "$dir/.venv" ] || [ -L "$dir/.venv" ]; then
    [ -x "$dir/.venv/bin/python" ] || environment_error "$dir"
    if ! (cd "$dir" && .venv/bin/python -c 'pass') >/dev/null 2>&1; then
      environment_error "$dir"
    fi
    PREFIX=(.venv/bin)
  fi
}

run_python() {
  local dir=$1; shift
  prefix_for "$dir"
  if [ "${#PREFIX[@]}" -eq 0 ]; then
    (cd "$dir" && "$PYTHON_BIN" "$@")
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

has_python_module() {
  local dir=$1 module=$2
  run_python "$dir" -c 'import importlib.util, sys; sys.exit(0 if importlib.util.find_spec(sys.argv[1]) else 1)' "$module" >/dev/null
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
  [ -f "$dir/pyproject.toml" ] && grep -Eiq -- "$pattern" "$dir/pyproject.toml"
}

pytest_cov_required() {
  local dir=$1
  [ -f "$dir/pyproject.toml" ] && grep -Eiq -- "(^|[[:space:]\"'])--cov([^[:alnum:]_-]|\$)" "$dir/pyproject.toml"
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
      (cd "$dir" && "$PYTHON_BIN" -m venv .venv)
    fi
    (cd "$dir" && .venv/bin/python -m pip install --upgrade pip)
    if [ -f "$dir/requirements-dev.txt" ]; then
      (cd "$dir" && .venv/bin/python -m pip install -r requirements-dev.txt)
    elif [ -f "$dir/requirements.txt" ]; then
      (cd "$dir" && .venv/bin/python -m pip install -r requirements.txt)
    elif [ -f "$dir/pyproject.toml" ]; then
      (cd "$dir" && .venv/bin/python -m pip install -e '.[dev]')
    else
      echo "WARN: no Python dependency manifest found in $dir" >&2
    fi
  fi
}

test_one() {
  local dir=$1
  echo "==> Python tests: $dir"
  if [ -d "$dir/tests" ] || configured "$dir" 'pytest|tool\.pytest'; then
    has_python_module "$dir" pytest || {
      echo "ERROR: tests/ or pytest config found in $dir but pytest is unavailable in the selected Python environment; run '$0 setup $dir'. If $dir/.venv is stale, remove it and rerun setup to recreate it." >&2
      exit 2
    }
    if pytest_cov_required "$dir"; then
      has_python_module "$dir" pytest_cov || {
        echo "ERROR: $dir/pyproject.toml enables pytest coverage (--cov), but pytest-cov is unavailable in the selected Python environment; run '$0 setup $dir'. If $dir/.venv is stale, remove it and rerun setup to recreate it." >&2
        exit 2
      }
    fi
    run_python "$dir" -m pytest
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
