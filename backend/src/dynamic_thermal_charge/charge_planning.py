"""Pure rolling-horizon demand estimation and charge optimisation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
import math
from time import monotonic
from typing import Any, Callable, Mapping, Sequence
from zoneinfo import ZoneInfo

from .models import (
    ChargeConstraint,
    ChargeTelemetry,
    Heater,
    TemperatureTarget,
    validate_temperature_targets,
)
from .scheduler import _normalize, advance_real, align_to_slot, next_slot_boundary
from .system_settings import MqttSystemSettings
from .weather import HourlyForecastPoint

# ``VALID`` is the only successful public status.  Keep ``FEASIBLE`` as an
# import-level compatibility alias for integrations that still import the old
# symbol; it deliberately has the new persisted value.
VALID = "VALID"
FEASIBLE = VALID
CONVERGING = "CONVERGING"
DEGRADED = "DEGRADED"
INVALID = "INVALID"
# Direct planner callers without persisted site settings retain the historical
# short fallback. Application entry points always inject the persisted value.
SOLVER_TIME_LIMIT_SECONDS = 30
PLANNING_HORIZON_HOURS = 24

logger = logging.getLogger(__name__)


def _key(at: datetime) -> datetime:
    """A dictionary key that tells the two passes of a repeated hour apart.

    Two aware datetimes in the same zone compare equal *and hash equal* when
    their wall clocks match, even when they are an hour apart across a fall-back
    (Python ignores the shared tzinfo and compares the base datetimes). Keying
    slots by a zone-local instant would therefore collapse both passes of the
    repeated hour into one entry and silently lose a slot. The UTC form is
    unique.
    """
    return at.astimezone(timezone.utc)


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
                temperature_c=getattr(mqtt, "fixed_indoor_temperature_c", 20.0),
                stored_charge_percent=getattr(mqtt, "fixed_stored_soc_percent", 50.0),
                temperature_received_at=observed_at,
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
        stamps = (value.temperature_received_at, value.stored_charge_received_at)
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
    target_window_start: datetime | None = None
    target_window_end: datetime | None = None

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
    # Room-energy projection.  The historical fields above remain populated
    # for readers of old plans; these are the authoritative values for new
    # plans.
    stored_energy_kwh: dict[str, float] | None = None
    target_temperature_c: dict[str, float] | None = None
    heat_delivered_kwh: dict[str, float] | None = None
    thermal_loss_kwh: dict[str, float] | None = None
    temperature_shortfall_c: dict[str, float] | None = None
    charge_energy_kwh: dict[str, float] | None = None
    # Room-energy boundary values. The historical fields above remain
    # readable for persisted plans; new room-energy plans expose the slot end
    # explicitly in these maps.
    stored_energy_next_kwh: dict[str, float] | None = None
    indoor_temperature_next_c: dict[str, float] | None = None
    temperature_shortfall_start_c: dict[str, float] | None = None
    # Emission capability applied to the slot, so a comfort deficit caused by a
    # low state of charge is distinguishable from one caused by empty storage.
    heat_delivery_limit_kwh: dict[str, float] | None = None


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
    initial_indoor_temperature_c: float | None = None
    final_indoor_temperature_c: float | None = None
    total_heat_delivered_kwh: float = 0.0
    total_thermal_loss_kwh: float = 0.0
    maximum_temperature_shortfall_c: float = 0.0
    initial_stored_energy_kwh: float | None = None
    final_stored_energy_kwh: float | None = None
    total_charge_energy_kwh: float | None = None
    forecast_contribution_kwh: float | None = None
    terminal_surplus_energy_kwh: float | None = None
    next_target_temperature_c: float | None = None
    next_target_start: datetime | None = None
    next_target_end: datetime | None = None
    # ``None`` means this evidence was not recorded by an older persisted
    # preview; an empty tuple is a measured/calculated zero-charge result.
    charge_reasons: tuple[dict[str, Any], ...] | None = None


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
    convergence_by_heater: Mapping[str, datetime | None] = field(default_factory=dict)
    convergence_at: datetime | None = None
    guaranteed_until: datetime | None = None

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
    solver_time_limit_seconds: int | None = None
    generated_at: datetime | None = None
    exploration_limit: int = 100_000
    progress_callback: Callable[[str], None] | None = None
    cancellation_probe: Callable[[], bool] | None = None
    # Explicitly supplied by the room-energy API.  Keeping it separate from
    # the legacy percentage constraints lets historical preview payloads remain
    # readable while ensuring new planning has no percentage input.
    temperature_targets: Mapping[str, Sequence[TemperatureTarget]] = field(
        default_factory=dict
    )
    room_energy_model: bool = False


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
                    heater.id, start, advance_real(start, slot_minutes), outdoor,
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
    while not _key(horizon_end) < _key(cursor):
        boundaries.append(cursor)
        cursor = next_slot_boundary(cursor, slot_minutes)
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
        if _is_room_energy_request(request):
            return _build_room_energy_plan(request)
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
            # The rolling horizon starts at the first slot boundary that has
            # not passed yet. This keeps automatic, preview and activation
            # responses executable without planning an already-started slot.
            horizon_start = align_to_slot(request.horizon_start, request.slot_minutes)
        except (ValueError, ArithmeticError) as exc:
            return _invalid_plan(request, request.horizon_start, (), str(exc), "invalid_configuration", generated_at)
        _notify(request, "coverage")
        boundaries = _continuous_forecast_slots(horizon_start, request.forecast, request.horizon_hours, request.slot_minutes)
        starts = boundaries[:-1] if boundaries else ()
        if not starts or not request.forecast_automatic_eligible:
            reason = "forecast_not_eligible" if not request.forecast_automatic_eligible else "missing_aemet_coverage"
            logger.debug("Automatic planning rejected: reason=%s", reason)
            return _invalid_plan(request, horizon_start, (), reason, reason, generated_at)
        horizon_end = boundaries[-1]
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
            return self._solve(request, boundaries, demand, materialized, generated_at)
        except (ValueError, ArithmeticError) as exc:
            logger.debug("Automatic planning rejected: %s", exc)
            return _invalid_plan(request, horizon_start, starts, str(exc), "invalid_configuration", generated_at)

    def _solve(self, request: PlanningInput, boundaries: Sequence[datetime], demand: Sequence[DemandEstimate], constraints: Sequence[MaterializedConstraint], generated_at: datetime) -> AutomaticPlan:
        # One source of truth for slot edges: the boundary list carries the end
        # of the last slot, so no slot end is ever recomputed.
        starts = tuple(boundaries[:-1])
        try:
            import pulp
        except ImportError:
            return _invalid_plan(request, starts[0], starts, "PuLP is unavailable", "solver_unavailable", generated_at)
        heaters = tuple(sorted((item for item in request.heaters if item.enabled), key=lambda item: item.id))
        slot_hours = request.slot_minutes / 60
        heating_limit_w = request.max_heating_power_w or request.max_total_power_w
        contracted_limit_w = request.max_total_power_w - request.base_load_w
        limit_w = min(heating_limit_w, contracted_limit_w)
        oversized = tuple(item for item in heaters if item.power_w > limit_w)
        demand_by_key = {(item.heater_id, _key(item.start)): item.demand_kwh for item in demand}
        boundary_index = {_key(boundary): index for index, boundary in enumerate(boundaries)}
        model = pulp.LpProblem("dynamic_thermal_charge", pulp.LpMinimize)
        on = {(h.id, i): pulp.LpVariable(f"on_{h.id}_{i:03d}", cat="Binary") for h in heaters for i in range(len(starts))}
        energy = {(h.id, i): pulp.LpVariable(f"energy_{h.id}_{i:03d}", lowBound=0, upBound=h.capacity_kwh) for h in heaters for i in range(len(starts) + 1)}
        unmet = {(h.id, i): pulp.LpVariable(f"unmet_{h.id}_{i:03d}", lowBound=0, upBound=demand_by_key[(h.id, _key(starts[i]))]) for h in heaters for i in range(len(starts))}
        # A constraint shortfall cannot exceed the energy required by its
        # target.  Keeping this slack bounded also avoids a CBC 2.10.12
        # presolve/postsolve assertion when an exactly feasible 100% target
        # leaves the slack at zero while its upper bound is infinite.
        c_short = {
            index: pulp.LpVariable(
                f"constraint_shortfall_{index:03d}",
                lowBound=0,
                upBound=_heater(heaters, rule.heater_id).capacity_kwh
                * rule.minimum_soc_percent / 100,
            )
            for index, rule in enumerate(constraints)
        }
        for h in heaters:
            initial_energy = h.capacity_kwh * float(request.telemetry[h.id].stored_charge_percent) / 100
            model += energy[(h.id, 0)] == initial_energy
            for i, start in enumerate(starts):
                model += energy[(h.id, i + 1)] == energy[(h.id, i)] + h.charge_power_kw * slot_hours * on[(h.id, i)] - demand_by_key[(h.id, _key(start))] + unmet[(h.id, i)]
            if request.horizon_hours <= PLANNING_HORIZON_HOURS:
                # This prefix bound is implied by the balance equations and
                # unmet_i >= 0. It tightens the LP relaxation by preventing
                # energy from drifting below the cumulative state. Keep it
                # dense only on the standard horizon; its quadratic matrix
                # growth is counterproductive for the optional 48-hour one.
                for boundary in range(1, len(starts) + 1):
                    charge = h.charge_power_kw * slot_hours * pulp.lpSum(
                        on[(h.id, i)] for i in range(boundary)
                    )
                    demand_total = sum(
                        demand_by_key[(h.id, _key(starts[i]))] for i in range(boundary)
                    )
                    model += energy[(h.id, boundary)] >= initial_energy + charge - demand_total
        for i in range(len(starts)):
            heating_power = pulp.lpSum(h.power_w * on[(h.id, i)] for h in heaters)
            # The original rows impose the minimum of these two raw limits.
            # Keeping one row also preserves the intentionally infeasible case
            # where the configured base load exceeds contracted power.
            model += heating_power <= limit_w
        for h in oversized:
            for i in range(len(starts)):
                model += on[(h.id, i)] == 0
        for index, rule in enumerate(constraints):
            model += energy[(rule.heater_id, boundary_index[_key(rule.at)])] + c_short[index] >= _heater(heaters, rule.heater_id).capacity_kwh * rule.minimum_soc_percent / 100
        solver_time_limit_seconds = request.solver_time_limit_seconds or SOLVER_TIME_LIMIT_SECONDS
        solver = _cbc_solver(pulp, time_limit_seconds=solver_time_limit_seconds)
        solver_deadline = monotonic() + solver_time_limit_seconds
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
        solver_started = monotonic()
        logger.debug(
            "Automatic planning solver model built: variables=%d constraints=%d phases=%d "
            "budget_seconds=%.6g",
            len(model.variables()),
            len(model.constraints),
            len(phases),
            solver_time_limit_seconds,
        )
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
            phase_started = monotonic()
            status = model.solve(solver)
            phase_duration = monotonic() - phase_started
            _check_cancelled(request)
            logger.debug(
                "Automatic planning solver phase=%d/%d status=%s duration_seconds=%.6g "
                "total_elapsed_seconds=%.6g budget_seconds=%.6g variables=%d constraints=%d",
                phase_index + 1,
                len(phases),
                pulp.LpStatus[status],
                phase_duration,
                monotonic() - solver_started,
                solver_time_limit_seconds,
                len(model.variables()),
                len(model.constraints),
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
                achieved = float(energy[(h.id, boundary_index[_key(rule.at)])].value() or 0.0) / h.capacity_kwh * 100
                violations.append(PlanningViolation(h.id, "minimum_soc", achieved, short_kwh / h.capacity_kwh * 100, rule.at, "insufficient_capacity_or_power"))
        for h in heaters:
            for i, start in enumerate(starts):
                short = float(unmet[(h.id, i)].value() or 0.0)
                if short > 1e-6:
                    served = demand_by_key[(h.id, _key(start))] - short
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
                start, boundaries[i + 1], active,
                sum(_heater(heaters, heater_id).power_w for heater_id in active),
                {h.id: _charge_percent(energy[(h.id, i + 1)].value(), h.capacity_kwh) for h in heaters},
                {h.id: round(demand_by_key[(h.id, _key(start))] / h.capacity_kwh * 100, 6) for h in heaters},
                _weather_at(start, request.forecast),
                {h.id: float(request.telemetry[h.id].temperature_c) for h in heaters},
                {h.id: _charge_percent(energy[(h.id, i)].value(), h.capacity_kwh) for h in heaters},
                {h.id: round(demand_by_key[(h.id, _key(start))], 9) for h in heaters},
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
            starts[0], boundaries[-1], request.slot_minutes,
            tuple(plan_slots), tuple(violations), DEGRADED if violations or time_limited else FEASIBLE,
            tuple(score), input_token(request), generated_at, explanations, tuple(demand),
        )
        _notify(request, "safety")
        _notify(request, "summary")
        logger.debug(
            "Automatic planning completed: status=%s slots=%d violations=%d token=%s "
            "solver_total_elapsed_seconds=%.6g solver_budget_seconds=%.6g",
            plan.status,
            len(plan.slots),
            len(plan.violations),
            plan.input_token,
            monotonic() - solver_started,
            solver_time_limit_seconds,
        )
        return plan


class DeterministicChargeOptimizer(MilpChargePlanner):
    """Compatibility name for the V1 MILP planner."""


def input_token(request: PlanningInput) -> str:
    # The calculation is anchored to the next slot boundary. The token must
    # use the same stable anchor so preview and activation remain compatible
    # while the clock advances within that slot.
    token_horizon_start = request.horizon_start
    if request.slot_minutes > 0:
        token_horizon_start = align_to_slot(request.horizon_start, request.slot_minutes)
    room_energy = _is_room_energy_request(request)
    payload = {
        "heaters": (
            [
                (
                    h.id,
                    h.power_w,
                    h.full_charge_minutes,
                    h.full_discharge_minutes,
                    h.static_emission_percent,
                    h.enabled,
                    h.priority,
                )
                for h in request.heaters
            ]
            if room_energy
            else [
                (h.id, h.power_w, h.full_charge_minutes, h.enabled, h.priority, h.demand_factor, h.reserve_percent)
                for h in request.heaters
            ]
        ),
        "telemetry": {key: _json_telemetry(value, room_energy=room_energy) for key, value in sorted(request.telemetry.items())},
        "forecast": [(point.timestamp.isoformat(), point.temperature_c, point.interpolated) for point in request.forecast],
        "horizon_start": token_horizon_start.astimezone(timezone.utc).isoformat(),
        "horizon_hours": request.horizon_hours, "slot_minutes": request.slot_minutes,
        "max_total_power_w": request.max_total_power_w, "base_load_w": request.base_load_w, "max_heating_power_w": request.max_heating_power_w,
        "timezone_name": request.timezone_name,
        "forecast_automatic_eligible": request.forecast_automatic_eligible,
        "solver_time_limit_seconds": request.solver_time_limit_seconds or SOLVER_TIME_LIMIT_SECONDS,
    }
    if room_energy:
        payload["room_energy_model"] = True
        # A preview from the previous end-only model must not be reused for
        # activation after the boundary semantics change.
        payload["room_energy_model_version"] = "boundary_targets_v2"
        payload["room_coefficients"] = {
            heater.id: {
                "capacity_kwh_per_c": heater.room_thermal_capacity_kwh_per_c,
                "heat_loss_kw_per_c": heater.room_heat_loss_kw_per_c,
            }
            for heater in sorted(request.heaters, key=lambda item: item.id)
        }
        payload["temperature_targets"] = {
            heater.id: [
                {
                    "target_temperature_c": target.target_temperature_c,
                    "start_time": target.start_time.strftime("%H:%M"),
                    "end_time": target.end_time.strftime("%H:%M"),
                    "weekdays": list(target.weekdays),
                    "enabled": target.enabled,
                }
                for target in _room_targets(request, heater)
            ]
            for heater in sorted(request.heaters, key=lambda item: item.id)
        }
    else:
        payload.update(
            {
                "constraints": [(c.id, c.heater_id, c.target_charge, c.at.isoformat(), c.weekdays) for c in request.constraints],
                "design_indoor_temperature_c": request.design_indoor_temperature_c,
                "design_outdoor_temperature_c": request.design_outdoor_temperature_c,
                "feedback_horizon_hours": request.feedback_horizon_hours,
            }
        )
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _json_telemetry(value: ChargeTelemetry, *, room_energy: bool = False) -> dict[str, object]:
    # Receipt times validate freshness but do not affect the plan itself. They
    # must not invalidate activation when the same fixed/live values are read
    # again a few minutes after the preview.
    if room_energy:
        return {
            "heater_id": value.heater_id,
            "indoor_temperature_c": value.indoor_temperature_c,
            "stored_soc_percent": value.stored_soc_percent,
        }
    return {
        "heater_id": value.heater_id,
        "temperature_c": value.temperature_c,
        "target_temperature_c": value.target_temperature_c,
        "stored_charge_percent": value.stored_charge_percent,
    }


def _charge_percent(value: float | None, capacity_kwh: float) -> float:
    """Round solver noise away at the physical 0/100% boundaries."""
    percent = round(float(value or 0) / capacity_kwh * 100, 6)
    if math.isclose(percent, 0.0, abs_tol=1e-6):
        return 0.0
    if math.isclose(percent, 100.0, abs_tol=1e-6):
        return 100.0
    return percent


def _validate_input(request: PlanningInput) -> None:
    if request.horizon_start.tzinfo is None:
        raise ValueError("horizon_start requires a timezone")
    if request.slot_minutes <= 0 or request.slot_minutes > 60 or 60 % request.slot_minutes:
        raise ValueError("slot_minutes must be a positive divisor of one hour")
    if request.horizon_hours <= 0 or request.horizon_hours > 48:
        raise ValueError("horizon_hours must be between 1 and 48")
    if request.solver_time_limit_seconds is not None and (
        isinstance(request.solver_time_limit_seconds, bool)
        or not isinstance(request.solver_time_limit_seconds, int)
        or request.solver_time_limit_seconds <= 0
    ):
        raise ValueError("solver_time_limit_seconds must be a positive integer")
    if request.max_total_power_w <= 0 or request.base_load_w < 0 or (request.max_heating_power_w is not None and request.max_heating_power_w <= 0):
        raise ValueError("power limits must be positive")
    if not _is_room_energy_request(request):
        if request.design_indoor_temperature_c <= request.design_outdoor_temperature_c:
            raise ValueError("design indoor temperature must exceed design outdoor temperature")
        if request.feedback_horizon_hours <= 0:
            raise ValueError("feedback_horizon_hours must be positive")
    ZoneInfo(request.timezone_name)


def _continuous_forecast_slots(start: datetime, forecast: Sequence[HourlyForecastPoint], horizon_hours: int, slot_minutes: int) -> tuple[datetime, ...]:
    """Every boundary of the covered horizon, including its end.

    The horizon length is counted on the wall clock, so the number of slots is
    not fixed: a 24-hour horizon holds one slot more on the day the clocks go
    back and two fewer on the day they go forward. The previous fixed-count
    guard would have rejected exactly those two days and left the installation
    without a plan, so coverage is now required per slot instead.
    """
    if not forecast:
        return ()
    naive_end = start.replace(tzinfo=None) + timedelta(hours=horizon_hours)
    # Normalised: a horizon that ends on a wall clock that never happens would
    # otherwise resolve to an instant before its own start.
    configured_end = _normalize(naive_end.replace(tzinfo=start.tzinfo))
    boundaries = [start]
    while _key(boundaries[-1]) < _key(configured_end):
        if _weather_at(boundaries[-1], forecast) is None:
            logger.debug("Forecast coverage is not continuous: missing_at=%s", boundaries[-1].isoformat())
            return ()
        boundaries.append(next_slot_boundary(boundaries[-1], slot_minutes))
    return tuple(boundaries) if len(boundaries) > 1 else ()


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
    """The forecast temperature covering an instant.

    Matching is by real time. The repeated hour of a fall-back then has no
    absolute coverage, because the provider publishes one value per wall-clock
    hour, so both of its passes fall back to the value for that wall-clock hour.
    That value is the right one for both -- it is the forecast for that hour --
    so it is not marked as degraded the way an interpolated point is.

    Relying instead on ``<=`` between two same-zone aware datetimes would give
    the same answer today by accident, because that comparison silently uses the
    wall clock; the fallback is written out so the behaviour is intended.
    """
    absolute = [
        point.temperature_c
        for point in points
        if _key(point.timestamp) <= _key(at) < _key(point.timestamp) + timedelta(hours=1)
    ]
    if absolute:
        return float(absolute[-1])
    wall_hour = at.replace(minute=0, second=0, microsecond=0, tzinfo=None)
    reused = [
        point.temperature_c
        for point in points
        if point.timestamp.replace(minute=0, second=0, microsecond=0, tzinfo=None)
        == wall_hour
    ]
    if reused:
        logger.debug("Reusing the forecast for wall-clock hour %s", wall_hour.isoformat())
        return float(reused[-1])
    return None


def _heater(heaters: Sequence[Heater], heater_id: str) -> Heater:
    return next(item for item in heaters if item.id == heater_id)


def _cbc_solver(
    pulp,
    *,
    time_limit_seconds: float | None = None,
    gap_relative: float | None = None,
    warm_start: bool = False,
):
    import shutil
    kwargs = {
        "msg": False,
        "threads": 1,
        "options": ["randomSeed 0"],
        "timeLimit": time_limit_seconds,
        "warmStart": warm_start,
    }
    if gap_relative is not None:
        kwargs["gapRel"] = gap_relative
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


def _clean_solver_energy(value: float) -> float:
    """Remove sub-tolerance energy residue from the public physical trace."""
    return 0.0 if abs(value) <= 1e-6 else value


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
        at, advance_real(at, request.slot_minutes), (), 0,
        {h.id: float(request.telemetry[h.id].stored_charge_percent or 0) if h.id in request.telemetry else 0.0 for h in enabled},
        {h.id: 0.0 for h in enabled}, _weather_at(at, request.forecast), None,
        {h.id: float(request.telemetry[h.id].stored_charge_percent or 0) if h.id in request.telemetry else 0.0 for h in enabled},
        {h.id: 0.0 for h in enabled}, {h.id: 0 for h in enabled},
    ) for at in usable_starts)
    horizon_end = advance_real(usable_starts[-1], request.slot_minutes) if usable_starts else advance_real(start, request.horizon_hours * 60)
    return AutomaticPlan(start, horizon_end, request.slot_minutes, slots, violations, INVALID, (), input_token(request), generated_at)


# --------------------------------------------------------------------------- #
# Room-energy model
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class RoomEnergyInterval:
    """Auditable physical quantities for one heater and one planning slot."""

    heater_id: str
    start: datetime
    end: datetime
    outdoor_temperature_c: float
    target_temperature_c: float | None
    indoor_temperature_c: float
    indoor_temperature_next_c: float
    stored_energy_kwh: float
    stored_energy_next_kwh: float
    stored_soc_percent: float
    stored_soc_next_percent: float
    charge_energy_kwh: float
    heat_delivered_kwh: float
    thermal_loss_kwh: float
    temperature_shortfall_c: float
    temperature_shortfall_start_c: float = 0.0
    heat_delivery_limit_kwh: float = 0.0

    @property
    def demand_kwh(self) -> float:
        """Compatibility name for consumers that call the interval heat need."""
        return max(0.0, self.heat_delivered_kwh)


def _is_room_energy_request(request: PlanningInput) -> bool:
    if request.room_energy_model or bool(request.temperature_targets):
        return True
    # A new telemetry snapshot has no controller-provided target.  Combined
    # with a weekly target on the heater (or a profile created with only the new
    # coefficients), this is enough to select the new calculation for direct
    # callers without making them know about the API switch.
    for heater in request.heaters:
        if not heater.enabled:
            continue
        state = request.telemetry.get(heater.id)
        if state is not None and state.target_temperature_c is None:
            if heater.temperature_targets or (
                heater.thermal is not None
                and heater.thermal.target_temperature_c is None
            ):
                return True
    return False


def _room_targets(
    request: PlanningInput, heater: Heater
) -> tuple[TemperatureTarget, ...]:
    if heater.id in request.temperature_targets:
        supplied = tuple(request.temperature_targets[heater.id])
        return tuple(sorted(supplied, key=_target_sort_key))
    return tuple(sorted(heater.temperature_targets, key=_target_sort_key))


def _target_sort_key(target: TemperatureTarget) -> tuple[object, ...]:
    return (
        target.start_time.hour,
        target.start_time.minute,
        target.end_time.hour,
        target.end_time.minute,
        target.weekdays,
        target.id if target.id is not None else -1,
    )


def active_temperature_target(
    targets: Sequence[TemperatureTarget], at: datetime, timezone_name: str
) -> float | None:
    """Return the target active at an instant according to weekly wall time.

    The selected weekday belongs to the interval start.  A cross-midnight
    interval therefore remains active on the following natural day until its
    exclusive end.  No previous rule is carried forward across a gap.
    """
    if not targets:
        return None
    validate_temperature_targets(tuple(targets))
    zone = ZoneInfo(timezone_name)
    local = at.astimezone(zone)
    minute = local.hour * 60 + local.minute + local.second / 60 + local.microsecond / 60_000_000
    weekday = local.weekday()
    matches: list[TemperatureTarget] = []
    for target in targets:
        if not target.enabled:
            continue
        start = target.start_time.hour * 60 + target.start_time.minute
        end = target.end_time.hour * 60 + target.end_time.minute
        if start == end:
            active = weekday in target.weekdays
        elif end > start:
            active = weekday in target.weekdays and start <= minute < end
        else:
            active = (
                (weekday in target.weekdays and minute >= start)
                or (((weekday - 1) % 7) in target.weekdays and minute < end)
            )
        if active:
            matches.append(target)
    if not matches:
        return None
    if len(matches) > 1:
        # The domain validation above should make this unreachable, but keep a
        # deterministic guard for callers supplying a non-standard sequence.
        raise ValueError("multiple temperature target intervals are active")
    return float(matches[0].target_temperature_c)


def _target_window_for_at(
    targets: Sequence[TemperatureTarget], at: datetime, timezone_name: str
) -> tuple[datetime, datetime] | None:
    """Return the concrete occurrence of the weekly target covering ``at``."""
    zone = ZoneInfo(timezone_name)
    local = at.astimezone(zone)
    minute = local.hour * 60 + local.minute + local.second / 60 + local.microsecond / 60_000_000
    weekday = local.weekday()
    local_date = local.date()
    for target in targets:
        if not target.enabled:
            continue
        start = target.start_time.hour * 60 + target.start_time.minute
        end = target.end_time.hour * 60 + target.end_time.minute
        if start == end:
            if weekday not in target.weekdays:
                continue
            return (
                datetime.combine(local_date, target.start_time, tzinfo=zone),
                datetime.combine(local_date + timedelta(days=1), target.end_time, tzinfo=zone),
            )
        if end > start:
            if weekday not in target.weekdays or not start <= minute < end:
                continue
            return (
                datetime.combine(local_date, target.start_time, tzinfo=zone),
                datetime.combine(local_date, target.end_time, tzinfo=zone),
            )
        if weekday in target.weekdays and minute >= start:
            return (
                datetime.combine(local_date, target.start_time, tzinfo=zone),
                datetime.combine(local_date + timedelta(days=1), target.end_time, tzinfo=zone),
            )
        previous_weekday = (weekday - 1) % 7
        if previous_weekday in target.weekdays and minute < end:
            previous_date = local_date - timedelta(days=1)
            return (
                datetime.combine(previous_date, target.start_time, tzinfo=zone),
                datetime.combine(local_date, target.end_time, tzinfo=zone),
            )
    return None


def _target_occurrence_for_at(
    targets: Sequence[TemperatureTarget], at: datetime, timezone_name: str
) -> tuple[TemperatureTarget, datetime, datetime] | None:
    """Return the weekly target rule and concrete window active at ``at``."""
    for target in targets:
        if not target.enabled:
            continue
        if active_temperature_target((target,), at, timezone_name) is None:
            continue
        window = _target_window_for_at((target,), at, timezone_name)
        if window is not None:
            return target, window[0], window[1]
    return None


def _next_target_occurrence(
    targets: Sequence[TemperatureTarget], at: datetime, timezone_name: str
) -> tuple[TemperatureTarget, datetime, datetime] | None:
    """Return the next concrete weekly target occurrence after ``at``."""
    if not targets:
        return None
    validate_temperature_targets(tuple(targets))
    zone = ZoneInfo(timezone_name)
    local = at.astimezone(zone)
    candidates: list[tuple[TemperatureTarget, datetime, datetime]] = []
    # The planning horizon is at most 48 hours, but two weeks also covers the
    # next occurrence of a rule on any weekday without relying on that limit.
    for day_offset in range(-1, 15):
        local_date = local.date() + timedelta(days=day_offset)
        weekday = local_date.weekday()
        for target in targets:
            if not target.enabled or weekday not in target.weekdays:
                continue
            start = datetime.combine(local_date, target.start_time, tzinfo=zone)
            end_time = target.end_time
            end_date = local_date
            if target.start_time == end_time or end_time <= target.start_time:
                end_date += timedelta(days=1)
            end = datetime.combine(end_date, end_time, tzinfo=zone)
            if _key(start) < _key(at) or _key(end) <= _key(at):
                continue
            candidates.append((target, start, end))
    if not candidates:
        return None
    return min(candidates, key=lambda item: (_key(item[1]), _target_sort_key(item[0])))


def _value_from_violation(
    violation: PlanningViolation | Mapping[str, Any], name: str, default: Any = None
) -> Any:
    if isinstance(violation, Mapping):
        return violation.get(name, default)
    return getattr(violation, name, default)


def _violation_time_key(value: Any) -> tuple[int, str]:
    if isinstance(value, datetime):
        return (0, _key(value).isoformat())
    if value is None:
        return (2, "")
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return (1, str(value))
    return (0, _key(parsed).isoformat() if parsed.tzinfo is not None else parsed.isoformat())


def group_planning_violations(
    violations: Sequence[PlanningViolation | Mapping[str, Any]],
    *,
    slot_minutes: int | None = None,
) -> list[dict[str, Any]]:
    """Collapse consecutive observations for the operator-facing summary.

    The input is intentionally left untouched: callers can expose the returned
    groups while retaining every original boundary observation in the technical
    ``violations`` collection.
    """
    grouped: dict[tuple[Any, ...], list[PlanningViolation | Mapping[str, Any]]] = {}
    for violation in violations:
        reason = str(_value_from_violation(violation, "reason", ""))
        window_start = _value_from_violation(violation, "target_window_start")
        window_end = _value_from_violation(violation, "target_window_end")
        key = (
            _value_from_violation(violation, "heater_id"),
            _value_from_violation(violation, "requirement", ""),
            reason.split(":", 1)[0],
            _violation_time_key(window_start),
            _violation_time_key(window_end),
        )
        grouped.setdefault(key, []).append(violation)

    result: list[dict[str, Any]] = []
    for candidates in grouped.values():
        ordered_candidates = sorted(
            candidates,
            key=lambda item: _violation_time_key(_value_from_violation(item, "at")),
        )
        runs: list[list[PlanningViolation | Mapping[str, Any]]] = []
        for item in ordered_candidates:
            if not runs or not _violation_run_is_contiguous(
                runs[-1][-1], item, slot_minutes
            ):
                runs.append([item])
            else:
                runs[-1].append(item)
        for items in runs:
            ordered = sorted(
                items,
                key=lambda item: _violation_time_key(_value_from_violation(item, "at")),
            )
            first = ordered[0]
            shortfalls = [
                float(value)
                for item in items
                if (value := _value_from_violation(item, "shortfall")) is not None
            ]
            achievable = [
                float(value)
                for item in items
                if (value := _value_from_violation(item, "achievable_value")) is not None
            ]
            first_shortfall = _value_from_violation(first, "shortfall")
            first_achievable = _value_from_violation(first, "achievable_value")
            requirement = str(_value_from_violation(first, "requirement", ""))
            max_shortfall = max(shortfalls, default=None)
            first_at = _value_from_violation(first, "at")
            last_at = _value_from_violation(ordered[-1], "at")
            result.append(
                {
                    "heater_id": _value_from_violation(first, "heater_id"),
                    "requirement": requirement,
                    "achievable_value": min(achievable) if achievable else first_achievable,
                    "shortfall": max_shortfall,
                    "at": first_at,
                    "reason": str(_value_from_violation(first, "reason", "")).split(":", 1)[0],
                    "target_temperature_c": (
                        float(first_achievable) + float(first_shortfall)
                        if requirement == "temperature_comfort"
                        and first_achievable is not None
                        and first_shortfall is not None
                        else None
                    ),
                    "projected_temperature_c": min(achievable) if achievable else None,
                    "shortfall_c": max_shortfall if requirement == "temperature_comfort" else None,
                    "stored_energy_kwh": _value_from_violation(first, "stored_energy_kwh"),
                    "stored_soc_percent": _value_from_violation(first, "stored_soc_percent"),
                    "target_window_start": _value_from_violation(first, "target_window_start"),
                    "target_window_end": _value_from_violation(first, "target_window_end"),
                    "affected_from": first_at,
                    "affected_until": last_at,
                    "observation_count": len(items),
                }
            )
    return sorted(
        result,
        key=lambda item: (
            _violation_time_key(item.get("target_window_start")),
            _violation_time_key(item.get("affected_from")),
            str(item.get("heater_id") or ""),
        ),
    )


def _violation_run_is_contiguous(
    previous: PlanningViolation | Mapping[str, Any],
    current: PlanningViolation | Mapping[str, Any],
    slot_minutes: int | None,
) -> bool:
    """Keep separate runs separate when a target gap has no observations."""
    if slot_minutes is None or slot_minutes <= 0:
        return True
    previous_at = _violation_datetime(_value_from_violation(previous, "at"))
    current_at = _violation_datetime(_value_from_violation(current, "at"))
    if previous_at is None or current_at is None:
        return True
    if previous_at.tzinfo is not None and current_at.tzinfo is not None:
        elapsed = (_key(current_at) - _key(previous_at)).total_seconds()
    else:
        elapsed = (current_at - previous_at).total_seconds()
    return elapsed <= slot_minutes * 60 + 1e-6


def _violation_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if value is None:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _room_telemetry_usable(value: ChargeTelemetry | None) -> bool:
    if value is None or value.indoor_temperature_c is None or value.stored_soc_percent is None:
        return False
    return value.indoor_received_at is not None and value.stored_soc_received_at is not None


def _room_telemetry_fresh(
    value: ChargeTelemetry | None,
    observed_at: datetime,
    max_age_seconds: float = 900,
) -> bool:
    if not _room_telemetry_usable(value):
        return False
    assert value is not None
    return all(
        0 <= (observed_at - received_at).total_seconds() <= max_age_seconds
        for received_at in (value.indoor_received_at, value.stored_soc_received_at)
        if received_at is not None
    )


def _heat_delivery_limit_kwh(
    heater: Heater, slot_minutes: int, stored_energy_kwh: float
) -> float:
    """Return the emission limit for one slot at a given state of charge.

    A storage heater emits less as its core cools, so the capability decays
    with the state of charge from ``emission_power_kw`` down to the residual
    ``static_emission_power_kw``.  The state of charge is the one at the slot
    start, before its own charge: conservative, and affine in the stored energy
    so the optimiser keeps the same limit as a linear constraint.
    """
    floor_kw = heater.static_emission_power_kw
    span_kw = heater.emission_power_kw - floor_kw
    state_of_charge = stored_energy_kwh / heater.capacity_kwh
    return (floor_kw + span_kw * state_of_charge) * slot_minutes / 60


def room_energy_step(
    heater: Heater,
    *,
    start: datetime,
    outdoor_temperature_c: float,
    target_temperature_c: float | None,
    indoor_temperature_c: float,
    stored_energy_kwh: float,
    slot_minutes: int,
    charge_on: bool = False,
    heat_delivered_kwh: float | None = None,
) -> RoomEnergyInterval:
    """Project one physical room/storage interval.

    ``charge_on`` is the discrete electrical decision.  If no heat quantity is
    supplied, the ideal room controller delivers the least heat that reaches
    the target, limited by the energy available after that charge decision.
    This helper is also the equation boundary used by tests and explanations;
    it never maps SOC directly to a temperature.
    """
    if slot_minutes <= 0:
        raise ValueError("slot_minutes must be positive")
    values = (outdoor_temperature_c, indoor_temperature_c, stored_energy_kwh)
    if not all(math.isfinite(float(value)) for value in values):
        raise ValueError("room-energy values must be finite")
    if target_temperature_c is not None and not math.isfinite(float(target_temperature_c)):
        raise ValueError("target_temperature_c must be finite when present")
    capacity = heater.room_thermal_capacity_kwh_per_c
    heat_loss_coefficient = heater.room_heat_loss_kw_per_c
    if stored_energy_kwh < -1e-9 or stored_energy_kwh > heater.capacity_kwh + 1e-9:
        raise ValueError("stored energy must be between zero and accumulator capacity")
    stored_energy_kwh = max(0.0, min(heater.capacity_kwh, stored_energy_kwh))
    hours = slot_minutes / 60
    charge_energy = heater.charge_power_kw * hours if charge_on else 0.0
    thermal_loss = heat_loss_coefficient * (
        indoor_temperature_c - outdoor_temperature_c
    ) * hours
    no_heat_next = indoor_temperature_c - thermal_loss / capacity
    required_heat = (
        0.0
        if target_temperature_c is None
        else max(0.0, (target_temperature_c - no_heat_next) * capacity)
    )
    available = stored_energy_kwh + charge_energy
    heat = required_heat if heat_delivered_kwh is None else float(heat_delivered_kwh)
    if not math.isfinite(heat) or heat < 0:
        raise ValueError("heat_delivered_kwh must be finite and non-negative")
    delivery_limit = _heat_delivery_limit_kwh(
        heater, slot_minutes, stored_energy_kwh
    )
    heat = min(heat, available, delivery_limit)
    stored_next = max(0.0, min(heater.capacity_kwh, available - heat))
    indoor_next = indoor_temperature_c + (heat - thermal_loss) / capacity
    return RoomEnergyInterval(
        heater_id=heater.id,
        start=start,
        end=advance_real(start, slot_minutes),
        outdoor_temperature_c=float(outdoor_temperature_c),
        target_temperature_c=(
            None if target_temperature_c is None else float(target_temperature_c)
        ),
        indoor_temperature_c=float(indoor_temperature_c),
        indoor_temperature_next_c=float(indoor_next),
        stored_energy_kwh=float(stored_energy_kwh),
        stored_energy_next_kwh=float(stored_next),
        stored_soc_percent=float(stored_energy_kwh / heater.capacity_kwh * 100),
        stored_soc_next_percent=float(stored_next / heater.capacity_kwh * 100),
        charge_energy_kwh=float(charge_energy),
        heat_delivered_kwh=float(heat),
        thermal_loss_kwh=float(thermal_loss),
        temperature_shortfall_c=(
            0.0
            if target_temperature_c is None
            else float(max(0.0, target_temperature_c - indoor_next))
        ),
        temperature_shortfall_start_c=(
            0.0
            if target_temperature_c is None
            else float(max(0.0, target_temperature_c - indoor_temperature_c))
        ),
        heat_delivery_limit_kwh=float(delivery_limit),
    )


class RoomEnergyDemandEstimator:
    """Calculate the room balance without deriving temperature from SOC."""

    name = "room_energy_balance_v1"

    def estimate(
        self,
        heaters: Sequence[Heater],
        telemetry: Mapping[str, ChargeTelemetry],
        forecast: Sequence[HourlyForecastPoint],
        starts: Sequence[datetime],
        slot_minutes: int,
        *,
        timezone_name: str = "UTC",
        targets: Mapping[str, Sequence[TemperatureTarget]] | None = None,
        charge_on: Mapping[str, Sequence[bool]] | None = None,
        heat_delivered_kwh: Mapping[str, Sequence[float | None]] | None = None,
    ) -> tuple[RoomEnergyInterval, ...]:
        result: list[RoomEnergyInterval] = []
        target_map = {} if targets is None else targets
        for heater in sorted((item for item in heaters if item.enabled), key=lambda item: item.id):
            state = telemetry.get(heater.id)
            if not _room_telemetry_usable(state):
                raise ValueError(f"missing required telemetry for heater {heater.id}")
            assert state is not None
            target_rules = (
                tuple(target_map[heater.id])
                if heater.id in target_map
                else tuple(heater.temperature_targets)
            )
            validate_temperature_targets(target_rules)
            if not any(target.enabled for target in target_rules):
                raise ValueError(f"missing weekly temperature target schedule for heater {heater.id}")
            inside = float(state.indoor_temperature_c)
            stored = heater.capacity_kwh * float(state.stored_soc_percent) / 100
            on_values = tuple(charge_on.get(heater.id, (False,) * len(starts))) if charge_on else (False,) * len(starts)
            heat_values = tuple(heat_delivered_kwh.get(heater.id, (None,) * len(starts))) if heat_delivered_kwh else (None,) * len(starts)
            if len(on_values) != len(starts) or len(heat_values) != len(starts):
                raise ValueError(f"room-energy decisions for heater {heater.id} do not cover every interval")
            for index, start in enumerate(starts):
                outdoor = _weather_at(start, forecast)
                target = active_temperature_target(target_rules, start, timezone_name)
                if outdoor is None:
                    raise ValueError(f"missing room-energy inputs at {start.isoformat()}")
                interval = room_energy_step(
                    heater,
                    start=start,
                    outdoor_temperature_c=outdoor,
                    target_temperature_c=target,
                    indoor_temperature_c=inside,
                    stored_energy_kwh=stored,
                    slot_minutes=slot_minutes,
                    charge_on=on_values[index],
                    heat_delivered_kwh=heat_values[index],
                )
                result.append(interval)
                inside, stored = interval.indoor_temperature_next_c, interval.stored_energy_next_kwh
        return tuple(result)


class RoomEnergyPlanner:
    """Public planner entry point for the coupled room/storage model."""

    def build(self, request: PlanningInput) -> AutomaticPlan:
        return _build_room_energy_plan(request)


def _build_room_energy_plan(request: PlanningInput) -> AutomaticPlan:
    generated_at = request.generated_at or request.horizon_start
    _notify(request, "inputs")
    _check_cancelled(request)
    try:
        _validate_input(request)
        if request.constraints:
            raise ValueError("percentage charge constraints are not accepted by the room-energy planner")
        horizon_start = align_to_slot(request.horizon_start, request.slot_minutes)
    except (ValueError, ArithmeticError) as exc:
        return _invalid_room_plan(
            request, request.horizon_start, (), str(exc), "invalid_configuration", generated_at
        )
    boundaries = _continuous_forecast_slots(
        horizon_start, request.forecast, request.horizon_hours, request.slot_minutes
    )
    starts = boundaries[:-1] if boundaries else ()
    if not starts or not request.forecast_automatic_eligible:
        reason = "forecast_not_eligible" if not request.forecast_automatic_eligible else "missing_forecast_coverage"
        return _invalid_room_plan(request, horizon_start, starts, reason, reason, generated_at)
    missing_telemetry = [
        heater.id
        for heater in request.heaters
        if heater.enabled and not _room_telemetry_fresh(
            request.telemetry.get(heater.id), request.horizon_start
        )
    ]
    if missing_telemetry:
        return _invalid_room_plan(
            request,
            horizon_start,
            starts,
            "missing fresh indoor temperature or stored SOC telemetry",
            "missing_required_state",
            generated_at,
            missing_telemetry,
        )
    missing_targets = [
        heater.id
        for heater in request.heaters
        if heater.enabled
        and not any(target.enabled for target in _room_targets(request, heater))
    ]
    if missing_targets:
        return _invalid_room_plan(
            request,
            horizon_start,
            starts,
            "missing weekly temperature target schedule",
            "missing_temperature_schedule",
            generated_at,
            missing_targets,
        )
    try:
        for heater in request.heaters:
            if heater.enabled:
                validate_temperature_targets(_room_targets(request, heater))
    except ValueError as exc:
        return _invalid_room_plan(
            request,
            horizon_start,
            starts,
            str(exc),
            "invalid_temperature_schedule",
            generated_at,
        )
    _notify(request, "telemetry")
    _notify(request, "room_model")
    try:
        return _solve_room_energy(request, boundaries, generated_at)
    except (ValueError, ArithmeticError) as exc:
        logger.debug("Room-energy planning rejected: %s", exc)
        return _invalid_room_plan(
            request, horizon_start, starts, str(exc), "invalid_configuration", generated_at
        )


def _room_convergence_by_heater(
    intervals: Sequence[RoomEnergyInterval],
    heaters: Sequence[Heater],
    horizon_end: datetime,
    *,
    targets: Mapping[str, Sequence[TemperatureTarget]] | None = None,
    timezone_name: str = "UTC",
    tolerance: float = 1e-6,
) -> dict[str, datetime]:
    """Find the first active target boundary after which comfort stays met."""
    result: dict[str, datetime] = {}
    target_map = targets or {}
    for heater in heaters:
        # A room target is an invariant at both borders of each active slot.
        # Do not count a target-window end or an untargeted gap as evidence:
        # the target must still be active at the boundary after the interval.
        observations_by_boundary: dict[datetime, tuple[datetime, float]] = {}
        for interval in intervals:
            if interval.heater_id != heater.id or interval.target_temperature_c is None:
                continue
            start_key = _key(interval.start)
            previous = observations_by_boundary.get(start_key)
            if previous is None or interval.temperature_shortfall_start_c > previous[1]:
                observations_by_boundary[start_key] = (
                    interval.start,
                    interval.temperature_shortfall_start_c,
                )
            end_target = active_temperature_target(
                target_map.get(heater.id, ()), interval.end, timezone_name
            )
            if end_target is not None and math.isclose(
                end_target, interval.target_temperature_c, abs_tol=tolerance
            ):
                end_key = _key(interval.end)
                previous = observations_by_boundary.get(end_key)
                if previous is None or interval.temperature_shortfall_c > previous[1]:
                    observations_by_boundary[end_key] = (
                        interval.end,
                        interval.temperature_shortfall_c,
                    )
        observations = sorted(
            observations_by_boundary.values(), key=lambda item: _key(item[0])
        )
        if not observations or not any(shortfall > tolerance for _, shortfall in observations):
            continue
        # A converging plan may only start with a deficit.  If a later target
        # becomes deficient after an already-satisfied boundary, it is not a
        # temporary adaptation and must remain DEGRADED.
        first_deficit = next(
            index for index, (_, shortfall) in enumerate(observations) if shortfall > tolerance
        )
        if first_deficit != 0:
            continue
        for index in range(1, len(observations)):
            at, shortfall = observations[index]
            if shortfall > tolerance:
                continue
            if all(value <= tolerance for _, value in observations[index:]):
                if _key(at) < _key(horizon_end):
                    result[heater.id] = at
                break
    return result


def _room_heater_explanation(
    heater: Heater,
    intervals: Sequence[RoomEnergyInterval],
    request: PlanningInput,
) -> HeaterExplanation:
    """Summarise a room plan from its persisted physical interval series."""
    state = request.telemetry[heater.id]
    targets = _room_targets(request, heater)
    initial_indoor = float(state.indoor_temperature_c)
    initial_stored = (
        intervals[0].stored_energy_kwh
        if intervals
        else heater.capacity_kwh * float(state.stored_soc_percent) / 100
    )
    final_indoor = (
        intervals[-1].indoor_temperature_next_c
        if intervals
        else initial_indoor
    )
    final_stored = (
        intervals[-1].stored_energy_next_kwh
        if intervals
        else initial_stored
    )
    current_target = _target_occurrence_for_at(
        targets, request.horizon_start, request.timezone_name
    )
    next_target = current_target or _next_target_occurrence(
        targets, request.horizon_start, request.timezone_name
    )
    charge_reasons: list[dict[str, Any]] = []
    charge_periods: list[tuple[datetime, datetime]] = []
    for interval in intervals:
        if interval.charge_energy_kwh <= 1e-6:
            continue
        charge_periods.append((interval.start, interval.end))
        active_target = _target_occurrence_for_at(
            targets, interval.start, request.timezone_name
        )
        target_occurrence = active_target or _next_target_occurrence(
            targets, interval.start, request.timezone_name
        )
        reason = (
            "necessary_for_target"
            if active_target is not None
            else "preheating_for_next_target"
            if target_occurrence is not None
            else "residual_storage"
        )
        charge_reasons.append(
            {
                "start": interval.start,
                "end": interval.end,
                "reason": reason,
                "target_temperature_c": (
                    None
                    if target_occurrence is None
                    else float(target_occurrence[0].target_temperature_c)
                ),
                "target_window_start": (
                    None if target_occurrence is None else target_occurrence[1]
                ),
                "target_window_end": (
                    None if target_occurrence is None else target_occurrence[2]
                ),
                "charge_energy_kwh": interval.charge_energy_kwh,
                "heat_delivered_kwh": interval.heat_delivered_kwh,
            }
        )
    return HeaterExplanation(
        heater_id=heater.id,
        actual_soc_percent=float(state.stored_soc_percent),
        total_demand_kwh=sum(item.heat_delivered_kwh for item in intervals),
        demand_factor=1.0,
        reserve_percent=0.0,
        next_constraint_at=None if next_target is None else next_target[1],
        charge_periods=tuple(charge_periods),
        capacity_kwh=heater.capacity_kwh,
        initial_indoor_temperature_c=initial_indoor,
        final_indoor_temperature_c=final_indoor,
        total_heat_delivered_kwh=sum(item.heat_delivered_kwh for item in intervals),
        total_thermal_loss_kwh=sum(item.thermal_loss_kwh for item in intervals),
        maximum_temperature_shortfall_c=max(
            (
                max(item.temperature_shortfall_c, item.temperature_shortfall_start_c)
                for item in intervals
            ),
            default=0.0,
        ),
        initial_stored_energy_kwh=initial_stored,
        final_stored_energy_kwh=final_stored,
        total_charge_energy_kwh=sum(item.charge_energy_kwh for item in intervals),
        forecast_contribution_kwh=-sum(item.thermal_loss_kwh for item in intervals),
        terminal_surplus_energy_kwh=max(0.0, final_stored - initial_stored),
        next_target_temperature_c=(
            None
            if next_target is None
            else float(next_target[0].target_temperature_c)
        ),
        next_target_start=None if next_target is None else next_target[1],
        next_target_end=None if next_target is None else next_target[2],
        charge_reasons=tuple(charge_reasons),
    )


def _solve_room_energy(
    request: PlanningInput, boundaries: Sequence[datetime], generated_at: datetime
) -> AutomaticPlan:
    try:
        import pulp
    except ImportError:
        return _invalid_room_plan(
            request, boundaries[0], boundaries[:-1], "PuLP is unavailable", "solver_unavailable", generated_at
        )
    heaters = tuple(sorted((item for item in request.heaters if item.enabled), key=lambda item: item.id))
    starts = tuple(boundaries[:-1])
    slot_hours = request.slot_minutes / 60
    limit_w = min(
        request.max_heating_power_w or request.max_total_power_w,
        request.max_total_power_w - request.base_load_w,
    )
    if limit_w <= 0:
        return _invalid_room_plan(
            request, starts[0], starts, "no electrical power remains for heating", "infeasible_power_configuration", generated_at
        )
    model = pulp.LpProblem("dynamic_room_energy", pulp.LpMinimize)
    on = {
        (heater.id, index): pulp.LpVariable(f"room_on_{heater.id}_{index:03d}", cat="Binary")
        for heater in heaters
        for index in range(len(starts))
    }
    stored = {
        (heater.id, index): pulp.LpVariable(
            f"stored_energy_{heater.id}_{index:03d}",
            lowBound=0,
            upBound=heater.capacity_kwh,
        )
        for heater in heaters
        for index in range(len(starts) + 1)
    }
    indoor = {
        (heater.id, index): pulp.LpVariable(
            f"indoor_temperature_{heater.id}_{index:03d}",
            lowBound=-100,
            upBound=100,
        )
        for heater in heaters
        for index in range(len(starts) + 1)
    }
    heat = {
        (heater.id, index): pulp.LpVariable(
            f"heat_delivered_{heater.id}_{index:03d}", lowBound=0
        )
        for heater in heaters
        for index in range(len(starts))
    }
    shortfall = {
        (heater.id, index): pulp.LpVariable(
            f"temperature_shortfall_{heater.id}_{index:03d}", lowBound=0, upBound=200
        )
        for heater in heaters
        for index in range(len(starts))
    }
    start_shortfall = {
        (heater.id, index): pulp.LpVariable(
            f"temperature_start_shortfall_{heater.id}_{index:03d}",
            lowBound=0,
            upBound=200,
        )
        for heater in heaters
        for index in range(len(starts))
    }
    charge = {
        (heater.id, index): heater.charge_power_kw * slot_hours * on[(heater.id, index)]
        for heater in heaters
        for index in range(len(starts))
    }
    target_values: dict[tuple[str, int], float | None] = {}
    outdoor_values: dict[tuple[str, int], float] = {}
    for heater in heaters:
        state = request.telemetry[heater.id]
        model += stored[(heater.id, 0)] == heater.capacity_kwh * float(state.stored_soc_percent) / 100
        model += indoor[(heater.id, 0)] == float(state.indoor_temperature_c)
        targets = _room_targets(request, heater)
        for index, start in enumerate(starts):
            outdoor = _weather_at(start, request.forecast)
            if outdoor is None:
                raise ValueError(f"missing forecast at {start.isoformat()}")
            outdoor_values[(heater.id, index)] = outdoor
            target_values[(heater.id, index)] = active_temperature_target(
                targets, start, request.timezone_name
            )
        # The discharge system only emits on demand, so a slot with no target
        # ahead of it never delivers heat.  A slot inside a gap that precedes a
        # target may still emit, which is what lets the plan preheat towards
        # the starting edge of that target.
        emission_allowed: list[bool] = []
        target_ahead = False
        for index in reversed(range(len(starts))):
            target_ahead = target_ahead or target_values[(heater.id, index)] is not None
            emission_allowed.append(target_ahead)
        emission_allowed.reverse()
        emission_floor_kwh = heater.static_emission_power_kw * slot_hours
        emission_span_kwh = (
            heater.emission_power_kw - heater.static_emission_power_kw
        ) * slot_hours
        for index in range(len(starts)):
            outdoor = outdoor_values[(heater.id, index)]
            target = target_values[(heater.id, index)]
            loss_factor = heater.room_heat_loss_kw_per_c * slot_hours
            capacity = heater.room_thermal_capacity_kwh_per_c
            model += heat[(heater.id, index)] <= stored[(heater.id, index)] + charge[(heater.id, index)]
            # Emission capability decays with the state of charge, so a poorly
            # charged accumulator can no longer reach the target however much
            # time it is given.  Affine in ``stored``, so no binary is needed.
            model += heat[(heater.id, index)] <= (
                emission_floor_kwh
                + emission_span_kwh * stored[(heater.id, index)] / heater.capacity_kwh
            )
            if not emission_allowed[index]:
                model += heat[(heater.id, index)] == 0
            model += stored[(heater.id, index + 1)] == stored[(heater.id, index)] + charge[(heater.id, index)] - heat[(heater.id, index)]
            # E_loss = K_room * (T_inside - T_outside) * dt, substituted into
            # the affine temperature balance below.  This retains the sign:
            # warmer outdoor air produces a negative exchange.
            model += indoor[(heater.id, index + 1)] == (
                (1 - loss_factor / capacity) * indoor[(heater.id, index)]
                + heat[(heater.id, index)] / capacity
                + loss_factor * outdoor / capacity
            )
            if target is None:
                model += shortfall[(heater.id, index)] == 0
                model += start_shortfall[(heater.id, index)] == 0
            else:
                # A target is a boundary invariant, not merely an end-of-slot
                # result. The start row makes the optimiser preheat in earlier
                # untargeted slots when that is necessary.
                model += start_shortfall[(heater.id, index)] >= target - indoor[(heater.id, index)]
                model += shortfall[(heater.id, index)] >= target - indoor[(heater.id, index + 1)]
    for index in range(len(starts)):
        model += sum(heater.power_w * on[(heater.id, index)] for heater in heaters) <= limit_w

    initial_energy = {
        heater.id: heater.capacity_kwh
        * float(request.telemetry[heater.id].stored_soc_percent)
        / 100
        for heater in heaters
    }
    terminal_surplus = {
        heater.id: pulp.LpVariable(
            f"terminal_surplus_{heater.id}", lowBound=0
        )
        for heater in heaters
    }
    for heater in heaters:
        # Only energy added by this plan is eligible for the terminal-surplus
        # tie-breaker. Existing stored energy is a real input, not an implicit
        # reserve that the optimiser may discharge merely to improve its score.
        model += terminal_surplus[heater.id] >= (
            stored[(heater.id, len(starts))] - initial_energy[heater.id]
        )

    total_charge = pulp.lpSum(charge.values())
    total_heat = pulp.lpSum(heat.values())
    premature_heat = pulp.lpSum(
        heat[(heater.id, index)]
        for heater in heaters
        for index in range(len(starts))
        if target_values[(heater.id, index)] is None
    )
    latest_charge = pulp.lpSum(
        (len(starts) - index)
        * charge[(heater.id, index)]
        for heater in heaters
        for index in range(len(starts))
    )
    deterministic = pulp.lpSum(
        on[(heater.id, index)] * (index + 1) * (position + 1)
        for position, heater in enumerate(heaters)
        for index in range(len(starts))
    )
    heat_timing = pulp.lpSum(
        (len(starts) - index) * (position + 1) * heat[(heater.id, index)]
        for position, heater in enumerate(heaters)
        for index in range(len(starts))
    )
    # Keep the objectives genuinely lexicographic for compact decision spaces.
    # A weighted sum can trade a measurable comfort deficit for a cheaper
    # schedule when CBC's tolerances are larger than the secondary
    # coefficients. Solving and locking each phase makes priority, comfort,
    # energy, terminal state and recency explicit. Full rolling-horizon
    # installations can contain hundreds of binary decisions, however; a
    # repeated MILP solve there exhausts the planning budget before returning
    # an actionable plan. The bounded scalar fallback below keeps the same
    # order of terms and uses CBC's fast incumbent search for that case.
    comfort_phases = [
        pulp.lpSum(
            shortfall[(heater.id, index)] + start_shortfall[(heater.id, index)]
            for heater in heaters
            if heater.priority == priority
            for index in range(len(starts))
        )
        for priority in sorted({heater.priority for heater in heaters}, reverse=True)
    ]
    secondary_phases = (
        total_charge,
        pulp.lpSum(terminal_surplus.values()),
        total_heat,
        premature_heat,
        latest_charge,
        deterministic,
        heat_timing,
    )
    lexicographic_model = len(on) <= 96
    if lexicographic_model:
        phases = comfort_phases + list(secondary_phases)
        solver_gap_relative = None
    else:
        priorities = sorted({heater.priority for heater in heaters}, reverse=True)
        comfort_bounds = {
            priority: float(400 * len(starts) * max(
                1, sum(heater.priority == priority for heater in heaters)
            ))
            for priority in priorities
        }
        weighted_comfort = pulp.lpSum(
            (2 ** (len(priorities) - rank - 1))
            * objective
            / comfort_bounds[priority]
            for rank, (priority, objective) in enumerate(zip(priorities, comfort_phases))
        )
        charge_bound = max(
            1.0,
            sum(
                heater.capacity_kwh
                + heater.charge_power_kw * slot_hours * len(starts)
                for heater in heaters
            ),
        )
        heat_bound = charge_bound
        terminal_bound = max(1.0, sum(heater.capacity_kwh for heater in heaters))
        latest_bound = max(1.0, charge_bound * len(starts))
        deterministic_bound = max(
            1.0,
            sum(
                (index + 1) * (position + 1)
                for position in range(len(heaters))
                for index in range(len(starts))
            ),
        )
        heat_timing_bound = max(
            1.0, heat_bound * len(starts) * max(1, len(heaters))
        )
        weighted_objective = (
            1e13 * weighted_comfort
            + 1e6 * total_charge / charge_bound
            + 1e3 * pulp.lpSum(terminal_surplus.values()) / terminal_bound
            + total_heat / heat_bound
            + 1e-3 * premature_heat / heat_bound
            + 1e-6 * latest_charge / latest_bound
            + 1e-9 * heat_timing / heat_timing_bound
            + 1e-12 * deterministic / deterministic_bound
        )
        phases = [weighted_objective]
        solver_gap_relative = 1.0
    score: list[float] = []
    solver_started = monotonic()
    time_limit = float(request.solver_time_limit_seconds or SOLVER_TIME_LIMIT_SECONDS)
    solver_deadline = solver_started + time_limit
    time_limited = False
    _notify(request, "solver")
    logger.debug(
        "Room-energy solver model built: variables=%d constraints=%d phases=%d "
        "budget_seconds=%.6g",
        len(model.variables()),
        len(model.constraints),
        len(phases),
        time_limit,
    )
    for phase_index, objective in enumerate(phases):
        _notify(request, f"solver_phase_{phase_index + 1}")
        _check_cancelled(request)
        remaining_seconds = solver_deadline - monotonic()
        if remaining_seconds <= 0:
            if not _model_solution_is_feasible(model, pulp, on):
                return _invalid_room_plan(
                    request,
                    starts[0],
                    starts,
                    "solver reached its total time limit without a verified feasible room-energy plan",
                    "solver_failure",
                    generated_at,
                )
            time_limited = True
            break
        phase_started = monotonic()
        model.setObjective(objective)
        status = model.solve(
            _cbc_solver(
                pulp,
                time_limit_seconds=remaining_seconds,
                gap_relative=solver_gap_relative,
                warm_start=phase_index > 0,
            )
        )
        phase_duration = monotonic() - phase_started
        _check_cancelled(request)
        logger.debug(
            "Room-energy solver phase=%d/%d status=%s duration_seconds=%.6g "
            "total_elapsed_seconds=%.6g budget_seconds=%.6g variables=%d constraints=%d",
            phase_index + 1,
            len(phases),
            pulp.LpStatus[status],
            phase_duration,
            monotonic() - solver_started,
            time_limit,
            len(model.variables()),
            len(model.constraints),
        )
        if status == pulp.LpStatusNotSolved:
            if not _model_solution_is_feasible(model, pulp, on):
                return _invalid_room_plan(
                    request,
                    starts[0],
                    starts,
                    "solver reached its time limit without a verified feasible room-energy plan",
                    "solver_failure",
                    generated_at,
                )
            time_limited = True
            break
        if status != pulp.LpStatusOptimal:
            return _invalid_room_plan(
                request,
                starts[0],
                starts,
                f"solver status {pulp.LpStatus[status]}",
                "solver_failure",
                generated_at,
            )
        objective_value = pulp.value(objective)
        if objective_value is None:
            # PuLP returns ``None`` for a constant zero expression (for
            # example, premature heat when every slot is already targeted).
            # That is a valid optimum and must not invalidate the plan.
            objective_value = getattr(objective, "constant", objective)
        optimum = _required_solver_value(
            objective_value, f"room-energy phase {phase_index + 1} objective"
        )
        score.append(optimum)
        logger.debug(
            "Room-energy solver phase=%d optimum=%.9g",
            phase_index + 1,
            optimum,
        )
        if phase_index < len(phases) - 1 and list(objective.items()):
            model += objective <= optimum + 1e-7

    violations: list[PlanningViolation] = []
    for heater in heaters:
        if heater.power_w > limit_w:
            violations.append(
                PlanningViolation(
                    heater.id,
                    "individual_power_limit",
                    0.0,
                    float(heater.power_w - limit_w),
                    starts[0],
                    "heater_power_exceeds_global_limit",
                )
            )
    room_intervals: list[RoomEnergyInterval] = []
    plan_slots: list[AutomaticPlanSlot] = []
    for index, start in enumerate(starts):
        interval_heat: dict[str, float] = {}
        interval_loss: dict[str, float] = {}
        interval_charge: dict[str, float] = {}
        interval_stored: dict[str, float] = {}
        interval_next_stored: dict[str, float] = {}
        interval_indoor: dict[str, float] = {}
        interval_next_indoor: dict[str, float] = {}
        interval_target: dict[str, float] = {}
        interval_start_shortfall: dict[str, float] = {}
        interval_shortfall: dict[str, float] = {}
        interval_heat_limit: dict[str, float] = {}
        initial_soc: dict[str, float] = {}
        demand: dict[str, float] = {}
        power_by_heater: dict[str, int] = {}
        active: list[str] = []
        for heater in heaters:
            state = request.telemetry[heater.id]
            on_value = float(on[(heater.id, index)].value() or 0)
            stored_value = _clean_solver_energy(
                _required_solver_value(stored[(heater.id, index)].value(), "stored energy")
            )
            next_stored_value = _clean_solver_energy(
                _required_solver_value(
                    stored[(heater.id, index + 1)].value(), "next stored energy"
                )
            )
            indoor_value = _required_solver_value(indoor[(heater.id, index)].value(), "indoor temperature")
            next_indoor_value = _required_solver_value(indoor[(heater.id, index + 1)].value(), "next indoor temperature")
            heat_value = _clean_solver_energy(
                _required_solver_value(heat[(heater.id, index)].value(), "heat delivered")
            )
            target = target_values[(heater.id, index)]
            outdoor = outdoor_values[(heater.id, index)]
            target_window = (
                None
                if target is None
                else _target_window_for_at(
                    _room_targets(request, heater), start, request.timezone_name
                )
            )
            loss_value = heater.room_heat_loss_kw_per_c * (indoor_value - outdoor) * slot_hours
            charge_value = heater.charge_power_kw * slot_hours * on_value
            limit_value = _heat_delivery_limit_kwh(
                heater, request.slot_minutes, stored_value
            )
            start_short_value = 0.0 if target is None else max(0.0, target - indoor_value)
            short_value = 0.0 if target is None else max(0.0, target - next_indoor_value)
            if target is not None and start_short_value > 1e-6:
                violations.append(
                    PlanningViolation(
                        heater.id,
                        "temperature_comfort",
                        indoor_value,
                        start_short_value,
                        start,
                        "insufficient_stored_energy_or_power",
                        None if target_window is None else target_window[0],
                        None if target_window is None else target_window[1],
                    )
                )
            if target is not None and short_value > 1e-6:
                violations.append(
                    PlanningViolation(
                        heater.id,
                        "temperature_comfort",
                        next_indoor_value,
                        short_value,
                        boundaries[index + 1],
                        "insufficient_stored_energy_or_power",
                        None if target_window is None else target_window[0],
                        None if target_window is None else target_window[1],
                    )
                )
            if on_value > 0.5:
                active.append(heater.id)
            interval_stored[heater.id] = round(stored_value, 9)
            interval_next_stored[heater.id] = round(next_stored_value, 9)
            interval_indoor[heater.id] = round(indoor_value, 9)
            interval_next_indoor[heater.id] = round(next_indoor_value, 9)
            if target is not None:
                interval_target[heater.id] = target
            interval_heat[heater.id] = round(heat_value, 9)
            interval_loss[heater.id] = round(loss_value, 9)
            interval_charge[heater.id] = round(charge_value, 9)
            interval_start_shortfall[heater.id] = round(start_short_value, 9)
            interval_shortfall[heater.id] = round(short_value, 9)
            interval_heat_limit[heater.id] = round(limit_value, 9)
            initial_soc[heater.id] = round(stored_value / heater.capacity_kwh * 100, 6)
            demand[heater.id] = round(heat_value, 9)
            power_by_heater[heater.id] = heater.power_w if on_value > 0.5 else 0
            room_intervals.append(
                RoomEnergyInterval(
                    heater.id,
                    start,
                    boundaries[index + 1],
                    outdoor,
                    target,
                    indoor_value,
                    next_indoor_value,
                    stored_value,
                    next_stored_value,
                    stored_value / heater.capacity_kwh * 100,
                    next_stored_value / heater.capacity_kwh * 100,
                    charge_value,
                    heat_value,
                    loss_value,
                    short_value,
                    start_short_value,
                    limit_value,
                )
            )
        plan_slots.append(
            AutomaticPlanSlot(
                start,
                boundaries[index + 1],
                tuple(active),
                sum(power_by_heater.values()),
                {key: round(value / _heater(heaters, key).capacity_kwh * 100, 6) for key, value in interval_next_stored.items()},
                {key: 0.0 for key in interval_target},
                outdoor_values[(heaters[0].id, index)] if heaters else None,
                interval_indoor,
                initial_soc,
                demand,
                power_by_heater,
                interval_stored,
                interval_target,
                interval_heat,
                interval_loss,
                interval_shortfall,
                interval_charge,
                interval_next_stored,
                interval_next_indoor,
                interval_start_shortfall,
                interval_heat_limit,
            )
        )
    by_heater = {heater.id: [item for item in room_intervals if item.heater_id == heater.id] for heater in heaters}
    explanations = tuple(
        _room_heater_explanation(heater, by_heater[heater.id], request)
        for heater in heaters
    )
    if time_limited:
        violations.append(PlanningViolation(None, "solver_time_limit", None, None, starts[0], "solver_time_limit"))
    convergence_by_heater = _room_convergence_by_heater(
        room_intervals,
        heaters,
        boundaries[-1],
        targets={heater.id: _room_targets(request, heater) for heater in heaters},
        timezone_name=request.timezone_name,
    )
    comfort_heaters = {
        item.heater_id
        for item in violations
        if item.requirement == "temperature_comfort" and item.heater_id is not None
    }
    non_comfort_violations = tuple(
        item for item in violations if item.requirement != "temperature_comfort"
    )
    if not violations:
        status = VALID
    elif (
        comfort_heaters
        and not non_comfort_violations
        and comfort_heaters == set(convergence_by_heater)
    ):
        status = CONVERGING
    else:
        status = DEGRADED
    convergence_at = (
        max(convergence_by_heater.values())
        if convergence_by_heater
        else None
    )
    plan = AutomaticPlan(
        starts[0], boundaries[-1], request.slot_minutes, tuple(plan_slots), tuple(violations),
        status, tuple(score), input_token(request), generated_at, explanations,
        tuple(room_intervals),
        convergence_by_heater,
        convergence_at,
        boundaries[-1] if status in {VALID, CONVERGING} else None,
    )
    _notify(request, "safety")
    _notify(request, "summary")
    return plan


def _invalid_room_plan(
    request: PlanningInput,
    start: datetime,
    starts: Sequence[datetime],
    detail: str,
    reason: str,
    generated_at: datetime,
    heater_ids: Sequence[str] = (),
) -> AutomaticPlan:
    enabled = tuple(sorted((item for item in request.heaters if item.enabled), key=lambda item: item.id))
    violations = tuple(
        PlanningViolation(heater_id, "safe_planning_input", None, None, start, reason)
        for heater_id in heater_ids
    ) or (PlanningViolation(None, "safe_planning_input", None, None, start, f"{reason}: {detail}"),)
    slots: list[AutomaticPlanSlot] = []
    for at in starts:
        end = advance_real(at, request.slot_minutes)
        stored: dict[str, float] = {}
        indoor: dict[str, float] = {}
        target: dict[str, float] = {}
        for heater in enabled:
            state = request.telemetry.get(heater.id)
            soc = 0.0 if state is None or state.stored_soc_percent is None else float(state.stored_soc_percent)
            value = 0.0 if state is None or state.indoor_temperature_c is None else float(state.indoor_temperature_c)
            stored[heater.id] = soc * heater.capacity_kwh / 100
            indoor[heater.id] = value
            active = active_temperature_target(_room_targets(request, heater), at, request.timezone_name)
            if active is not None:
                target[heater.id] = active
        slots.append(
            AutomaticPlanSlot(
                at, end, (), 0,
                {heater.id: (stored[heater.id] / heater.capacity_kwh * 100) for heater in enabled},
                {heater.id: 0.0 for heater in enabled},
                _weather_at(at, request.forecast),
                indoor,
                {heater.id: (stored[heater.id] / heater.capacity_kwh * 100) for heater in enabled},
                {heater.id: 0.0 for heater in enabled},
                {heater.id: 0 for heater in enabled},
                stored,
                target,
                {heater.id: 0.0 for heater in enabled},
                {heater.id: 0.0 for heater in enabled},
                {heater.id: max(0.0, target.get(heater.id, indoor[heater.id]) - indoor[heater.id]) for heater in enabled},
                {heater.id: 0.0 for heater in enabled},
                stored,
                indoor,
                {heater.id: max(0.0, target.get(heater.id, indoor[heater.id]) - indoor[heater.id]) for heater in enabled},
            )
        )
    horizon_end = advance_real(starts[-1], request.slot_minutes) if starts else advance_real(start, request.horizon_hours * 60)
    return AutomaticPlan(
        start,
        horizon_end,
        request.slot_minutes,
        tuple(slots),
        violations,
        INVALID,
        (),
        input_token(request),
        generated_at,
    )


__all__ = [
    "AutomaticPlan", "AutomaticPlanSlot", "CONVERGING", "DEGRADED", "DemandEstimate",
    "DegreeHoursDemandEstimator", "DeterministicChargeOptimizer", "FEASIBLE",
    "HeaterExplanation", "INVALID", "MaterializedConstraint", "MilpChargePlanner",
    "PlanningCancelled", "PlanningDeficit", "PlanningInput", "PlanningViolation", "PLANNING_HORIZON_HOURS", "SOLVER_TIME_LIMIT_SECONDS", "input_token",
    "materialize_constraints", "resolve_planning_telemetry", "RoomEnergyDemandEstimator",
    "RoomEnergyInterval", "RoomEnergyPlanner", "VALID", "active_temperature_target",
    "group_planning_violations", "room_energy_step",
]
