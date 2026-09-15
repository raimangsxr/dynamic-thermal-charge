# Keep GPIO deployment configuration reconciled

Status: approved

## Goal

Ensure the production controller always receives the current host GPIO device
group and fails early with an actionable error when the GPIO device is absent.
This prevents an unchanged application release from retaining a stale Docker
group configuration.

## Requirements

- R1: Every execution of `deploy/reconcile.sh` must validate that `/dev/gpiochip0` exists as a character device before resolving or applying the production Compose configuration; a missing device must produce a non-zero result and an actionable message.
- R2: Every execution must derive `DTC_GPIO_GID` from the current `/dev/gpiochip0` ownership, including when the application release is unchanged. A pre-existing value that differs from the detected GID must fail with an actionable mismatch message.
- R3: When the release is unchanged, the reconciler must still apply an idempotent Compose reconciliation so a changed GPIO GID updates the running backend; image pulling remains limited to release changes.
- R4: The production Compose file must not silently use a hard-coded fallback GPIO GID; missing `DTC_GPIO_GID` must fail Compose configuration validation.
- R5: Deployment documentation and automated checks must describe and verify the automatic GPIO preflight and reconciliation behavior.

## Acceptance

- A1: A host with `/dev/gpiochip0` owned by GID `986` causes the reconciler's effective backend configuration to use `986` even when `deploy/release` matches the running image.
- A2: A stale configured GID or a missing `/dev/gpiochip0` causes the reconciler to exit non-zero before `docker compose up` and identifies the corrective condition.
- A3: A production Compose configuration without `DTC_GPIO_GID` is rejected instead of resolving to `997`.
- A4: Tests and the repository quality gate pass, including the production Compose validation check.
- A5: README deployment instructions state how automatic reconciliation and manual deployments obtain the GPIO GID.
