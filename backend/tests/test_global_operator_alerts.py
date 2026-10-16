from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import timedelta
from threading import Barrier, Event, Thread

from sqlalchemy import event

from dynamic_thermal_charge.alerts import (
    ALERT_EMAIL_FAILED,
    CONTROLLER_UNRESPONSIVE,
    OUTPUT_FAILURE,
    PLAN_RECALCULATION_INVALID,
    AlertDeliveryError,
    AlertService,
)
from dynamic_thermal_charge.calibration_runtime import finish_calibration
from dynamic_thermal_charge.system_settings import EmailSystemSettings
from dynamic_thermal_charge.push import WebPushDelivery
from dynamic_thermal_charge.persistence.alerts import SqlAlertRepository
from dynamic_thermal_charge.persistence.calibration import SqlCalibrationRepository

from .conftest import API_NOW, AUTH


def _settings() -> EmailSystemSettings:
    return EmailSystemSettings(
        enabled=True,
        host="smtp.example.org",
        sender="operator@example.org",
        recipients=("operator@example.org",),
    )


class _FailingSender:
    def send(self, _settings, _alert):
        raise AlertDeliveryError("smtp refused")


def test_global_alerts_keep_episode_history_and_cursor_pagination(initialised_store):
    repository = initialised_store.alerts
    first_at = API_NOW - timedelta(minutes=5)
    second_at = API_NOW

    assert repository.open_alert(
        PLAN_RECALCULATION_INVALID,
        severity="critical",
        subject="invalid",
        body="invalid body",
        at=first_at,
        email_enabled=False,
        push_enabled=False,
    )
    assert not repository.open_alert(
        PLAN_RECALCULATION_INVALID,
        severity="critical",
        subject="duplicate",
        body="duplicate body",
        at=second_at,
        email_enabled=False,
        push_enabled=False,
    )
    page = repository.list_alerts(view="active", limit=1)
    assert page.active_count == 1
    assert page.items[0].alert_type == PLAN_RECALCULATION_INVALID
    assert page.maximum_severity == "critical"

    alert_id = page.items[0].id
    assert repository.acknowledge(alert_id, at=second_at)
    assert repository.list_alerts(view="active").items == ()
    history = repository.list_alerts(view="history")
    assert [item.id for item in history.items] == [alert_id]
    assert history.items[0].acknowledged_at == second_at

    assert repository.open_alert(
        CONTROLLER_UNRESPONSIVE,
        severity="critical",
        subject="old",
        body="old body",
        at=API_NOW - timedelta(days=3),
        email_enabled=False,
        push_enabled=False,
        resolved=True,
    )
    old_id = next(
        item.id
        for item in repository.list_alerts(view="history", limit=100).items
        if item.alert_type == CONTROLLER_UNRESPONSIVE
    )
    from dynamic_thermal_charge.persistence.history import SqlHistoryRecorder

    recorder = SqlHistoryRecorder(
        initialised_store.application_engine or initialised_store.engine,
        initialised_store.repository.installation_id(),
        initialised_store.location,
    )
    report = recorder.prune(API_NOW, retention_days=1)
    assert report.deleted.get("operator_notification", 0) >= 1
    assert repository.notification(old_id) is None


def test_email_and_push_rows_are_independent_and_claimable(initialised_store):
    repository = initialised_store.alerts
    subscription = initialised_store.calibration.register_subscription(
        user_id="operator",
        browser_id="browser-a",
        endpoint="https://push.example/a",
        p256dh="p256dh",
        auth="auth",
        at=API_NOW,
    )
    assert repository.open_alert(
        CONTROLLER_UNRESPONSIVE,
        severity="critical",
        subject="controller",
        body="controller body",
        at=API_NOW,
        email_enabled=True,
        push_enabled=True,
    )
    assert repository.pending_count() == 1
    attempts = initialised_store.calibration.push_attempts_for_alert(
        repository.list_alerts(view="active").items[0].id
    )
    assert len(attempts) == 1
    assert attempts[0].subscription_id == subscription.id
    assert initialised_store.calibration.claim_push_attempt(
        attempts[0].id, owner="push-a", at=API_NOW
    )
    assert not initialised_store.calibration.claim_push_attempt(
        attempts[0].id, owner="push-b", at=API_NOW
    )
    assert not initialised_store.calibration.mark_push_attempt(
        attempts[0].id,
        status="error",
        error="stale worker",
        at=API_NOW,
        owner="push-b",
    )
    assert initialised_store.calibration.mark_push_attempt(
        attempts[0].id,
        status="error",
        error="push refused",
        at=API_NOW,
        owner="push-a",
    )

    claimed = repository.claim_pending(API_NOW, owner="worker-a")
    assert len(claimed) == 1
    assert repository.claim_pending(API_NOW, owner="worker-b") == ()
    assert not repository.mark_attempt_failed(
        claimed[0].id,
        attempts=1,
        next_attempt_at=None,
        error="stale worker",
        owner="worker-b",
    )
    assert repository.mark_attempt_failed(
        claimed[0].id,
        attempts=1,
        next_attempt_at=None,
        error="smtp refused",
        at=API_NOW,
        owner="worker-a",
    )
    assert repository.pending_count() == 0


def test_reopening_a_resolved_episode_has_one_winner_across_processes(initialised_store):
    repository = initialised_store.alerts
    assert repository.open_alert(
        CONTROLLER_UNRESPONSIVE,
        severity="critical",
        subject="initial",
        body="initial body",
        at=API_NOW - timedelta(minutes=2),
        email_enabled=True,
        push_enabled=False,
    )
    claimed = repository.claim_pending(API_NOW - timedelta(minutes=2), owner="setup")
    assert len(claimed) == 1
    assert repository.mark_sent(claimed[0].id, API_NOW - timedelta(minutes=2), owner="setup")
    repository.resolve_alert(CONTROLLER_UNRESPONSIVE, at=API_NOW - timedelta(minutes=1))

    barrier = Barrier(2)
    application_engine = initialised_store.application_engine or initialised_store.engine

    def reopen() -> bool:
        local = type(repository)(
            initialised_store.configuration_engine or initialised_store.engine,
            application_engine,
            initialised_store.repository.installation_id(),
        )
        barrier.wait()
        return local.open_alert(
            CONTROLLER_UNRESPONSIVE,
            severity="critical",
            subject="reopened",
            body="reopened body",
            at=API_NOW,
            email_enabled=True,
            push_enabled=False,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(lambda _index: reopen(), range(2)))

    assert sorted(results) == [False, True]
    assert repository.pending_count() == 1
    assert len(
        [
            item
            for item in repository.list_alerts(view="all", limit=100).items
            if item.alert_type == CONTROLLER_UNRESPONSIVE
        ]
    ) == 2


def test_exhausted_email_delivery_opens_non_email_diagnostic(initialised_store):
    service = AlertService(
        initialised_store.alerts,
        settings=_settings,
        sender=_FailingSender(),
        clock=lambda: API_NOW,
        max_attempts=1,
    )
    assert service.raise_alert(
        PLAN_RECALCULATION_INVALID,
        subject="invalid",
        body="invalid body",
    )
    assert service.deliver_pending() == 0
    page = initialised_store.alerts.list_alerts(view="active", limit=100)
    assert {item.alert_type for item in page.items} == {
        PLAN_RECALCULATION_INVALID,
        ALERT_EMAIL_FAILED,
    }
    assert initialised_store.alerts.pending_count() == 0


def test_disabled_catalogue_type_stays_in_the_inbox_without_channels(initialised_store):
    repository = initialised_store.alerts
    repository.set_type_enabled(CONTROLLER_UNRESPONSIVE, False)
    subscription = initialised_store.calibration.register_subscription(
        user_id="operator",
        browser_id="browser-disabled",
        endpoint="https://push.example/disabled",
        p256dh="p256dh",
        auth="auth",
        at=API_NOW,
    )
    service = AlertService(
        repository,
        settings=_settings,
        sender=_FailingSender(),
        clock=lambda: API_NOW,
    )

    assert service.raise_alert(
        CONTROLLER_UNRESPONSIVE,
        subject="disabled",
        body="still visible",
    )
    page = repository.list_alerts(view="active")
    assert page.items[0].body == "still visible"
    assert repository.pending_count() == 0
    assert subscription.id not in repository.pending_push_alert_ids()


def test_disabling_catalogue_type_suppresses_already_queued_channels(initialised_store):
    repository = initialised_store.alerts
    repository.set_type_enabled(CONTROLLER_UNRESPONSIVE, True)
    subscription = initialised_store.calibration.register_subscription(
        user_id="operator",
        browser_id="browser-queued",
        endpoint="https://push.example/queued",
        p256dh="p256dh",
        auth="auth",
        at=API_NOW,
    )
    assert repository.open_alert(
        CONTROLLER_UNRESPONSIVE,
        severity="critical",
        subject="queued",
        body="queued body",
        at=API_NOW,
        email_enabled=True,
        push_enabled=True,
    )
    alert_id = repository.list_alerts(view="active").items[0].id
    assert repository.pending_count() == 1
    assert repository.pending_push_alert_ids() == (alert_id,)

    repository.set_type_enabled(CONTROLLER_UNRESPONSIVE, False)

    assert repository.pending_count() == 0
    assert repository.pending_push_alert_ids() == ()
    assert repository.list_alerts(view="active").items[0].id == alert_id
    assert subscription.id > 0


def test_disabling_catalogue_type_cannot_race_email_handoff(initialised_store):
    repository = initialised_store.alerts
    assert repository.open_alert(
        CONTROLLER_UNRESPONSIVE,
        severity="critical",
        subject="queued",
        body="queued body",
        at=API_NOW,
        email_enabled=True,
        push_enabled=False,
    )
    ready = Barrier(2)
    release = Event()
    disable_started = Event()
    catalogue_committed = Event()
    sent: list[int] = []

    class GatedRepository(SqlAlertRepository):
        @contextmanager
        def _locked_type_enabled(self, alert_type):
            # The delivery transaction has already locked the application row
            # when this gate opens.  Disable can therefore commit its
            # catalogue change while cleanup waits on that row.
            ready.wait(timeout=5)
            release.wait(timeout=5)
            with super()._locked_type_enabled(alert_type) as enabled:
                yield enabled

    class Sender:
        def send(self, _settings, alert):
            sent.append(alert.id)

    gated = GatedRepository(
        repository._configuration,
        repository._application,
        repository._installation_id,
        repository._configuration_location,
        repository._application_location,
    )

    config_engine = initialised_store.configuration_engine or initialised_store.engine

    def on_commit(_connection):
        if disable_started.is_set():
            catalogue_committed.set()

    event.listen(config_engine, "commit", on_commit)
    errors: list[BaseException] = []
    worker_errors: list[BaseException] = []

    service = AlertService(
        gated,
        settings=_settings,
        sender=Sender(),
        clock=lambda: API_NOW,
    )
    def deliver():
        try:
            service.deliver_pending()
        except BaseException as exc:  # pragma: no cover - assertion below
            worker_errors.append(exc)

    worker = Thread(target=deliver)
    worker.start()
    assert ready.wait(timeout=5) in (0, 1)

    def disable():
        try:
            disable_started.set()
            repository.set_type_enabled(CONTROLLER_UNRESPONSIVE, False)
        except BaseException as exc:  # pragma: no cover - assertion below
            errors.append(exc)

    disabler = Thread(target=disable)
    disabler.start()
    assert catalogue_committed.wait(timeout=5)
    # The commit event is the non-blocking proof that the durable catalogue
    # state is false while cleanup is still waiting on the worker's row lock.
    release.set()
    worker.join(timeout=5)
    disabler.join(timeout=5)
    event.remove(config_engine, "commit", on_commit)

    assert not worker.is_alive()
    assert not disabler.is_alive()
    assert errors == []
    assert worker_errors == []
    assert repository.type_enabled(CONTROLLER_UNRESPONSIVE) is False
    assert sent == []
    assert repository.pending_count() == 0


def test_disabling_catalogue_type_cannot_race_push_handoff(initialised_store):
    repository = initialised_store.alerts
    initialised_store.calibration.register_subscription(
        user_id="operator",
        browser_id="browser-race",
        endpoint="https://push.example/race",
        p256dh="p256dh",
        auth="auth",
        at=API_NOW,
    )
    assert repository.open_alert(
        CONTROLLER_UNRESPONSIVE,
        severity="critical",
        subject="queued",
        body="queued body",
        at=API_NOW,
        email_enabled=False,
        push_enabled=True,
    )
    alert_id = repository.list_alerts(view="active").items[0].id
    ready = Barrier(2)
    release = Event()
    disable_started = Event()
    catalogue_committed = Event()
    sent: list[str] = []

    class GatedRepository(SqlCalibrationRepository):
        @contextmanager
        def _locked_type_enabled(self, alert_type):
            ready.wait(timeout=5)
            release.wait(timeout=5)
            with super()._locked_type_enabled(alert_type) as enabled:
                yield enabled

    calibration = initialised_store.calibration
    gated = GatedRepository(
        calibration._configuration,
        calibration._application,
        calibration._installation_id,
        calibration._configuration_location,
        calibration._application_location,
    )

    config_engine = initialised_store.configuration_engine or initialised_store.engine

    def on_commit(_connection):
        if disable_started.is_set():
            catalogue_committed.set()

    event.listen(config_engine, "commit", on_commit)
    errors: list[BaseException] = []
    worker_errors: list[BaseException] = []

    delivery = WebPushDelivery(
        gated,
        sender=lambda _subscription, payload: sent.append(payload),
        clock=lambda: API_NOW,
    )
    def deliver():
        try:
            delivery.deliver_pending(alert_id=alert_id)
        except BaseException as exc:  # pragma: no cover - assertion below
            worker_errors.append(exc)

    worker = Thread(target=deliver)
    worker.start()
    assert ready.wait(timeout=5) in (0, 1)

    def disable():
        try:
            disable_started.set()
            repository.set_type_enabled(CONTROLLER_UNRESPONSIVE, False)
        except BaseException as exc:  # pragma: no cover - assertion below
            errors.append(exc)

    disabler = Thread(target=disable)
    disabler.start()
    assert catalogue_committed.wait(timeout=5)
    # Do not query the configuration store here: the disabler is intentionally
    # waiting on the application row held by the worker.
    release.set()
    worker.join(timeout=5)
    disabler.join(timeout=5)
    event.remove(config_engine, "commit", on_commit)

    assert not worker.is_alive()
    assert not disabler.is_alive()
    assert errors == []
    assert worker_errors == []
    assert repository.type_enabled(CONTROLLER_UNRESPONSIVE) is False
    assert sent == []
    assert repository.pending_push_alert_ids() == ()


def test_alert_cursor_is_a_bad_request(client):
    response = client.get("/api/v1/alerts?cursor=garbage", headers=AUTH)

    assert response.status_code == 400, response.text
    assert response.json()["code"] == "bad_request"
    assert response.json()["field"] == "cursor"


def test_same_owner_email_finalization_rejects_an_expired_lease(initialised_store):
    now = [API_NOW]
    repository = SqlAlertRepository(
        initialised_store.configuration_engine or initialised_store.engine,
        initialised_store.application_engine or initialised_store.engine,
        initialised_store.repository.installation_id(),
        initialised_store.location,
        initialised_store.location,
        clock=lambda: now[0],
    )
    assert repository.open_alert(
        CONTROLLER_UNRESPONSIVE,
        severity="critical",
        subject="expired",
        body="expired body",
        at=API_NOW,
        email_enabled=True,
        push_enabled=False,
    )
    claimed = repository.claim_pending(API_NOW, owner="owner")
    assert len(claimed) == 1
    expired_at = API_NOW + timedelta(seconds=31)

    assert not repository.mark_sent(claimed[0].id, expired_at, owner="owner")
    reclaimed = repository.claim_pending(expired_at, owner="new-owner")
    assert len(reclaimed) == 1
    assert repository.mark_sent(reclaimed[0].id, expired_at, owner="new-owner")

    assert repository.open_alert(
        "output_failure",
        severity="critical",
        subject="failed",
        body="failed body",
        at=API_NOW,
        email_enabled=True,
        push_enabled=False,
    )
    failed_claim = repository.claim_pending(API_NOW, owner="failure-owner")
    assert len(failed_claim) == 1
    now[0] = expired_at
    assert not repository.mark_attempt_failed(
        failed_claim[0].id,
        attempts=1,
        next_attempt_at=None,
        error="expired",
        owner="failure-owner",
    )
    failed_reclaim = repository.claim_pending(expired_at, owner="new-failure-owner")
    assert len(failed_reclaim) == 1
    assert repository.mark_attempt_failed(
        failed_reclaim[0].id,
        attempts=1,
        next_attempt_at=None,
        error="valid",
        at=expired_at,
        owner="new-failure-owner",
    )

    now[0] = API_NOW
    assert repository.open_alert(
        PLAN_RECALCULATION_INVALID,
        severity="critical",
        subject="valid",
        body="valid body",
        at=API_NOW,
        email_enabled=True,
        push_enabled=False,
    )
    valid_claim = repository.claim_pending(API_NOW, owner="valid-owner")
    assert len(valid_claim) == 1
    assert repository.mark_attempt_failed(
        valid_claim[0].id,
        attempts=1,
        next_attempt_at=None,
        error="valid",
        owner="valid-owner",
    )


def test_same_owner_push_finalization_rejects_an_expired_lease(initialised_store):
    now = [API_NOW]
    repository = SqlAlertRepository(
        initialised_store.configuration_engine or initialised_store.engine,
        initialised_store.application_engine or initialised_store.engine,
        initialised_store.repository.installation_id(),
        initialised_store.location,
        initialised_store.location,
        clock=lambda: now[0],
    )
    calibration = SqlCalibrationRepository(
        initialised_store.configuration_engine or initialised_store.engine,
        initialised_store.application_engine or initialised_store.engine,
        initialised_store.repository.installation_id(),
        initialised_store.location,
        initialised_store.location,
        clock=lambda: now[0],
    )
    calibration.register_subscription(
        user_id="operator",
        browser_id="browser-expiry",
        endpoint="https://push.example/expiry",
        p256dh="p256dh",
        auth="auth",
        at=API_NOW,
    )
    assert repository.open_alert(
        CONTROLLER_UNRESPONSIVE,
        severity="critical",
        subject="expired",
        body="expired body",
        at=API_NOW,
        email_enabled=False,
        push_enabled=True,
    )
    alert_id = repository.list_alerts(view="active").items[0].id
    attempt = calibration.push_attempts_for_alert(alert_id)[0]
    assert calibration.claim_push_attempt(
        attempt.id, owner="owner", at=API_NOW
    )
    expired_at = API_NOW + timedelta(seconds=31)
    now[0] = expired_at

    assert not calibration.mark_push_attempt(
        attempt.id,
        status="sent",
        owner="owner",
    )
    assert calibration.claim_push_attempt(
        attempt.id, owner="new-owner", at=expired_at
    )
    assert calibration.mark_push_attempt(
        attempt.id,
        status="sent",
        at=expired_at,
        owner="new-owner",
    )

    now[0] = API_NOW
    assert repository.open_alert(
        OUTPUT_FAILURE,
        severity="critical",
        subject="valid",
        body="valid body",
        at=API_NOW,
        email_enabled=False,
        push_enabled=True,
    )
    valid_alert_id = next(
        item.id
        for item in repository.list_alerts(view="active", limit=100).items
        if item.alert_type == OUTPUT_FAILURE
    )
    valid_attempt = calibration.push_attempts_for_alert(valid_alert_id)[0]
    assert calibration.claim_push_attempt(
        valid_attempt.id, owner="valid-owner", at=API_NOW
    )
    assert calibration.mark_push_attempt(
        valid_attempt.id,
        status="sent",
        owner="valid-owner",
    )
    assert calibration.push_attempts_for_alert(valid_alert_id)[0].attempted_at == API_NOW


def test_api_detector_opens_and_resolves_stale_controller_alert(
    client,
    initialised_store,
    heartbeat,
    api_clock,
    monkeypatch,
):
    import dynamic_thermal_charge.push as push

    heartbeat.publish(API_NOW - timedelta(seconds=90), degraded=False)
    sent: list[str] = []
    monkeypatch.setattr(
        push,
        "_default_sender",
        lambda _subscription, payload: sent.append(payload),
    )
    initialised_store.calibration.register_subscription(
        user_id="operator",
        browser_id="browser-a",
        endpoint="https://push.example/a",
        p256dh="p256dh",
        auth="auth",
        at=API_NOW,
    )

    response = client.get("/api/v1/status", headers=AUTH)
    assert response.status_code == 200, response.text
    active = client.get("/api/v1/alerts", headers=AUTH).json()
    assert active["items"][0]["alert_type"] == CONTROLLER_UNRESPONSIVE
    assert sent and '"alert_type":"controller_unresponsive"' in sent[0]

    heartbeat.publish(api_clock(), degraded=False)
    response = client.get("/api/v1/status", headers=AUTH)
    assert response.status_code == 200, response.text
    assert client.get("/api/v1/alerts", headers=AUTH).json()["items"] == []


def test_api_liveness_supervisor_opens_and_resolves_without_http(
    api_app,
    initialised_store,
    heartbeat,
    api_clock,
    monkeypatch,
):
    import dynamic_thermal_charge.push as push

    heartbeat.publish(API_NOW - timedelta(seconds=90), degraded=False)
    sent: list[str] = []
    monkeypatch.setattr(
        push,
        "_default_sender",
        lambda _subscription, payload: sent.append(payload),
    )
    initialised_store.calibration.register_subscription(
        user_id="operator",
        browser_id="browser-supervisor",
        endpoint="https://push.example/supervisor",
        p256dh="p256dh",
        auth="auth",
        at=API_NOW,
    )

    supervisor = api_app.state.controller_liveness_supervisor
    supervisor.run_cycle()
    active = initialised_store.alerts.list_alerts(view="active")
    assert [item.alert_type for item in active.items] == [CONTROLLER_UNRESPONSIVE]
    assert sent and '"alert_type":"controller_unresponsive"' in sent[0]

    heartbeat.publish(api_clock(), degraded=False)
    supervisor.run_cycle()
    assert initialised_store.alerts.list_alerts(view="active").items == ()


def test_api_liveness_supervisor_covers_multiple_controllers_and_recovers(
    api_app,
    initialised_store,
    heartbeat,
):
    from dynamic_thermal_charge.persistence.heartbeat import SqlHeartbeatPublisher

    heartbeat.publish(API_NOW, degraded=False)
    api_app.state.controller_liveness_supervisor.run_cycle()
    second = SqlHeartbeatPublisher(
        initialised_store.application_engine or initialised_store.engine,
        initialised_store.repository.installation_id(),
        poll_seconds=5.0,
        driver_kind="gpio",
        started_at=API_NOW - timedelta(hours=4),
        runner_id="runner-b",
        location=initialised_store.location,
    )
    second.publish(API_NOW, degraded=False)

    api_app.state.controller_liveness_supervisor.run_cycle()
    assert initialised_store.alerts.list_alerts(view="active").items[0].alert_type == CONTROLLER_UNRESPONSIVE

    second.publish(API_NOW, degraded=False)
    api_app.state.controller_liveness_supervisor.run_cycle()
    assert initialised_store.alerts.list_alerts(view="active").items == ()


def test_info_alerts_are_push_only(initialised_store):
    from dynamic_thermal_charge.alerts import PLAN_DEVIATION_REPLAN

    initialised_store.calibration.register_subscription(
        user_id="operator",
        browser_id="browser-info",
        endpoint="https://push.example/info",
        p256dh="p256dh",
        auth="auth",
        at=API_NOW,
    )
    service = AlertService(
        initialised_store.alerts,
        settings=_settings,
        sender=_FailingSender(),
        clock=lambda: API_NOW,
    )
    assert service.raise_alert(
        PLAN_DEVIATION_REPLAN,
        subject="deviation",
        body="deviation body",
    )
    assert initialised_store.alerts.pending_count() == 0
    page = initialised_store.alerts.list_alerts(view="active")
    assert page.items[0].severity == "info"
    attempts = initialised_store.calibration.push_attempts_for_alert(page.items[0].id)
    assert len(attempts) == 1
    assert attempts[0].status == "pending"


def test_terminal_calibration_reconciles_email_without_duplicate_push(
    initialised_store,
):
    calibration = initialised_store.calibration
    repository = initialised_store.alerts
    session = calibration.start("salon", now=API_NOW)
    calibration.register_subscription(
        user_id="operator",
        browser_id="browser-terminal",
        endpoint="https://push.example/terminal",
        p256dh="p256dh",
        auth="auth",
        at=API_NOW,
    )
    sent: list[object] = []

    class Sender:
        def send(self, _settings, alert):
            sent.append(alert)

    service = AlertService(
        repository,
        settings=_settings,
        sender=Sender(),
        clock=lambda: API_NOW,
    )

    assert finish_calibration(
        initialised_store,
        session.id,
        result=None,
        status="failed",
        cause="inputs_missing_over_one_hour",
        now=API_NOW,
        heater_id="salon",
        alerts=service,
    )
    notification = repository.list_alerts(view="all").items[0]
    assert notification.alert_type == "thermal_calibration_terminal"
    assert repository.pending_count() == 1
    assert len(calibration.push_attempts_for_alert(notification.id)) == 1

    # The calibration repository created the inbox and Push rows first;
    # enqueue_message must fill only the missing email channel row.
    assert service.enqueue_message(
        "thermal_calibration_terminal",
        subject="duplicate",
        body="duplicate",
        session_id=session.id,
    )
    assert repository.pending_count() == 1
    assert len(calibration.push_attempts_for_alert(notification.id)) == 1

    assert service.deliver_pending() == 1
    assert [item.subject for item in sent] == [
        f"[{initialised_store.repository.installation_name()}] "
        "Calibración térmica failed (salon)"
    ]

    pushed: list[str] = []
    delivery = WebPushDelivery(
        calibration,
        sender=lambda _subscription, payload: pushed.append(payload),
        clock=lambda: API_NOW,
    )
    assert delivery.deliver_pending(alert_id=notification.id) == 1
    assert len(pushed) == 1
    assert len(calibration.push_attempts_for_alert(notification.id)) == 1


def test_output_failure_alert_is_emitted_once_per_transition():
    from dynamic_thermal_charge.controller import ChargeController
    from dynamic_thermal_charge.scheduler import ScheduleResult, ScheduleSlot

    class Driver:
        def __init__(self):
            self.fail = True

        def set_state(self, _heater_id, _enabled, _at):
            if self.fail:
                raise RuntimeError("relay refused")

        def close(self):
            return None

    events: list[set[str]] = []
    driver = Driver()
    controller = ChargeController(
        ("salon",),
        driver,
        output_failure_callback=lambda failed, _at: events.append(failed),
    )
    schedule = ScheduleResult(
        slots=(
            ScheduleSlot(
                API_NOW,
                API_NOW + timedelta(minutes=30),
                ("salon",),
                2000,
            ),
        ),
        allocated_minutes={"salon": 30},
        unmet_minutes={},
    )
    controller.apply(schedule, API_NOW)
    controller.apply(schedule, API_NOW + timedelta(seconds=5))
    driver.fail = False
    controller.apply(schedule, API_NOW + timedelta(seconds=10))
    assert events == [{"salon"}, set()]


def test_plan_deviation_alert_follows_replan_transition():
    from dynamic_thermal_charge.service import ControllerService

    class Alerts:
        def __init__(self):
            self.raised: list[str] = []
            self.cleared: list[str] = []

        def raise_alert(self, alert_type, *, subject, body):
            self.raised.append(alert_type)
            return True

        def clear_alert(self, alert_type):
            self.cleared.append(alert_type)

    alerts = Alerts()
    service = ControllerService(
        controller=None,
        store=None,
        refresh_plan=lambda _at: None,
        poll_seconds=1,
        error_retry_seconds=1,
        alerts=alerts,
        deviation_check=lambda _at: True,
    )
    assert service._deviation_detected(API_NOW)
    assert alerts.raised == ["plan_deviation_replan"]

    service._deviation_check = lambda _at: False
    assert not service._deviation_detected(API_NOW + timedelta(minutes=1))
    assert alerts.cleared == ["plan_deviation_replan"]
