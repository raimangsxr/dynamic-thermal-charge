AI_PROFILE_SETUP_TARGETS += aes-angular-setup
AI_PROFILE_TEST_TARGETS += aes-angular-test
AI_PROFILE_LINT_TARGETS += aes-angular-lint
AI_PROFILE_EXTRA_CHECK_TARGETS += aes-angular-check

.PHONY: aes-angular-setup aes-angular-test aes-angular-lint aes-angular-check aes-angular-dev

aes-angular-setup:
	@$(AI_STANDARD_ROOT)/quality/scripts/angular.sh setup $(AI_ANGULAR_DIRS)

aes-angular-test:
	@$(AI_STANDARD_ROOT)/quality/scripts/angular.sh test $(AI_ANGULAR_DIRS)

aes-angular-lint:
	@$(AI_STANDARD_ROOT)/quality/scripts/angular.sh lint $(AI_ANGULAR_DIRS)

aes-angular-check:
	@$(AI_STANDARD_ROOT)/quality/scripts/angular.sh check $(AI_ANGULAR_DIRS)

ifneq ($(strip $(AI_ANGULAR_DEV_CMD)),)
AI_PROFILE_DEV_TARGETS += aes-angular-dev
aes-angular-dev:
	@cd $(firstword $(AI_ANGULAR_DIRS)) && $(AI_ANGULAR_DEV_CMD)
endif
