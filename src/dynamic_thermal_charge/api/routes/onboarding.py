"""Minimal public first-run surface guarded by the one-use local credential."""

from __future__ import annotations

from fastapi import APIRouter, Request, status
from pydantic import BaseModel, Field

from ...persistence.secret_digest import digest_secret
from ...persistence.system_configuration import SecretAction, SecretMutation
from ..errors import ApiError
from ..settings import ApiSettings, ApiSettingsError


router = APIRouter(prefix="/api/v1/onboarding", tags=["onboarding"])
ONBOARDING_ERRORS = {
    401: {"description": "Invalid, expired or already-used onboarding credential"},
    409: {"description": "Concurrent onboarding operation"},
    422: {"description": "Invalid administrator token"},
    503: {"description": "Bootstrap or canonical store unavailable"},
}


class CompleteOnboardingRequest(BaseModel):
    onboarding_credential: str = Field(min_length=1, repr=False)
    administrator_token: str = Field(min_length=32, repr=False)


@router.get("/status", responses={503: ONBOARDING_ERRORS[503]})
def onboarding_status(request: Request) -> dict[str, object]:
    store = request.app.state.store_factory()
    state = store.context.bootstrap.state()
    return {
        "required": state.installation_state != "configured",
        "state": state.installation_state,
    }


@router.post(
    "/complete", status_code=status.HTTP_204_NO_CONTENT,
    responses=ONBOARDING_ERRORS,
)
def complete_onboarding(payload: CompleteOnboardingRequest, request: Request) -> None:
    store = request.app.state.store_factory()
    bootstrap = store.context.bootstrap
    # Apply the same strength/placeholder policy before reserving the one-use
    # credential, so a user can correct a weak administrator token.
    try:
        ApiSettings(token=payload.administrator_token)
    except ApiSettingsError as exc:
        raise ApiError(422, "validation_error", str(exc)) from exc
    if not bootstrap.reserve_onboarding(payload.onboarding_credential):
        raise ApiError(401, "unauthorized", "invalid or expired onboarding credential")
    try:
        repository = store.system_configuration
        revision = repository.current().revision
        repository.update_section(
            "api",
            {},
            expected_revision=revision,
            secret_mutations={
                "admin_token_digest": SecretMutation(
                    SecretAction.REPLACE, digest_secret(payload.administrator_token)
                )
            },
            actor=(request.client.host if request.client else "onboarding"),
        )
        repository.record_audit(
            actor=request.client.host if request.client else "onboarding",
            action="onboarding",
            section="api",
            fields=("admin_token_digest",),
            revision_before=revision,
            revision_after=revision + 1,
        )
        bootstrap.finish_onboarding()
    except Exception:
        bootstrap.release_onboarding()
        raise


__all__ = ["router"]
