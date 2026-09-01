"""Persistence adapters for automatic planning state."""

from __future__ import annotations

from datetime import date, datetime, time, timezone
import json
from typing import Any, Mapping

from sqlalchemy import delete, insert, select, update
from sqlalchemy.engine import Engine

from ..charge_planning import AutomaticPlan, AutomaticPlanSlot, PlanningDeficit
from ..models import ChargeConstraint, ChargeTelemetry
from ..weather import ForecastCycleState, HourlyForecastPoint, future_forecast_points
from . import ConfigConflictError, ConfigValidationError, ForecastRef
from .engine import store_errors, transaction
from .mapping import from_utc, parse_time, parse_weekdays, to_utc
from .schema import (
    automatic_plan,
    automatic_plan_slot,
    charge_constraint,
    charge_planning_site,
    heater_telemetry,
    plan_audit,
)
from .url import StoreLocation


class SqlPlanningRepository:
    """Own planning-specific records while preserving the legacy repositories."""

    def __init__(
        self,
        configuration_engine: Engine,
        application_engine: Engine,
        installation_id: int,
        configuration_location: StoreLocation | None = None,
        application_location: StoreLocation | None = None,
    ) -> None:
        self._configuration = configuration_engine
        self._application = application_engine
        self._installation_id = installation_id
        self._configuration_location = configuration_location
        self._application_location = application_location

    def site(self) -> dict[str, int | float]:
        with store_errors(self._configuration_location):
            with self._configuration.connect() as connection:
                row = connection.execute(
                    select(charge_planning_site).where(
                        charge_planning_site.c.installation_id == self._installation_id
                    )
                ).mappings().first()
        if row is None:
            return {"revision": 1, "replan_minutes": 30, "forecast_horizon_hours": 48, "aemet_query_hour": 12, "contracted_power_w": 5200, "max_heating_power_w": 5200, "design_indoor_temperature_c": 21.0, "design_outdoor_temperature_c": 0.0, "feedback_horizon_hours": 6.0}
        integers = ("revision", "replan_minutes", "forecast_horizon_hours", "aemet_query_hour", "contracted_power_w", "max_heating_power_w")
        floats = ("design_indoor_temperature_c", "design_outdoor_temperature_c", "feedback_horizon_hours")
        return {**{key: int(row[key]) for key in integers}, **{key: float(row[key]) for key in floats}}

    def heater_charge_config(self) -> dict[str, dict[str, Any]]:
        from .schema import heater_charge_config
        with store_errors(self._configuration_location):
            with self._configuration.connect() as connection:
                rows = connection.execute(select(heater_charge_config).where(heater_charge_config.c.installation_id == self._installation_id)).mappings().all()
        return {str(row["heater_id"]): dict(row) for row in rows}

    def update_heater_charge_config(self, heater_id: str, values: Mapping[str, Any]) -> None:
        from .schema import heater_charge_config
        allowed = {key: values[key] for key in ("temperature_topic", "target_temperature_topic", "stored_charge_topic", "reserve_percent", "demand_factor") if key in values}
        if "reserve_percent" in allowed and float(allowed["reserve_percent"]) < 0:
            raise ConfigValidationError("reserve_percent must be non-negative", field="reserve_percent", heater_id=heater_id)
        if "demand_factor" in allowed and float(allowed["demand_factor"]) <= 0:
            raise ConfigValidationError("demand_factor must be positive", field="demand_factor", heater_id=heater_id)
        with transaction(self._configuration, self._configuration_location) as connection:
            existing = connection.execute(select(heater_charge_config).where((heater_charge_config.c.installation_id == self._installation_id) & (heater_charge_config.c.heater_id == heater_id))).first()
            if existing is None:
                connection.execute(insert(heater_charge_config).values(installation_id=self._installation_id, heater_id=heater_id, **allowed))
            else:
                connection.execute(update(heater_charge_config).where((heater_charge_config.c.installation_id == self._installation_id) & (heater_charge_config.c.heater_id == heater_id)).values(**allowed))

    def update_site(self, values: Mapping[str, int | float], expected_revision: int) -> int:
        current = self.site()
        if current["revision"] != expected_revision:
            raise ConfigConflictError("planning configuration changed; recalculate before saving")
        integer_fields = {"replan_minutes", "forecast_horizon_hours", "aemet_query_hour", "contracted_power_w", "max_heating_power_w"}
        float_fields = {"design_indoor_temperature_c", "design_outdoor_temperature_c", "feedback_horizon_hours"}
        allowed = {key: (int(value) if key in integer_fields else float(value)) for key, value in values.items() if key in integer_fields | float_fields}
        combined = {**current, **allowed}
        if not 0 < int(combined["forecast_horizon_hours"]) <= 48:
            raise ConfigValidationError("forecast_horizon_hours must be between 1 and 48", field="forecast_horizon_hours")
        if int(combined["contracted_power_w"]) <= 0 or int(combined["max_heating_power_w"]) <= 0:
            raise ConfigValidationError("power limits must be positive", field="contracted_power_w")
        if float(combined["design_indoor_temperature_c"]) <= float(combined["design_outdoor_temperature_c"]):
            raise ConfigValidationError("design indoor temperature must exceed design outdoor temperature", field="design_indoor_temperature_c")
        if float(combined["feedback_horizon_hours"]) <= 0:
            raise ConfigValidationError("feedback_horizon_hours must be positive", field="feedback_horizon_hours")
        next_revision = expected_revision + 1
        with transaction(self._configuration, self._configuration_location) as connection:
            existing = connection.execute(select(charge_planning_site).where(charge_planning_site.c.installation_id == self._installation_id)).first()
            if existing is None:
                connection.execute(insert(charge_planning_site).values(installation_id=self._installation_id, revision=next_revision, **allowed))
            else:
                changed = connection.execute(update(charge_planning_site).where((charge_planning_site.c.installation_id == self._installation_id) & (charge_planning_site.c.revision == expected_revision)).values(revision=next_revision, **allowed))
                if changed.rowcount != 1:
                    raise ConfigConflictError("planning configuration changed; recalculate before saving")
        return next_revision

    def telemetry(self) -> dict[str, ChargeTelemetry]:
        with store_errors(self._application_location):
            with self._application.connect() as connection:
                rows = connection.execute(select(heater_telemetry).where(heater_telemetry.c.installation_id == self._installation_id)).mappings().all()
        return {str(row["heater_id"]): ChargeTelemetry(
            heater_id=str(row["heater_id"]),
            temperature_c=_float_or_none(row["temperature_c"]),
            target_temperature_c=_float_or_none(row["target_temperature_c"]),
            stored_charge_percent=_float_or_none(row["stored_charge_percent"]),
            temperature_received_at=from_utc(row["temperature_received_at"]),
            target_received_at=from_utc(row["target_received_at"]),
            stored_charge_received_at=from_utc(row["stored_charge_received_at"]),
        ) for row in rows}

    def record_telemetry(self, heater_id: str, field: str, value: float, received_at: datetime) -> None:
        if field not in {"temperature_c", "target_temperature_c", "stored_charge_percent"}:
            raise ConfigValidationError(f"unknown telemetry field {field}", field=field, heater_id=heater_id)
        if received_at.tzinfo is None:
            raise ValueError("received_at requires a timezone")
        if field == "stored_charge_percent" and not 0 <= value <= 100:
            raise ConfigValidationError("stored charge must be between 0 and 100", field=field, heater_id=heater_id)
        timestamp = {
            "temperature_c": "temperature_received_at",
            "target_temperature_c": "target_received_at",
            "stored_charge_percent": "stored_charge_received_at",
        }[field]
        with transaction(self._application, self._application_location) as connection:
            row = connection.execute(select(heater_telemetry).where((heater_telemetry.c.installation_id == self._installation_id) & (heater_telemetry.c.heater_id == heater_id))).mappings().first()
            values: dict[str, Any] = {field: float(value), timestamp: to_utc(received_at), "invalid_field": None, "invalid_at": None}
            if row is None:
                connection.execute(insert(heater_telemetry).values(installation_id=self._installation_id, heater_id=heater_id, **values))
            else:
                connection.execute(update(heater_telemetry).where((heater_telemetry.c.installation_id == self._installation_id) & (heater_telemetry.c.heater_id == heater_id)).values(**values))

    def invalidate_telemetry(self, heater_id: str, field: str, at: datetime) -> None:
        with transaction(self._application, self._application_location) as connection:
            connection.execute(update(heater_telemetry).where((heater_telemetry.c.installation_id == self._installation_id) & (heater_telemetry.c.heater_id == heater_id)).values(invalid_field=field, invalid_at=to_utc(at)))

    def constraints(self, *, enabled_only: bool = True) -> tuple[ChargeConstraint, ...]:
        with store_errors(self._configuration_location):
            with self._configuration.connect() as connection:
                query = select(charge_constraint).where(charge_constraint.c.installation_id == self._installation_id)
                if enabled_only:
                    query = query.where(charge_constraint.c.enabled.is_(True))
                rows = connection.execute(query.order_by(charge_constraint.c.heater_id, charge_constraint.c.at_time, charge_constraint.c.id)).mappings().all()
        return tuple(ChargeConstraint(id=int(row["id"]), heater_id=str(row["heater_id"]), target_charge=float(row["target_charge"]), at=parse_time(str(row["at_time"]), "at_time"), weekdays=parse_weekdays(str(row["weekdays"]))) for row in rows)

    def replace_constraints(self, constraints: tuple[ChargeConstraint, ...], expected_revision: int) -> int:
        current = self.site()
        if current["revision"] != expected_revision:
            raise ConfigConflictError("constraints changed; recalculate before saving")
        now = datetime.now(timezone.utc)
        with transaction(self._configuration, self._configuration_location) as connection:
            connection.execute(delete(charge_constraint).where(charge_constraint.c.installation_id == self._installation_id))
            for constraint in constraints:
                connection.execute(insert(charge_constraint).values(installation_id=self._installation_id, heater_id=constraint.heater_id, target_charge=constraint.target_charge, at_time=constraint.at.strftime("%H:%M"), weekdays=",".join(str(day) for day in constraint.weekdays), enabled=True, created_at=to_utc(now), updated_at=to_utc(now)))
            row = connection.execute(select(charge_planning_site.c.revision).where(charge_planning_site.c.installation_id == self._installation_id)).first()
            if row is None:
                connection.execute(insert(charge_planning_site).values(installation_id=self._installation_id, revision=expected_revision + 1))
            else:
                changed = connection.execute(update(charge_planning_site).where((charge_planning_site.c.installation_id == self._installation_id) & (charge_planning_site.c.revision == expected_revision)).values(revision=expected_revision + 1))
                if changed.rowcount != 1:
                    raise ConfigConflictError("constraints changed; recalculate before saving")
        return expected_revision + 1

    def save_plan(self, plan: AutomaticPlan, *, configuration_revision: int, constraints_revision: int, reason: str, active: bool) -> int:
        now = datetime.now(timezone.utc)
        active = active and plan.status != "INVALID"
        stored_status = {"FEASIBLE": "feasible", "DEGRADED": "deficit", "INVALID": "preview"}.get(plan.status, plan.status)
        violations = [_json_ready(item.__dict__) for item in plan.violations]
        inputs = {
            "input_token": plan.input_token,
            "generated_at": None if plan.generated_at is None else plan.generated_at.isoformat(),
            "demand": [_json_ready(item.__dict__) for item in plan.demand],
            "explanations": [_json_ready(item.__dict__) for item in plan.explanations],
        }
        with transaction(self._application, self._application_location) as connection:
            if active:
                connection.execute(update(automatic_plan).where((automatic_plan.c.installation_id == self._installation_id) & automatic_plan.c.active.is_(True)).values(active=False))
            plan_id = int(connection.execute(insert(automatic_plan).values(installation_id=self._installation_id, configuration_revision=configuration_revision, constraints_revision=constraints_revision, horizon_start=to_utc(plan.horizon_start), horizon_end=to_utc(plan.horizon_end), slot_minutes=plan.slot_minutes, status=stored_status, reason=reason, input_token=plan.input_token, score_json=json.dumps(plan.score), deficits_json=json.dumps(violations), inputs_json=json.dumps(inputs), active=active, created_at=to_utc(now))).inserted_primary_key[0])
            for slot in plan.slots:
                connection.execute(insert(automatic_plan_slot).values(plan_id=plan_id, slot_start=to_utc(slot.start), slot_end=to_utc(slot.end), heater_ids_json=json.dumps(slot.heater_ids), power_w=slot.power_w, stored_charge_json=json.dumps(slot.stored_charge_percent), required_charge_json=json.dumps(slot.required_charge_percent), outdoor_temperature_c=slot.outdoor_temperature_c, initial_soc_json=json.dumps(slot.initial_soc_percent or {}), demand_json=json.dumps(slot.demand_kwh or {}), heater_power_json=json.dumps(slot.heater_power_w or {})))
            connection.execute(insert(plan_audit).values(installation_id=self._installation_id, plan_id=plan_id, event="activated" if active else "preview", reason=reason, details_json=json.dumps({"status": plan.status, "violations": violations}), occurred_at=to_utc(now)))
        return plan_id

    def active_plan(self) -> dict[str, Any] | None:
        with store_errors(self._application_location):
            with self._application.connect() as connection:
                row = connection.execute(select(automatic_plan).where((automatic_plan.c.installation_id == self._installation_id) & automatic_plan.c.active.is_(True)).order_by(automatic_plan.c.created_at.desc())).mappings().first()
                if row is None:
                    return None
                slots = connection.execute(select(automatic_plan_slot).where(automatic_plan_slot.c.plan_id == row["id"]).order_by(automatic_plan_slot.c.slot_start)).mappings().all()
        inputs = json.loads(row["inputs_json"])
        status = {"feasible": "FEASIBLE", "deficit": "DEGRADED", "best_effort": "DEGRADED", "preview": "INVALID"}.get(row["status"], row["status"])
        return {"id": int(row["id"]), "horizon_start": from_utc(row["horizon_start"]), "horizon_end": from_utc(row["horizon_end"]), "slot_minutes": int(row["slot_minutes"]), "status": status, "reason": row["reason"], "input_token": row["input_token"], "created_at": from_utc(row["created_at"]), "deficits": json.loads(row["deficits_json"]), "violations": json.loads(row["deficits_json"]), "demand": inputs.get("demand", []), "explanations": inputs.get("explanations", []), "slots": [{"start": from_utc(item["slot_start"]), "end": from_utc(item["slot_end"]), "heater_ids": json.loads(item["heater_ids_json"]), "power_w": int(item["power_w"]), "stored_charge_percent": json.loads(item["stored_charge_json"]), "required_charge_percent": json.loads(item["required_charge_json"]), "initial_soc_percent": json.loads(item["initial_soc_json"]), "demand_kwh": json.loads(item["demand_json"]), "heater_power_w": json.loads(item["heater_power_json"]), "outdoor_temperature_c": item["outdoor_temperature_c"]} for item in slots]}

    def latest_forecast(
        self, at: datetime | None = None
    ) -> tuple[HourlyForecastPoint, ...]:
        from .schema import forecast, forecast_hour

        with store_errors(self._application_location):
            with self._application.connect() as connection:
                forecast_id = connection.execute(select(forecast.c.id).where(forecast.c.installation_id == self._installation_id).order_by(forecast.c.retrieved_at.desc()).limit(1)).scalar()
                if forecast_id is None:
                    return ()
                rows = connection.execute(select(forecast_hour).where(forecast_hour.c.forecast_id == forecast_id).order_by(forecast_hour.c.observed_at)).mappings().all()
        points = tuple(
            HourlyForecastPoint(
                from_utc(row["observed_at"]),
                float(row["temperature_c"]),
                bool(row["interpolated"]),
            )
            for row in rows
        )
        if at is None:
            return points
        return future_forecast_points(points, at)

    def latest_forecast_automatic_eligible(self) -> bool:
        from .schema import forecast
        with store_errors(self._application_location):
            with self._application.connect() as connection:
                source = connection.execute(select(forecast.c.source).where(forecast.c.installation_id == self._installation_id).order_by(forecast.c.retrieved_at.desc()).limit(1)).scalar()
        return source == "aemet"

    def forecast_cycle(self, local_date: date, scheduled_at: datetime) -> ForecastCycleState:
        from .schema import forecast_cycle
        with transaction(self._application, self._application_location) as connection:
            row = connection.execute(select(forecast_cycle).where((forecast_cycle.c.installation_id == self._installation_id) & (forecast_cycle.c.local_date == local_date))).mappings().first()
            if row is None:
                connection.execute(insert(forecast_cycle).values(installation_id=self._installation_id, local_date=local_date, scheduled_at=to_utc(scheduled_at), attempt=0, next_retry_at=None, last_error=None, last_forecast_id=None, stale=False, last_attempt_at=None, last_result=None, next_run_at=None, updated_at=to_utc(datetime.now(timezone.utc))))
                return ForecastCycleState(local_date, scheduled_at, 0, None, None, False)
        attempt = int(row["attempt"])
        return ForecastCycleState(
            local_date,
            from_utc(row["scheduled_at"]),
            attempt,
            from_utc(row["next_retry_at"]),
            row["last_error"],
            bool(row["stale"]),
            attempt >= 6,
            from_utc(row["last_attempt_at"]),
            row["last_result"],
            from_utc(row["next_run_at"]),
            None if row["last_forecast_id"] is None else int(row["last_forecast_id"]),
        )

    def save_forecast_cycle(
        self, state: ForecastCycleState, forecast_ref: ForecastRef | None = None
    ) -> None:
        from .schema import forecast_cycle
        with transaction(self._application, self._application_location) as connection:
            values = {
                "scheduled_at": to_utc(state.scheduled_at),
                "attempt": 6 if state.completed else state.attempt,
                "next_retry_at": None if state.next_retry_at is None else to_utc(state.next_retry_at),
                "last_error": state.last_error,
                "stale": state.stale,
                "last_attempt_at": None if state.last_attempt_at is None else to_utc(state.last_attempt_at),
                "last_result": state.last_result,
                "next_run_at": None if state.next_run_at is None else to_utc(state.next_run_at),
                "updated_at": to_utc(datetime.now(timezone.utc)),
            }
            if forecast_ref is not None:
                values["last_forecast_id"] = forecast_ref.id
            connection.execute(
                update(forecast_cycle)
                .where(
                    (forecast_cycle.c.installation_id == self._installation_id)
                    & (forecast_cycle.c.local_date == state.local_date)
                )
                .values(**values)
            )

    def latest_forecast_cycle(self) -> dict[str, Any] | None:
        from .schema import forecast_cycle
        with store_errors(self._application_location):
            with self._application.connect() as connection:
                row = connection.execute(
                    select(forecast_cycle)
                    .where(forecast_cycle.c.installation_id == self._installation_id)
                    .order_by(forecast_cycle.c.updated_at.desc(), forecast_cycle.c.id.desc())
                    .limit(1)
                ).mappings().first()
        if row is None:
            return None
        return {
            "local_date": row["local_date"],
            "scheduled_at": from_utc(row["scheduled_at"]),
            "last_attempt_at": from_utc(row["last_attempt_at"]),
            "last_result": row["last_result"],
            "last_error": row["last_error"],
            "next_run_at": from_utc(row["next_run_at"]),
            "stale": bool(row["stale"]),
            "last_forecast_id": None if row["last_forecast_id"] is None else int(row["last_forecast_id"]),
        }

    def forecast_cycle_status(self) -> dict[str, Any] | None:
        """Return only safe, operator-facing retrieval metadata."""
        cycle = self.latest_forecast_cycle()
        if cycle is None:
            return None
        return {
            "forecast_status": cycle["last_result"],
            "forecast_last_attempt_at": cycle["last_attempt_at"],
            "forecast_last_error": cycle["last_error"] if cycle["last_result"] == "error" else None,
            "forecast_next_run_at": cycle["next_run_at"],
        }

    def audit(self, since: datetime | None = None, until: datetime | None = None, limit: int = 100) -> list[dict[str, Any]]:
        with store_errors(self._application_location):
            with self._application.connect() as connection:
                query = select(plan_audit).where(plan_audit.c.installation_id == self._installation_id)
                if since is not None:
                    query = query.where(plan_audit.c.occurred_at >= to_utc(since))
                if until is not None:
                    query = query.where(plan_audit.c.occurred_at <= to_utc(until))
                rows = connection.execute(query.order_by(plan_audit.c.occurred_at.desc(), plan_audit.c.id.desc()).limit(max(1, min(limit, 500)))).mappings().all()
        return [{"id": int(row["id"]), "plan_id": row["plan_id"], "event": str(row["event"]), "reason": str(row["reason"]), "details": json.loads(row["details_json"]), "occurred_at": from_utc(row["occurred_at"])} for row in rows]


def _float_or_none(value: Any) -> float | None:
    return None if value is None else float(value)


def _json_ready(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, tuple):
        return [_json_ready(item) for item in value]
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_ready(item) for key, item in value.items()}
    return value


__all__ = ["SqlPlanningRepository"]
