AI_PROFILE_EXTRA_CHECK_TARGETS += aes-generic-check
.PHONY: aes-generic-check

ifeq ($(strip $(AI_GENERIC_CHECK_CMD)),)
aes-generic-check:
	@echo "ERROR: generic profile requires AI_GENERIC_CHECK_CMD in .ai-standard/project.mk" >&2
	@exit 2
else
aes-generic-check:
	@$(AI_GENERIC_CHECK_CMD)
endif
