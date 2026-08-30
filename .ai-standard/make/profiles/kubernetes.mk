AI_PROFILE_SETUP_TARGETS += aes-kubernetes-setup
AI_PROFILE_TEST_TARGETS += aes-kubernetes-test
AI_PROFILE_LINT_TARGETS += aes-kubernetes-lint
AI_PROFILE_EXTRA_CHECK_TARGETS += aes-kubernetes-check

.PHONY: aes-kubernetes-setup aes-kubernetes-test aes-kubernetes-lint aes-kubernetes-check

aes-kubernetes-setup:
	@$(AI_STANDARD_ROOT)/quality/scripts/kubernetes.sh setup $(AI_KUBERNETES_DIRS)

aes-kubernetes-test:
	@$(AI_STANDARD_ROOT)/quality/scripts/kubernetes.sh test $(AI_KUBERNETES_DIRS)

aes-kubernetes-lint:
	@$(AI_STANDARD_ROOT)/quality/scripts/kubernetes.sh lint $(AI_KUBERNETES_DIRS)

aes-kubernetes-check:
	@$(AI_STANDARD_ROOT)/quality/scripts/kubernetes.sh check $(AI_KUBERNETES_DIRS)
