# Project-local AI Engineering Standard configuration.
# Preserved by `aes update`; edit when auto-detection is insufficient.
AI_STANDARD_PROFILES := python-fastapi angular
AI_STANDARD_EXPOSE_TARGETS := setup dev test lint check

AI_PYTHON_DIRS := backend
AI_ANGULAR_DIRS := frontend
AI_KUBERNETES_DIRS := .
AI_ESPHOME_DIRS := .
AI_PLATFORMIO_DIRS := .

# Optional whole-target overrides. Leave empty to use profile behavior.
AI_SETUP_CMD :=
# `make dev` validates the persisted configuration, as it did before the
# harness was wired in. It is what the Compose healthcheck exercises.
AI_DEV_CMD := python -c 'from dynamic_thermal_charge.entrypoints import check_configuration; check_configuration()'
AI_TEST_CMD :=
# The harness runs `ruff format --check` as soon as ruff is configured at all,
# and this batch deliberately excludes reformatting (119 of 162 files would
# change). Lint is therefore overridden to the checks that are in scope. Drop
# this override when `ruff format` is adopted and the native lint takes over.
AI_LINT_CMD := cd backend && PATH="$$PWD/.venv/bin:$$PATH" ruff check . ../custom_components && PATH="$$PWD/.venv/bin:$$PATH" python -m compileall -q src tests ../custom_components
# Compose files stay part of the gate: a broken deployment descriptor is a
# build failure, not a surprise on the device.
AI_CHECK_EXTRA_CMD := $(MAKE) compose-check

# Required only when profile `generic` is active.
AI_GENERIC_CHECK_CMD :=

# Optional development commands, executed from the first component directory.
AI_PYTHON_DEV_CMD :=
AI_ANGULAR_DEV_CMD := npm run start
