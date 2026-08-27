"""Short SQL transactions for relay-test coordination.

This module deliberately never imports a driver.  HTTP records an intention and
the controller, in its own process, is the sole component that confirms GPIO.
"""
from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import and_, delete, insert, select, update
from sqlalchemy.engine import Engine

from . import ConfigConflictError, RelayTestError
from .engine import transaction
from .mapping import to_utc
from .repository import SqlConfigRepository
from .schema import controller_heartbeat, heater, installation, relay_test_control, relay_test_event, relay_test_output, relay_test_session
from .mapping import from_utc
from .url import StoreLocation


class SqlRelayTestRepository:
    def __init__(self, engine: Engine, location: StoreLocation | None = None, clock=None) -> None:
        self._engine, self._location, self._clock = engine, location, clock

    def _at(self, value: datetime) -> datetime:
        return to_utc(value)

    def _installation_id(self, connection) -> int:
        row = connection.execute(select(installation.c.id).order_by(installation.c.id).limit(1)).scalar()
        if row is None:
            raise RelayTestError("no_configuration", "no installation is configured")
        return int(row)

    def _view(self, connection, session_id: str | None, digest: str | None = None) -> dict | None:
        control = connection.execute(select(relay_test_control).where(relay_test_control.c.installation_id == self._installation_id(connection))).mappings().first()
        if control is None:
            return None
        session = None
        if session_id is not None:
            session = connection.execute(select(relay_test_session).where(relay_test_session.c.id == session_id)).mappings().first()
        if session is None and control["session_id"]:
            session = connection.execute(select(relay_test_session).where(relay_test_session.c.id == control["session_id"])).mappings().first()
        if session is None and not control["fault_latched"] and not control["audit_degraded"]:
            return None
        outputs = [] if session is None else [dict(row) for row in connection.execute(select(relay_test_output).where(relay_test_output.c.session_id == session["id"]).order_by(relay_test_output.c.position, relay_test_output.c.heater_id)).mappings()]
        return {"session": None if session is None else dict(session, owner=bool(digest and digest == session["owner_credential_digest"])), "safety": dict(control), "audit": {"degraded": bool(control["audit_degraded"]), "degraded_since": control["audit_degraded_since"]}, "heaters": outputs}

    def current(self, credential_digest: str | None = None) -> dict | None:
        with self._engine.connect() as connection:
            return self._view(connection, None, credential_digest)

    def get(self, session_id: str, credential_digest: str | None = None) -> dict | None:
        with self._engine.connect() as connection:
            return self._view(connection, session_id, credential_digest)

    def claim(self, credential_digest: str, now: datetime, lease_seconds: int) -> dict:
        from datetime import timedelta
        now = self._at(now)
        with transaction(self._engine, self._location) as connection:
            iid = self._installation_id(connection)
            control = connection.execute(select(relay_test_control).where(relay_test_control.c.installation_id == iid)).mappings().first()
            if control is None:
                connection.execute(relay_test_control.insert().values(installation_id=iid, updated_at=now))
                control = {"session_id": None, "fault_latched": False}
            if control["session_id"]:
                raise RelayTestError("relay_test_active", "a relay-test session is already active")
            if control["fault_latched"]:
                raise RelayTestError("relay_test_fault_latched", "safety recovery is still required")
            config, revision = SqlConfigRepository(self._engine, self._location).current()
            # AppConfig preserves the operator's configured order.  Snapshot it
            # once so panel order stays stable for the entire session.
            enabled = [h for h in config.heaters if h.enabled]
            if not enabled:
                raise RelayTestError("no_heaters", "no enabled heaters are configured")
            session_id = str(uuid4())
            connection.execute(relay_test_session.insert().values(id=session_id, installation_id=iid, owner_credential_digest=credential_digest, status="starting", installation_revision=revision, requested_at=now, lease_expires_at=now + timedelta(seconds=lease_seconds), last_owner_seen_at=now))
            connection.execute(relay_test_control.update().where(relay_test_control.c.installation_id == iid).values(session_id=session_id, updated_at=now))
            connection.execute(relay_test_output.insert(), [{"session_id": session_id, "heater_id": h.id, "heater_name": h.name, "position": i, "power_w": h.power_w, "desired_state": False, "command_seq": 0, "result": "idle"} for i, h in enumerate(enabled)])
            self._event(connection, iid, session_id, "session_start", now, "accepted")
            return self._view(connection, session_id, credential_digest) or {}

    def _owner(self, connection, session_id: str, digest: str, now: datetime, active: bool = True):
        row = connection.execute(select(relay_test_session).where(relay_test_session.c.id == session_id)).mappings().first()
        if row is None: raise RelayTestError("not_found", "relay-test session was not found")
        if row["owner_credential_digest"] != digest: raise RelayTestError("relay_test_not_owner", "the relay-test credential does not own this session")
        if active and row["status"] != "active": raise RelayTestError("relay_test_not_active", "the relay-test session is not active")
        if active and now > row["lease_expires_at"]: raise RelayTestError("relay_test_expired", "the relay-test lease expired")
        return row

    def renew(self, session_id: str, credential_digest: str, now: datetime, lease_seconds: int) -> dict:
        from datetime import timedelta
        now = self._at(now)
        with transaction(self._engine, self._location) as connection:
            self._owner(connection, session_id, credential_digest, now)
            connection.execute(update(relay_test_session).where(relay_test_session.c.id == session_id).values(lease_expires_at=now + timedelta(seconds=lease_seconds), last_owner_seen_at=now))
            return self._view(connection, session_id, credential_digest) or {}

    def command(self, session_id: str, heater_id: str, state: bool, credential_digest: str, now: datetime) -> dict:
        now = self._at(now)
        with transaction(self._engine, self._location) as connection:
            self._owner(connection, session_id, credential_digest, now)
            iid = self._installation_id(connection)
            control = connection.execute(select(relay_test_control).where(relay_test_control.c.installation_id == iid)).mappings().one()
            if control["fault_latched"]:
                raise RelayTestError("relay_test_fault_latched", "safety recovery is still required")
            output = connection.execute(select(relay_test_output).where(and_(relay_test_output.c.session_id == session_id, relay_test_output.c.heater_id == heater_id))).mappings().first()
            if output is None: raise RelayTestError("not_found", "the requested heater is not in this relay-test session", heater_id)
            config, revision = SqlConfigRepository(self._engine, self._location).current()
            if revision != self._owner(connection, session_id, credential_digest, now)["installation_revision"]:
                raise RelayTestError("relay_test_configuration_changed", "the installation configuration changed")
            proposed = sum(int(row["power_w"]) for row in connection.execute(select(relay_test_output).where(relay_test_output.c.session_id == session_id)).mappings() if row["heater_id"] != heater_id and bool(row["desired_state"]))
            if state:
                proposed += int(output["power_w"])
            if proposed > config.site.max_total_power_w:
                connection.execute(update(relay_test_output).where(and_(relay_test_output.c.session_id == session_id, relay_test_output.c.heater_id == heater_id)).values(result="rejected", result_code="power_limit", result_detail=None))
                self._event(connection, iid, session_id, "output_command", now, "rejected", heater_id, state, "power_limit")
                raise RelayTestError("relay_test_power_limit", "the requested output exceeds the configured power limit", heater_id)
            seq = int(output["command_seq"]) + 1
            connection.execute(update(relay_test_output).where(and_(relay_test_output.c.session_id == session_id, relay_test_output.c.heater_id == heater_id, relay_test_output.c.command_seq == output["command_seq"])).values(desired_state=state, command_seq=seq, requested_at=now, result="pending", result_code=None, result_detail=None))
            self._event(connection, iid, session_id, "output_command", now, "accepted", heater_id, state)
            return {"heater_id": heater_id, "desired_state": state, "result": "pending", "command_seq": seq}

    def request_end(self, session_id: str, credential_digest: str, now: datetime) -> dict:
        now = self._at(now)
        with transaction(self._engine, self._location) as connection:
            row = self._owner(connection, session_id, credential_digest, now, active=False)
            if row["status"] not in ("ended", "failed"):
                connection.execute(update(relay_test_session).where(relay_test_session.c.id == session_id).values(status="ending", ending_requested_at=now, last_owner_seen_at=now))
            return self._view(connection, session_id, credential_digest) or {}

    def request_controller_end(self, session_id: str, now: datetime, reason: str) -> None:
        """Controller-only fail-safe transition; it does not assert physical OFF."""
        with transaction(self._engine, self._location) as connection:
            connection.execute(update(relay_test_session).where(and_(relay_test_session.c.id == session_id, relay_test_session.c.status.in_(("starting", "active")))).values(status="ending", ending_requested_at=self._at(now), failure_detail=reason))

    def activate(self, session_id: str, runner_id: str, now: datetime) -> None:
        with transaction(self._engine, self._location) as c:
            updated = c.execute(update(relay_test_session).where(and_(relay_test_session.c.id == session_id, relay_test_session.c.status == "starting")).values(status="active", activated_at=self._at(now), controller_runner_id=runner_id)).rowcount
            if updated:
                self._event(c, self._installation_id(c), session_id, "session_activated", now, "confirmed")

    def confirm(self, session_id: str, heater_id: str, sequence: int, state: bool, now: datetime) -> None:
        with transaction(self._engine, self._location) as c:
            updated = c.execute(update(relay_test_output).where(and_(relay_test_output.c.session_id == session_id, relay_test_output.c.heater_id == heater_id, relay_test_output.c.command_seq == sequence)).values(confirmed_state=state, confirmed_seq=sequence, confirmed_at=self._at(now), result="confirmed", result_code=None)).rowcount
            if updated:
                self._event(c, self._installation_id(c), session_id, "output_confirmed", now, "confirmed", heater_id, state)

    def controller_can_switch(self, session_id: str, runner_id: str, now: datetime) -> bool:
        """Revalidate lease, controller ownership and configuration immediately before GPIO."""
        now = self._at(now)
        with self._engine.connect() as c:
            row = c.execute(select(relay_test_session).where(relay_test_session.c.id == session_id)).mappings().first()
            if row is None or row["status"] != "active" or row["controller_runner_id"] != runner_id or now > row["lease_expires_at"]:
                return False
            heartbeat = c.execute(select(controller_heartbeat).where(controller_heartbeat.c.installation_id == row["installation_id"])).mappings().first()
            if heartbeat is None or heartbeat["runner_id"] != runner_id:
                return False
            if (now - from_utc(heartbeat["updated_at"])).total_seconds() > max(3 * float(heartbeat["poll_seconds"]), 30):
                return False
            _, revision = SqlConfigRepository(self._engine, self._location).current()
            return revision == row["installation_revision"]

    def unknown(self, session_id: str, heater_id: str, sequence: int, now: datetime, code: str = "driver_failed") -> None:
        with transaction(self._engine, self._location) as c:
            c.execute(update(relay_test_output).where(and_(relay_test_output.c.session_id == session_id, relay_test_output.c.heater_id == heater_id, relay_test_output.c.command_seq == sequence)).values(result="unknown", result_code=code, result_detail=None))

    def arm_latch(self, session_id: str | None, now: datetime, reason: str) -> None:
        with transaction(self._engine, self._location) as c:
            iid = self._installation_id(c)
            c.execute(update(relay_test_control).where(relay_test_control.c.installation_id == iid).values(fault_latched=True, fault_generation=relay_test_control.c.fault_generation + 1, fault_session_id=session_id, fault_reason=reason, fault_latched_at=self._at(now), fault_recovery_attempted_at=self._at(now), updated_at=self._at(now)))
            if session_id:
                self._event(c, iid, session_id, "fault_latched", now, "failed", code=reason)

    def recover_latch(self, generation: int, now: datetime) -> bool:
        with transaction(self._engine, self._location) as c:
            iid = self._installation_id(c)
            updated = c.execute(update(relay_test_control).where(and_(relay_test_control.c.installation_id == iid, relay_test_control.c.fault_latched.is_(True), relay_test_control.c.fault_generation == generation)).values(fault_latched=False, fault_session_id=None, fault_reason=None, fault_recovery_attempted_at=self._at(now), fault_recovered_at=self._at(now), updated_at=self._at(now))).rowcount
            if updated:
                self._event(c, iid, "recovery", "fault_recovered", now, "recovered")
            return bool(updated)

    def end(self, session_id: str, now: datetime, failed: bool = False, reason: str = "owner_finished") -> None:
        with transaction(self._engine, self._location) as c:
            iid = self._installation_id(c)
            c.execute(update(relay_test_session).where(relay_test_session.c.id == session_id).values(status="failed" if failed else "ended", ended_at=self._at(now), end_reason=reason))
            values = {"session_id": None, "updated_at": self._at(now)}
            if failed: values.update(fault_latched=True, fault_generation=relay_test_control.c.fault_generation + 1, fault_session_id=session_id, fault_reason=reason, fault_latched_at=self._at(now))
            c.execute(update(relay_test_control).where(relay_test_control.c.installation_id == iid).values(**values))
            self._event(c, iid, session_id, "session_failed" if failed else "session_ended", now, "failed" if failed else "confirmed", code=reason)

    def _event(self, connection, installation_id: int, session_id: str, kind: str, now: datetime, result: str, heater_id: str | None = None, requested_state: bool | None = None, code: str | None = None) -> None:
        """Audit is deliberately best effort: safety transitions never wait on it."""
        try:
            # A savepoint prevents a failed audit insert from poisoning the
            # surrounding safety transaction (notably on PostgreSQL).
            with connection.begin_nested():
                connection.execute(insert(relay_test_event).values(installation_id=installation_id, session_id=session_id, kind=kind, heater_id=heater_id, requested_state=requested_state, result=result, code=code, occurred_at=self._at(now)))
        except Exception:
            try:
                connection.execute(update(relay_test_control).where(relay_test_control.c.installation_id == installation_id).values(audit_degraded=True, audit_degraded_since=self._at(now), updated_at=self._at(now)))
            except Exception:
                pass
            return
        # A subsequent persisted event proves the audit channel recovered.  The
        # marker is observability only and is never consulted by control.
        control = connection.execute(select(relay_test_control.c.audit_degraded).where(relay_test_control.c.installation_id == installation_id)).scalar()
        if control and kind != "audit_recovered":
            try:
                with connection.begin_nested():
                    connection.execute(insert(relay_test_event).values(installation_id=installation_id, session_id=session_id, kind="audit_recovered", result="recovered", occurred_at=self._at(now)))
                connection.execute(update(relay_test_control).where(relay_test_control.c.installation_id == installation_id).values(audit_degraded=False, audit_degraded_since=None, updated_at=self._at(now)))
            except Exception:
                # The original event did persist; retain degraded until a later
                # successful recovery can be recorded.
                pass

__all__ = ["SqlRelayTestRepository"]
