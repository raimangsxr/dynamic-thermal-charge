AI_PROFILE_SETUP_TARGETS += aes-esphome-setup
AI_PROFILE_TEST_TARGETS += aes-esphome-test
AI_PROFILE_LINT_TARGETS += aes-esphome-lint
AI_PROFILE_EXTRA_CHECK_TARGETS += aes-esphome-check

.PHONY: aes-esphome-setup aes-esphome-test aes-esphome-lint aes-esphome-check

aes-esphome-setup:
	@$(AI_STANDARD_ROOT)/quality/scripts/esphome.sh setup $(AI_ESPHOME_DIRS)

aes-esphome-test:
	@$(AI_STANDARD_ROOT)/quality/scripts/esphome.sh test $(AI_ESPHOME_DIRS)

aes-esphome-lint:
	@$(AI_STANDARD_ROOT)/quality/scripts/esphome.sh lint $(AI_ESPHOME_DIRS)

aes-esphome-check:
	@$(AI_STANDARD_ROOT)/quality/scripts/esphome.sh check $(AI_ESPHOME_DIRS)
