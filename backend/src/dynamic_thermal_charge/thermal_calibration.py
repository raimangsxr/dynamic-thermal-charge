"""Deterministic thermal-calibration domain logic.

The module intentionally has no database, MQTT, FastAPI or hardware imports.
It is the small, testable core used by the controller and by the API's explicit
estimation flow.  Persistence adapters store the dataclasses defined here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import json
import math
from typing import Any, Mapping, Sequence


DEFAULT_CAPACITY_KWH_PER_C = 2.5
DEFAULT_LOSS_KW_PER_C = 0.12
OUTDOOR_MAX_AGE = timedelta(minutes=15)
CALIBRATION_PHASES = ("baseline", "charge", "release", "cool", "fit", "applying")


class CalibrationError(ValueError):
    """A calibration input or transition is not safe to accept."""


def validate_outdoor_temperature(value: object) -> float:
    """Validate one outdoor value according to the MQTT contract."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CalibrationError("outdoor_temperature_c must be a JSON number")
    numeric = float(value)
    if not math.isfinite(numeric) or not -60 <= numeric <= 60:
        raise CalibrationError("outdoor_temperature_c must be finite and between -60 and 60")
    return numeric


def parse_outdoor_payload(payload: Mapping[str, Any] | str | bytes) -> float:
    """Accept exactly ``{"outdoor_temperature_c": number}`` and nothing else."""
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8", errors="strict")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise CalibrationError("outdoor payload must be valid JSON") from exc
    if not isinstance(payload, Mapping) or set(payload) != {"outdoor_temperature_c"}:
        raise CalibrationError(
            "outdoor payload must contain exactly outdoor_temperature_c"
        )
    return validate_outdoor_temperature(payload["outdoor_temperature_c"])


@dataclass(frozen=True)
class OutdoorReading:
    temperature_c: float
    received_at: datetime
    retained: bool = False

    def __post_init__(self) -> None:
        validate_outdoor_temperature(self.temperature_c)
        if self.received_at.tzinfo is None:
            raise CalibrationError("outdoor received_at requires a timezone")

    def is_fresh(self, now: datetime, *, max_age: timedelta = OUTDOOR_MAX_AGE) -> bool:
        if now.tzinfo is None:
            raise CalibrationError("freshness checks require an aware clock")
        age = now.astimezone(timezone.utc) - self.received_at.astimezone(timezone.utc)
        return timedelta(0) <= age <= max_age


@dataclass(frozen=True)
class RoomEstimateInput:
    surface_m2: float
    walls_exterior: int
    windows_m2: float
    insulation: str
    height_m: float
    other_heat_sources_kw: float

    def __post_init__(self) -> None:
        if not math.isfinite(self.surface_m2) or self.surface_m2 <= 0:
            raise CalibrationError("surface_m2 must be positive")
        if self.walls_exterior not in range(5):
            raise CalibrationError("walls_exterior must be between 0 and 4")
        if not math.isfinite(self.windows_m2) or self.windows_m2 < 0:
            raise CalibrationError("windows_m2 must be non-negative")
        if self.insulation not in {"poor", "medium", "good"}:
            raise CalibrationError("insulation must be poor, medium or good")
        if not math.isfinite(self.height_m) or not 2 <= self.height_m <= 6:
            raise CalibrationError("height_m must be between 2 and 6")
        if (
            not math.isfinite(self.other_heat_sources_kw)
            or self.other_heat_sources_kw < 0
        ):
            raise CalibrationError("other_heat_sources_kw must be non-negative")


@dataclass(frozen=True)
class RoomEstimate:
    capacity_kwh_per_c: float
    loss_kw_per_c: float
    enclosure_m2: float
    volume_m3: float


def estimate_room(values: RoomEstimateInput | Mapping[str, Any]) -> RoomEstimate:
    """Apply the v1 deterministic estimation formula exactly."""
    if not isinstance(values, RoomEstimateInput):
        values = RoomEstimateInput(
            surface_m2=float(values["surface_m2"]),
            walls_exterior=int(values["walls_exterior"]),
            windows_m2=float(values["windows_m2"]),
            insulation=str(values["insulation"]),
            height_m=float(values["height_m"]),
            other_heat_sources_kw=float(values.get("other_heat_sources_kw", 0)),
        )
    volume = values.surface_m2 * values.height_m
    capacity = max(0.2, 0.035 * values.surface_m2 + 0.00033 * volume)
    enclosure = (
        4 * math.sqrt(values.surface_m2) * values.height_m * values.walls_exterior / 4
    )
    if values.windows_m2 > enclosure:
        raise CalibrationError("windows_m2 cannot exceed the estimated enclosure")
    u_values = {
        "poor": (1.5, 2.8, 0.8),
        "medium": (0.8, 2.0, 0.5),
        "good": (0.4, 1.4, 0.3),
    }
    opaque_u, window_u, air_changes = u_values[values.insulation]
    loss = (
        opaque_u * max(0.0, enclosure - values.windows_m2)
        + window_u * values.windows_m2
        + 0.33 * air_changes * volume
    ) / 1000 - values.other_heat_sources_kw / 20
    loss = min(1.5, max(0.01, loss))
    return RoomEstimate(capacity, loss, enclosure, volume)


@dataclass(frozen=True)
class CalibrationSample:
    observed_at: datetime
    indoor_temperature_c: float
    outdoor_temperature_c: float
    soc_percent: float
    discharge_enabled: bool
    damper_position_percent: float | None = None
    heat_delivered_kwh: float = 0.0
    synchronized: bool = True
    phase: str | None = None

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None:
            raise CalibrationError("sample observed_at requires a timezone")
        for name, value in (
            ("indoor_temperature_c", self.indoor_temperature_c),
            ("outdoor_temperature_c", self.outdoor_temperature_c),
            ("soc_percent", self.soc_percent),
            ("heat_delivered_kwh", self.heat_delivered_kwh),
        ):
            if not math.isfinite(float(value)):
                raise CalibrationError(f"sample {name} must be finite")
        validate_outdoor_temperature(self.outdoor_temperature_c)
        if not 0 <= self.soc_percent <= 100:
            raise CalibrationError("sample soc_percent must be between 0 and 100")
        if self.heat_delivered_kwh < 0:
            raise CalibrationError("sample heat_delivered_kwh must be non-negative")
        if self.damper_position_percent is not None and not 0 <= self.damper_position_percent <= 100:
            raise CalibrationError("sample damper_position_percent must be between 0 and 100")


@dataclass(frozen=True)
class CalibrationQuality:
    sample_count: int
    elapsed_hours: float
    heating_windows: int
    cooling_windows: int
    indoor_range_c: float
    differential_range_c: float
    heat_delivered_kwh: float
    rmse_c: float | None = None
    bias_c: float | None = None
    capacity_confidence_relative: float | None = None
    loss_confidence_relative: float | None = None
    condition_number: float | None = None
    sufficient: bool = False
    reason: str | None = None


@dataclass(frozen=True)
class CalibrationFit:
    capacity_kwh_per_c: float | None
    loss_kw_per_c: float | None
    quality: CalibrationQuality
    status: str
    validation_predictions: tuple[float, ...] = ()

    @property
    def acceptable(self) -> bool:
        return self.status == "calibrated" and self.quality.sufficient


def _runs(samples: Sequence[CalibrationSample], enabled: bool) -> int:
    count = 0
    in_run = False
    started: datetime | None = None
    for sample in samples:
        selected = bool(sample.discharge_enabled) is enabled
        if selected and not in_run:
            in_run = True
            started = sample.observed_at
        elif not selected and in_run:
            if started is not None and sample.observed_at - started >= timedelta(minutes=30):
                count += 1
            in_run = False
            started = None
    if in_run and started is not None:
        if samples[-1].observed_at - started >= timedelta(minutes=30):
            count += 1
    return count


def _phase_runs(
    samples: Sequence[CalibrationSample], phases: set[str]
) -> int:
    """Count contiguous protocol windows that meet the 30-minute minimum."""
    count = 0
    started: datetime | None = None
    previous: datetime | None = None
    for sample in samples:
        selected = sample.phase in phases
        if selected and started is None:
            started = sample.observed_at
        if not selected and started is not None:
            if previous is not None and previous - started >= timedelta(minutes=30):
                count += 1
            started = None
        previous = sample.observed_at
    if started is not None and previous is not None:
        if previous - started >= timedelta(minutes=30):
            count += 1
    return count


def _solve_3x3(matrix: list[list[float]], vector: list[float]) -> list[float]:
    augmented = [row[:] + [vector[index]] for index, row in enumerate(matrix)]
    for pivot in range(3):
        row = max(range(pivot, 3), key=lambda index: abs(augmented[index][pivot]))
        if abs(augmented[row][pivot]) < 1e-12:
            raise CalibrationError("calibration inputs are not identifiable")
        augmented[pivot], augmented[row] = augmented[row], augmented[pivot]
        factor = augmented[pivot][pivot]
        augmented[pivot] = [value / factor for value in augmented[pivot]]
        for index in range(3):
            if index == pivot:
                continue
            factor = augmented[index][pivot]
            augmented[index] = [
                left - factor * right
                for left, right in zip(augmented[index], augmented[pivot])
            ]
    return [augmented[index][3] for index in range(3)]


def _inverse_3x3(matrix: list[list[float]]) -> list[list[float]]:
    # ``_solve_3x3(matrix, e_i)`` returns column ``i`` of the inverse.  Turn
    # those columns into rows before indexing the covariance diagonals below.
    columns = [
        _solve_3x3(matrix, [1.0 if row == column else 0.0 for row in range(3)])
        for column in range(3)
    ]
    return [
        [columns[column][row] for column in range(3)]
        for row in range(3)
    ]


def _intervals(samples: Sequence[CalibrationSample], capacity_kwh: float):
    ordered = sorted(samples, key=lambda item: item.observed_at)
    intervals = []
    for previous, current in zip(ordered, ordered[1:]):
        duration = (current.observed_at - previous.observed_at).total_seconds() / 3600
        if duration <= 0 or duration > 0.25 or not previous.synchronized or not current.synchronized:
            continue
        midpoint_soc = (previous.soc_percent + current.soc_percent) / 2
        soc_fraction = max(0.0, min(1.0, midpoint_soc / 100))
        # ``CalibrationCoordinator`` stores the modeled total: residual heat
        # is present in every phase, while the controlled component is gated by
        # discharge and damper state.  Use the interval average; applying the
        # gate again here would double-count it.
        heat = (
            max(0.0, (previous.heat_delivered_kwh + current.heat_delivered_kwh) / 2)
        )
        integral = ((previous.indoor_temperature_c - previous.outdoor_temperature_c) + (current.indoor_temperature_c - current.outdoor_temperature_c)) / 2 * duration
        intervals.append((current.observed_at, current.indoor_temperature_c - previous.indoor_temperature_c, integral, heat, duration, soc_fraction, capacity_kwh))
    return intervals


def fit_calibration(
    samples: Sequence[CalibrationSample],
    *,
    capacity_kwh: float,
    min_samples: int = 60,
) -> CalibrationFit:
    """Fit ``C*dT = Q - K*integral(Tin-Tout)`` deterministically."""
    ordered = tuple(sorted(samples, key=lambda item: item.observed_at))
    if not ordered:
        quality = CalibrationQuality(0, 0.0, 0, 0, 0.0, 0.0, 0.0, reason="no_samples")
        return CalibrationFit(None, None, quality, "failed")
    synchronized = tuple(item for item in ordered if item.synchronized)
    if synchronized:
        elapsed = (synchronized[-1].observed_at - synchronized[0].observed_at).total_seconds() / 3600
        indoor_range = max(item.indoor_temperature_c for item in synchronized) - min(item.indoor_temperature_c for item in synchronized)
        differential = [item.indoor_temperature_c - item.outdoor_temperature_c for item in synchronized]
        differential_range = max(differential) - min(differential)
        heat = sum(max(0.0, item.heat_delivered_kwh) for item in synchronized)
    else:
        elapsed = 0.0
        indoor_range = differential_range = heat = 0.0
    if any(item.phase is not None for item in synchronized):
        heating_windows = _phase_runs(synchronized, {"charge", "release"})
        cooling_windows = _phase_runs(synchronized, {"cool"})
    else:
        heating_windows = _runs(synchronized, True)
        cooling_windows = _runs(synchronized, False)
    base = dict(
        # R9 counts usable synchronized samples, not raw rows that were kept
        # for diagnostics but could not participate in the fit.
        sample_count=len(synchronized),
        elapsed_hours=elapsed,
        heating_windows=heating_windows,
        cooling_windows=cooling_windows,
        indoor_range_c=indoor_range,
        differential_range_c=differential_range,
        heat_delivered_kwh=heat,
    )
    if len(synchronized) < min_samples:
        quality = CalibrationQuality(**base, reason="not_enough_samples")
        return CalibrationFit(None, None, quality, "failed")
    if elapsed < 6 or heating_windows < 2 or cooling_windows < 2:
        quality = CalibrationQuality(**base, reason="excitation_criteria_not_met")
        return CalibrationFit(None, None, quality, "failed")
    if indoor_range < 1 or differential_range < 3 or heat < capacity_kwh * 0.15:
        quality = CalibrationQuality(**base, reason="quality_criteria_not_met")
        return CalibrationFit(None, None, quality, "failed")
    intervals = _intervals(ordered, capacity_kwh)
    if len(intervals) < 3:
        quality = CalibrationQuality(**base, reason="not_enough_intervals")
        return CalibrationFit(None, None, quality, "failed")
    split_at = max(1, min(len(intervals) - 1, math.floor(len(intervals) * 0.8)))
    train, validation = intervals[:split_at], intervals[split_at:]
    # Regress Q on (delta-T, integral(delta-T), intercept).  The intercept is
    # diagnostic only and is not applied to a room.
    matrix = [[0.0] * 3 for _ in range(3)]
    vector = [0.0] * 3
    for _at, dt, integral, delivered, duration, _soc, _capacity in train:
        x = [dt, integral, 1.0]
        weight = max(1e-6, duration)
        for row in range(3):
            vector[row] += weight * x[row] * delivered
            for column in range(3):
                matrix[row][column] += weight * x[row] * x[column]
    try:
        coefficients = _solve_3x3(matrix, vector)
    except CalibrationError as exc:
        quality = CalibrationQuality(**base, reason=str(exc))
        return CalibrationFit(None, None, quality, "failed")
    capacity_coefficient, loss_coefficient, _intercept = coefficients
    predictions = tuple(capacity_coefficient * dt + loss_coefficient * integral + _intercept for _at, dt, integral, _q, _duration, _soc, _capacity in validation)
    heat_residuals = tuple(
        prediction - delivered
        for prediction, (_at, _dt, _integral, delivered, _duration, _soc, _capacity) in zip(predictions, validation)
    )
    # The fitted equation predicts interval energy.  R10 thresholds are in
    # degrees C, so evaluate the temporal validation residual in temperature
    # units rather than comparing kWh directly to a Celsius limit.
    if abs(capacity_coefficient) <= 1e-12:
        residuals = tuple(math.inf for _ in heat_residuals)
    else:
        residuals = tuple(value / capacity_coefficient for value in heat_residuals)
    rmse = math.sqrt(sum(value * value for value in residuals) / max(1, len(residuals)))
    bias = sum(residuals) / max(1, len(residuals))
    standardized = []
    for index in (0, 1):
        values = [item[index + 1] for item in train]
        mean = sum(values) / len(values)
        standard = math.sqrt(sum((value - mean) ** 2 for value in values) / len(values))
        standardized.append((mean, standard))
    if any(standard <= 1e-12 for _mean, standard in standardized):
        quality = CalibrationQuality(**base, rmse_c=rmse, bias_c=bias, reason="unidentifiable_columns")
        return CalibrationFit(None, None, quality, "failed", predictions)
    # For two standardized columns, the condition number of X'X is explicit.
    correlation = sum(
        (item[1] - standardized[0][0]) / standardized[0][1]
        * (item[2] - standardized[1][0]) / standardized[1][1]
        for item in train
    ) / len(train)
    correlation = max(-0.999999, min(0.999999, correlation))
    condition = (1 + abs(correlation)) / max(1e-12, 1 - abs(correlation))
    try:
        inverse = _inverse_3x3(matrix)
        sigma2 = sum(
            (
                capacity_coefficient * dt
                + loss_coefficient * integral
                + _intercept
                - delivered
            )
            ** 2
            for _at, dt, integral, delivered, _duration, _soc, _capacity in train
        ) / max(1, len(train) - 3)
        capacity_error = 1.96 * math.sqrt(max(0.0, sigma2 * inverse[0][0]))
        loss_error = 1.96 * math.sqrt(max(0.0, sigma2 * inverse[1][1]))
    except (ArithmeticError, IndexError):
        capacity_error = loss_error = math.inf
    capacity_relative = abs(capacity_error / capacity_coefficient) if capacity_coefficient else math.inf
    loss_relative = abs(loss_error / loss_coefficient) if loss_coefficient else math.inf
    sufficient = (
        0.2 <= capacity_coefficient <= 20
        and 0.01 <= loss_coefficient <= 1.5
        and rmse <= 0.35
        and abs(bias) <= 0.10
        and capacity_relative <= 0.30
        and loss_relative <= 0.30
        and condition <= 1000
    )
    quality = CalibrationQuality(
        **base,
        rmse_c=rmse,
        bias_c=bias,
        capacity_confidence_relative=capacity_relative,
        loss_confidence_relative=loss_relative,
        condition_number=condition,
        sufficient=sufficient,
        reason=None if sufficient else "fit_quality_not_met",
    )
    if not sufficient:
        return CalibrationFit(None, None, quality, "failed", predictions)
    return CalibrationFit(capacity_coefficient, loss_coefficient, quality, "calibrated", predictions)


@dataclass(frozen=True)
class CalibrationInput:
    now: datetime
    indoor_temperature_c: float | None
    outdoor_temperature_c: float | None
    soc_percent: float | None
    target_temperature_c: float
    relay_test_active: bool = False
    authority: bool = True
    global_power_available: bool = True
    confirmations: Mapping[str, bool] = field(default_factory=dict)


@dataclass(frozen=True)
class CalibrationCommand:
    charge: bool
    discharge: bool
    setpoint_temperature_c: float | None = None
    deferred: bool = False


@dataclass(frozen=True)
class CalibrationStep:
    phase: str
    command: CalibrationCommand
    terminal_status: str | None = None
    cause: str | None = None


class CalibrationProtocol:
    """Restart-safe phase machine; the persistence layer stores its snapshot."""

    def __init__(
        self,
        *,
        started_at: datetime,
        baseline_minutes: int = 60,
        phase: str = "baseline",
        phase_started_at: datetime | None = None,
        reference_soc: float | None = None,
        reference_temperature: float | None = None,
        cycle_count: int = 0,
    ) -> None:
        if started_at.tzinfo is None:
            raise CalibrationError("started_at requires a timezone")
        if phase not in CALIBRATION_PHASES:
            raise CalibrationError("unknown calibration phase")
        self.phase = phase
        self.phase_started_at = phase_started_at or started_at
        if self.phase_started_at.tzinfo is None:
            raise CalibrationError("phase_started_at requires a timezone")
        self.baseline_minutes = baseline_minutes
        self.reference_soc = reference_soc
        self.reference_temperature = reference_temperature
        self.cycle_count = max(0, int(cycle_count))

    @classmethod
    def restore(cls, session: Mapping[str, Any]) -> "CalibrationProtocol":
        """Restore the phase machine from a durable session projection."""
        metrics = session.get("metrics") or {}
        phase_started = metrics.get("phase_started_at")
        if isinstance(phase_started, str):
            phase_started = datetime.fromisoformat(phase_started)
        if phase_started is None:
            phase_started = session.get("updated_at") or session.get("started_at")
        started = session.get("started_at")
        if isinstance(started, str):
            started = datetime.fromisoformat(started)
        if not isinstance(started, datetime) or not isinstance(phase_started, datetime):
            raise CalibrationError("calibration session timestamps are invalid")
        return cls(
            started_at=started,
            phase=str(session.get("phase", "baseline")),
            phase_started_at=phase_started,
            reference_soc=(
                None
                if metrics.get("reference_soc") is None
                else float(metrics["reference_soc"])
            ),
            reference_temperature=(
                None
                if metrics.get("reference_temperature") is None
                else float(metrics["reference_temperature"])
            ),
            cycle_count=int(metrics.get("cycle_count", 0)),
        )

    def snapshot(self, *, now: datetime | None = None) -> dict[str, Any]:
        """Return JSON-safe phase state for the application store."""
        return {
            "phase_started_at": self.phase_started_at.isoformat(),
            "reference_soc": self.reference_soc,
            "reference_temperature": self.reference_temperature,
            "cycle_count": self.cycle_count,
            "elapsed_seconds": max(
                0.0,
                ((now or self.phase_started_at) - self.phase_started_at).total_seconds(),
            ),
        }

    def step(self, reading: CalibrationInput) -> CalibrationStep:
        if reading.now.tzinfo is None:
            raise CalibrationError("calibration clock requires a timezone")
        if reading.relay_test_active:
            return CalibrationStep("baseline", CalibrationCommand(False, False), "failed", "relay_test_active")
        if not reading.authority:
            return CalibrationStep(self.phase, CalibrationCommand(False, False), "failed", "authority_lost")
        if any(value is None for value in (reading.indoor_temperature_c, reading.outdoor_temperature_c, reading.soc_percent)):
            return CalibrationStep(self.phase, CalibrationCommand(False, False), "failed", "inputs_missing")
        if reading.outdoor_temperature_c is not None and not math.isfinite(reading.outdoor_temperature_c):
            return CalibrationStep(self.phase, CalibrationCommand(False, False), "failed", "outdoor_invalid")
        if self.reference_soc is None:
            self.reference_soc = float(reading.soc_percent)
        if self.reference_temperature is None:
            self.reference_temperature = float(reading.indoor_temperature_c)
        expected_confirmation = (
            "charge" if self.phase == "charge" else "discharge" if self.phase == "release" else None
        )
        if expected_confirmation is not None:
            # A command is not considered safe merely because no confirmation
            # was reported.  The controller/MQTT boundary must explicitly
            # prove the requested output state before the phase can continue.
            if reading.confirmations.get(expected_confirmation) is not True:
                return CalibrationStep(
                    self.phase,
                    CalibrationCommand(False, False),
                    "failed",
                    f"{expected_confirmation}_unconfirmed",
                )
        elapsed = reading.now - self.phase_started_at
        if self.phase == "baseline":
            if elapsed >= timedelta(minutes=self.baseline_minutes):
                self.phase = "charge"
                self.phase_started_at = reading.now
                self.reference_soc = float(reading.soc_percent)
                elapsed = timedelta(0)
            else:
                return CalibrationStep("baseline", CalibrationCommand(False, False))
        if self.phase == "charge":
            reference_soc = 0.0 if self.reference_soc is None else self.reference_soc
            if float(reading.soc_percent) >= min(95.0, reference_soc + 10.0) or elapsed >= timedelta(minutes=120):
                self.phase = "release"
                self.phase_started_at = reading.now
                self.reference_soc = float(reading.soc_percent)
                elapsed = timedelta(0)
            elif not reading.global_power_available:
                return CalibrationStep("charge", CalibrationCommand(False, False, deferred=True))
            else:
                return CalibrationStep("charge", CalibrationCommand(True, False))
        if self.phase == "release":
            safe_cap = min(26.0, reading.target_temperature_c + 2.0)
            reference_soc = 0.0 if self.reference_soc is None else self.reference_soc
            if float(reading.soc_percent) <= max(0.0, reference_soc - 10.0) or float(reading.indoor_temperature_c) >= safe_cap or elapsed >= timedelta(minutes=120):
                self.phase = "cool"
                self.phase_started_at = reading.now
                elapsed = timedelta(0)
            else:
                return CalibrationStep("release", CalibrationCommand(False, True, safe_cap))
        if self.phase == "cool":
            if elapsed < timedelta(minutes=60):
                return CalibrationStep("cool", CalibrationCommand(False, False))
            self.cycle_count += 1
            self.phase_started_at = reading.now
            if self.cycle_count < 2:
                self.phase = "baseline"
                self.reference_temperature = float(reading.indoor_temperature_c)
                return CalibrationStep("baseline", CalibrationCommand(False, False))
            self.phase = "fit"
            return CalibrationStep("fit", CalibrationCommand(False, False))
        if self.phase == "fit":
            return CalibrationStep("fit", CalibrationCommand(False, False))
        if self.phase == "applying":
            return CalibrationStep("applying", CalibrationCommand(False, False))
        return CalibrationStep(self.phase, CalibrationCommand(False, False), "failed", "invalid_phase")


def arbitrate_calibration_plan(
    heater_ids: Sequence[str],
    *,
    selected_heater_id: str | None,
    plan_heater_ids: Sequence[str] = (),
    calibration_charge: bool = False,
    authority: bool = True,
    relay_test_active: bool = False,
) -> tuple[str, ...]:
    """Resolve relay ownership with calibration ahead of a stale plan.

    The selected accumulator is removed from the planner's request before the
    calibration pulse is considered.  Safety and relay-test authority always
    win, and unknown ids never reach the output driver.
    """
    known = set(heater_ids)
    if not authority or relay_test_active:
        return ()
    requested = set(plan_heater_ids) & known
    if selected_heater_id is None:
        return tuple(sorted(requested))
    requested.discard(selected_heater_id)
    if calibration_charge and selected_heater_id in known:
        requested.add(selected_heater_id)
    return tuple(sorted(requested))


__all__ = [
    "CALIBRATION_PHASES",
    "CalibrationCommand",
    "CalibrationError",
    "CalibrationFit",
    "CalibrationInput",
    "CalibrationProtocol",
    "CalibrationQuality",
    "CalibrationSample",
    "CalibrationStep",
    "DEFAULT_CAPACITY_KWH_PER_C",
    "DEFAULT_LOSS_KW_PER_C",
    "OutdoorReading",
    "OUTDOOR_MAX_AGE",
    "RoomEstimate",
    "RoomEstimateInput",
    "estimate_room",
    "fit_calibration",
    "arbitrate_calibration_plan",
    "parse_outdoor_payload",
    "validate_outdoor_temperature",
]
