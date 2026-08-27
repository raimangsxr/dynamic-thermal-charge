"""HTTP edge for relay-test coordination; it never imports a driver."""
from __future__ import annotations

import os
from fastapi import APIRouter, Depends, Header, Request, status

from ...persistence import RelayTestError
from ...persistence.bootstrap import Store
from ...persistence.heartbeat import read_heartbeat
from ..dependencies import usable_store
from ..errors import ApiError
from ..schemas import RelayTestCommandRequest, RelayTestCommandResponse, RelayTestStartResponse, RelayTestView
from ..security import new_relay_test_credential, relay_test_credential_digest

router = APIRouter()
ERRORS = {401: {"description": "Unauthorized"}, 403: {"description": "Not owner"}, 404: {"description": "Not found"}, 409: {"description": "Relay test conflict"}, 503: {"description": "Controller unavailable"}}

def _lease() -> int:
    return int(os.environ.get("DTC_RELAY_TEST_LEASE_SECONDS", "30"))

def _digest(credential: str | None) -> str:
    if not credential:
        raise ApiError(403, "relay_test_not_owner", "the relay-test client credential is required")
    return relay_test_credential_digest(credential)

def _translate(exc: RelayTestError):
    mapping = {"not_found": 404, "relay_test_not_owner": 403, "relay_test_active": 409,
               "relay_test_not_active": 409, "relay_test_expired": 409,
               "relay_test_fault_latched": 409, "no_heaters": 409}
    raise ApiError(mapping.get(exc.code, 409), exc.code, str(exc), heater_id=exc.heater_id) from exc

def _view(store: Store, raw: dict | None) -> RelayTestView | None:
    if raw is None:
        return None
    heartbeat = read_heartbeat(store.engine, store.repository.installation_id(), store.location)
    current = heartbeat is not None
    session = raw.get("session")
    safety = raw["safety"]
    return RelayTestView(
        session=session,
        controller={"state_is_current": current, "last_seen_at": None if heartbeat is None else heartbeat.updated_at},
        safety={"automatic_control_blocked": bool(session) or bool(safety["fault_latched"]), "fault_latched": bool(safety["fault_latched"]), "fault_session_id": safety.get("fault_session_id"), "fault_reason": safety.get("fault_reason"), "fault_latched_at": safety.get("fault_latched_at"), "fault_recovery_attempted_at": safety.get("fault_recovery_attempted_at"), "fault_recovered_at": safety.get("fault_recovered_at")},
        audit=raw.get("audit", {"degraded": False}),
        heaters=[{"id": row["heater_id"], "name": row["heater_name"], "position": row["position"], "power_w": row["power_w"], "desired_state": row["desired_state"], "confirmed_state": row["confirmed_state"], "result": row["result"], "result_code": row["result_code"], "confirmed_at": row["confirmed_at"]} for row in raw["heaters"]],
    )

@router.post("/relay-test", response_model=RelayTestStartResponse, status_code=status.HTTP_202_ACCEPTED, responses=ERRORS)
def start(request: Request, store: Store = Depends(usable_store)):
    credential = new_relay_test_credential()
    try:
        view = store.relay_tests.claim(relay_test_credential_digest(credential), request.app.state.clock(), _lease())
    except RelayTestError as exc: _translate(exc)
    session = view["session"]
    return RelayTestStartResponse(session_id=session["id"], client_credential=credential, status="starting", lease_expires_at=session["lease_expires_at"])

@router.get("/relay-test", status_code=status.HTTP_200_OK, responses=ERRORS)
def current(store: Store = Depends(usable_store), x_relay_test_credential: str | None = Header(default=None)):
    return _view(store, store.relay_tests.current(relay_test_credential_digest(x_relay_test_credential) if x_relay_test_credential else None))

@router.get("/relay-test/{session_id}", responses=ERRORS)
def get(session_id: str, store: Store = Depends(usable_store), x_relay_test_credential: str | None = Header(default=None)):
    view = store.relay_tests.get(session_id, relay_test_credential_digest(x_relay_test_credential) if x_relay_test_credential else None)
    if view is None or view["session"] is None: raise ApiError(404, "not_found", "relay-test session was not found")
    return _view(store, view)

@router.post("/relay-test/{session_id}/lease", responses=ERRORS)
def lease(session_id: str, request: Request, store: Store = Depends(usable_store), x_relay_test_credential: str | None = Header(default=None)):
    try: return _view(store, store.relay_tests.renew(session_id, _digest(x_relay_test_credential), request.app.state.clock(), _lease()))
    except RelayTestError as exc: _translate(exc)

@router.put("/relay-test/{session_id}/heaters/{heater_id}", response_model=RelayTestCommandResponse, status_code=status.HTTP_202_ACCEPTED, responses=ERRORS)
def command(session_id: str, heater_id: str, payload: RelayTestCommandRequest, request: Request, store: Store = Depends(usable_store), x_relay_test_credential: str | None = Header(default=None)):
    try: return store.relay_tests.command(session_id, heater_id, payload.state, _digest(x_relay_test_credential), request.app.state.clock())
    except RelayTestError as exc: _translate(exc)

@router.delete("/relay-test/{session_id}", status_code=status.HTTP_202_ACCEPTED, responses=ERRORS)
def end(session_id: str, request: Request, store: Store = Depends(usable_store), x_relay_test_credential: str | None = Header(default=None)):
    try: return _view(store, store.relay_tests.request_end(session_id, _digest(x_relay_test_credential), request.app.state.clock()))
    except RelayTestError as exc: _translate(exc)
