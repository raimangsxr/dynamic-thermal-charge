"""Authenticated, read-only controller diagnostic events."""
from fastapi import APIRouter, Depends, Query

from ...persistence.bootstrap import Store
from ...persistence.controller_log import LOG_LEVELS, SqlControllerLogReader
from ..dependencies import usable_store
from ..errors import bad_request
from ..schemas import ControllerLogPage, READ_RESPONSES

router = APIRouter()


@router.get("/controller-log", response_model=ControllerLogPage, responses=READ_RESPONSES,
            summary="Recent controller diagnostic events")
def get_controller_log(
    limit: int = Query(default=100, ge=1), before_id: int | None = Query(default=None, ge=1),
    after_id: int | None = Query(default=None, ge=1), level: str | None = None,
    q: str | None = Query(default=None, max_length=200), store: Store = Depends(usable_store),
) -> ControllerLogPage:
    if before_id is not None and after_id is not None:
        raise bad_request("before_id and after_id cannot be combined", field="before_id")
    normalized = level.upper() if level else None
    if normalized is not None and normalized not in LOG_LEVELS:
        raise bad_request("level is not recognised", field="level")
    page = SqlControllerLogReader(
        store.application_engine or store.engine,
        store.repository.installation_id(),
        store.location,
    ).events(
        limit=limit, before_id=before_id, after_id=after_id, level=normalized, query=q)
    return ControllerLogPage(**page)
