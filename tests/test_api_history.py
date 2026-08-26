"""Reading history over HTTP: FR-032 to FR-037."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from tests.conftest import AUTH


SEED_END = datetime(2026, 1, 16, 12, 0, tzinfo=timezone.utc)


def _seed(store, nights: int, end: datetime = SEED_END):
    from test_persistence_retention import _seed_history

    _seed_history(store, nights=nights, end=end)


def _get(client, path: str, **params):
    """Uses params= so the client encodes the values.

    An ISO instant carries "+00:00", and a raw '+' in a query string means a
    space: hand-built query strings silently corrupt every timestamp.
    """
    return client.get(
        path,
        headers=AUTH,
        params={k: v for k, v in params.items() if v is not None},
    )


# --------------------------------------------------------------------------- #
# FR-033, FR-034: always paged, newest first
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("resource", ["plans", "forecasts", "transitions"])
def test_the_default_page_is_bounded(client, initialised_store, resource):
    _seed(initialised_store, nights=120)
    body = _get(client, f"/api/v1/history/{resource}").json()
    assert body["limit_applied"] == 50
    assert len(body["items"]) == 50
    assert body["has_more"] is True
    assert body["next_cursor"]


@pytest.mark.parametrize("resource", ["plans", "forecasts", "transitions"])
def test_no_request_returns_the_whole_history(client, initialised_store, resource):
    _seed(initialised_store, nights=200)
    body = _get(client, f"/api/v1/history/{resource}").json()
    assert len(body["items"]) <= 50


def test_an_oversized_limit_is_capped_and_says_so(client, initialised_store):
    _seed(initialised_store, nights=10)
    body = _get(client, "/api/v1/history/plans", limit=99999).json()
    assert body["limit_applied"] == 500


def test_results_come_newest_first(client, initialised_store):
    _seed(initialised_store, nights=6)
    instants = [item["created_at"] for item in _get(client, "/api/v1/history/plans").json()["items"]]
    assert instants == sorted(instants, reverse=True)


def test_the_cursor_walks_the_history_without_repeats(client, initialised_store):
    _seed(initialised_store, nights=25)
    seen: list[int] = []
    cursor = None
    for _ in range(10):
        body = _get(client, "/api/v1/history/plans", limit=10, cursor=cursor).json()
        seen.extend(item["id"] for item in body["items"])
        if not body["has_more"]:
            break
        cursor = body["next_cursor"]
    assert len(seen) == 25
    assert len(set(seen)) == 25


def test_a_tampered_cursor_is_a_bad_request(client, initialised_store):
    _seed(initialised_store, nights=3)
    response = _get(client, "/api/v1/history/plans", cursor="garbage")
    assert response.status_code == 400
    assert response.json()["code"] == "bad_request"


# --------------------------------------------------------------------------- #
# FR-035: ranges
# --------------------------------------------------------------------------- #

def test_a_range_selects_only_what_it_covers(client, initialised_store):
    _seed(initialised_store, nights=30)
    since = SEED_END - timedelta(days=5)
    body = _get(client, "/api/v1/history/plans", **{"from": since.isoformat()}).json()
    assert body["items"]
    for item in body["items"]:
        assert datetime.fromisoformat(item["created_at"]) >= since


def test_an_empty_range_returns_an_empty_page_not_an_error(client, initialised_store):
    _seed(initialised_store, nights=5)
    body = _get(
        client,
        "/api/v1/history/plans",
        **{
            "from": (SEED_END + timedelta(days=100)).isoformat(),
            "to": (SEED_END + timedelta(days=200)).isoformat(),
        },
    )
    assert body.status_code == 200
    assert body.json()["items"] == []
    assert body.json()["has_more"] is False


def test_an_inverted_range_is_rejected(client, initialised_store):
    _seed(initialised_store, nights=5)
    response = _get(
        client,
        "/api/v1/history/plans",
        **{"from": SEED_END.isoformat(), "to": (SEED_END - timedelta(days=5)).isoformat()},
    )
    assert response.status_code == 400
    assert "starts after it ends" in response.json()["message"]


# --------------------------------------------------------------------------- #
# FR-036: a removed heater keeps its history
# --------------------------------------------------------------------------- #

def test_transitions_can_be_filtered_by_heater(client, initialised_store):
    _seed(initialised_store, nights=5)
    body = _get(client, "/api/v1/history/transitions", heater_id="salon").json()
    assert body["items"]
    assert {item["heater_id"] for item in body["items"]} == {"salon"}


def test_an_unknown_heater_gives_an_empty_page_not_a_404(client, initialised_store):
    """It may have existed and been removed: absence is not an error."""
    _seed(initialised_store, nights=3)
    response = _get(client, "/api/v1/history/transitions", heater_id="never-existed")
    assert response.status_code == 200
    assert response.json()["items"] == []


@pytest.mark.parametrize("suffix", ["+00:00", "Z"])
def test_both_iso_timezone_spellings_are_accepted(client, initialised_store, suffix):
    """Clients write either; both must work."""
    _seed(initialised_store, nights=5)
    stamp = (SEED_END - timedelta(days=3)).isoformat().replace("+00:00", suffix)
    response = _get(client, "/api/v1/history/plans", **{"from": stamp})
    assert response.status_code == 200, response.text
    assert response.json()["items"]


def test_the_forecast_source_is_reported(client, initialised_store):
    _seed(initialised_store, nights=3)
    body = _get(client, "/api/v1/history/forecasts").json()
    assert body["items"]
    assert all(item["source"] in ("aemet", "simulated", "fallback") for item in body["items"])


# --------------------------------------------------------------------------- #
# FR-037: retention from a client
# --------------------------------------------------------------------------- #

def test_prune_reports_what_it_deleted(client, initialised_store, api_clock):
    _seed(initialised_store, nights=40, end=api_clock.now)
    api_clock.advance(days=400)
    response = client.post("/api/v1/history/prune", headers=AUTH)
    assert response.status_code == 200
    body = response.json()
    assert body["total"] > 0
    assert body["retention_days"] == 365
    assert body["unlimited"] is False
    # And the configuration survived.
    assert client.get("/api/v1/config", headers=AUTH).json()["heaters"]


def test_prune_says_when_retention_is_unlimited(client):
    revision = client.get("/api/v1/config", headers=AUTH).json()["config_revision"]
    client.patch(
        "/api/v1/config",
        headers=AUTH,
        json={"revision": revision, "field": "retention_days", "value": "none"},
    )
    body = client.post("/api/v1/history/prune", headers=AUTH).json()
    assert body["unlimited"] is True
    assert body["total"] == 0


def test_prune_keeps_a_live_plan(client, initialised_store, api_clock, recorder):
    from dynamic_thermal_charge.scheduler import ChargeScheduler

    config, revision = initialised_store.repository.current()
    plan = ChargeScheduler().build(config.site, config.heaters, api_clock.now)
    recorder.record_plan(plan, None, revision)
    client.post("/api/v1/history/prune", headers=AUTH)
    body = _get(client, "/api/v1/history/plans").json()
    assert body["items"], "the live plan was pruned"
