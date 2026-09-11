"""Alerts: the episode rule, the retries and what survives a restart."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from dynamic_thermal_charge.alerts import (
    ALERT_TYPES,
    MAX_ATTEMPTS,
    PLAN_RECALCULATION_DEGRADED,
    PLAN_RECALCULATION_INVALID,
    AlertDeliveryError,
    AlertService,
    PendingAlert,
    alert_catalogue,
    plan_recalculation_invalid_message,
)
from dynamic_thermal_charge.persistence.alerts import SqlAlertRepository
from dynamic_thermal_charge.system_settings import EmailSystemSettings


NOW = datetime(2026, 1, 16, 1, 0, tzinfo=timezone.utc)

DELIVERABLE = EmailSystemSettings(
    enabled=True,
    host="smtp.example.org",
    port=587,
    sender="dtc@example.org",
    recipients=("operador@example.org",),
)


class FakeRepository:
    """The durable half, in memory, with the same contract."""

    def __init__(self, enabled: dict[str, bool] | None = None) -> None:
        self.enabled = enabled or {}
        self.episodes: dict[str, bool] = {}
        self.queue: list[dict] = []
        self.next_id = 1

    def type_enabled(self, alert_type):
        return self.enabled.get(alert_type, True)

    def episode_active(self, alert_type):
        return self.episodes.get(alert_type, False)

    def set_episode(self, alert_type, *, active, at):
        self.episodes[alert_type] = active

    def open_episode(self, alert_type, *, subject, body, at):
        if self.episode_active(alert_type):
            return False
        self.enqueue(alert_type, subject=subject, body=body, at=at)
        self.set_episode(alert_type, active=True, at=at)
        return True

    def enqueue(self, alert_type, *, subject, body, at):
        item = {
            "id": self.next_id, "alert_type": alert_type, "subject": subject,
            "body": body, "attempts": 0, "status": "pending", "next_attempt_at": at,
            "last_error": None,
        }
        self.queue.append(item)
        self.next_id += 1
        return item["id"]

    def due(self, at, limit=10):
        return tuple(
            PendingAlert(
                id=item["id"], alert_type=item["alert_type"], subject=item["subject"],
                body=item["body"], attempts=item["attempts"],
            )
            for item in self.queue
            if item["status"] == "pending" and item["next_attempt_at"] <= at
        )[:limit]

    def mark_sent(self, delivery_id, at):
        self._item(delivery_id).update(status="sent", sent_at=at)

    def mark_attempt_failed(self, delivery_id, *, attempts, next_attempt_at, error):
        item = self._item(delivery_id)
        item.update(
            attempts=attempts,
            status="pending" if next_attempt_at is not None else "failed",
            last_error=error,
        )
        if next_attempt_at is not None:
            item["next_attempt_at"] = next_attempt_at

    def _item(self, delivery_id):
        return next(item for item in self.queue if item["id"] == delivery_id)


class FakeSender:
    def __init__(self, failures: int = 0) -> None:
        self.failures = failures
        self.sent: list[PendingAlert] = []
        self.settings = None

    def send(self, settings, alert):
        self.settings = settings
        if self.failures > 0:
            self.failures -= 1
            raise AlertDeliveryError("connection refused")
        self.sent.append(alert)


def _service(repository, sender, *, settings=DELIVERABLE, clock=None):
    return AlertService(
        repository,
        settings=lambda: settings,
        sender=sender,
        clock=clock or (lambda: NOW),
    )


# --------------------------------------------------------------------------- #
# R4, R6: raising by episode
# --------------------------------------------------------------------------- #

def test_an_alert_is_queued_once_per_episode():
    repository, sender = FakeRepository(), FakeSender()
    service = _service(repository, sender)

    assert service.raise_alert(PLAN_RECALCULATION_INVALID, subject="s", body="b") is True
    assert service.raise_alert(PLAN_RECALCULATION_INVALID, subject="s", body="b") is False
    assert len(repository.queue) == 1


def test_a_resolved_condition_rearms_the_alert():
    repository, sender = FakeRepository(), FakeSender()
    service = _service(repository, sender)
    service.raise_alert(PLAN_RECALCULATION_INVALID, subject="s", body="b")

    service.clear_alert(PLAN_RECALCULATION_INVALID)
    assert service.raise_alert(PLAN_RECALCULATION_INVALID, subject="s", body="b") is True
    assert len(repository.queue) == 2


def test_raising_never_sends_synchronously():
    """R4: the detection queues and returns; delivery is a separate step."""
    repository, sender = FakeRepository(), FakeSender()
    service = _service(repository, sender)

    service.raise_alert(PLAN_RECALCULATION_INVALID, subject="s", body="b")

    assert sender.sent == []


def test_an_unknown_alert_type_is_a_programming_error():
    service = _service(FakeRepository(), FakeSender())

    with pytest.raises(ValueError, match="unknown alert type"):
        service.raise_alert("not_in_the_catalogue", subject="s", body="b")


# --------------------------------------------------------------------------- #
# R7: disabled or unconfigured
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    ("label", "repository_kwargs", "settings"),
    [
        ("type disabled", {"enabled": {PLAN_RECALCULATION_INVALID: False}}, DELIVERABLE),
        ("email disabled", {}, EmailSystemSettings()),
    ],
)
def test_a_disabled_or_unconfigured_alert_is_not_queued(label, repository_kwargs, settings):
    repository, sender = FakeRepository(**repository_kwargs), FakeSender()
    service = _service(repository, sender, settings=settings)

    assert service.raise_alert(PLAN_RECALCULATION_INVALID, subject="s", body="b") is False, label
    assert repository.queue == []
    # No episode was opened, so enabling it later still notifies.
    assert repository.episodes.get(PLAN_RECALCULATION_INVALID) is not True


def test_enabling_email_requires_a_complete_configuration():
    """The section cannot be saved half-configured, so alerts cannot half-work."""
    with pytest.raises(ValueError, match="email.recipients is required"):
        EmailSystemSettings(enabled=True, host="smtp.example.org", sender="a@b.c")
    with pytest.raises(ValueError, match="email.host is required"):
        EmailSystemSettings(enabled=True, sender="a@b.c", recipients=("x@y.z",))
    with pytest.raises(ValueError, match="email.sender is required"):
        EmailSystemSettings(enabled=True, host="smtp.example.org", recipients=("x@y.z",))


def test_a_disabled_installation_delivers_nothing():
    repository, sender = FakeRepository(), FakeSender()
    repository.enqueue(PLAN_RECALCULATION_INVALID, subject="s", body="b", at=NOW)
    service = _service(repository, sender, settings=EmailSystemSettings())

    assert service.deliver_pending() == 0
    assert sender.sent == []


# --------------------------------------------------------------------------- #
# R5: delivery, retries and exhaustion
# --------------------------------------------------------------------------- #

def test_a_queued_alert_is_delivered_once():
    repository, sender = FakeRepository(), FakeSender()
    service = _service(repository, sender)
    service.raise_alert(PLAN_RECALCULATION_INVALID, subject="s", body="b")

    assert service.deliver_pending() == 1
    assert service.deliver_pending() == 0
    assert len(sender.sent) == 1
    assert sender.settings is DELIVERABLE


def test_a_failed_attempt_waits_before_retrying_and_then_succeeds():
    repository, sender = FakeRepository(), FakeSender(failures=1)
    now = NOW
    service = _service(repository, sender, clock=lambda: now)
    service.raise_alert(PLAN_RECALCULATION_INVALID, subject="s", body="b")

    assert service.deliver_pending() == 0
    item = repository.queue[0]
    assert item["status"] == "pending"
    assert item["attempts"] == 1
    assert item["next_attempt_at"] == NOW + timedelta(seconds=60)
    assert "connection refused" in item["last_error"]

    # Still waiting: the same instant does not retry.
    assert service.deliver_pending() == 0
    assert item["attempts"] == 1

    now = NOW + timedelta(minutes=2)
    assert service.deliver_pending() == 1
    assert item["status"] == "sent"


def test_the_retries_stop_and_the_alert_is_marked_failed():
    repository, sender = FakeRepository(), FakeSender(failures=MAX_ATTEMPTS)
    now = NOW
    service = _service(repository, sender, clock=lambda: now)
    service.raise_alert(PLAN_RECALCULATION_INVALID, subject="s", body="b")

    for _attempt in range(MAX_ATTEMPTS):
        service.deliver_pending()
        now = now + timedelta(hours=1)

    item = repository.queue[0]
    assert item["status"] == "failed"
    assert item["attempts"] == MAX_ATTEMPTS
    assert service.deliver_pending() == 0


def test_a_test_message_bypasses_the_catalogue_and_the_queue():
    repository, sender = FakeRepository(), FakeSender()
    service = _service(repository, sender)

    service.send_test_message("asunto", "cuerpo")

    assert [item.subject for item in sender.sent] == ["asunto"]
    assert repository.queue == []
    assert repository.episodes == {}


def test_a_test_message_without_configuration_is_refused():
    service = _service(FakeRepository(), FakeSender(), settings=EmailSystemSettings())

    with pytest.raises(AlertDeliveryError, match="disabled or incompletely"):
        service.send_test_message("asunto", "cuerpo")


# --------------------------------------------------------------------------- #
# R3, R8: catalogue and message content
# --------------------------------------------------------------------------- #

def test_the_catalogue_defaults_to_enabled_and_reflects_stored_state():
    assert [item["name"] for item in alert_catalogue()] == [
        item.name for item in ALERT_TYPES
    ]
    assert all(item["enabled"] for item in alert_catalogue())
    disabled = alert_catalogue({PLAN_RECALCULATION_INVALID: False})
    assert disabled[0]["enabled"] is False


@pytest.mark.parametrize("preserved", [True, False])
def test_the_recalculation_message_states_the_consequence(preserved):
    subject, body = plan_recalculation_invalid_message(
        installation="Casa",
        at=NOW,
        reason="missing_temperature_schedule",
        detail="temperature_comfort: missing_temperature_schedule",
        previous_plan_preserved=preserved,
    )

    assert subject == "[Casa] Replanificación imposible"
    assert "missing_temperature_schedule" in body
    assert NOW.isoformat() in body
    if preserved:
        assert "conserva el plan anterior" in body
    else:
        assert "sin plan activo" in body


# --------------------------------------------------------------------------- #
# D2: the durable half
# --------------------------------------------------------------------------- #

def test_the_queue_and_its_episode_survive_a_restart(initialised_store):
    repository = SqlAlertRepository(
        initialised_store.configuration_engine or initialised_store.engine,
        initialised_store.application_engine or initialised_store.engine,
        initialised_store.repository.installation_id(),
    )
    repository.enqueue(PLAN_RECALCULATION_INVALID, subject="asunto", body="cuerpo", at=NOW)
    repository.set_episode(PLAN_RECALCULATION_INVALID, active=True, at=NOW)

    # A new repository is what the next process gets.
    reopened = SqlAlertRepository(
        initialised_store.configuration_engine or initialised_store.engine,
        initialised_store.application_engine or initialised_store.engine,
        initialised_store.repository.installation_id(),
    )
    pending = reopened.due(NOW)

    assert [item.subject for item in pending] == ["asunto"]
    assert reopened.episode_active(PLAN_RECALCULATION_INVALID) is True

    reopened.mark_sent(pending[0].id, NOW)
    assert reopened.due(NOW) == ()
    assert reopened.pending_count() == 0

    reopened.set_episode(PLAN_RECALCULATION_INVALID, active=False, at=NOW)
    assert reopened.episode_active(PLAN_RECALCULATION_INVALID) is False


def test_opening_an_episode_atomically_queues_only_its_first_delivery(initialised_store):
    repository = SqlAlertRepository(
        initialised_store.configuration_engine or initialised_store.engine,
        initialised_store.application_engine or initialised_store.engine,
        initialised_store.repository.installation_id(),
    )

    assert repository.open_episode(
        PLAN_RECALCULATION_INVALID, subject="primero", body="cuerpo", at=NOW
    ) is True
    assert repository.open_episode(
        PLAN_RECALCULATION_INVALID, subject="duplicado", body="cuerpo", at=NOW
    ) is False

    assert [item.subject for item in repository.due(NOW)] == ["primero"]
    assert repository.episode_active(PLAN_RECALCULATION_INVALID) is True


def test_the_stored_catalogue_only_records_deviations(initialised_store):
    repository = SqlAlertRepository(
        initialised_store.configuration_engine or initialised_store.engine,
        initialised_store.application_engine or initialised_store.engine,
        initialised_store.repository.installation_id(),
    )

    assert repository.type_enabled(PLAN_RECALCULATION_INVALID) is True

    repository.set_type_enabled(PLAN_RECALCULATION_INVALID, False)
    assert repository.type_enabled(PLAN_RECALCULATION_INVALID) is False
    assert repository.enabled_types() == {
        PLAN_RECALCULATION_INVALID: False,
        PLAN_RECALCULATION_DEGRADED: True,
    }

    repository.set_type_enabled(PLAN_RECALCULATION_INVALID, True)
    assert repository.type_enabled(PLAN_RECALCULATION_INVALID) is True


def test_an_unknown_type_cannot_be_stored(initialised_store):
    repository = SqlAlertRepository(
        initialised_store.configuration_engine or initialised_store.engine,
        initialised_store.application_engine or initialised_store.engine,
        initialised_store.repository.installation_id(),
    )

    with pytest.raises(ValueError, match="unknown alert type"):
        repository.set_type_enabled("not_in_the_catalogue", False)


# --------------------------------------------------------------------------- #
# R5, R7: the control loop drains the queue and tolerates its failures
# --------------------------------------------------------------------------- #

def _service_loop(alerts):
    from dynamic_thermal_charge.controller import ChargeController
    from dynamic_thermal_charge.drivers import SimulatedOutputDriver
    from dynamic_thermal_charge.service import ControllerService, PlanRefresh

    class _Store:
        def load(self):
            return None

        def save(self, *args, **kwargs):
            return None

    return ControllerService(
        controller=ChargeController(("salon",), SimulatedOutputDriver()),
        store=_Store(),
        refresh_plan=lambda _now: PlanRefresh(None, 60),
        poll_seconds=1,
        error_retry_seconds=60,
        clock=lambda: NOW,
        wait=lambda _seconds: None,
        alerts=alerts,
    )


def test_every_control_cycle_drains_the_alert_queue():
    repository, sender = FakeRepository(), FakeSender()
    service = _service(repository, sender)
    service.raise_alert(PLAN_RECALCULATION_INVALID, subject="s", body="b")

    _service_loop(service).run(max_cycles=1)

    assert len(sender.sent) == 1


def test_a_failing_alert_delivery_never_breaks_the_control_cycle(caplog):
    caplog.set_level("INFO")

    class Exploding:
        def __init__(self):
            self.calls = 0

        def deliver_pending(self, limit=10):
            self.calls += 1
            raise RuntimeError("the alert store is unreachable")

    alerts = Exploding()
    loop = _service_loop(alerts)

    assert loop.run(max_cycles=2) == 0
    assert alerts.calls == 2
    # Collapsed like the other infrastructure failures: once per transition.
    assert caplog.text.count("Could not deliver queued alerts") == 1


def test_the_recalculation_alert_is_raised_and_rearmed_by_the_refresh():
    from dynamic_thermal_charge.charge_planning import AutomaticPlan, PlanningViolation
    from dynamic_thermal_charge.runtime import _notify_recalculation_result

    repository, sender = FakeRepository(), FakeSender()
    service = _service(repository, sender)

    def plan(status, violations=()):
        return AutomaticPlan(NOW, NOW, 30, (), tuple(violations), status, (), "token", NOW)

    invalid = plan(
        "INVALID",
        [
            PlanningViolation(
                None, "temperature_comfort", None, None, NOW, "missing_temperature_schedule"
            )
        ],
    )
    _notify_recalculation_result(service, invalid, installation="Casa", at=NOW)

    assert len(repository.queue) == 1
    assert "missing_temperature_schedule" in repository.queue[0]["body"]
    assert "sin plan activo" in repository.queue[0]["body"]

    # A valid recalculation rearms it, and the next invalid one notifies again.
    _notify_recalculation_result(service, plan("FEASIBLE"), installation="Casa", at=NOW)
    _notify_recalculation_result(service, invalid, installation="Casa", at=NOW)
    assert len(repository.queue) == 2


def test_a_degraded_recalculation_is_deduplicated_and_rearmed():
    from dynamic_thermal_charge.charge_planning import (
        AutomaticPlan,
        DEGRADED,
        PlanningViolation,
        VALID,
    )
    from dynamic_thermal_charge.runtime import _notify_recalculation_result

    repository, sender = FakeRepository(), FakeSender()
    service = _service(repository, sender)
    window_start = NOW + timedelta(hours=1)
    window_end = NOW + timedelta(hours=4)
    degraded = AutomaticPlan(
        NOW,
        NOW + timedelta(hours=6),
        30,
        (),
        (
            PlanningViolation(
                "salon",
                "temperature_comfort",
                20.0,
                0.75,
                window_start,
                "insufficient_stored_energy_or_power",
                window_start,
                window_end,
            ),
        ),
        DEGRADED,
        (),
        "degraded-token",
        NOW,
    )
    valid = AutomaticPlan(NOW, NOW, 30, (), (), VALID, (), "valid-token", NOW)

    _notify_recalculation_result(
        service,
        degraded,
        installation="Casa",
        at=NOW,
        retained_horizon_end=NOW + timedelta(hours=2),
    )
    _notify_recalculation_result(
        service,
        degraded,
        installation="Casa",
        at=NOW + timedelta(minutes=30),
        retained_horizon_end=NOW + timedelta(hours=2),
    )

    assert len(repository.queue) == 1
    body = repository.queue[0]["body"]
    assert "Casa" in body
    assert "salon" in body
    assert window_start.isoformat() in body
    assert window_end.isoformat() in body
    assert "0.75 °C" in body
    assert (NOW + timedelta(hours=2)).isoformat() in body
    assert "No se activa el candidato degradado" in body

    _notify_recalculation_result(
        service,
        valid,
        installation="Casa",
        at=NOW + timedelta(hours=1),
    )
    _notify_recalculation_result(
        service,
        degraded,
        installation="Casa",
        at=NOW + timedelta(hours=2),
        retained_horizon_end=NOW + timedelta(hours=3),
    )

    assert len(repository.queue) == 2


def test_the_refresh_alert_never_propagates_a_failure():
    from dynamic_thermal_charge.charge_planning import AutomaticPlan
    from dynamic_thermal_charge.runtime import _notify_recalculation_result

    class Exploding:
        def raise_alert(self, *args, **kwargs):
            raise RuntimeError("the alert store is unreachable")

        def clear_alert(self, *args, **kwargs):
            raise RuntimeError("the alert store is unreachable")

    plan = AutomaticPlan(NOW, NOW, 30, (), (), "INVALID", (), "token", NOW)

    _notify_recalculation_result(Exploding(), plan, installation="Casa", at=NOW)
