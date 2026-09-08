"""Persistence adapters for automatic planning state."""

from __future__ import annotations

from datetime import date, datetime, timezone
import json
from typing import Any, Mapping
from uuid import uuid4

from sqlalchemy import delete, insert, select, update
from sqlalchemy.engine import Engine

from ..charge_planning import AutomaticPlan
from ..models import ChargeTelemetry, TemperatureTarget, validate_temperature_targets
from ..weather import ForecastCycleState, HourlyForecastPoint, future_forecast_points
from . import ConfigConflictError, ConfigValidationError, ForecastRef
from .engine import store_errors, transaction
from .mapping import (
    format_temperature_target_end_time,
    from_utc,
    parse_temperature_target_end_time,
    parse_time,
    parse_weekdays,
    to_utc,
)
from .schema import (
    automatic_plan,
    automatic_plan_slot,
    charge_planning_site,
    heater_telemetry,
    plan_audit,
    preview_job,
    preview_job_step,
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
            return {
                "revision": 1,
                "replan_minutes": 30,
                "planning_window_hours": 12,
                "forecast_horizon_hours": 24,
                "solver_time_limit_seconds": 120,
                "aemet_query_hour": 12,
                "contracted_power_w": 5200,
                "max_heating_power_w": 5200,
                "base_load_w": 0,
                "mqtt_simulation_enabled": False,
                "mqtt_simulation_initial_temperature_c": 45.0,
                "mqtt_simulation_publish_seconds": 30.0,
                "mqtt_simulation_topic_prefix": "dtc/sim",
                "mqtt_simulation_thermal_loss_c_per_hour": 2.0,
            }
        integers = (
            "revision",
            "replan_minutes",
            "planning_window_hours",
            "forecast_horizon_hours",
            "solver_time_limit_seconds",
            "aemet_query_hour",
            "contracted_power_w",
            "max_heating_power_w",
            "base_load_w",
        )
        floats = (
            "mqtt_simulation_initial_temperature_c",
            "mqtt_simulation_publish_seconds",
            "mqtt_simulation_thermal_loss_c_per_hour",
        )
        booleans = ("mqtt_simulation_enabled",)
        strings = ("mqtt_simulation_topic_prefix",)
        values = {
            **{key: int(row[key]) for key in integers},
            **{key: float(row[key]) for key in floats},
            **{key: bool(row[key]) for key in booleans},
            **{key: str(row[key]) for key in strings},
        }
        return values

    def heater_charge_config(self) -> dict[str, dict[str, Any]]:
        from .schema import heater_charge_config
        with store_errors(self._configuration_location):
            with self._configuration.connect() as connection:
                rows = connection.execute(select(heater_charge_config).where(heater_charge_config.c.installation_id == self._installation_id)).mappings().all()
        return {str(row["heater_id"]): dict(row) for row in rows}

    def update_heater_charge_config(self, heater_id: str, values: Mapping[str, Any]) -> None:
        from .schema import heater_charge_config
        allowed = {
            key: values[key]
            for key in (
                "stored_soc_topic",
                "damper_topic",
            )
            if key in values
        }
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
        integer_fields = {
            "replan_minutes",
            "planning_window_hours",
            "forecast_horizon_hours",
            "solver_time_limit_seconds",
            "aemet_query_hour",
            "contracted_power_w",
            "max_heating_power_w",
            "base_load_w",
        }
        float_fields = {
            "mqtt_simulation_initial_temperature_c",
            "mqtt_simulation_publish_seconds",
            "mqtt_simulation_thermal_loss_c_per_hour",
        }
        boolean_fields = {"mqtt_simulation_enabled"}
        string_fields = {"mqtt_simulation_topic_prefix"}
        allowed = {}
        for key, value in values.items():
            if key in integer_fields:
                if key in {"planning_window_hours", "forecast_horizon_hours", "solver_time_limit_seconds"} and (
                    isinstance(value, bool) or int(value) != float(value)
                ):
                    raise ConfigValidationError(f"{key} must be an integer", field=key)
                allowed[key] = int(value)
            elif key in float_fields:
                allowed[key] = float(value)
            elif key in boolean_fields:
                allowed[key] = bool(value)
            elif key in string_fields:
                allowed[key] = str(value).strip()
        combined = {**current, **allowed}
        window_hours = int(combined["planning_window_hours"])
        horizon_hours = int(combined["forecast_horizon_hours"])
        if not 1 <= window_hours <= 48:
            raise ConfigValidationError("planning_window_hours must be between 1 and 48", field="planning_window_hours")
        if not 1 <= horizon_hours <= 48:
            raise ConfigValidationError("forecast_horizon_hours must be between 1 and 48", field="forecast_horizon_hours")
        if window_hours > horizon_hours:
            raise ConfigValidationError("planning_window_hours must not exceed forecast_horizon_hours", field="planning_window_hours")
        if int(combined["solver_time_limit_seconds"]) <= 0:
            raise ConfigValidationError("solver_time_limit_seconds must be positive", field="solver_time_limit_seconds")
        if int(combined["contracted_power_w"]) <= 0 or int(combined["max_heating_power_w"]) <= 0:
            raise ConfigValidationError("power limits must be positive", field="contracted_power_w")
        if int(combined["base_load_w"]) < 0:
            raise ConfigValidationError("base_load_w must be non-negative", field="base_load_w")
        if not -50 <= float(combined["mqtt_simulation_initial_temperature_c"]) <= 80:
            raise ConfigValidationError(
                "mqtt_simulation_initial_temperature_c must be between -50 and 80",
                field="mqtt_simulation_initial_temperature_c",
            )
        if float(combined["mqtt_simulation_publish_seconds"]) <= 0:
            raise ConfigValidationError(
                "mqtt_simulation_publish_seconds must be positive",
                field="mqtt_simulation_publish_seconds",
            )
        if not str(combined["mqtt_simulation_topic_prefix"]).strip():
            raise ConfigValidationError(
                "mqtt_simulation_topic_prefix cannot be empty",
                field="mqtt_simulation_topic_prefix",
            )
        if float(combined["mqtt_simulation_thermal_loss_c_per_hour"]) < 0:
            raise ConfigValidationError(
                "mqtt_simulation_thermal_loss_c_per_hour must be non-negative",
                field="mqtt_simulation_thermal_loss_c_per_hour",
            )
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
            indoor_temperature_c=_float_or_none(row["temperature_c"]),
            stored_soc_percent=_float_or_none(row["stored_soc_percent"]),
            indoor_received_at=from_utc(row["temperature_received_at"]),
            stored_soc_received_at=from_utc(row["stored_soc_received_at"]),
            damper_position_percent=_float_or_none(row.get("damper_position_percent")),
            damper_received_at=from_utc(row.get("damper_received_at")),
        ) for row in rows}

    def record_telemetry(self, heater_id: str, field: str, value: float, received_at: datetime) -> None:
        aliases = {
            "indoor_temperature_c": "temperature_c",
            "stored_soc_percent": "stored_soc_percent",
            "damper_position_percent": "damper_position_percent",
        }
        field = aliases.get(field, field)
        if field not in {"temperature_c", "stored_soc_percent", "damper_position_percent"}:
            raise ConfigValidationError(f"unknown telemetry field {field}", field=field, heater_id=heater_id)
        if received_at.tzinfo is None:
            raise ValueError("received_at requires a timezone")
        if field == "stored_soc_percent" and not 0 <= value <= 100:
            raise ConfigValidationError("stored SOC must be between 0 and 100", field=field, heater_id=heater_id)
        if field == "damper_position_percent" and not 0 <= value <= 100:
            raise ConfigValidationError("damper position must be between 0 and 100", field=field, heater_id=heater_id)
        timestamp = {
            "temperature_c": "temperature_received_at",
            "stored_soc_percent": "stored_soc_received_at",
            "damper_position_percent": "damper_received_at",
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

    def temperature_targets(self, *, enabled_only: bool = True) -> dict[str, tuple]:
        """Read the weekly target schedule used by room-energy planning."""
        from .schema import temperature_target
        with store_errors(self._configuration_location):
            with self._configuration.connect() as connection:
                query = select(temperature_target).where(
                    temperature_target.c.installation_id == self._installation_id
                )
                if enabled_only:
                    query = query.where(temperature_target.c.enabled.is_(True))
                rows = connection.execute(
                    query.order_by(
                        temperature_target.c.heater_id,
                        temperature_target.c.start_time,
                        temperature_target.c.end_time,
                        temperature_target.c.id,
                    )
                ).mappings().all()
        from ..models import TemperatureTarget
        result: dict[str, list[TemperatureTarget]] = {}
        for row in rows:
            result.setdefault(str(row["heater_id"]), []).append(
                TemperatureTarget(
                    target_temperature_c=float(row["target_temperature_c"]),
                    start_time=parse_time(str(row["start_time"]), "start_time"),
                    end_time=parse_temperature_target_end_time(
                        str(row["end_time"]), "end_time"
                    ),
                    weekdays=parse_weekdays(str(row["weekdays"])),
                    id=int(row["id"]),
                    enabled=bool(row["enabled"]),
                )
            )
        return {heater_id: tuple(items) for heater_id, items in result.items()}

    def replace_temperature_targets(
        self,
        heater_id: str,
        targets: tuple,
        expected_revision: int,
    ) -> int:
        """Persist a heater's weekly targets with an optimistic lock."""
        from .schema import temperature_target
        try:
            validate_temperature_targets(tuple(targets))
        except ValueError as exc:
            raise ConfigValidationError(
                str(exc), field="temperature_targets", heater_id=heater_id
            ) from exc
        current = self.site()
        if current["revision"] != expected_revision:
            raise ConfigConflictError("planning configuration changed; recalculate before saving")
        now = datetime.now(timezone.utc)
        with transaction(self._configuration, self._configuration_location) as connection:
            connection.execute(delete(temperature_target).where(
                (temperature_target.c.installation_id == self._installation_id)
                & (temperature_target.c.heater_id == heater_id)
            ))
            for target in targets:
                connection.execute(insert(temperature_target).values(
                    installation_id=self._installation_id,
                    heater_id=heater_id,
                    target_temperature_c=target.target_temperature_c,
                    start_time=target.start_time.strftime("%H:%M"),
                    end_time=format_temperature_target_end_time(
                        target.start_time, target.end_time
                    ),
                    weekdays=",".join(str(day) for day in target.weekdays),
                    enabled=target.enabled,
                    created_at=to_utc(now),
                    updated_at=to_utc(now),
                ))
            changed = connection.execute(update(charge_planning_site).where(
                (charge_planning_site.c.installation_id == self._installation_id)
                & (charge_planning_site.c.revision == expected_revision)
            ).values(revision=expected_revision + 1))
            if changed.rowcount != 1:
                existing = connection.execute(select(charge_planning_site.c.installation_id).where(
                    charge_planning_site.c.installation_id == self._installation_id
                )).first()
                if existing is not None:
                    raise ConfigConflictError("planning configuration changed; recalculate before saving")
                site_values = {
                    key: current[key]
                    for key in charge_planning_site.c.keys()
                    if key in current and key != "revision"
                }
                connection.execute(insert(charge_planning_site).values(
                    installation_id=self._installation_id,
                    revision=expected_revision + 1,
                    **site_values,
                ))
        return expected_revision + 1

    def replace_all_temperature_targets(
        self,
        targets_by_heater: Mapping[str, tuple],
        expected_revision: int,
    ) -> int:
        """Replace the submitted weekly schedules in one revisioned write."""
        from .schema import temperature_target

        normalized_targets: dict[str, tuple[TemperatureTarget, ...]] = {}
        for heater_id, targets in targets_by_heater.items():
            normalized = tuple(targets)
            try:
                validate_temperature_targets(normalized)
            except ValueError as exc:
                raise ConfigValidationError(
                    str(exc), field="temperature_targets", heater_id=heater_id
                ) from exc
            normalized_targets[heater_id] = normalized

        current = self.site()
        if current["revision"] != expected_revision:
            raise ConfigConflictError("planning configuration changed; recalculate before saving")
        now = datetime.now(timezone.utc)
        with transaction(self._configuration, self._configuration_location) as connection:
            for heater_id, targets in normalized_targets.items():
                connection.execute(delete(temperature_target).where(
                    (temperature_target.c.installation_id == self._installation_id)
                    & (temperature_target.c.heater_id == heater_id)
                ))
                for target in targets:
                    connection.execute(insert(temperature_target).values(
                    installation_id=self._installation_id,
                    heater_id=heater_id,
                    target_temperature_c=target.target_temperature_c,
                    start_time=target.start_time.strftime("%H:%M"),
                    end_time=format_temperature_target_end_time(
                        target.start_time, target.end_time
                    ),
                        weekdays=",".join(str(day) for day in target.weekdays),
                        enabled=target.enabled,
                        created_at=to_utc(now),
                        updated_at=to_utc(now),
                    ))
            changed = connection.execute(update(charge_planning_site).where(
                (charge_planning_site.c.installation_id == self._installation_id)
                & (charge_planning_site.c.revision == expected_revision)
            ).values(revision=expected_revision + 1))
            if changed.rowcount != 1:
                existing = connection.execute(select(charge_planning_site.c.installation_id).where(
                    charge_planning_site.c.installation_id == self._installation_id
                )).first()
                if existing is not None:
                    raise ConfigConflictError("planning configuration changed; recalculate before saving")
                site_values = {
                    key: current[key]
                    for key in charge_planning_site.c.keys()
                    if key in current and key != "revision"
                }
                connection.execute(insert(charge_planning_site).values(
                    installation_id=self._installation_id,
                    revision=expected_revision + 1,
                    **site_values,
                ))
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
            if active or plan.status == "INVALID":
                connection.execute(update(automatic_plan).where((automatic_plan.c.installation_id == self._installation_id) & automatic_plan.c.active.is_(True)).values(active=False))
            plan_id = int(connection.execute(insert(automatic_plan).values(installation_id=self._installation_id, configuration_revision=configuration_revision, constraints_revision=constraints_revision, horizon_start=to_utc(plan.horizon_start), horizon_end=to_utc(plan.horizon_end), slot_minutes=plan.slot_minutes, status=stored_status, reason=reason, input_token=plan.input_token, score_json=json.dumps(plan.score), deficits_json=json.dumps(violations), inputs_json=json.dumps(inputs), active=active, created_at=to_utc(now))).inserted_primary_key[0])
            for slot in plan.slots:
                connection.execute(insert(automatic_plan_slot).values(
                    plan_id=plan_id,
                    slot_start=to_utc(slot.start),
                    slot_end=to_utc(slot.end),
                    heater_ids_json=json.dumps(slot.heater_ids),
                    power_w=slot.power_w,
                    stored_charge_json=json.dumps(slot.stored_charge_percent),
                    required_charge_json=json.dumps(slot.required_charge_percent),
                    outdoor_temperature_c=slot.outdoor_temperature_c,
                    initial_soc_json=json.dumps(slot.initial_soc_percent or {}),
                    demand_json=json.dumps(slot.demand_kwh or {}),
                    heater_power_json=json.dumps(slot.heater_power_w or {}),
                    stored_energy_json=json.dumps(slot.stored_energy_kwh or {}),
                    indoor_temperature_json=json.dumps(slot.indoor_temperature_c or {}),
                    target_temperature_json=json.dumps(slot.target_temperature_c or {}),
                    heat_delivered_json=json.dumps(slot.heat_delivered_kwh or {}),
                    thermal_loss_json=json.dumps(slot.thermal_loss_kwh or {}),
                    temperature_shortfall_json=json.dumps(slot.temperature_shortfall_c or {}),
                    charge_energy_json=json.dumps(slot.charge_energy_kwh or {}),
                ))
            connection.execute(insert(plan_audit).values(installation_id=self._installation_id, plan_id=plan_id, event="activated" if active else "preview", reason=reason, details_json=json.dumps({"status": plan.status, "violations": violations}), occurred_at=to_utc(now)))
        return plan_id

    def create_preview_job(
        self,
        constraints: list[dict[str, Any]],
        *,
        temperature_targets: list[dict[str, Any]] | None = None,
        configuration_revision: int,
        constraints_revision: int,
        requested_at: datetime,
        steps: tuple[str, ...],
    ) -> str:
        job_id = str(uuid4())
        with transaction(self._application, self._application_location) as connection:
            connection.execute(insert(preview_job).values(
                id=job_id,
                installation_id=self._installation_id,
                configuration_revision=configuration_revision,
                constraints_revision=constraints_revision,
                # Percentage constraints were removed in 0014.  Keep the
                # positional argument temporarily for callers upgrading from
                # the old repository API, but never persist it or let it enter
                # the cache key.
                request_json=json.dumps({"temperature_targets": _json_ready(temperature_targets or [])}, separators=(",", ":")),
                status="queued",
                cancellation_requested=False,
                requested_at=to_utc(requested_at),
            ))
            connection.execute(insert(preview_job_step), [
                {"job_id": job_id, "position": position, "name": name, "status": "pending"}
                for position, name in enumerate(steps)
            ])
        return job_id

    def preview_job(self, job_id: str) -> dict[str, Any] | None:
        with store_errors(self._application_location):
            with self._application.connect() as connection:
                row = connection.execute(select(preview_job).where(
                    (preview_job.c.id == job_id) &
                    (preview_job.c.installation_id == self._installation_id)
                )).mappings().first()
                if row is None:
                    return None
                steps = connection.execute(select(preview_job_step).where(
                    preview_job_step.c.job_id == job_id
                ).order_by(preview_job_step.c.position)).mappings().all()
        return {
            "id": str(row["id"]),
            "configuration_revision": int(row["configuration_revision"]),
            "constraints_revision": int(row["constraints_revision"]),
            "request": json.loads(row["request_json"]),
            "status": str(row["status"]),
            "cancellation_requested": bool(row["cancellation_requested"]),
            "requested_at": from_utc(row["requested_at"]),
            "started_at": from_utc(row["started_at"]),
            "finished_at": from_utc(row["finished_at"]),
            "result": None if row["result_json"] is None else json.loads(row["result_json"]),
            "error_code": row["error_code"],
            "error_detail": row["error_detail"],
            "steps": [{
                "name": str(item["name"]), "status": str(item["status"]),
                "started_at": from_utc(item["started_at"]),
                "finished_at": from_utc(item["finished_at"]), "detail": item["detail"],
            } for item in steps],
        }

    def latest_preview_job(self) -> dict[str, Any] | None:
        with store_errors(self._application_location):
            with self._application.connect() as connection:
                job_id = connection.execute(select(preview_job.c.id).where(
                    preview_job.c.installation_id == self._installation_id
                ).order_by(preview_job.c.requested_at.desc()).limit(1)).scalar()
        return None if job_id is None else self.preview_job(str(job_id))

    def latest_completed_preview_job(
        self,
        *,
        configuration_revision: int,
        constraints_revision: int,
        constraints: list[dict[str, Any]] | None = None,
        temperature_targets: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any] | None:
        """Return the newest durable preview matching the activation inputs."""
        with store_errors(self._application_location):
            with self._application.connect() as connection:
                job_ids = connection.execute(select(preview_job.c.id).where(
                    (preview_job.c.installation_id == self._installation_id)
                    & (preview_job.c.configuration_revision == configuration_revision)
                    & (preview_job.c.constraints_revision == constraints_revision)
                    & (preview_job.c.status == "completed")
                ).order_by(preview_job.c.requested_at.desc())).scalars().all()
        expected_targets = temperature_targets or []
        for job_id in job_ids:
            job = self.preview_job(str(job_id))
            if job is not None and job["request"].get("temperature_targets", []) == expected_targets:
                return job
        return None

    def mark_interrupted_preview_jobs(self) -> None:
        now = datetime.now(timezone.utc)
        with transaction(self._application, self._application_location) as connection:
            rows = connection.execute(select(preview_job.c.id).where(
                (preview_job.c.installation_id == self._installation_id) &
                preview_job.c.status.in_(("queued", "running", "cancelling"))
            )).scalars().all()
            if not rows:
                return
            connection.execute(update(preview_job).where(preview_job.c.id.in_(rows)).values(
                status="interrupted", finished_at=to_utc(now), error_code="interrupted",
                error_detail="El servicio se reinició mientras se calculaba la vista previa.",
            ))
            connection.execute(update(preview_job_step).where(
                preview_job_step.c.job_id.in_(rows) &
                preview_job_step.c.status.in_(("pending", "running"))
            ).values(status="error", finished_at=to_utc(now), detail="interrupted"))

    def request_preview_cancel(self, job_id: str) -> dict[str, Any] | None:
        with transaction(self._application, self._application_location) as connection:
            row = connection.execute(select(preview_job).where(
                (preview_job.c.id == job_id) &
                (preview_job.c.installation_id == self._installation_id)
            )).mappings().first()
            if row is None:
                return None
            if row["status"] in ("queued", "running"):
                connection.execute(update(preview_job).where(preview_job.c.id == job_id).values(
                    status="cancelling", cancellation_requested=True
                ))
            elif row["status"] == "cancelling":
                connection.execute(update(preview_job).where(preview_job.c.id == job_id).values(cancellation_requested=True))
        return self.preview_job(job_id)

    def preview_job_cancel_requested(self, job_id: str) -> bool:
        with store_errors(self._application_location):
            with self._application.connect() as connection:
                value = connection.execute(select(preview_job.c.cancellation_requested).where(
                    (preview_job.c.id == job_id) &
                    (preview_job.c.installation_id == self._installation_id)
                )).scalar()
        return bool(value)

    def update_preview_step(self, job_id: str, name: str, status: str, detail: str | None = None) -> None:
        now = datetime.now(timezone.utc)
        with transaction(self._application, self._application_location) as connection:
            if status == "running":
                connection.execute(update(preview_job_step).where(
                    (preview_job_step.c.job_id == job_id) &
                    (preview_job_step.c.status == "running")
                ).values(status="completed", finished_at=to_utc(now)))
                connection.execute(update(preview_job_step).where(
                    (preview_job_step.c.job_id == job_id) &
                    (preview_job_step.c.name == name)
                ).values(status="running", started_at=to_utc(now), detail=detail))
            else:
                connection.execute(update(preview_job_step).where(
                    (preview_job_step.c.job_id == job_id) &
                    (preview_job_step.c.name == name)
                ).values(status=status, finished_at=to_utc(now), detail=detail))

    def finish_preview_job(
        self,
        job_id: str,
        *,
        status: str,
        result: dict[str, Any] | None = None,
        error_code: str | None = None,
        error_detail: str | None = None,
    ) -> None:
        now = datetime.now(timezone.utc)
        with transaction(self._application, self._application_location) as connection:
            connection.execute(update(preview_job).where(
                (preview_job.c.id == job_id) &
                (preview_job.c.installation_id == self._installation_id)
            ).values(
                status=status, finished_at=to_utc(now),
                result_json=None if result is None else json.dumps(_json_ready(result), separators=(",", ":")),
                error_code=error_code, error_detail=error_detail,
            ))
            step_status = "cancelled" if status == "cancelled" else "error" if status in ("error", "interrupted") else "completed"
            connection.execute(update(preview_job_step).where(
                (preview_job_step.c.job_id == job_id) &
                preview_job_step.c.status.in_(("running", "pending"))
            ).values(status=step_status, finished_at=to_utc(now), detail=error_detail))

    def start_preview_job(self, job_id: str) -> bool:
        now = datetime.now(timezone.utc)
        with transaction(self._application, self._application_location) as connection:
            changed = connection.execute(update(preview_job).where(
                (preview_job.c.id == job_id) &
                (preview_job.c.installation_id == self._installation_id) &
                preview_job.c.status.in_(("queued", "cancelling"))
            ).values(status="running", started_at=to_utc(now))).rowcount
        return changed == 1

    def active_plan(self) -> dict[str, Any] | None:
        with store_errors(self._application_location):
            with self._application.connect() as connection:
                row = connection.execute(select(automatic_plan).where((automatic_plan.c.installation_id == self._installation_id) & automatic_plan.c.active.is_(True)).order_by(automatic_plan.c.created_at.desc())).mappings().first()
                if row is None:
                    return None
                slots = connection.execute(select(automatic_plan_slot).where(automatic_plan_slot.c.plan_id == row["id"]).order_by(automatic_plan_slot.c.slot_start)).mappings().all()
        inputs = json.loads(row["inputs_json"])
        status = {"feasible": "FEASIBLE", "deficit": "DEGRADED", "best_effort": "DEGRADED", "preview": "INVALID"}.get(row["status"], row["status"])
        return {"id": int(row["id"]), "horizon_start": from_utc(row["horizon_start"]), "horizon_end": from_utc(row["horizon_end"]), "slot_minutes": int(row["slot_minutes"]), "status": status, "reason": row["reason"], "input_token": row["input_token"], "created_at": from_utc(row["created_at"]), "deficits": json.loads(row["deficits_json"]), "violations": json.loads(row["deficits_json"]), "demand": inputs.get("demand", []), "explanations": inputs.get("explanations", []), "slots": [{"start": from_utc(item["slot_start"]), "end": from_utc(item["slot_end"]), "heater_ids": json.loads(item["heater_ids_json"]), "power_w": int(item["power_w"]), "stored_charge_percent": json.loads(item["stored_charge_json"]), "required_charge_percent": json.loads(item["required_charge_json"]), "initial_soc_percent": json.loads(item["initial_soc_json"]), "demand_kwh": json.loads(item["demand_json"]), "heater_power_w": json.loads(item["heater_power_json"]), "outdoor_temperature_c": item["outdoor_temperature_c"], "stored_energy_kwh": json.loads(item.get("stored_energy_json", "{}")), "indoor_temperature_c": json.loads(item.get("indoor_temperature_json", "{}")), "target_temperature_c": json.loads(item.get("target_temperature_json", "{}")), "heat_delivered_kwh": json.loads(item.get("heat_delivered_json", "{}")), "thermal_loss_kwh": json.loads(item.get("thermal_loss_json", "{}")), "temperature_shortfall_c": json.loads(item.get("temperature_shortfall_json", "{}")), "charge_energy_kwh": json.loads(item.get("charge_energy_json", "{}"))} for item in slots]}

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

    def latest_forecast_snapshot(self) -> dict[str, Any] | None:
        """Return the complete latest forecast for a dedicated API operation."""
        from .schema import forecast, forecast_hour

        with store_errors(self._application_location):
            with self._application.connect() as connection:
                row = connection.execute(
                    select(forecast)
                    .where(forecast.c.installation_id == self._installation_id)
                    .order_by(forecast.c.retrieved_at.desc(), forecast.c.id.desc())
                    .limit(1)
                ).mappings().first()
                if row is None:
                    return None
                hours = connection.execute(
                    select(forecast_hour)
                    .where(forecast_hour.c.forecast_id == row["id"])
                    .order_by(forecast_hour.c.observed_at)
                ).mappings().all()
        return {
            "retrieved_at": from_utc(row["retrieved_at"]),
            "source": str(row["source"]),
            "forecast_date": row["forecast_date"].isoformat(),
            "points": [
                {
                    "timestamp": from_utc(item["observed_at"]),
                    "temperature_c": float(item["temperature_c"]),
                    "interpolated": bool(item["interpolated"]),
                }
                for item in hours
            ],
        }

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
