"""Persistence adapters for automatic thermal calibration and operator channels."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import logging
from typing import Any, Callable, Mapping
from uuid import uuid4

from sqlalchemy import and_, delete, insert, or_, select, update
from sqlalchemy.engine import Engine

from ..thermal_calibration import CalibrationFit, CalibrationSample
from . import ConfigConflictError, ConfigValidationError
from .engine import store_errors, transaction
from .mapping import from_utc, to_utc
from .schema import (
    operator_notification,
    heater as heater_table,
    room,
    thermal_calibration_sample,
    thermal_calibration_session,
    alert_type_config,
    web_push_attempt,
    web_push_subscription,
)
from .url import StoreLocation


PUSH_CLAIM_LEASE_SECONDS = 30
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CalibrationSession:
    id: str
    heater_id: str
    status: str
    phase: str
    started_at: datetime
    updated_at: datetime
    phase_deadline_at: datetime | None
    lease_owner: str | None
    lease_expires_at: datetime | None
    missing_since: dict[str, str]
    commands: dict[str, Any]
    metrics: dict[str, Any]
    terminal_cause: str | None


@dataclass(frozen=True)
class OperatorNotification:
    id: int
    session_id: str | None
    kind: str
    title: str
    body: str
    created_at: datetime
    acknowledged_at: datetime | None = None
    alert_type: str = "thermal_calibration_terminal"
    severity: str = "info"
    episode_id: str | None = None
    opened_at: datetime | None = None
    resolved_at: datetime | None = None


@dataclass(frozen=True)
class WebPushSubscription:
    id: int
    user_id: str
    browser_id: str
    endpoint: str
    p256dh: str
    auth: str
    status: str
    created_at: datetime
    updated_at: datetime
    last_error: str | None


@dataclass(frozen=True)
class WebPushAttempt:
    id: int
    subscription_id: int
    session_id: str
    status: str
    attempted_at: datetime | None
    error: str | None
    alert_id: int | None = None
    claimed_by: str | None = None
    claimed_until: datetime | None = None


class SqlCalibrationRepository:
    """Keep active calibration operational data restart-safe and bounded."""

    def __init__(
        self,
        configuration_engine: Engine,
        application_engine: Engine,
        installation_id: int,
        configuration_location: StoreLocation | None = None,
        application_location: StoreLocation | None = None,
        *,
        clock=None,
    ) -> None:
        self._configuration = configuration_engine
        self._application = application_engine
        self._installation_id = installation_id
        self._configuration_location = configuration_location
        self._application_location = application_location
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def active(self, heater_id: str | None = None) -> CalibrationSession | None:
        with store_errors(self._application_location):
            with self._application.connect() as connection:
                query = select(thermal_calibration_session).where(
                    thermal_calibration_session.c.installation_id == self._installation_id
                )
                if heater_id is not None:
                    query = query.where(thermal_calibration_session.c.heater_id == heater_id)
                row = connection.execute(query.order_by(thermal_calibration_session.c.updated_at.desc())).mappings().first()
        return None if row is None else _session_from_row(row)

    def projection(self, config) -> dict[str, dict[str, Any]]:
        """Compact read model shared by MQTT, API and Home Assistant."""
        active_by_heater: dict[str, CalibrationSession] = {}
        with self._application.connect() as connection:
            rows = connection.execute(
                select(thermal_calibration_session).where(
                    thermal_calibration_session.c.installation_id == self._installation_id
                )
            ).mappings().all()
        for row in rows:
            active_by_heater[str(row["heater_id"])] = _session_from_row(row)
        result: dict[str, dict[str, Any]] = {}
        for heater in config.heaters:
            room_value = heater.room
            payload = {
                "status": "approximate" if room_value is None else room_value.status,
                "capacity_kwh_per_c": heater.room_thermal_capacity_kwh_per_c,
                "loss_kw_per_c": heater.room_heat_loss_kw_per_c,
            }
            session = active_by_heater.get(heater.id)
            if session is not None:
                payload.update(
                    {
                        "session_id": session.id,
                        "phase": session.phase,
                        "progress": session.metrics.get("progress"),
                        "quality": session.metrics.get("quality"),
                        "commands": dict(session.commands),
                    }
                )
            elif room_value is not None and room_value.terminal_result is not None:
                payload["result"] = room_value.terminal_result
                if room_value.terminal_at is not None:
                    terminal_age = self._clock() - room_value.terminal_at
                    if timedelta(0) <= terminal_age <= timedelta(seconds=30):
                        # Keep a just-finished session's output projection
                        # authoritative for one publication cycle.  A
                        # controller that restarts between the terminal DB
                        # commit and its next MQTT poll must still publish OFF
                        # rather than resurrecting a planned discharge.
                        payload["commands"] = {"terminal_off": True}
            result[heater.id] = payload
        return result

    def samples(self, session_id: str) -> tuple[CalibrationSample, ...]:
        with store_errors(self._application_location):
            with self._application.connect() as connection:
                rows = connection.execute(
                    select(thermal_calibration_sample)
                    .join(
                        thermal_calibration_session,
                        thermal_calibration_sample.c.session_id == thermal_calibration_session.c.id,
                    )
                    .where(
                        (thermal_calibration_sample.c.session_id == session_id)
                        & (thermal_calibration_session.c.installation_id == self._installation_id)
                    )
                    .order_by(thermal_calibration_sample.c.observed_at, thermal_calibration_sample.c.id)
                ).mappings().all()
        return tuple(
            CalibrationSample(
                observed_at=from_utc(row["observed_at"]),
                indoor_temperature_c=float(row["indoor_temperature_c"]),
                outdoor_temperature_c=float(row["outdoor_temperature_c"]),
                soc_percent=float(row["soc_percent"]),
                discharge_enabled=bool(row["discharge_enabled"]),
                damper_position_percent=None if row["damper_position_percent"] is None else float(row["damper_position_percent"]),
                heat_delivered_kwh=float(row["heat_delivered_kwh"] or 0),
                synchronized=bool(row["synchronized"]),
                phase=None if row.get("phase") is None else str(row["phase"]),
            )
            for row in rows
        )

    def start(
        self,
        heater_id: str,
        *,
        now: datetime | None = None,
        phase: str = "baseline",
        deadline: datetime | None = None,
        lease_owner: str | None = None,
    ) -> CalibrationSession:
        moment = to_utc(now or self._clock())
        session_id = str(uuid4())
        with transaction(self._application, self._application_location) as connection:
            if connection.execute(
                select(thermal_calibration_session.c.id).where(
                    (thermal_calibration_session.c.installation_id == self._installation_id)
                    & (thermal_calibration_session.c.heater_id == heater_id)
                )
            ).first() is not None:
                raise ConfigConflictError("a calibration session is already active for this accumulator")
            connection.execute(
                insert(thermal_calibration_session).values(
                    id=session_id,
                    installation_id=self._installation_id,
                    heater_id=heater_id,
                    status="active",
                    phase=phase,
                    started_at=moment,
                    updated_at=moment,
                    phase_deadline_at=None if deadline is None else to_utc(deadline),
                    lease_owner=lease_owner,
                    lease_expires_at=None,
                    missing_since_json="{}",
                    commands_json="{}",
                    metrics_json="{}",
                )
            )
        result = self.active(heater_id)
        assert result is not None
        return result

    def save_state(
        self,
        session_id: str,
        *,
        phase: str | None = None,
        phase_deadline_at: datetime | None = None,
        lease_owner: str | None = None,
        lease_expires_at: datetime | None = None,
        missing_since: Mapping[str, str] | None = None,
        commands: Mapping[str, Any] | None = None,
        metrics: Mapping[str, Any] | None = None,
        now: datetime | None = None,
    ) -> bool:
        moment = to_utc(now or self._clock())
        values: dict[str, Any] = {"updated_at": moment}
        if phase is not None:
            values["phase"] = phase
        if phase_deadline_at is not None:
            values["phase_deadline_at"] = to_utc(phase_deadline_at)
        if lease_owner is not None:
            values["lease_owner"] = lease_owner
        if lease_expires_at is not None:
            values["lease_expires_at"] = to_utc(lease_expires_at)
        if missing_since is not None:
            values["missing_since_json"] = json.dumps(dict(missing_since), sort_keys=True)
        if commands is not None:
            values["commands_json"] = json.dumps(dict(commands), sort_keys=True)
        if metrics is not None:
            values["metrics_json"] = json.dumps(dict(metrics), sort_keys=True)
        with transaction(self._application, self._application_location) as connection:
            changed = connection.execute(
                update(thermal_calibration_session)
                .where(
                    (thermal_calibration_session.c.id == session_id)
                    & (thermal_calibration_session.c.installation_id == self._installation_id)
                    & (thermal_calibration_session.c.status == "active")
                )
                .values(**values)
            ).rowcount
        return changed == 1

    def confirm_command(
        self,
        heater_id: str,
        output: str,
        *,
        at: datetime | None = None,
    ) -> bool:
        """Record a successful charge/discharge boundary acknowledgement.

        The controller and MQTT publisher are separate processes.  Both use
        this idempotent projection after their transport reports success; the
        next calibration tick can therefore require an explicit confirmation
        instead of inferring one from an issued command.
        """
        if output not in {"charge", "discharge"}:
            raise ConfigValidationError("calibration output is invalid")
        moment = to_utc(at or self._clock())
        with transaction(self._application, self._application_location) as connection:
            row = connection.execute(
                select(thermal_calibration_session).where(
                    (thermal_calibration_session.c.installation_id == self._installation_id)
                    & (thermal_calibration_session.c.heater_id == heater_id)
                    & (thermal_calibration_session.c.status == "active")
                )
            ).mappings().first()
            if row is None:
                return False
            commands = _json_object(row["commands_json"])
            confirmations = _json_object(commands.get("confirmations"))
            confirmations[output] = True
            commands["confirmations"] = confirmations
            changed = connection.execute(
                update(thermal_calibration_session)
                .where(
                    (thermal_calibration_session.c.id == row["id"])
                    & (thermal_calibration_session.c.installation_id == self._installation_id)
                    & (thermal_calibration_session.c.status == "active")
                )
                .values(commands_json=json.dumps(commands, sort_keys=True), updated_at=moment)
            ).rowcount
        return changed == 1

    def renew_lease(self, session_id: str, owner: str, *, now: datetime | None = None, seconds: int = 30) -> bool:
        moment = now or self._clock()
        return self.save_state(
            session_id,
            lease_owner=owner,
            lease_expires_at=moment + timedelta(seconds=seconds),
            now=moment,
        )

    def claim_lease(
        self,
        session_id: str,
        owner: str,
        *,
        now: datetime | None = None,
        seconds: int = 30,
    ) -> bool:
        """Claim an expired or unowned session without stealing a live owner."""
        moment = to_utc(now or self._clock())
        deadline = moment + timedelta(seconds=seconds)
        with transaction(self._application, self._application_location) as connection:
            changed = connection.execute(
                update(thermal_calibration_session)
                .where(
                    (thermal_calibration_session.c.id == session_id)
                    & (thermal_calibration_session.c.installation_id == self._installation_id)
                    & (thermal_calibration_session.c.status == "active")
                    & (
                        thermal_calibration_session.c.lease_owner.is_(None)
                        | (thermal_calibration_session.c.lease_expires_at <= moment)
                        | (thermal_calibration_session.c.lease_owner == owner)
                    )
                )
                .values(lease_owner=owner, lease_expires_at=deadline, updated_at=moment)
            ).rowcount
        return changed == 1

    def add_sample(self, session_id: str, sample: CalibrationSample) -> int:
        with transaction(self._application, self._application_location) as connection:
            valid = connection.execute(
                select(thermal_calibration_session.c.id).where(
                    (thermal_calibration_session.c.id == session_id)
                    & (thermal_calibration_session.c.installation_id == self._installation_id)
                    & (thermal_calibration_session.c.status == "active")
                )
            ).first()
            if valid is None:
                raise ConfigValidationError("calibration session is not active")
            return int(
                connection.execute(
                    insert(thermal_calibration_sample).values(
                        session_id=session_id,
                        observed_at=to_utc(sample.observed_at),
                        indoor_temperature_c=sample.indoor_temperature_c,
                        outdoor_temperature_c=sample.outdoor_temperature_c,
                        soc_percent=sample.soc_percent,
                        discharge_enabled=sample.discharge_enabled,
                        damper_position_percent=sample.damper_position_percent,
                        heat_delivered_kwh=sample.heat_delivered_kwh,
                        synchronized=sample.synchronized,
                        phase=sample.phase,
                    )
                ).inserted_primary_key[0]
            )

    def abort_start(self, session_id: str) -> bool:
        """Remove a just-created session without a terminal side effect.

        API startup spans the application and configuration stores.  If the
        optimistic configuration write loses a race after the application row
        was inserted, this compensating step restores the pre-start state
        without creating a false cancellation notice.
        """
        with transaction(self._application, self._application_location) as connection:
            connection.execute(
                delete(thermal_calibration_sample).where(
                    thermal_calibration_sample.c.session_id == session_id
                )
            )
            changed = connection.execute(
                delete(thermal_calibration_session).where(
                    (thermal_calibration_session.c.id == session_id)
                    & (thermal_calibration_session.c.installation_id == self._installation_id)
                )
            ).rowcount
        return changed == 1

    def finish(
        self,
        session_id: str,
        *,
        result: CalibrationFit | None,
        status: str,
        cause: str | None = None,
        now: datetime | None = None,
    ) -> bool:
        if status not in {"calibrated", "failed", "cancelled"}:
            raise ConfigValidationError("terminal calibration status is invalid")
        notification_at = now or self._clock()
        moment = to_utc(notification_at)
        with self._application.connect() as connection:
            row = connection.execute(
                select(thermal_calibration_session).where(
                    (thermal_calibration_session.c.id == session_id)
                    & (thermal_calibration_session.c.installation_id == self._installation_id)
                )
            ).mappings().first()
        if row is None:
            return False
        fit_summary = {} if result is None else {
            "capacity_kwh_per_c": result.capacity_kwh_per_c,
            "loss_kw_per_c": result.loss_kw_per_c,
            "quality": result.quality.__dict__,
        }
        fit_summary.update({"session_id": session_id, "status": status})
        # Config and application databases are separate by design.  The room
        # update and generation bump form the first saga step.  The terminal
        # session marker makes a retry after a process crash idempotent.
        heater_id = str(row["heater_id"])
        with transaction(self._configuration, self._configuration_location) as connection:
            heater_key = connection.execute(
                select(heater_table.c.id).where(
                    (heater_table.c.installation_id == self._installation_id)
                    & (heater_table.c.heater_id == heater_id)
                )
            ).scalar()
            if heater_key is None:
                raise ConfigValidationError("heater is missing for the terminal accumulator")
            room_row = connection.execute(
                select(room).where(room.c.heater_id == heater_key)
            ).mappings().first()
            if room_row is None:
                raise ConfigValidationError("room is missing for the terminal accumulator")
            previous_result = _json_object(room_row["terminal_result_json"])
            already_applied = (
                room_row["applied_session_id"] == session_id
                or previous_result.get("session_id") == session_id
            )
            if not already_applied:
                if status == "calibrated" and result is not None and result.acceptable:
                    values = dict(
                        room_thermal_capacity_kwh_per_c=result.capacity_kwh_per_c,
                        room_heat_loss_kw_per_c=result.loss_kw_per_c,
                        status="calibrated",
                        applied_session_id=session_id,
                        terminal_result_json=json.dumps(fit_summary, sort_keys=True, default=str),
                        terminal_cause=cause,
                        terminal_at=moment,
                        updated_at=moment,
                    )
                else:
                    values = dict(
                        status=status,
                        applied_session_id=None,
                        terminal_result_json=json.dumps(fit_summary, sort_keys=True, default=str),
                        terminal_cause=cause,
                        terminal_at=moment,
                        updated_at=moment,
                    )
                changed = connection.execute(
                    update(room)
                    .where(room.c.heater_id == heater_key)
                    .values(**values)
                ).rowcount
                if changed != 1:
                    raise ConfigValidationError("room terminal transition was not applied")
                _mirror_legacy_thermal_profile(connection, int(heater_key))
                # The installation generation is the planner's cross-process
                # invalidation signal.  A terminal calibration always requests
                # a new plan, even when the previous coefficients are retained.
                from .schema import installation

                connection.execute(
                    update(installation)
                    .where(installation.c.id == self._installation_id)
                    .values(
                        revision=installation.c.revision + 1,
                        recalculation_requested_generation=(
                            installation.c.recalculation_requested_generation + 1
                        ),
                        updated_at=moment,
                    )
                )
        with transaction(self._application, self._application_location) as connection:
            connection.execute(
                delete(thermal_calibration_sample).where(
                    thermal_calibration_sample.c.session_id == session_id
                )
            )
            connection.execute(
                delete(thermal_calibration_session).where(
                    (thermal_calibration_session.c.id == session_id)
                    & (thermal_calibration_session.c.installation_id == self._installation_id)
                )
            )
        notification_id = self.create_notification(
            session_id,
            kind=f"thermal_calibration_{status}",
            title="Calibración térmica finalizada",
            body=cause or ("Calibración aplicada" if status == "calibrated" else "Calibración no aplicada"),
            at=notification_at,
        )
        # Queue one durable attempt per current browser.  The unique key on
        # ``web_push_attempt`` makes this safe when a controller restart
        # retries the terminal saga.
        self.queue_push_attempts(session_id, alert_id=notification_id)
        return True

    # ------------------------------------------------------------------ UI notifications

    def create_notification(self, session_id: str | None, *, kind: str, title: str, body: str, at: datetime | None = None) -> int:
        moment = to_utc(at or self._clock())
        episode_id = session_id or str(uuid4())
        with transaction(self._application, self._application_location) as connection:
            existing = None
            if session_id is not None:
                existing = connection.execute(
                    select(operator_notification.c.id).where(
                        (operator_notification.c.installation_id == self._installation_id)
                        & (operator_notification.c.session_id == session_id)
                    )
                ).scalar()
            if existing is not None:
                return int(existing)
            return int(
                connection.execute(
                    insert(operator_notification).values(
                        installation_id=self._installation_id,
                        session_id=session_id,
                        kind=kind,
                        alert_type="thermal_calibration_terminal",
                        severity="info",
                        episode_id=episode_id,
                        title=title[:512],
                        body=body,
                        created_at=moment,
                        opened_at=moment,
                        # Calibration is an event, so it is resolved when
                        # created while remaining visible in history.
                        resolved_at=moment,
                    )
                ).inserted_primary_key[0]
            )

    def notifications(self, *, include_acknowledged: bool = False, limit: int = 100) -> tuple[OperatorNotification, ...]:
        with self._application.connect() as connection:
            # Compatibility surface for the calibration page. The global
            # alerts page reads through SqlAlertRepository; this method keeps
            # terminal calibration events visible until explicitly accused.
            query = select(operator_notification).where(
                (operator_notification.c.installation_id == self._installation_id)
                & operator_notification.c.session_id.is_not(None)
            )
            if not include_acknowledged:
                query = query.where(operator_notification.c.acknowledged_at.is_(None))
            rows = connection.execute(query.order_by(operator_notification.c.created_at.desc(), operator_notification.c.id.desc()).limit(limit)).mappings().all()
        return tuple(_notification_from_row(row) for row in rows)

    def append_notification_status(self, session_id: str, status: str) -> bool:
        """Record an independent channel outcome beside the in-app notice."""
        with transaction(self._application, self._application_location) as connection:
            row = connection.execute(
                select(operator_notification.c.id, operator_notification.c.body).where(
                    (operator_notification.c.installation_id == self._installation_id)
                    & (operator_notification.c.session_id == session_id)
                )
            ).mappings().first()
            if row is None:
                return False
            marker = f"[{status}]"
            if marker in str(row["body"]):
                return True
            connection.execute(
                update(operator_notification)
                .where(operator_notification.c.id == row["id"])
                .values(body=f"{row['body']}\n{marker}")
            )
            return True

    def acknowledge_notification(self, notification_id: int, *, at: datetime | None = None) -> bool:
        with transaction(self._application, self._application_location) as connection:
            changed = connection.execute(
                update(operator_notification)
                .where(
                    (operator_notification.c.id == notification_id)
                    & (operator_notification.c.installation_id == self._installation_id)
                    & operator_notification.c.acknowledged_at.is_(None)
                )
                .values(acknowledged_at=to_utc(at or self._clock()))
            ).rowcount
            return changed == 1

    # ------------------------------------------------------------------ Push subscriptions

    def register_subscription(self, *, user_id: str, browser_id: str, endpoint: str, p256dh: str, auth: str, at: datetime | None = None) -> WebPushSubscription:
        for value, name in ((user_id, "user_id"), (browser_id, "browser_id"), (endpoint, "endpoint"), (p256dh, "p256dh"), (auth, "auth")):
            if not str(value).strip():
                raise ConfigValidationError(f"push {name} cannot be empty")
        moment = to_utc(at or self._clock())
        with transaction(self._application, self._application_location) as connection:
            existing = connection.execute(
                select(web_push_subscription).where(
                    (web_push_subscription.c.installation_id == self._installation_id)
                    & (web_push_subscription.c.user_id == user_id)
                    & (web_push_subscription.c.browser_id == browser_id)
                )
            ).mappings().first()
            values = dict(endpoint=endpoint, p256dh=p256dh, auth=auth, status="active", updated_at=moment, last_error=None)
            if existing is None:
                subscription_id = connection.execute(
                    insert(web_push_subscription).values(
                        installation_id=self._installation_id,
                        user_id=user_id,
                        browser_id=browser_id,
                        created_at=moment,
                        **values,
                    )
                ).inserted_primary_key[0]
            else:
                subscription_id = existing["id"]
                connection.execute(update(web_push_subscription).where(web_push_subscription.c.id == subscription_id).values(**values))
        return self.subscription(int(subscription_id))  # type: ignore[return-value]

    def revoke_subscription(self, *, user_id: str, browser_id: str, at: datetime | None = None) -> bool:
        with transaction(self._application, self._application_location) as connection:
            return connection.execute(
                update(web_push_subscription)
                .where(
                    (web_push_subscription.c.installation_id == self._installation_id)
                    & (web_push_subscription.c.user_id == user_id)
                    & (web_push_subscription.c.browser_id == browser_id)
                )
                .values(status="revoked", updated_at=to_utc(at or self._clock()))
            ).rowcount == 1

    def subscription(self, subscription_id: int) -> WebPushSubscription | None:
        with self._application.connect() as connection:
            row = connection.execute(select(web_push_subscription).where((web_push_subscription.c.id == subscription_id) & (web_push_subscription.c.installation_id == self._installation_id))).mappings().first()
        return None if row is None else _subscription_from_row(row)

    def subscriptions(self) -> tuple[WebPushSubscription, ...]:
        with self._application.connect() as connection:
            rows = connection.execute(select(web_push_subscription).where((web_push_subscription.c.installation_id == self._installation_id) & (web_push_subscription.c.status == "active")).order_by(web_push_subscription.c.id)).mappings().all()
        return tuple(_subscription_from_row(row) for row in rows)

    def mark_subscription_status(
        self,
        subscription_id: int,
        *,
        status: str,
        error: str | None = None,
        at: datetime | None = None,
    ) -> bool:
        if status not in {"active", "revoked", "expired", "error"}:
            raise ConfigValidationError("push subscription status is invalid")
        with transaction(self._application, self._application_location) as connection:
            return connection.execute(
                update(web_push_subscription)
                .where(
                    (web_push_subscription.c.id == subscription_id)
                    & (web_push_subscription.c.installation_id == self._installation_id)
                )
                .values(
                    status=status,
                    updated_at=to_utc(at or self._clock()),
                    last_error=None if error is None else error[:512],
                )
            ).rowcount == 1

    def queue_push_attempts(self, session_id: str, *, alert_id: int | None = None) -> tuple[WebPushAttempt, ...]:
        if alert_id is not None and not self._alert_type_enabled(
            "thermal_calibration_terminal"
        ):
            return self.push_attempts(session_id)
        with transaction(self._application, self._application_location) as connection:
            for subscription in connection.execute(select(web_push_subscription).where((web_push_subscription.c.installation_id == self._installation_id) & (web_push_subscription.c.status == "active"))).mappings():
                predicate = (
                    (web_push_attempt.c.alert_id == alert_id)
                    & (web_push_attempt.c.subscription_id == subscription["id"])
                    if alert_id is not None
                    else (web_push_attempt.c.session_id == session_id)
                    & (web_push_attempt.c.subscription_id == subscription["id"])
                )
                existing = connection.execute(select(web_push_attempt.c.id).where(predicate)).scalar()
                if existing is None:
                    connection.execute(insert(web_push_attempt).values(subscription_id=subscription["id"], session_id=session_id, alert_id=alert_id, status="pending"))
        return self.push_attempts(session_id)

    def _alert_type_enabled(self, alert_type: str) -> bool:
        with self._configuration.connect() as connection:
            row = connection.execute(
                select(alert_type_config.c.enabled).where(
                    alert_type_config.c.name == alert_type
                )
            ).first()
        return True if row is None else bool(row[0])

    @contextmanager
    def _locked_type_enabled(self, alert_type: str):
        """Read one catalogue row while holding its transaction lock."""
        with transaction(self._configuration, self._configuration_location) as connection:
            try:
                row = connection.execute(
                    select(alert_type_config.c.enabled)
                    .where(alert_type_config.c.name == alert_type)
                    .with_for_update()
                ).first()
            except Exception:  # noqa: BLE001 - Push delivery remains best effort
                logger.warning(
                    "Could not read catalogue state for Push alert %s",
                    alert_type,
                    exc_info=True,
                )
                row = None
            yield True if row is None else bool(row[0])

    def alert_type_enabled(self, alert_type: str) -> bool:
        """Expose catalogue state to the independent Push worker."""
        return self._alert_type_enabled(alert_type)

    def push_attempts(self, session_id: str) -> tuple[WebPushAttempt, ...]:
        with self._application.connect() as connection:
            rows = connection.execute(
                select(web_push_attempt)
                .where(
                    web_push_attempt.c.session_id == session_id,
                    web_push_attempt.c.subscription_id.in_(
                        select(web_push_subscription.c.id).where(
                            web_push_subscription.c.installation_id
                            == self._installation_id
                        )
                    ),
                )
                .order_by(web_push_attempt.c.id)
            ).mappings().all()
        return tuple(_attempt_from_row(row) for row in rows)

    def pending_push_session_ids(self) -> tuple[str, ...]:
        """Return terminal sessions whose Push work still needs delivery."""
        with self._application.connect() as connection:
            rows = connection.execute(
                select(web_push_attempt.c.session_id)
                .where(
                    web_push_attempt.c.status.in_(("pending", "error")),
                    web_push_attempt.c.subscription_id.in_(
                        select(web_push_subscription.c.id).where(
                            web_push_subscription.c.installation_id
                            == self._installation_id
                        )
                    ),
                )
                .distinct()
                .order_by(web_push_attempt.c.session_id)
            ).scalars().all()
        return tuple(str(value) for value in rows)

    def pending_push_alert_ids(self) -> tuple[int, ...]:
        with self._application.connect() as connection:
            rows = connection.execute(
                select(web_push_attempt.c.alert_id)
                .where(
                    web_push_attempt.c.alert_id.is_not(None),
                    web_push_attempt.c.status.in_(("pending", "error")),
                    web_push_attempt.c.subscription_id.in_(
                        select(web_push_subscription.c.id).where(
                            web_push_subscription.c.installation_id
                            == self._installation_id
                        )
                    ),
                )
                .distinct()
                .order_by(web_push_attempt.c.alert_id)
            ).scalars().all()
        return tuple(int(value) for value in rows)

    def push_attempts_for_alert(self, alert_id: int) -> tuple[WebPushAttempt, ...]:
        with self._application.connect() as connection:
            rows = connection.execute(
                select(web_push_attempt)
                .where(
                    web_push_attempt.c.alert_id == alert_id,
                    web_push_attempt.c.subscription_id.in_(
                        select(web_push_subscription.c.id).where(
                            web_push_subscription.c.installation_id
                            == self._installation_id
                        )
                    ),
                )
                .order_by(web_push_attempt.c.id)
            ).mappings().all()
        return tuple(_attempt_from_row(row) for row in rows)

    def claim_push_attempt(
        self,
        attempt_id: int,
        *,
        owner: str,
        at: datetime | None = None,
        lease_seconds: int = PUSH_CLAIM_LEASE_SECONDS,
    ) -> bool:
        """Claim one Push attempt so API/controller workers cannot duplicate it."""
        moment = to_utc(at or self._clock())
        lease_until = moment + timedelta(seconds=lease_seconds)
        with transaction(self._application, self._application_location) as connection:
            return (
                connection.execute(
                    update(web_push_attempt)
                    .where(
                        and_(
                            web_push_attempt.c.id == attempt_id,
                            web_push_attempt.c.status.in_(("pending", "error")),
                            or_(
                                web_push_attempt.c.claimed_until.is_(None),
                                web_push_attempt.c.claimed_until <= moment,
                            ),
                            web_push_attempt.c.subscription_id.in_(
                                select(web_push_subscription.c.id).where(
                                    web_push_subscription.c.installation_id
                                    == self._installation_id
                                )
                            ),
                        )
                    )
                    .values(claimed_by=owner, claimed_until=lease_until)
                ).rowcount
                == 1
            )

    def deliver_claimed_push(
        self,
        attempt_id: int,
        *,
        owner: str,
        at: datetime,
        alert_type: str | None,
        send: Callable[[WebPushSubscription], None],
    ) -> str:
        """Revalidate a Push claim while serialising catalogue cleanup."""
        moment = to_utc(at)
        with transaction(self._application, self._application_location) as connection:
            condition = and_(
                web_push_attempt.c.id == attempt_id,
                web_push_attempt.c.status.in_(("pending", "error")),
                web_push_attempt.c.claimed_by == owner,
                web_push_attempt.c.claimed_until > moment,
                web_push_attempt.c.subscription_id.in_(
                    select(web_push_subscription.c.id).where(
                        web_push_subscription.c.installation_id == self._installation_id
                    )
                ),
            )
            claimed = connection.execute(
                update(web_push_attempt)
                .where(condition)
                # Retain the lease while taking the row lock used to
                # serialise this handoff with catalogue cleanup.
                .values(claimed_until=web_push_attempt.c.claimed_until)
            ).rowcount
            if claimed != 1:
                return "lost"
            subscription_row = connection.execute(
                select(web_push_subscription).where(
                    and_(
                        web_push_subscription.c.id
                        == select(web_push_attempt.c.subscription_id)
                        .where(web_push_attempt.c.id == attempt_id)
                        .scalar_subquery(),
                        web_push_subscription.c.installation_id == self._installation_id,
                    )
                )
            ).mappings().first()
            if subscription_row is None or subscription_row["status"] != "active":
                return "inactive"
            if alert_type is None:
                send(_subscription_from_row(subscription_row))
            else:
                with self._locked_type_enabled(alert_type) as enabled:
                    if not enabled:
                        connection.execute(
                            update(web_push_attempt)
                            .where(web_push_attempt.c.id == attempt_id)
                            .values(
                                status="denied",
                                error="alert_type_disabled",
                                attempted_at=moment,
                                claimed_by=None,
                                claimed_until=None,
                            )
                        )
                        return "disabled"
                    send(_subscription_from_row(subscription_row))
        return "sent"

    def alert_notification(self, alert_id: int) -> OperatorNotification | None:
        with self._application.connect() as connection:
            row = connection.execute(
                select(operator_notification).where(
                    (operator_notification.c.id == alert_id)
                    & (operator_notification.c.installation_id == self._installation_id)
                )
            ).mappings().first()
        return None if row is None else _notification_from_row(row)

    def mark_push_attempt(
        self,
        attempt_id: int,
        *,
        status: str,
        error: str | None = None,
        at: datetime | None = None,
        owner: str | None = None,
    ) -> bool:
        if status not in {"pending", "sent", "denied", "unsupported", "expired", "error"}:
            raise ConfigValidationError("push attempt status is invalid")
        moment = to_utc(at if at is not None else self._clock())
        with transaction(self._application, self._application_location) as connection:
            conditions = [
                web_push_attempt.c.id == attempt_id,
                web_push_attempt.c.subscription_id.in_(
                    select(web_push_subscription.c.id).where(
                        web_push_subscription.c.installation_id
                        == self._installation_id
                    )
                ),
            ]
            if owner is not None:
                conditions.append(web_push_attempt.c.claimed_by == owner)
                conditions.append(web_push_attempt.c.claimed_until > moment)
            return connection.execute(
                update(web_push_attempt)
                .where(and_(*conditions))
                .values(
                    status=status,
                    error=None if error is None else error[:512],
                    attempted_at=moment,
                    claimed_by=None,
                    claimed_until=None,
                )
            ).rowcount == 1


def _json_object(value: object) -> dict[str, Any]:
    if not value:
        return {}
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return {}
    return dict(value) if isinstance(value, Mapping) else {}


def _mirror_legacy_thermal_profile(connection, heater_key: int) -> None:
    """Best-effort mirror for the legacy one-database compatibility table."""
    from .schema import thermal_profile

    try:
        values = connection.execute(
            select(room).where(room.c.heater_id == heater_key)
        ).mappings().first()
        if values is not None:
            connection.execute(
                update(thermal_profile)
                .where(thermal_profile.c.heater_id == values["heater_id"])
                .values(
                    room_thermal_capacity_kwh_per_c=values[
                        "room_thermal_capacity_kwh_per_c"
                    ],
                    room_heat_loss_kw_per_c=values["room_heat_loss_kw_per_c"],
                )
            )
    except Exception:
        # Split stores deliberately omit the compatibility relation.
        return


def _session_from_row(row: Mapping[str, Any]) -> CalibrationSession:
    return CalibrationSession(
        id=str(row["id"]),
        heater_id=str(row["heater_id"]),
        status=str(row["status"]),
        phase=str(row["phase"]),
        started_at=from_utc(row["started_at"]),
        updated_at=from_utc(row["updated_at"]),
        phase_deadline_at=from_utc(row["phase_deadline_at"]),
        lease_owner=None if row["lease_owner"] is None else str(row["lease_owner"]),
        lease_expires_at=from_utc(row["lease_expires_at"]),
        missing_since=_json_object(row["missing_since_json"]),
        commands=_json_object(row["commands_json"]),
        metrics=_json_object(row["metrics_json"]),
        terminal_cause=None if row["terminal_cause"] is None else str(row["terminal_cause"]),
    )


def _notification_from_row(row: Mapping[str, Any]) -> OperatorNotification:
    return OperatorNotification(
        id=int(row["id"]),
        session_id=None if row["session_id"] is None else str(row["session_id"]),
        kind=str(row["kind"]),
        alert_type=str(row.get("alert_type") or row["kind"]),
        severity=str(row.get("severity") or "info"),
        episode_id=None if row.get("episode_id") is None else str(row["episode_id"]),
        title=str(row["title"]),
        body=str(row["body"]),
        created_at=from_utc(row["created_at"]),
        opened_at=from_utc(row.get("opened_at") or row["created_at"]),
        resolved_at=from_utc(row.get("resolved_at")),
        acknowledged_at=from_utc(row["acknowledged_at"]),
    )


def _subscription_from_row(row: Mapping[str, Any]) -> WebPushSubscription:
    return WebPushSubscription(
        id=int(row["id"]),
        user_id=str(row["user_id"]),
        browser_id=str(row["browser_id"]),
        endpoint=str(row["endpoint"]),
        p256dh=str(row["p256dh"]),
        auth=str(row["auth"]),
        status=str(row["status"]),
        created_at=from_utc(row["created_at"]),
        updated_at=from_utc(row["updated_at"]),
        last_error=None if row["last_error"] is None else str(row["last_error"]),
    )


def _attempt_from_row(row: Mapping[str, Any]) -> WebPushAttempt:
    return WebPushAttempt(
        id=int(row["id"]),
        subscription_id=int(row["subscription_id"]),
        session_id=str(row["session_id"]),
        alert_id=None if row.get("alert_id") is None else int(row["alert_id"]),
        status=str(row["status"]),
        attempted_at=from_utc(row["attempted_at"]),
        error=None if row["error"] is None else str(row["error"]),
        claimed_by=None if row.get("claimed_by") is None else str(row["claimed_by"]),
        claimed_until=from_utc(row.get("claimed_until")),
    )


__all__ = [
    "CalibrationSession",
    "OperatorNotification",
    "SqlCalibrationRepository",
    "WebPushAttempt",
    "WebPushSubscription",
]
