# Project-local AI Engineering Standard configuration.
# Preserved by `aes update`; edit when auto-detection is insufficient.
AI_STANDARD_PROFILES := python-fastapi angular
AI_STANDARD_EXPOSE_TARGETS := 

AI_PYTHON_DIRS := backend
AI_ANGULAR_DIRS := frontend
AI_KUBERNETES_DIRS := .
AI_ESPHOME_DIRS := .
AI_PLATFORMIO_DIRS := .

# Optional whole-target overrides. Leave empty to use profile behavior.
AI_SETUP_CMD :=
AI_DEV_CMD :=
AI_TEST_CMD :=
AI_LINT_CMD :=
AI_CHECK_EXTRA_CMD :=

# Required only when profile `generic` is active.
AI_GENERIC_CHECK_CMD :=

# Optional development commands, executed from the first component directory.
AI_PYTHON_DEV_CMD :=
AI_ANGULAR_DEV_CMD := npm run start
