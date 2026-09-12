"""Deterministic, persisted evidence and operator explanations for plans."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from .charge_planning import PlanningInput


def _instant(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def _stable_summary_value(value: Any) -> Any:
    """Make solver-derived presentation values stable across preview reloads."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        if isinstance(value, Mapping):
            return {key: _stable_summary_value(item) for key, item in value.items()}
        if isinstance(value, list):
            return [_stable_summary_value(item) for item in value]
        if isinstance(value, tuple):
            return tuple(_stable_summary_value(item) for item in value)
        return value
    rounded = round(float(value), 6)
    return 0.0 if rounded == 0.0 else rounded


def planning_evidence(
    request: PlanningInput,
    *,
    planning_site: Mapping[str, Any],
    forecast_status: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Capture only safe inputs actually supplied to the optimiser."""
    telemetry = {
        heater_id: {
            "state": "ready",
            "indoor_temperature_c": value.indoor_temperature_c,
            "stored_soc_percent": value.stored_soc_percent,
            "indoor_received_at": _instant(value.indoor_received_at),
            "stored_soc_received_at": _instant(value.stored_soc_received_at),
        }
        for heater_id, value in request.telemetry.items()
    }
    heaters = [
        {
            "id": heater.id,
            "name": heater.name,
            "enabled": heater.enabled,
            "priority": heater.priority,
            "power_w": heater.power_w,
            "capacity_kwh": heater.capacity_kwh,
            "full_charge_minutes": heater.full_charge_minutes,
            "full_discharge_minutes": heater.full_discharge_minutes,
            "static_emission_percent": heater.static_emission_percent,
            "room_thermal_capacity_kwh_per_c": heater.room_thermal_capacity_kwh_per_c,
            "room_heat_loss_kw_per_c": heater.room_heat_loss_kw_per_c,
        }
        for heater in request.heaters
    ]
    targets = [
        {
            "heater_id": heater_id,
            "target_temperature_c": target.target_temperature_c,
            "start_time": target.start_time.strftime("%H:%M"),
            "end_time": target.end_time.strftime("%H:%M"),
            "weekdays": list(target.weekdays),
            "enabled": target.enabled,
        }
        for heater_id, values in request.temperature_targets.items()
        for target in values
    ]
    forecast = [
        {
            "timestamp": point.timestamp.isoformat(),
            "temperature_c": point.temperature_c,
            "interpolated": point.interpolated,
        }
        for point in request.forecast
    ]
    return {
        "captured_at": _instant(request.generated_at or request.horizon_start),
        "timezone": request.timezone_name,
        "limits": {
            "contracted_power_w": request.max_total_power_w,
            "max_heating_power_w": request.max_heating_power_w,
            "base_load_w": request.base_load_w,
            "solver_time_limit_seconds": request.solver_time_limit_seconds,
            "slot_minutes": request.slot_minutes,
        },
        "planning": {
            key: value
            for key, value in planning_site.items()
            if key
            in {
                "revision",
                "replan_minutes",
                "planning_window_hours",
                "forecast_horizon_hours",
                "deviation_shortfall_tolerance_c",
                "deviation_surplus_soc_percent",
            }
        },
        "heaters": heaters,
        "telemetry": telemetry,
        "missing_telemetry_heater_ids": sorted(
            heater.id
            for heater in request.heaters
            if heater.enabled and heater.id not in request.telemetry
        ),
        "telemetry_state_by_heater": {
            heater.id: ("ready" if heater.id in request.telemetry else "missing_or_stale")
            for heater in request.heaters
            if heater.enabled
        },
        "temperature_targets": targets,
        "forecast": forecast,
        "forecast_automatic_eligible": request.forecast_automatic_eligible,
        "forecast_status": dict(forecast_status or {}),
    }


def operator_summary(plan: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Build concise statements strictly from persisted plan evidence."""
    result: list[dict[str, Any]] = []
    evidence = plan.get("evidence") or {}
    names = {
        str(item.get("id")): str(item.get("name") or item.get("id"))
        for item in evidence.get("heaters", [])
        if isinstance(item, Mapping) and item.get("id") is not None
    }
    for item in plan.get("explanations") or []:
        if not isinstance(item, Mapping):
            continue
        heater_id = str(item.get("heater_id", ""))
        periods = item.get("charge_periods") or []
        result.append(
            {
                "heater_id": heater_id,
                "heater_name": names.get(heater_id, heater_id),
                "initial_indoor_temperature_c": _stable_summary_value(item.get("initial_indoor_temperature_c")),
                "initial_soc_percent": _stable_summary_value(item.get("actual_soc_percent")),
                "total_demand_kwh": _stable_summary_value(item.get("total_demand_kwh")),
                "total_heat_delivered_kwh": _stable_summary_value(item.get("total_heat_delivered_kwh")),
                "total_thermal_loss_kwh": _stable_summary_value(item.get("total_thermal_loss_kwh")),
                "final_indoor_temperature_c": _stable_summary_value(item.get("final_indoor_temperature_c")),
                "maximum_temperature_shortfall_c": _stable_summary_value(item.get("maximum_temperature_shortfall_c")),
                "initial_stored_energy_kwh": _stable_summary_value(item.get("initial_stored_energy_kwh")),
                "final_stored_energy_kwh": _stable_summary_value(item.get("final_stored_energy_kwh")),
                "total_charge_energy_kwh": _stable_summary_value(item.get("total_charge_energy_kwh")),
                "forecast_contribution_kwh": _stable_summary_value(item.get("forecast_contribution_kwh")),
                "terminal_surplus_energy_kwh": _stable_summary_value(item.get("terminal_surplus_energy_kwh")),
                "next_constraint_at": item.get("next_constraint_at"),
                "next_target_temperature_c": _stable_summary_value(item.get("next_target_temperature_c")),
                "next_target_start": item.get("next_target_start"),
                "next_target_end": item.get("next_target_end"),
                "charge_periods": periods,
                "charge_reasons": _stable_summary_value(item.get("charge_reasons")),
                "charge_minutes": sum(
                    max(
                        0,
                        round(
                            (
                                datetime.fromisoformat(str(period[1]))
                                - datetime.fromisoformat(str(period[0]))
                            ).total_seconds()
                            / 60
                        ),
                    )
                    for period in periods
                    if isinstance(period, (list, tuple)) and len(period) == 2
                ),
            }
        )
    return result


def compare_plans(current: Mapping[str, Any], previous: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if previous is None:
        return None

    def assignments(plan: Mapping[str, Any]) -> set[tuple[str, str, str]]:
        return {
            (str(slot.get("start")), str(slot.get("end")), str(heater_id))
            for slot in plan.get("slots") or []
            if isinstance(slot, Mapping)
            for heater_id in slot.get("heater_ids") or []
        }

    before = assignments(previous)
    after = assignments(current)

    def final_values(plan: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
        values: dict[str, dict[str, Any]] = {}
        for slot in plan.get("slots") or []:
            if not isinstance(slot, Mapping):
                continue
            for key, target in (
                ("stored_energy_next_kwh", "stored_energy_kwh"),
                ("indoor_temperature_next_c", "indoor_temperature_c"),
                ("stored_charge_percent", "stored_soc_percent"),
                ("temperature_shortfall_c", "temperature_shortfall_c"),
            ):
                for heater_id, value in (slot.get(key) or {}).items():
                    values.setdefault(str(heater_id), {})[target] = value
        return values

    return {
        "predecessor_plan_id": previous.get("id"),
        "replaced": bool(current.get("active")),
        "predecessor_preserved": bool(current.get("predecessor_preserved")),
        "input_changes": _input_changes(current.get("evidence"), previous.get("evidence")),
        "added_charge_intervals": [
            {"start": start, "end": end, "heater_id": heater_id}
            for start, end, heater_id in sorted(after - before)
        ],
        "removed_charge_intervals": [
            {"start": start, "end": end, "heater_id": heater_id}
            for start, end, heater_id in sorted(before - after)
        ],
        "final_values_before": final_values(previous),
        "final_values_after": final_values(current),
        "deficits_before": len(previous.get("deficits") or []),
        "deficits_after": len(current.get("deficits") or []),
    }


def _input_changes(current: Any, previous: Any) -> list[dict[str, Any]]:
    if not isinstance(current, Mapping) or not isinstance(previous, Mapping):
        return []
    changes: list[dict[str, Any]] = []
    for heater_id in sorted(
        set((current.get("telemetry") or {})) | set((previous.get("telemetry") or {}))
    ):
        before = (previous.get("telemetry") or {}).get(heater_id)
        after = (current.get("telemetry") or {}).get(heater_id)
        if before != after:
            changes.append(
                {"kind": "telemetry", "heater_id": heater_id, "before": before, "after": after}
            )
    for key in ("limits", "temperature_targets", "forecast_status"):
        if previous.get(key) != current.get(key):
            changes.append(
                {"kind": key, "before": previous.get(key), "after": current.get(key)}
            )
    return changes


def diagnostic_report(detail: Mapping[str, Any]) -> dict[str, Any]:
    """Return the deliberately allow-listed support bundle."""
    return {
        "format": "dynamic-thermal-charge-plan-diagnostic-v1",
        "generated_from_persisted_evidence": True,
        "plan": detail.get("plan"),
        "evidence_available": detail.get("evidence_available"),
        "operator_summary": detail.get("operator_summary"),
        "comparison": detail.get("comparison"),
        "audit": detail.get("audit"),
        "transitions": detail.get("transitions"),
    }


__all__ = ["compare_plans", "diagnostic_report", "operator_summary", "planning_evidence"]
