"""Controller-side orchestration for automatic thermal calibration.

The estimator and phase machine live in :mod:`thermal_calibration`; this
module is the small adapter that samples the latest MQTT state, renews the
durable execution lease and hands the controller a time-bounded relay override.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
from typing import Any, Mapping, Sequence

from .charge_planning import room_energy_step
from .models import AppConfig, ChargeTelemetry, Heater
from .push import WebPushDelivery
from .thermal_calibration import (
    CalibrationInput,
    CalibrationProtocol,
    CalibrationSample,
    fit_calibration,
)


logger = logging.getLogger(__name__)

MAX_INPUT_AGE = timedelta(minutes=15)
MAX_MISSING_INPUT = timedelta(hours=1)
SAMPLE_PERIOD = timedelta(minutes=5)
LEASE_SECONDS = 30
TERMINAL_OFF_WINDOW = timedelta(seconds=30)


def active_calibration_heater_ids(store, config: AppConfig) -> tuple[str, ...]:
    """Return the durable calibration ownership set for planner arbitration."""
    calibration = getattr(store, "calibration", None)
    if calibration is None:
        return ()
    active: list[str] = []
    for heater in config.heaters:
        try:
            if calibration.active(heater.id) is not None:
                active.append(heater.id)
        except Exception:
            # A store read failure must not make an old plan compete with a
            # calibration that may still own a relay. The controller provider
            # separately forces outputs off on errors.
            logger.error("Could not read calibration ownership", exc_info=True)
            return tuple(item.id for item in config.heaters)
    return tuple(sorted(active))


def active_calibration_exclusions(
    store,
    config: AppConfig,
    existing: Sequence[Mapping[str, str]] = (),
) -> tuple[dict[str, str], ...]:
    """Overlay live calibration ownership on a persisted exclusion list.

    A plan can be read between the calibration start request and the
    controller's next recalculation. The live session is authoritative for
    operator projections in that interval, while persisted telemetry
    exclusions for other accumulators remain visible.
    """
    active_ids = set(active_calibration_heater_ids(store, config))
    projected = [
        {
            "heater_id": str(item["heater_id"]),
            "cause": str(item.get("cause", "missing_required_state")),
        }
        for item in existing
        if item.get("heater_id") not in active_ids
    ]
    projected_ids = {item["heater_id"] for item in projected}
    projected.extend(
        {"heater_id": heater.id, "cause": "calibration_active"}
        for heater in config.heaters
        if heater.id in active_ids and heater.id not in projected_ids
    )
    return tuple(projected)


class CalibrationCoordinator:
    """Run every durable session once per controller poll.

    No relay is enabled merely because a session row exists.  A successful
    ``tick`` writes a short-lived authorization timestamp; the controller only
    applies a charge override while that timestamp is fresh.
    """

    def __init__(self, store, *, owner: str = "controller", clock=None, alerts=None) -> None:
        self._store = store
        self._owner = owner
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._alerts = alerts
        self._push = WebPushDelivery(store.calibration, clock=self._clock)

    def active_heater_ids(self, config: AppConfig | None = None) -> tuple[str, ...]:
        configuration = config or self._store.repository.current()[0]
        result: list[str] = []
        for heater in configuration.heaters:
            try:
                if self._store.calibration.active(heater.id) is not None:
                    result.append(heater.id)
            except Exception:
                logger.error("Could not read active calibration sessions", exc_info=True)
                return tuple(item.id for item in configuration.heaters)
        return tuple(sorted(result))

    def owned_heater_ids(
        self,
        config: AppConfig | None = None,
        *,
        at: datetime | None = None,
    ) -> tuple[str, ...]:
        """Return active sessions plus a short terminal safety-off window."""
        configuration = config or self._store.repository.current()[0]
        moment = at or self._clock()
        owned = set(self.active_heater_ids(configuration))
        for heater in configuration.heaters:
            room = heater.room
            if room is None or room.terminal_at is None:
                continue
            if (
                room.status in {"calibrated", "failed", "cancelled"}
                and timedelta(0) <= moment - room.terminal_at <= TERMINAL_OFF_WINDOW
            ):
                owned.add(heater.id)
        return tuple(sorted(owned))

    def outputs(self, at: datetime | None = None) -> set[str] | None:
        """Tick sessions and return the selected relay override, if any."""
        moment = at or self._clock()
        config = self._store.repository.current()[0]
        heater_by_id = {heater.id: heater for heater in config.heaters}
        active = set(self.active_heater_ids(config))
        alert_repository = getattr(self._store, "alerts", None)
        pending_alert_ids = getattr(
            alert_repository, "pending_push_alert_ids", lambda: ()
        )
        owned = set(self.owned_heater_ids(config, at=moment))
        if not owned:
            for session_id in self._store.calibration.pending_push_session_ids():
                self._push.deliver_pending(session_id=session_id)
            for alert_id in pending_alert_ids():
                self._push.deliver_pending(alert_id=alert_id)
            return None
        outputs: set[str] = set()
        for heater_id in active:
            session = self._store.calibration.active(heater_id)
            heater = heater_by_id.get(heater_id)
            if session is None or heater is None:
                continue
            try:
                updated = self._tick_session(session, heater, moment)
                self._push.deliver_pending(session_id=session.id)
            except Exception:
                logger.error(
                    "Calibration session %s failed safely", session.id, exc_info=True
                )
                self._safe_fail(session.id, moment, "controller_exception", heater_id=heater_id)
                continue
            if updated is None:
                continue
            command = updated.commands
            authorized_at = _parse_instant(command.get("authorized_at"))
            if (
                authorized_at is not None
                and timedelta(0) <= moment - authorized_at <= timedelta(seconds=LEASE_SECONDS)
                and bool(command.get("charge"))
            ):
                outputs.add(heater_id)
        # A terminal saga can commit before a controller restart.  Delivery is
        # therefore drained independently of the active-session loop.
        for session_id in self._store.calibration.pending_push_session_ids():
            self._push.deliver_pending(session_id=session_id)
        for alert_id in pending_alert_ids():
            self._push.deliver_pending(alert_id=alert_id)
        # A non-None result owns every relay for the cycle.  Thus an active
        # baseline/cool session also forces the stale plan's output OFF.
        return outputs

    def discharge_override(self, config: AppConfig | None = None) -> Mapping[str, dict[str, Any]]:
        """Return durable release commands for the MQTT publisher projection."""
        configuration = config or self._store.repository.current()[0]
        result: dict[str, dict[str, Any]] = {}
        for heater_id in self.active_heater_ids(configuration):
            session = self._store.calibration.active(heater_id)
            if session is None:
                continue
            command = session.commands
            result[heater_id] = {
                "discharge": bool(command.get("discharge")),
                "setpoint_temperature_c": command.get("setpoint_temperature_c"),
                "authorized_at": command.get("authorized_at"),
            }
        return result

    def _tick_session(self, session, heater: Heater, now: datetime):
        repository = self._store.calibration
        if not repository.claim_lease(
            session.id, self._owner, now=now, seconds=LEASE_SECONDS
        ):
            return None
        current = repository.active(heater.id)
        if current is None:
            return None
        if current.phase == "applying":
            # ``applying`` is the terminal saga boundary.  The preceding
            # tick has already persisted an acceptable fit and forced both
            # outputs off; a restart can leave only the configuration write
            # and application-store cleanup unfinished.  Resume that saga
            # before reading live inputs so a stale/absent telemetry sample
            # cannot strand the session in an active phase.
            self._attempt_fit(current, heater, now)
            return None
        telemetry = self._store.planning.telemetry().get(heater.id)
        outdoor = self._store.outdoor_temperature.latest()
        control = self._store.home_assistant.control_state()
        relay_test = self._store.relay_tests.current()
        authority = (
            heater.enabled
            and control.automatic_control_enabled
            and control.heater_modes.get(heater.id, "AUTO") == "AUTO"
            and not _relay_test_active(relay_test)
        )
        missing = _missing_inputs(telemetry, outdoor, now)
        missing_since = dict(current.missing_since)
        for key in tuple(missing_since):
            if key not in missing:
                missing_since.pop(key, None)
        for key in missing:
            missing_since.setdefault(key, now.isoformat())
        if not authority:
            self._safe_fail(current.id, now, "authority_lost", heater_id=heater.id)
            return None
        stale_key = next(
            (
                key
                for key, value in missing_since.items()
                if _parse_instant(value) is not None
                and now - _parse_instant(value) >= MAX_MISSING_INPUT
            ),
            None,
        )
        if stale_key is not None:
            self._safe_fail(current.id, now, f"{stale_key}_missing_over_one_hour", heater_id=heater.id)
            return None
        if now - current.started_at >= timedelta(hours=24):
            # The 24-hour boundary is the last chance to evaluate the samples.
            # Do not advance the protocol beyond its maximum duration: fit the
            # data already collected, then finish atomically as calibrated or
            # failed for insufficient quality.
            self._attempt_fit(current, heater, now)
            return None
        if missing:
            repository.save_state(
                current.id,
                missing_since=missing_since,
                commands={"authorized_at": None, "charge": False, "discharge": False},
                now=now,
            )
            return repository.active(heater.id)

        assert telemetry is not None and outdoor is not None
        protocol = CalibrationProtocol.restore(
            {
                "started_at": current.started_at,
                "updated_at": current.updated_at,
                "phase": current.phase,
                "metrics": current.metrics,
            }
        )
        target = _target(telemetry, heater)
        global_power_available = _global_power_available(self._store, heater, now)
        step = protocol.step(
            CalibrationInput(
                now=now,
                indoor_temperature_c=telemetry.indoor_temperature_c,
                outdoor_temperature_c=outdoor.temperature_c,
                soc_percent=telemetry.stored_soc_percent,
                target_temperature_c=target,
                relay_test_active=False,
                authority=True,
                global_power_available=global_power_available,
                confirmations=(
                    {
                        str(key): bool(value)
                        for key, value in current.commands["confirmations"].items()
                    }
                    if isinstance(current.commands.get("confirmations"), Mapping)
                    else {}
                ),
            )
        )
        if step.terminal_status is not None:
            self._safe_fail(current.id, now, step.cause or step.terminal_status, heater_id=heater.id)
            return None

        metrics = dict(current.metrics)
        metrics.update(protocol.snapshot(now=now))
        metrics["progress"] = min(
            1.0,
            max(0.0, (now - current.started_at).total_seconds() / (24 * 3600)),
        )
        last_sample = _parse_instant(metrics.get("last_sample_at"))
        if last_sample is None or now - last_sample >= SAMPLE_PERIOD:
            repository.add_sample(
                current.id,
                _sample_for(heater, telemetry, outdoor.temperature_c, now, step.phase),
            )
            metrics["last_sample_at"] = now.isoformat()
            metrics["sample_count"] = int(metrics.get("sample_count", 0)) + 1

        command = {
            "charge": bool(step.command.charge and global_power_available),
            "discharge": bool(step.command.discharge),
            "setpoint_temperature_c": step.command.setpoint_temperature_c,
            "deferred": bool(step.command.deferred or not global_power_available),
            "authorized_at": now.isoformat(),
        }
        # A confirmation belongs to the command that produced it.  Preserve
        # it while the phase keeps issuing the same command, and clear it at a
        # phase transition so the next order must be acknowledged afresh.
        if step.phase == current.phase:
            previous_confirmations = current.commands.get("confirmations")
            previous_output = (
                bool(current.commands.get("charge")),
                bool(current.commands.get("discharge")),
            )
            current_output = (command["charge"], command["discharge"])
            if (
                isinstance(previous_confirmations, Mapping)
                and previous_output == current_output
            ):
                command["confirmations"] = dict(previous_confirmations)
        if step.phase == "fit":
            self._attempt_fit(current, heater, now, metrics=metrics)
            return None

        repository.save_state(
            current.id,
            phase=protocol.phase,
            missing_since={},
            commands=command,
            metrics=metrics,
            now=now,
        )
        return repository.active(heater.id)

    def fail_active_relay(
        self,
        heater_id: str,
        *,
        at: datetime | None = None,
        cause: str = "relay_off_failed",
    ) -> bool:
        """Durably fail an active calibration after a relay safety failure."""
        session = self._store.calibration.active(heater_id)
        if session is None:
            return False
        return self._safe_fail(
            session.id,
            at or self._clock(),
            cause,
            heater_id=heater_id,
        )

    def _attempt_fit(
        self,
        session,
        heater: Heater,
        now: datetime,
        *,
        metrics: Mapping[str, Any] | None = None,
    ) -> bool:
        repository = self._store.calibration
        fit = fit_calibration(
            repository.samples(session.id),
            capacity_kwh=heater.room_thermal_capacity_kwh_per_c,
        )
        fit_metrics = dict(session.metrics if metrics is None else metrics)
        fit_metrics["quality"] = fit.quality.__dict__
        if fit.acceptable:
            repository.save_state(
                session.id,
                phase="applying",
                commands={"authorized_at": None, "charge": False, "discharge": False},
                metrics=fit_metrics,
                missing_since={},
                now=now,
            )
            finish_calibration(
                self._store,
                session.id,
                result=fit,
                status="calibrated",
                cause="quality_criteria_met",
                now=now,
                heater_id=heater.id,
                alerts=self._alerts,
            )
            return True
        self._safe_fail(
            session.id,
            now,
            fit.quality.reason or "fit_quality_not_met",
            fit=fit,
            heater_id=heater.id,
        )
        return False

    def _safe_fail(self, session_id: str, now: datetime, cause: str, fit=None, heater_id: str | None = None) -> bool:
        try:
            return finish_calibration(
                self._store,
                session_id,
                result=fit,
                status="failed",
                cause=cause,
                now=now,
                heater_id=heater_id,
                alerts=self._alerts,
            )
        except Exception:
            logger.error("Could not persist failed calibration session %s", session_id, exc_info=True)
            return False


def finish_calibration(
    store,
    session_id: str,
    *,
    result,
    status: str,
    cause: str | None,
    now: datetime,
    heater_id: str | None = None,
    alerts=None,
) -> bool:
    """Finish the durable saga and independently queue the SMTP fallback."""
    completed = store.calibration.finish(
        session_id,
        result=result,
        status=status,
        cause=cause,
        now=now,
    )
    if completed:
        _notify_terminal_email(
            store,
            session_id=session_id,
            heater_id=heater_id or _session_heater_id(store, session_id),
            status=status,
            cause=cause,
            at=now,
            alerts=alerts,
        )
    return completed


def _session_heater_id(store, session_id: str) -> str:
    """Best-effort lookup for the terminal email after the session is deleted."""
    # The session is removed by ``finish`` before this helper runs.  The
    # notification key still gives us a useful installation-level message;
    # callers that know the heater can supply it explicitly.
    return session_id


def _notify_terminal_email(
    store,
    *,
    session_id: str,
    heater_id: str,
    status: str,
    cause: str | None,
    at: datetime,
    alerts=None,
) -> str:
    from .alerts import (
        THERMAL_CALIBRATION_TERMINAL,
        build_alert_service,
        thermal_calibration_terminal_message,
    )

    service = alerts if alerts is not None else build_alert_service(store)
    channel_status = "email_unconfigured"
    if service is not None:
        try:
            subject, body = thermal_calibration_terminal_message(
                installation=store.repository.installation_name(),
                heater_id=heater_id,
                status=status,
                cause=cause,
                at=at,
            )
            queued = service.enqueue_message(
                THERMAL_CALIBRATION_TERMINAL,
                subject=subject,
                body=body,
                session_id=session_id,
            )
            channel_status = "queued" if queued else "email_unconfigured"
        except Exception:  # noqa: BLE001 - SMTP is independent of control
            logger.warning("Could not queue terminal calibration email", exc_info=True)
            channel_status = "email_error"
    try:
        store.calibration.append_notification_status(session_id, channel_status)
    except Exception:  # noqa: BLE001 - in-app notice remains durable
        logger.warning("Could not record terminal email status", exc_info=True)
    return channel_status


def _target(telemetry: ChargeTelemetry, heater: Heater) -> float:
    if telemetry.target_temperature_c is not None:
        return float(telemetry.target_temperature_c)
    enabled = [item.target_temperature_c for item in heater.temperature_targets if item.enabled]
    return float(enabled[0]) if enabled else 21.0


def _missing_inputs(telemetry: ChargeTelemetry | None, outdoor, now: datetime) -> tuple[str, ...]:
    missing: list[str] = []
    if telemetry is None or not _fresh(telemetry.indoor_received_at, now):
        missing.append("indoor_temperature")
    if telemetry is None or not _fresh(telemetry.stored_soc_received_at, now):
        missing.append("soc")
    if outdoor is None or not _fresh(outdoor.received_at, now):
        missing.append("outdoor_temperature")
    return tuple(missing)


def _fresh(value: datetime | None, now: datetime) -> bool:
    return value is not None and timedelta(0) <= now - value <= MAX_INPUT_AGE


def _relay_test_active(view: Mapping[str, Any] | None) -> bool:
    if not view:
        return False
    session = view.get("session")
    if isinstance(session, Mapping) and session.get("status") in {"starting", "active", "ending"}:
        return True
    safety = view.get("safety")
    return bool(
        isinstance(safety, Mapping)
        and (safety.get("fault_latched") or safety.get("audit_degraded"))
    )


def _global_power_available(store, heater: Heater, now: datetime) -> bool:
    """Conservatively reserve a calibration pulse against the site limit."""
    try:
        site = store.planning.site()
        contracted_limit = int(site.get("contracted_power_w", 0) or 0)
        heating_limit = int(site.get("max_heating_power_w", 0) or 0)
        base_load = max(0, int(site.get("base_load_w", 0) or 0))
        states = store.planning.active_plan()
        current_power = 0
        if states and isinstance(states, Mapping):
            for slot in states.get("slots", ()):
                start, end = slot.get("start"), slot.get("end")
                if isinstance(start, datetime) and isinstance(end, datetime) and start <= now < end:
                    current_power = int(slot.get("power_w", 0))
                    # Calibration replaces the selected accumulator's
                    # planned pulse; reserve the global limit against the
                    # other planned heaters before adding its own command.
                    if heater.id in set(slot.get("heater_ids", ())):
                        current_power = max(0, current_power - heater.power_w)
                    break
        # Several accumulators may calibrate concurrently.  Their active
        # charge commands are not represented in the stale planner slot, so
        # reserve those powers before admitting this pulse as well.
        calibration = getattr(store, "calibration", None)
        configuration = store.repository.current()[0]
        for other_heater in configuration.heaters:
            if other_heater.id == heater.id or calibration is None:
                continue
            other = calibration.active(other_heater.id)
            if other is not None and bool(other.commands.get("charge")):
                current_power += other_heater.power_w
        requested_power = current_power + heater.power_w
        if contracted_limit > 0 and base_load + requested_power > contracted_limit:
            return False
        if heating_limit > 0 and requested_power > heating_limit:
            return False
        return True
    except Exception:
        # Unreadable planner state is not permission to energise a relay.
        return False


def _sample_for(
    heater: Heater,
    telemetry: ChargeTelemetry,
    outdoor_temperature_c: float,
    now: datetime,
    phase: str,
) -> CalibrationSample:
    discharge = phase == "release"
    soc = float(telemetry.stored_soc_percent or 0.0)
    damper = telemetry.damper_position_percent
    factor = 1.0 if damper is None else max(0.0, min(1.0, damper / 100.0))
    duration_minutes = int(SAMPLE_PERIOD.total_seconds() / 60)
    duration_hours = SAMPLE_PERIOD.total_seconds() / 3600
    emission_power = (
        heater.static_emission_power_kw
        + (heater.emission_power_kw - heater.static_emission_power_kw) * (soc / 100.0)
    )
    stored_energy = heater.capacity_kwh * (soc / 100.0)
    forced_only = room_energy_step(
        heater,
        start=now,
        outdoor_temperature_c=float(outdoor_temperature_c),
        target_temperature_c=None,
        indoor_temperature_c=float(telemetry.indoor_temperature_c),
        stored_energy_kwh=stored_energy,
        slot_minutes=duration_minutes,
        # The residual path is physical and is not attenuated by the damper.
        # Calculate it separately before applying the calibration gate to the
        # controlled component.
        discharge_enabled=False,
        controlled_heat_kwh=0.0,
    )
    ungated_total = min(stored_energy, emission_power * duration_hours)
    controlled_heat = (
        max(0.0, ungated_total - forced_only.forced_heat_kwh) * factor
        if discharge
        else 0.0
    )
    step = room_energy_step(
        heater,
        start=now,
        outdoor_temperature_c=float(outdoor_temperature_c),
        target_temperature_c=None,
        indoor_temperature_c=float(telemetry.indoor_temperature_c),
        stored_energy_kwh=stored_energy,
        slot_minutes=duration_minutes,
        discharge_enabled=discharge,
        controlled_heat_kwh=controlled_heat,
    )
    return CalibrationSample(
        observed_at=now,
        indoor_temperature_c=float(telemetry.indoor_temperature_c),
        outdoor_temperature_c=float(outdoor_temperature_c),
        soc_percent=soc,
        discharge_enabled=discharge,
        damper_position_percent=damper,
        heat_delivered_kwh=max(0.0, step.heat_delivered_kwh),
        synchronized=True,
        phase=phase,
    )


def _parse_instant(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


__all__ = [
    "CalibrationCoordinator",
    "active_calibration_exclusions",
    "active_calibration_heater_ids",
]
