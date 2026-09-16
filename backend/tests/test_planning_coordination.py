"""Durable single-flight and installation-lease behaviour."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Event, Lock
import time

from dynamic_thermal_charge.charge_planning import AutomaticPlan, PlanningInput, VALID, input_token
from dynamic_thermal_charge.planning_coordination import coordinated_plan


START = datetime(2026, 1, 16, 0, tzinfo=timezone.utc)


def _request(start: datetime = START) -> PlanningInput:
    return PlanningInput(
        heaters=(),
        telemetry={},
        constraints=(),
        forecast=(),
        horizon_start=start,
        horizon_hours=1,
        slot_minutes=60,
        max_total_power_w=1,
        generated_at=start,
    )


def _plan(request: PlanningInput) -> AutomaticPlan:
    return AutomaticPlan(
        request.horizon_start,
        request.horizon_start + timedelta(hours=request.horizon_hours),
        request.slot_minutes,
        (),
        (),
        VALID,
        (),
        input_token(request),
        request.generated_at,
    )


def test_equal_tokens_share_one_durable_calculation(initialised_store):
    request = _request()
    started = Event()
    release = Event()
    calls = 0

    def builder():
        nonlocal calls
        calls += 1
        started.set()
        assert release.wait(2)
        return _plan(request)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(
            coordinated_plan,
            initialised_store.planning,
            request,
            kind="automatic",
            builder=builder,
            poll_seconds=0.01,
        )
        assert started.wait(2)
        second = executor.submit(
            coordinated_plan,
            initialised_store.planning,
            request,
            kind="preview",
            builder=builder,
            poll_seconds=0.01,
        )
        time.sleep(0.05)
        release.set()
        first_plan = first.result(timeout=2)
        second_plan = second.result(timeout=2)

    assert calls == 1
    assert first_plan == second_plan
    assert first_plan.diagnostics["coordination"]["joined"] is False
    record = initialised_store.planning.planning_calculation(input_token(request))
    assert record is not None
    assert record["status"] == "completed"


def test_different_tokens_never_run_concurrently(initialised_store):
    requests = (_request(), _request(START + timedelta(hours=1)))
    active = 0
    maximum_active = 0
    calls = 0
    guard = Lock()

    def make_builder(request):
        def builder():
            nonlocal active, maximum_active, calls
            with guard:
                calls += 1
                active += 1
                maximum_active = max(maximum_active, active)
            time.sleep(0.1)
            with guard:
                active -= 1
            return _plan(request)

        return builder

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(
                coordinated_plan,
                initialised_store.planning,
                request,
                kind="automatic",
                builder=make_builder(request),
                poll_seconds=0.01,
            )
            for request in requests
        ]
        plans = [future.result(timeout=3) for future in futures]

    assert calls == 2
    assert maximum_active == 1
    assert {plan.input_token for plan in plans} == {
        input_token(request) for request in requests
    }


def test_queued_calculation_lease_can_be_renewed(initialised_store):
    request = _request()
    token = input_token(request)
    claim = initialised_store.planning.claim_planning_calculation(
        token,
        kind="preview",
        requested_at=request.generated_at,
        lease_seconds=1,
    )

    before = initialised_store.planning.planning_calculation(token)
    assert before is not None
    assert initialised_store.planning.renew_planning_calculation(
        token,
        claim["owner"],
        lease_seconds=30,
    )
    after = initialised_store.planning.planning_calculation(token)
    assert after is not None
    assert after["lease_until"] > before["lease_until"]


def test_malformed_completed_result_is_reclaimed(initialised_store):
    request = _request()
    token = input_token(request)
    claim = initialised_store.planning.claim_planning_calculation(
        token,
        kind="preview",
        requested_at=request.generated_at,
    )
    assert initialised_store.planning.finish_planning_calculation(
        token,
        claim["owner"],
        result={"not": "an automatic plan"},
    )

    calls = 0

    def builder():
        nonlocal calls
        calls += 1
        return _plan(request)

    result = coordinated_plan(
        initialised_store.planning,
        request,
        kind="preview",
        builder=builder,
    )

    assert calls == 1
    assert result.input_token == token
    assert initialised_store.planning.planning_calculation(token)["status"] == "completed"
