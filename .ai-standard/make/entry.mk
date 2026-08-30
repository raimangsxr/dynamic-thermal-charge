# Generated runtime entrypoint. Project-specific values live in ../project.mk.
AI_STANDARD_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/..)
include $(AI_STANDARD_ROOT)/project.mk
include $(foreach p,$(AI_STANDARD_PROFILES),$(AI_STANDARD_ROOT)/make/profiles/$(p).mk)
include $(AI_STANDARD_ROOT)/make/base.mk
