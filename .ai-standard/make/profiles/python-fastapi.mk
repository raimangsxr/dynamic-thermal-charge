AI_PROFILE_SETUP_TARGETS += aes-python-fastapi-setup
AI_PROFILE_TEST_TARGETS += aes-python-fastapi-test
AI_PROFILE_LINT_TARGETS += aes-python-fastapi-lint
AI_PROFILE_EXTRA_CHECK_TARGETS += aes-python-fastapi-check

.PHONY: aes-python-fastapi-setup aes-python-fastapi-test aes-python-fastapi-lint aes-python-fastapi-check aes-python-fastapi-dev

aes-python-fastapi-setup:
	@$(AI_STANDARD_ROOT)/quality/scripts/python-fastapi.sh setup $(AI_PYTHON_DIRS)

aes-python-fastapi-test:
	@$(AI_STANDARD_ROOT)/quality/scripts/python-fastapi.sh test $(AI_PYTHON_DIRS)

aes-python-fastapi-lint:
	@$(AI_STANDARD_ROOT)/quality/scripts/python-fastapi.sh lint $(AI_PYTHON_DIRS)

aes-python-fastapi-check:
	@$(AI_STANDARD_ROOT)/quality/scripts/python-fastapi.sh check $(AI_PYTHON_DIRS)

ifneq ($(strip $(AI_PYTHON_DEV_CMD)),)
AI_PROFILE_DEV_TARGETS += aes-python-fastapi-dev
aes-python-fastapi-dev:
	@cd $(firstword $(AI_PYTHON_DIRS)) && $(AI_PYTHON_DEV_CMD)
endif
