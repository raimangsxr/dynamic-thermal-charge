"""Reproducible, bounded projections of a persisted forecast snapshot."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.engine import Connection

from .mapping import from_utc
from .schema import forecast, forecast_hour


CONTEXT_HOURS = 12


def persisted_forecast_context(
    connection: Connection,
    *,
    installation_id: int,
    forecast_id: int | None,
    plan_start: datetime,
    plan_end: datetime,
) -> dict[str, Any]:
    """Project only the linked snapshot and its bounded context points.

    The caller supplies the plan's persisted foreign-key value.  This helper
    deliberately has no "latest forecast" fallback: a missing or deleted link
    is part of the historical result and is reported as unavailable.
    """
    requested_start = plan_start - timedelta(hours=CONTEXT_HOURS)
    requested_end = plan_end + timedelta(hours=CONTEXT_HOURS)
    base = {
        "requested_interval": {
            "start": requested_start.isoformat(),
            "end": requested_end.isoformat(),
        },
        "available_interval": None,
        "leading_context_incomplete": True,
        "trailing_context_incomplete": True,
        "hourly_points": [],
    }

    if forecast_id is None:
        return {
            **base,
            "available": False,
            "status": "unavailable",
            "reason": "no_linked_forecast",
            "forecast_id": None,
        }

    row = connection.execute(
        select(forecast).where(
            (forecast.c.installation_id == installation_id)
            & (forecast.c.id == forecast_id)
        )
    ).mappings().first()
    if row is None:
        return {
            **base,
            "available": False,
            "status": "unavailable",
            "reason": "linked_forecast_unavailable",
            "forecast_id": int(forecast_id),
        }

    points = connection.execute(
        select(forecast_hour)
        .where(
            (forecast_hour.c.forecast_id == forecast_id)
            & (forecast_hour.c.observed_at >= _stored_instant(requested_start))
            & (forecast_hour.c.observed_at <= _stored_instant(requested_end))
        )
        .order_by(forecast_hour.c.observed_at, forecast_hour.c.id)
    ).mappings().all()
    projected_points = [
        {
            "timestamp": from_utc(item["observed_at"]).isoformat(),
            "temperature_c": float(item["temperature_c"]),
            "interpolated": bool(item["interpolated"]),
        }
        for item in points
    ]
    if projected_points:
        actual_start = from_utc(points[0]["observed_at"])
        actual_end = from_utc(points[-1]["observed_at"])
        base.update(
            {
                "available_interval": {
                    "start": actual_start.isoformat(),
                    "end": actual_end.isoformat(),
                },
                "leading_context_incomplete": actual_start > requested_start,
                "trailing_context_incomplete": actual_end < requested_end,
                "hourly_points": projected_points,
            }
        )

    return {
        **base,
        "available": True,
        "status": "available",
        "forecast_id": int(row["id"]),
        "source": str(row["source"]),
        "municipality": row["municipality"],
        "forecast_date": row["forecast_date"].isoformat(),
        "retrieved_at": from_utc(row["retrieved_at"]).isoformat(),
        "average_temperature_c": float(row["average_temperature_c"]),
        "minimum_temperature_c": row["minimum_temperature_c"],
        "maximum_temperature_c": row["maximum_temperature_c"],
    }


def _stored_instant(value: datetime) -> datetime:
    """Convert an aware instant to the schema's naive UTC representation."""
    return value.astimezone(timezone.utc).replace(tzinfo=None)


__all__ = ["CONTEXT_HOURS", "persisted_forecast_context"]
