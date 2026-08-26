"""Reading the audit trail, always bounded, and running the retention policy."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request

from ...persistence.bootstrap import Store
from ...persistence.history import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    CursorError,
    SqlHistoryReader,
    SqlHistoryRecorder,
)
from ..dependencies import usable_store
from ..errors import bad_request
from ..schemas import (
    ERROR_RESPONSES,
    READ_RESPONSES,
    ForecastPage,
    PlanPage,
    PruneResponse,
    TransitionPage,
)


router = APIRouter()

PAGE_DESCRIPTION = (
    f"Paged, newest first. Default page size {DEFAULT_PAGE_SIZE}, maximum "
    f"{MAX_PAGE_SIZE}: no request ever returns the whole history. `next_cursor` "
    "is opaque and encodes the (instant, id) pair of the last item, so an insert "
    "between two pages cannot produce a repeated or skipped item."
)


def _reader(store: Store) -> SqlHistoryReader:
    return SqlHistoryReader(
        store.engine, store.repository.installation_id(), store.location
    )


def _check_range(since: datetime | None, until: datetime | None) -> None:
    if since is not None and until is not None and since > until:
        raise bad_request(
            "the range starts after it ends: 'from' must not be later than 'to'",
            field="from",
        )


def _page(call, **kwargs):
    try:
        return call(**kwargs)
    except CursorError as exc:
        raise bad_request(str(exc), field="cursor") from exc


@router.get(
    "/history/plans",
    response_model=PlanPage,
    responses={**READ_RESPONSES, 400: ERROR_RESPONSES[404]},
    summary="Plans that were generated",
    description=PAGE_DESCRIPTION,
)
def get_plans(
    since: datetime | None = Query(default=None, alias="from"),
    until: datetime | None = Query(default=None, alias="to"),
    limit: int | None = Query(default=None, ge=1),
    cursor: str | None = None,
    store: Store = Depends(usable_store),
) -> PlanPage:
    _check_range(since, until)
    page = _page(
        _reader(store).plans, since=since, until=until, limit=limit, cursor=cursor
    )
    return PlanPage(
        items=page.items,
        limit_applied=page.limit_applied,
        has_more=page.has_more,
        next_cursor=page.next_cursor,
    )


@router.get(
    "/history/forecasts",
    response_model=ForecastPage,
    responses={**READ_RESPONSES, 400: ERROR_RESPONSES[404]},
    summary="Forecasts that were used",
    description=PAGE_DESCRIPTION + " `source` says whether the real provider worked.",
)
def get_forecasts(
    since: datetime | None = Query(default=None, alias="from"),
    until: datetime | None = Query(default=None, alias="to"),
    limit: int | None = Query(default=None, ge=1),
    cursor: str | None = None,
    store: Store = Depends(usable_store),
) -> ForecastPage:
    _check_range(since, until)
    page = _page(
        _reader(store).forecasts, since=since, until=until, limit=limit, cursor=cursor
    )
    return ForecastPage(
        items=page.items,
        limit_applied=page.limit_applied,
        has_more=page.has_more,
        next_cursor=page.next_cursor,
    )


@router.get(
    "/history/transitions",
    response_model=TransitionPage,
    responses={**READ_RESPONSES, 400: ERROR_RESPONSES[404]},
    summary="Output transitions that happened",
    description=(
        PAGE_DESCRIPTION
        + " `heater_id` filters, and still returns transitions of heaters that "
        "have since been removed: an unknown id yields an empty page, not 404, "
        "because it may have existed."
    ),
)
def get_transitions(
    since: datetime | None = Query(default=None, alias="from"),
    until: datetime | None = Query(default=None, alias="to"),
    limit: int | None = Query(default=None, ge=1),
    cursor: str | None = None,
    heater_id: str | None = None,
    store: Store = Depends(usable_store),
) -> TransitionPage:
    _check_range(since, until)
    page = _page(
        _reader(store).transitions,
        since=since,
        until=until,
        limit=limit,
        cursor=cursor,
        heater_id=heater_id,
    )
    return TransitionPage(
        items=page.items,
        limit_applied=page.limit_applied,
        has_more=page.has_more,
        next_cursor=page.next_cursor,
    )


@router.post(
    "/history/prune",
    response_model=PruneResponse,
    responses=READ_RESPONSES,
    summary="Apply the retention policy now",
    description=(
        "Deletes history older than the configured retention. Never touches the "
        "configuration nor a live plan. With unlimited retention nothing is "
        "deleted and the response says so."
    ),
)
def post_prune(request: Request, store: Store = Depends(usable_store)) -> PruneResponse:
    config, _ = store.repository.current()
    recorder = SqlHistoryRecorder(
        store.engine, store.repository.installation_id(), store.location
    )
    report = recorder.prune(request.app.state.clock(), config.retention_days)
    return PruneResponse(
        deleted=report.deleted,
        total=report.total,
        retention_days=config.retention_days,
        unlimited=config.retention_days is None,
    )


__all__ = ["router"]
