"""Global operator alert inbox and acknowledgement API."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query, Request

from ...persistence.bootstrap import Store
from ..dependencies import usable_store
from ..errors import bad_request
from ..schemas import AlertPage, AlertView, ERROR_RESPONSES, READ_RESPONSES


router = APIRouter()


def _page_response(page, view: str) -> AlertPage:
    return AlertPage(
        items=[
            AlertView(
                id=item.id,
                alert_type=item.alert_type,
                severity=item.severity,
                title=item.title,
                body=item.body,
                episode_id=item.episode_id,
                session_id=item.session_id,
                opened_at=item.opened_at,
                resolved_at=item.resolved_at,
                acknowledged_at=item.acknowledged_at,
                active=item.active,
            )
            for item in page.items
        ],
        view=view,
        limit_applied=page.limit_applied,
        has_more=page.has_more,
        next_cursor=page.next_cursor,
        active_count=page.active_count,
        maximum_severity=page.maximum_severity,
    )


@router.get("/alerts", response_model=AlertPage, responses=READ_RESPONSES)
def list_alerts(
    view: Literal["active", "history", "all"] = Query("active"),
    limit: int = Query(50, ge=1, le=500),
    cursor: str | None = Query(None),
    store: Store = Depends(usable_store),
) -> AlertPage:
    try:
        page = store.alerts.list_alerts(view=view, limit=limit, cursor=cursor)
    except ValueError as exc:
        raise bad_request(str(exc), field="cursor") from exc
    return _page_response(page, view)


@router.post(
    "/alerts/{alert_id}/ack",
    response_model=AlertPage,
    responses=ERROR_RESPONSES,
)
def acknowledge_alert(
    alert_id: int,
    request: Request,
    view: Literal["active", "history", "all"] = Query("active"),
    limit: int = Query(50, ge=1, le=500),
    store: Store = Depends(usable_store),
) -> AlertPage:
    store.alerts.acknowledge(
        alert_id,
        at=request.app.state.clock(),
    )
    return _page_response(store.alerts.list_alerts(view=view, limit=limit), view)


__all__ = ["router"]
