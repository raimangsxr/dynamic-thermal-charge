.PHONY: aes-setup aes-dev aes-test aes-lint aes-extra-check

AI_PROFILE_SETUP_TARGETS ?=
AI_PROFILE_DEV_TARGETS ?=
AI_PROFILE_TEST_TARGETS ?=
AI_PROFILE_LINT_TARGETS ?=
AI_PROFILE_EXTRA_CHECK_TARGETS ?=

ifneq ($(strip $(AI_SETUP_CMD)),)
aes-setup:
	@$(AI_SETUP_CMD)
else
aes-setup: $(AI_PROFILE_SETUP_TARGETS)
endif

ifneq ($(strip $(AI_DEV_CMD)),)
aes-dev:
	@$(AI_DEV_CMD)
else
aes-dev: $(AI_PROFILE_DEV_TARGETS)
	@if [ -z "$(strip $(AI_PROFILE_DEV_TARGETS))" ]; then echo "INFO: no dev command configured; set AI_DEV_CMD in .ai-standard/project.mk if needed"; fi
endif

ifneq ($(strip $(AI_TEST_CMD)),)
aes-test:
	@$(AI_TEST_CMD)
else
aes-test: $(AI_PROFILE_TEST_TARGETS)
endif

ifneq ($(strip $(AI_LINT_CMD)),)
aes-lint:
	@$(AI_LINT_CMD)
else
aes-lint: $(AI_PROFILE_LINT_TARGETS)
endif

ifneq ($(strip $(AI_CHECK_EXTRA_CMD)),)
aes-extra-check: $(AI_PROFILE_EXTRA_CHECK_TARGETS)
	@$(AI_CHECK_EXTRA_CMD)
else
aes-extra-check: $(AI_PROFILE_EXTRA_CHECK_TARGETS)
	@:
endif

# Only targets missing from the pre-existing Makefile are bridged here.
ifneq ($(filter setup,$(AI_STANDARD_EXPOSE_TARGETS)),)
.PHONY: setup
setup: aes-setup
endif

ifneq ($(filter dev,$(AI_STANDARD_EXPOSE_TARGETS)),)
.PHONY: dev
dev: aes-dev
endif

ifneq ($(filter test,$(AI_STANDARD_EXPOSE_TARGETS)),)
.PHONY: test
test: aes-test
endif

ifneq ($(filter lint,$(AI_STANDARD_EXPOSE_TARGETS)),)
.PHONY: lint
lint: aes-lint
endif

ifneq ($(filter check,$(AI_STANDARD_EXPOSE_TARGETS)),)
.PHONY: check
check: test lint aes-extra-check
endif
