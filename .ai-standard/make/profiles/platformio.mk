AI_PROFILE_SETUP_TARGETS += aes-platformio-setup
AI_PROFILE_TEST_TARGETS += aes-platformio-test
AI_PROFILE_LINT_TARGETS += aes-platformio-lint
AI_PROFILE_EXTRA_CHECK_TARGETS += aes-platformio-check

.PHONY: aes-platformio-setup aes-platformio-test aes-platformio-lint aes-platformio-check

aes-platformio-setup:
	@$(AI_STANDARD_ROOT)/quality/scripts/platformio.sh setup $(AI_PLATFORMIO_DIRS)

aes-platformio-test:
	@$(AI_STANDARD_ROOT)/quality/scripts/platformio.sh test $(AI_PLATFORMIO_DIRS)

aes-platformio-lint:
	@$(AI_STANDARD_ROOT)/quality/scripts/platformio.sh lint $(AI_PLATFORMIO_DIRS)

aes-platformio-check:
	@$(AI_STANDARD_ROOT)/quality/scripts/platformio.sh check $(AI_PLATFORMIO_DIRS)
