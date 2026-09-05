"""Pure rolling-horizon demand estimation and charge optimisation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
import math
from time import monotonic
from typing import Callable, Mapping, Sequence
from zoneinfo import ZoneInfo

from .models import ChargeConstraint, ChargeTelemetry, Heater
from .system_settings import MqttSystemSettings
from .weather import HourlyForecastPoint

FEASIBLE = "FEASIBLE"
DEGRADED = "DEGRADED"
INVALID = "INVALID"
SOLVER_TIME_LIMIT_SECONDS = 30
PLANNING_HORIZON_HOURS = 24

logger = logging.getLogger(__name__)


def resolve_planning_telemetry(
    heaters: Sequence[Heater],
    persisted: Mapping[str, ChargeTelemetry],
    observed_at: datetime,
    *,
    mqtt: MqttSystemSettings | None = None,
    max_age_seconds: float = 900,
) -> dict[str, ChargeTelemetry]:
    """Return the telemetry snapshot automatic planning should use."""
    if mqtt is not None and not mqtt.enabled:
        return {
            heater.id: ChargeTelemetry(
                heater_id=heater.id,
                temperature_c=mqtt.fixed_temperature_c,
                target_temperature_c=mqtt.fixed_target_temperature_c,
                stored_charge_percent=mqtt.fixed_stored_charge_percent,
                temperature_received_at=observed_at,
                target_received_at=observed_at,
                stored_charge_received_at=observed_at,
            )
            for heater in heaters
            if heater.enabled
        }
    valid: dict[str, ChargeTelemetry] = {}
    for heater in heaters:
        if not heater.enabled:
            continue
        value = persisted.get(heater.id)
        if value is None:
            continue
        stamps = (
            value.temperature_received_at,
            value.target_received_at,
            value.stored_charge_received_at,
        )
        if all(
            item is not None and (observed_at - item).total_seconds() <= max_age_seconds
            for item in stamps
        ):
            valid[heater.id] = value
    return valid


@dataclass(frozen=True)
class DemandEstimate:
    heater_id: str
    start: datetime
    end: datetime
    outdoor_temperature_c: float
    target_temperature_c: float
    feedback_temperature_c: float
    degree_hours: float
    thermal_coefficient: float
    demand_factor: float
    reserve_percent: float
    demand_kwh: float


@dataclass(frozen=True)
class MaterializedConstraint:
    requirement_id: int | None
    heater_id: str
    at: datetime
    minimum_soc_percent: float
    priority: int


@dataclass(frozen=True)
class PlanningViolation:
    heater_id: str | None
    requirement: str
    achievable_value: float | None
    shortfall: float | None
    at: datetime | None
    reason: str

    @property
    def target_charge_percent(self) -> float:
        return float((self.achievable_value or 0) + (self.shortfall or 0))

    @property
    def projected_charge_percent(self) -> float:
        return float(self.achievable_value or 0)

    @property
    def deficit_percent(self) -> float:
        return float(self.shortfall or 0)


PlanningDeficit = PlanningViolation


class PlanningCancelled(Exception):
    """Raised when a cooperative preview cancellation reaches a safe boundary."""


@dataclass(frozen=True)
class AutomaticPlanSlot:
    start: datetime
    end: datetime
    heater_ids: tuple[str, ...]
    power_w: int
    stored_charge_percent: dict[str, float]
    required_charge_percent: dict[str, float]
    outdoor_temperature_c: float | None = None
    indoor_temperature_c: dict[str, float] | None = None
    initial_soc_percent: dict[str, float] | None = None
    demand_kwh: dict[str, float] | None = None
    heater_power_w: dict[str, int] | None = None


@dataclass(frozen=True)
class HeaterExplanation:
    heater_id: str
    actual_soc_percent: float
    total_demand_kwh: float
    demand_factor: float
    reserve_percent: float
    next_constraint_at: datetime | None
    charge_periods: tuple[tuple[datetime, datetime], ...]
    capacity_kwh: float = 0.0


@dataclass(frozen=True)
class AutomaticPlan:
    horizon_start: datetime
    horizon_end: datetime
    slot_minutes: int
    slots: tuple[AutomaticPlanSlot, ...]
    deficits: tuple[PlanningViolation, ...]
    status: str
    score: tuple[float, ...]
    input_token: str
    generated_at: datetime | None = None
    explanations: tuple[HeaterExplanation, ...] = ()
    demand: tuple[DemandEstimate, ...] = ()

    @property
    def violations(self) -> tuple[PlanningViolation, ...]:
        return self.deficits


@dataclass(frozen=True)
class PlanningInput:
    heaters: tuple[Heater, ...]
    telemetry: Mapping[str, ChargeTelemetry]
    constraints: tuple[ChargeConstraint, ...]
    forecast: Sequence[HourlyForecastPoint]
    horizon_start: datetime
    horizon_hours: int = PLANNING_HORIZON_HOURS
    slot_minutes: int = 30
    max_total_power_w: int = 5200
    base_load_w: int = 0
    timezone_name: str = "UTC"
    design_indoor_temperature_c: float = 21.0
    design_outdoor_temperature_c: float = 0.0
    feedback_horizon_hours: float = 6.0
    max_heating_power_w: int | None = None
    forecast_automatic_eligible: bool = True
    generated_at: datetime | None = None
    exploration_limit: int = 100_000
    progress_callback: Callable[[str], None] | None = None
    cancellation_probe: Callable[[], bool] | None = None


class DegreeHoursDemandEstimator:
    """Deterministic ``degree_hours_v1`` estimator."""

    name = "degree_hours_v1"

    def estimate(
        self,
        heaters: Sequence[Heater],
        telemetry: Mapping[str, ChargeTelemetry],
        forecast: Sequence[HourlyForecastPoint],
        starts: Sequence[datetime],
        slot_minutes: int,
        *,
        design_indoor_temperature_c: float,
        design_outdoor_temperature_c: float,
        feedback_horizon_hours: float,
    ) -> tuple[DemandEstimate, ...]:
        design_delta = design_indoor_temperature_c - design_outdoor_temperature_c
        if design_delta <= 0:
            raise ValueError("design indoor temperature must exceed design outdoor temperature")
        if feedback_horizon_hours <= 0:
            raise ValueError("feedback_horizon_hours must be positive")
        hours = slot_minutes / 60
        estimates: list[DemandEstimate] = []
        for heater in sorted((item for item in heaters if item.enabled), key=lambda item: item.id):
            state = telemetry.get(heater.id)
            if not _telemetry_usable(state):
                raise ValueError(f"missing required telemetry for heater {heater.id}")
            assert state is not None
            coefficient = heater.capacity_kwh / (24 * design_delta)
            actual = float(state.temperature_c)
            target = float(state.target_temperature_c)
            for index, start in enumerate(starts):
                outdoor = _weather_at(start, forecast)
                if outdoor is None:
                    raise ValueError(f"missing continuous forecast at {start.isoformat()}")
                elapsed = (start - starts[0]).total_seconds() / 3600
                feedback_weight = max(0.0, 1.0 - elapsed / feedback_horizon_hours)
                feedback = (target - actual) * feedback_weight
                delta = max(0.0, target - outdoor + feedback)
                degree_hours = delta * hours
                demand = coefficient * degree_hours * heater.demand_factor
                demand *= 1 + heater.reserve_percent / 100
                estimates.append(DemandEstimate(
                    heater.id, start, start + timedelta(minutes=slot_minutes), outdoor,
                    target, feedback, degree_hours, coefficient, heater.demand_factor,
                    heater.reserve_percent, max(0.0, demand),
                ))
        return tuple(estimates)


def materialize_constraints(
    constraints: Sequence[ChargeConstraint], heaters: Sequence[Heater],
    horizon_start: datetime, horizon_end: datetime, slot_minutes: int,
    timezone_name: str,
) -> tuple[MaterializedConstraint, ...]:
    zone = ZoneInfo(timezone_name)
    priorities = {item.id: item.priority for item in heaters}
    boundaries: list[datetime] = []
    cursor = horizon_start
    while cursor <= horizon_end:
        boundaries.append(cursor)
        cursor += timedelta(minutes=slot_minutes)
    result: list[MaterializedConstraint] = []
    for rule in constraints:
        if rule.heater_id not in priorities:
            raise ValueError(f"unknown heater in constraint: {rule.heater_id}")
        if rule.at.minute % slot_minutes:
            raise ValueError("constraint time must align with the configured slot")
        for boundary in boundaries:
            local = boundary.astimezone(zone)
            if local.weekday() in rule.weekdays and local.time().replace(tzinfo=None) == rule.at:
                result.append(MaterializedConstraint(rule.id, rule.heater_id, boundary, rule.target_charge * 100, priorities[rule.heater_id]))
    return tuple(sorted(result, key=lambda item: (item.at, -item.priority, item.heater_id, item.requirement_id or 0)))


class MilpChargePlanner:
    """Lexicographic ON/OFF planner using PuLP and single-threaded CBC."""

    def build(self, request: PlanningInput) -> AutomaticPlan:
        generated_at = request.generated_at or request.horizon_start
        _notify(request, "inputs")
        _check_cancelled(request)
        logger.debug(
            "Automatic planning started: heaters=%d constraints=%d forecast_points=%d "
            "horizon_hours=%d slot_minutes=%d contracted_power_w=%d "
            "base_load_w=%d max_heating_power_w=%s",
            len(request.heaters),
            len(request.constraints),
            len(request.forecast),
            request.horizon_hours,
            request.slot_minutes,
            request.max_total_power_w,
            request.base_load_w,
            request.max_heating_power_w,
        )
        try:
            _validate_input(request)
            # The rolling horizon starts at the current slot, never in the
            # middle of one. This keeps automatic, preview and activation
            # responses on the same deterministic slot boundary.
            horizon_start = _floor_align(request.horizon_start, request.slot_minutes)
        except (ValueError, ArithmeticError) as exc:
            return _invalid_plan(request, request.horizon_start, (), str(exc), "invalid_configuration", generated_at)
        _notify(request, "coverage")
        starts = _continuous_forecast_slots(horizon_start, request.forecast, request.horizon_hours, request.slot_minutes)
        if not starts or not request.forecast_automatic_eligible:
            reason = "forecast_not_eligible" if not request.forecast_automatic_eligible else "missing_aemet_coverage"
            logger.debug("Automatic planning rejected: reason=%s", reason)
            return _invalid_plan(request, horizon_start, (), reason, reason, generated_at)
        horizon_end = starts[-1] + timedelta(minutes=request.slot_minutes)
        missing = [item.id for item in request.heaters if item.enabled and not _telemetry_usable(request.telemetry.get(item.id))]
        if missing:
            logger.debug("Automatic planning rejected: missing_telemetry=%s", ",".join(sorted(missing)))
            return _invalid_plan(request, horizon_start, starts, f"missing required MQTT state: {', '.join(sorted(missing))}", "missing_required_state", generated_at, missing)
        try:
            _notify(request, "telemetry")
            demand = DegreeHoursDemandEstimator().estimate(
                request.heaters, request.telemetry, request.forecast, starts, request.slot_minutes,
                design_indoor_temperature_c=request.design_indoor_temperature_c,
                design_outdoor_temperature_c=request.design_outdoor_temperature_c,
                feedback_horizon_hours=request.feedback_horizon_hours,
            )
            for item in demand:
                logger.debug(
                    "Planning demand: heater=%s start=%s demand_kwh=%.9g outdoor_c=%.3f feedback_c=%.3f",
                    item.heater_id, item.start.isoformat(), item.demand_kwh,
                    item.outdoor_temperature_c, item.feedback_temperature_c,
                )
            _notify(request, "demand")
            materialized = materialize_constraints(request.constraints, request.heaters, starts[0], horizon_end, request.slot_minutes, request.timezone_name)
            for item in materialized:
                logger.debug(
                    "Planning constraint materialized: heater=%s at=%s minimum_soc_percent=%.3f priority=%d",
                    item.heater_id, item.at.isoformat(), item.minimum_soc_percent, item.priority,
                )
            _notify(request, "constraints")
            return self._solve(request, starts, demand, materialized, generated_at)
        except (ValueError, ArithmeticError) as exc:
            logger.debug("Automatic planning rejected: %s", exc)
            return _invalid_plan(request, horizon_start, starts, str(exc), "invalid_configuration", generated_at)

    def _solve(self, request: PlanningInput, starts: Sequence[datetime], demand: Sequence[DemandEstimate], constraints: Sequence[MaterializedConstraint], generated_at: datetime) -> AutomaticPlan:
        try:
            import pulp
        except ImportError:
            return _invalid_plan(request, starts[0], starts, "PuLP is unavailable", "solver_unavailable", generated_at)
        heaters = tuple(sorted((item for item in request.heaters if item.enabled), key=lambda item: item.id))
        slot_hours = request.slot_minutes / 60
        heating_limit_w = request.max_heating_power_w or request.max_total_power_w
        contracted_limit_w = max(0, request.max_total_power_w - request.base_load_w)
        limit_w = min(heating_limit_w, contracted_limit_w)
        oversized = tuple(item for item in heaters if item.power_w > limit_w)
        demand_by_key = {(item.heater_id, item.start): item.demand_kwh for item in demand}
        boundary_index = {start: index for index, start in enumerate(starts)}
        boundary_index[starts[-1] + timedelta(minutes=request.slot_minutes)] = len(starts)
        model = pulp.LpProblem("dynamic_thermal_charge", pulp.LpMinimize)
        on = {(h.id, i): pulp.LpVariable(f"on_{h.id}_{i:03d}", cat="Binary") for h in heaters for i in range(len(starts))}
        energy = {(h.id, i): pulp.LpVariable(f"energy_{h.id}_{i:03d}", lowBound=0, upBound=h.capacity_kwh) for h in heaters for i in range(len(starts) + 1)}
        unmet = {(h.id, i): pulp.LpVariable(f"unmet_{h.id}_{i:03d}", lowBound=0, upBound=demand_by_key[(h.id, starts[i])]) for h in heaters for i in range(len(starts))}
        c_short = {index: pulp.LpVariable(f"constraint_shortfall_{index:03d}", lowBound=0) for index in range(len(constraints))}
        for h in heaters:
            model += energy[(h.id, 0)] == h.capacity_kwh * float(request.telemetry[h.id].stored_charge_percent) / 100
            for i, start in enumerate(starts):
                model += energy[(h.id, i + 1)] == energy[(h.id, i)] + h.charge_power_kw * slot_hours * on[(h.id, i)] - demand_by_key[(h.id, start)] + unmet[(h.id, i)]
        for i in range(len(starts)):
            heating_power = pulp.lpSum(h.power_w * on[(h.id, i)] for h in heaters)
            model += heating_power <= heating_limit_w
            model += heating_power + request.base_load_w <= request.max_total_power_w
        for h in oversized:
            for i in range(len(starts)):
                model += on[(h.id, i)] == 0
        for index, rule in enumerate(constraints):
            model += energy[(rule.heater_id, boundary_index[rule.at])] + c_short[index] >= _heater(heaters, rule.heater_id).capacity_kwh * rule.minimum_soc_percent / 100
        solver = _cbc_solver(pulp, time_limit_seconds=SOLVER_TIME_LIMIT_SECONDS)
        solver_deadline = monotonic() + SOLVER_TIME_LIMIT_SECONDS
        score: list[float] = []
        phases = []
        for priority in sorted({item.priority for item in constraints}, reverse=True):
            phases.append(pulp.lpSum(c_short[i] for i, item in enumerate(constraints) if item.priority == priority))
        for priority in sorted({item.priority for item in heaters}, reverse=True):
            phases.append(pulp.lpSum(unmet[(h.id, i)] for h in heaters if h.priority == priority for i in range(len(starts))))
        total_charge = pulp.lpSum(h.charge_power_kw * slot_hours * on[(h.id, i)] for h in heaters for i in range(len(starts)))
        phases.extend((
            total_charge,
            pulp.lpSum((len(starts) - i) * h.charge_power_kw * slot_hours * on[(h.id, i)] for h in heaters for i in range(len(starts))),
            pulp.lpSum((heater_index + 1) * (i + 1) * on[(h.id, i)] for heater_index, h in enumerate(heaters) for i in range(len(starts))),
        ))
        time_limited = False
        for phase_index, objective in enumerate(phases):
            _notify(request, f"solver_phase_{phase_index + 1}")
            _check_cancelled(request)
            remaining_seconds = solver_deadline - monotonic()
            if remaining_seconds <= 0:
                if not _model_solution_is_feasible(model, pulp, on):
                    return _invalid_plan(
                        request, starts[0], starts,
                        "solver reached its total time limit without a verified feasible solution",
                        "solver_failure", generated_at,
                    )
                logger.info(
                    "Automatic planning solver total time limit reached before phase=%d/%d",
                    phase_index + 1,
                    len(phases),
                )
                time_limited = True
                break
            solver.timeLimit = remaining_seconds
            model.setObjective(objective)
            status = model.solve(solver)
            _check_cancelled(request)
            logger.debug(
                "Automatic planning solver phase=%d/%d status=%s",
                phase_index + 1,
                len(phases),
                pulp.LpStatus[status],
            )
            if status == pulp.LpStatusNotSolved:
                if not _model_solution_is_feasible(model, pulp, on):
                    return _invalid_plan(
                        request, starts[0], starts,
                        "solver reached its time limit without a verified feasible solution",
                        "solver_failure", generated_at,
                    )
                time_limited = True
                break
            if status != pulp.LpStatusOptimal:
                return _invalid_plan(
                    request,
                    starts[0],
                    starts,
                    f"solver status {pulp.LpStatus[status]}",
                    "solver_failure",
                    generated_at,
                )
            try:
                optimum = _required_solver_value(pulp.value(objective), "objective")
            except ValueError as exc:
                return _invalid_plan(
                    request, starts[0], starts, str(exc), "solver_failure", generated_at
                )
            score.append(optimum)
            logger.debug(
                "Automatic planning solver phase=%d optimum=%.9g",
                phase_index + 1,
                optimum,
            )
            if phase_index < len(phases) - 1:
                model += objective <= optimum + 1e-7
        try:
            _require_solution_values(on, energy, unmet, c_short)
        except ValueError as exc:
            return _invalid_plan(request, starts[0], starts, str(exc), "solver_failure", generated_at)
        violations: list[PlanningViolation] = []
        if time_limited:
            violations.append(
                PlanningViolation(
                    None, "solver_time_limit", None, None, starts[0], "solver_time_limit"
                )
            )
        for h in oversized:
            violations.append(PlanningViolation(h.id, "individual_power_limit", 0.0, h.power_w - limit_w, starts[0], "heater_power_exceeds_global_limit"))
        for index, rule in enumerate(constraints):
            short_kwh = float(c_short[index].value() or 0.0)
            if short_kwh > 1e-6:
                h = _heater(heaters, rule.heater_id)
                achieved = float(energy[(h.id, boundary_index[rule.at])].value() or 0.0) / h.capacity_kwh * 100
                violations.append(PlanningViolation(h.id, "minimum_soc", achieved, short_kwh / h.capacity_kwh * 100, rule.at, "insufficient_capacity_or_power"))
        for h in heaters:
            for i, start in enumerate(starts):
                short = float(unmet[(h.id, i)].value() or 0.0)
                if short > 1e-6:
                    served = demand_by_key[(h.id, start)] - short
                    violations.append(PlanningViolation(h.id, "forecast_demand_kwh", served, short, start, "insufficient_stored_energy_or_power"))
        for violation in violations:
            logger.debug(
                "Planning deficit: heater=%s requirement=%s at=%s reason=%s shortfall=%s",
                violation.heater_id, violation.requirement,
                None if violation.at is None else violation.at.isoformat(),
                violation.reason, violation.shortfall,
            )
        plan_slots: list[AutomaticPlanSlot] = []
        for i, start in enumerate(starts):
            active = tuple(h.id for h in heaters if float(on[(h.id, i)].value() or 0) > .5)
            plan_slots.append(AutomaticPlanSlot(
                start, start + timedelta(minutes=request.slot_minutes), active,
                sum(_heater(heaters, heater_id).power_w for heater_id in active),
                {h.id: round(float(energy[(h.id, i + 1)].value() or 0) / h.capacity_kwh * 100, 6) for h in heaters},
                {h.id: round(demand_by_key[(h.id, start)] / h.capacity_kwh * 100, 6) for h in heaters},
                _weather_at(start, request.forecast),
                {h.id: float(request.telemetry[h.id].temperature_c) for h in heaters},
                {h.id: round(float(energy[(h.id, i)].value() or 0) / h.capacity_kwh * 100, 6) for h in heaters},
                {h.id: round(demand_by_key[(h.id, start)], 9) for h in heaters},
                {h.id: (h.power_w if h.id in active else 0) for h in heaters},
            ))
            logger.debug(
                "Planning slot chosen: start=%s heater_ids=%s power_w=%d",
                start.isoformat(), ",".join(active) or "none", sum(_heater(heaters, heater_id).power_w for heater_id in active),
            )
        explanations = tuple(HeaterExplanation(
            h.id, float(request.telemetry[h.id].stored_charge_percent),
            sum(item.demand_kwh for item in demand if item.heater_id == h.id),
            h.demand_factor, h.reserve_percent,
            next((item.at for item in constraints if item.heater_id == h.id), None),
            tuple((slot.start, slot.end) for slot in plan_slots if h.id in slot.heater_ids),
            h.capacity_kwh,
        ) for h in heaters)
        plan = AutomaticPlan(
            starts[0], starts[-1] + timedelta(minutes=request.slot_minutes), request.slot_minutes,
            tuple(plan_slots), tuple(violations), DEGRADED if violations or time_limited else FEASIBLE,
            tuple(score), input_token(request), generated_at, explanations, tuple(demand),
        )
        _notify(request, "safety")
        _notify(request, "summary")
        logger.debug(
            "Automatic planning completed: status=%s slots=%d violations=%d token=%s",
            plan.status,
            len(plan.slots),
            len(plan.violations),
            plan.input_token,
        )
        return plan


class DeterministicChargeOptimizer(MilpChargePlanner):
    """Compatibility name for the V1 MILP planner."""


def input_token(request: PlanningInput) -> str:
    # The calculation is anchored to the current slot. The token must use the
    # same stable anchor so preview and activation remain compatible while the
    # clock advances within that slot.
    token_horizon_start = request.horizon_start
    if request.slot_minutes > 0:
        token_horizon_start = _floor_align(request.horizon_start, request.slot_minutes)
    payload = {
        "heaters": [(h.id, h.power_w, h.full_charge_minutes, h.enabled, h.priority, h.demand_factor, h.reserve_percent) for h in request.heaters],
        "telemetry": {key: _json_telemetry(value) for key, value in sorted(request.telemetry.items())},
        "constraints": [(c.id, c.heater_id, c.target_charge, c.at.isoformat(), c.weekdays) for c in request.constraints],
        "forecast": [(point.timestamp.isoformat(), point.temperature_c, point.interpolated) for point in request.forecast],
        "horizon_start": token_horizon_start.astimezone(timezone.utc).isoformat(),
        "horizon_hours": request.horizon_hours, "slot_minutes": request.slot_minutes,
        "max_total_power_w": request.max_total_power_w, "base_load_w": request.base_load_w, "max_heating_power_w": request.max_heating_power_w,
        "timezone_name": request.timezone_name, "design_indoor_temperature_c": request.design_indoor_temperature_c,
        "design_outdoor_temperature_c": request.design_outdoor_temperature_c, "feedback_horizon_hours": request.feedback_horizon_hours,
        "forecast_automatic_eligible": request.forecast_automatic_eligible,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _json_telemetry(value: ChargeTelemetry) -> dict[str, object]:
    # Receipt times validate freshness but do not affect the plan itself. They
    # must not invalidate activation when the same fixed/live values are read
    # again a few minutes after the preview.
    return {
        "heater_id": value.heater_id,
        "temperature_c": value.temperature_c,
        "target_temperature_c": value.target_temperature_c,
        "stored_charge_percent": value.stored_charge_percent,
    }


def _validate_input(request: PlanningInput) -> None:
    if request.horizon_start.tzinfo is None:
        raise ValueError("horizon_start requires a timezone")
    if request.slot_minutes <= 0 or request.slot_minutes > 60 or 60 % request.slot_minutes:
        raise ValueError("slot_minutes must be a positive divisor of one hour")
    if request.horizon_hours <= 0 or request.horizon_hours > 48:
        raise ValueError("horizon_hours must be between 1 and 48")
    if request.max_total_power_w <= 0 or request.base_load_w < 0 or (request.max_heating_power_w is not None and request.max_heating_power_w <= 0):
        raise ValueError("power limits must be positive")
    if request.design_indoor_temperature_c <= request.design_outdoor_temperature_c:
        raise ValueError("design indoor temperature must exceed design outdoor temperature")
    if request.feedback_horizon_hours <= 0:
        raise ValueError("feedback_horizon_hours must be positive")
    ZoneInfo(request.timezone_name)


def _floor_align(value: datetime, minutes: int) -> datetime:
    return value.replace(
        second=0,
        microsecond=0,
        minute=(value.minute // minutes) * minutes,
    )


def _continuous_forecast_slots(start: datetime, forecast: Sequence[HourlyForecastPoint], horizon_hours: int, slot_minutes: int) -> tuple[datetime, ...]:
    if not forecast:
        return ()
    result = []
    cursor = start
    configured_end = start + timedelta(hours=horizon_hours)
    while cursor < configured_end:
        if _weather_at(cursor, forecast) is None:
            logger.debug("Forecast coverage is not continuous: missing_at=%s", cursor.isoformat())
            return ()
        result.append(cursor)
        cursor += timedelta(minutes=slot_minutes)
    return tuple(result) if len(result) == horizon_hours * 60 // slot_minutes else ()


def _notify(request: PlanningInput, step: str) -> None:
    logger.debug("Planning workflow step: %s", step)
    if request.progress_callback is not None:
        request.progress_callback(step)


def _check_cancelled(request: PlanningInput) -> None:
    if request.cancellation_probe is not None and request.cancellation_probe():
        logger.info("Automatic planning cancellation acknowledged at a phase boundary")
        raise PlanningCancelled()


def _telemetry_usable(value: ChargeTelemetry | None) -> bool:
    return value is not None and all(item is not None for item in (value.temperature_c, value.target_temperature_c, value.stored_charge_percent))


def _weather_at(at: datetime, points: Sequence[HourlyForecastPoint]) -> float | None:
    matches = [point.temperature_c for point in points if point.timestamp <= at < point.timestamp + timedelta(hours=1)]
    return float(matches[-1]) if matches else None


def _heater(heaters: Sequence[Heater], heater_id: str) -> Heater:
    return next(item for item in heaters if item.id == heater_id)


def _cbc_solver(pulp, *, time_limit_seconds: float | None = None):
    import shutil
    kwargs = {
        "msg": False,
        "threads": 1,
        "options": ["randomSeed 0"],
        "timeLimit": time_limit_seconds,
    }
    if shutil.which("cbc"):
        return pulp.COIN_CMD(**kwargs)
    return pulp.PULP_CBC_CMD(**kwargs)


def _required_solver_value(value, label: str) -> float:
    if value is None:
        raise ValueError(f"solver did not assign {label}")
    numeric = float(value)
    if not math.isfinite(numeric):
        raise ValueError(f"solver assigned a non-finite value to {label}")
    return numeric


def _require_solution_values(*variable_groups) -> None:
    for group in variable_groups:
        for key, variable in group.items():
            _required_solver_value(variable.value(), str(key))


def _model_solution_is_feasible(
    model, pulp, binary_variables, tolerance: float = 1e-6
) -> bool:
    """Accept a time-limited candidate only after checking every constraint."""
    try:
        for variable in binary_variables.values():
            value = _required_solver_value(variable.value(), "binary variable")
            if abs(value - round(value)) > tolerance:
                return False
        for constraint in model.constraints.values():
            value = _required_solver_value(pulp.value(constraint), "constraint")
            if constraint.sense == 0 and abs(value) > tolerance:
                return False
            if constraint.sense == -1 and value > tolerance:
                return False
            if constraint.sense == 1 and value < -tolerance:
                return False
    except ValueError:
        return False
    return True


def _invalid_plan(request: PlanningInput, start: datetime, starts: Sequence[datetime], detail: str, reason: str, generated_at: datetime, heater_ids: Sequence[str] = ()) -> AutomaticPlan:
    usable_starts = tuple(starts)
    enabled = tuple(sorted((item for item in request.heaters if item.enabled), key=lambda item: item.id))
    violations = tuple(PlanningViolation(heater_id, "safe_planning_input", None, None, start, reason) for heater_id in heater_ids) or (PlanningViolation(None, "safe_planning_input", None, None, start, f"{reason}: {detail}"),)
    slots = tuple(AutomaticPlanSlot(
        at, at + timedelta(minutes=request.slot_minutes), (), 0,
        {h.id: float(request.telemetry[h.id].stored_charge_percent or 0) if h.id in request.telemetry else 0.0 for h in enabled},
        {h.id: 0.0 for h in enabled}, _weather_at(at, request.forecast), None,
        {h.id: float(request.telemetry[h.id].stored_charge_percent or 0) if h.id in request.telemetry else 0.0 for h in enabled},
        {h.id: 0.0 for h in enabled}, {h.id: 0 for h in enabled},
    ) for at in usable_starts)
    horizon_end = usable_starts[-1] + timedelta(minutes=request.slot_minutes) if usable_starts else start + timedelta(hours=request.horizon_hours)
    return AutomaticPlan(start, horizon_end, request.slot_minutes, slots, violations, INVALID, (), input_token(request), generated_at)


__all__ = [
    "AutomaticPlan", "AutomaticPlanSlot", "DEGRADED", "DemandEstimate",
    "DegreeHoursDemandEstimator", "DeterministicChargeOptimizer", "FEASIBLE",
    "HeaterExplanation", "INVALID", "MaterializedConstraint", "MilpChargePlanner",
    "PlanningCancelled", "PlanningDeficit", "PlanningInput", "PlanningViolation", "PLANNING_HORIZON_HOURS", "SOLVER_TIME_LIMIT_SECONDS", "input_token",
    "materialize_constraints", "resolve_planning_telemetry",
]
