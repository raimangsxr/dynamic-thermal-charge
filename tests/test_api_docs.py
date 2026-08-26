"""The self-describing documentation: FR-042, FR-043, SC-010."""

from __future__ import annotations

from tests.conftest import API_TOKEN, AUTH


def _spec(client) -> dict:
    response = client.get("/openapi.json", headers=AUTH)
    assert response.status_code == 200
    return response.json()


def test_the_description_matches_what_is_served(client, api_app):
    """SC-010: no phantom operations, no undocumented ones."""
    from tests.conftest import iter_routes

    described = {
        (path, method.lower())
        for path, operations in _spec(client)["paths"].items()
        for method in operations
    }
    served = {
        (path, method)
        for path, method, in_schema in iter_routes(api_app)
        if in_schema
    }
    assert served, "the route walker found nothing; the test would be vacuous"
    assert described == served, (
        f"documented but not served: {sorted(described - served)}; "
        f"served but not documented: {sorted(served - described)}"
    )


def test_every_documented_operation_really_answers(client):
    """Introspection can agree with itself and still be wrong. This asks the app.

    A documented path that is not routed returns 404; anything else -- 200, 401,
    422, 503 -- proves the operation exists.
    """
    for path, operations in _spec(client)["paths"].items():
        concrete = path.replace("{heater_id}", "salon")
        for method in operations:
            response = client.request(method.upper(), concrete, headers=AUTH, json={})
            assert response.status_code != 404 or "heater" in response.text.lower(), (
                f"{method.upper()} {path} is documented but not routed"
            )


def test_every_operation_documents_its_error_codes(client):
    """FR-042: a client should learn the failure modes from the contract."""
    paths = _spec(client)["paths"]
    for path, operations in paths.items():
        if path == "/health":
            continue  # the one route that cannot fail on authentication
        for method, operation in operations.items():
            responses = set(operation.get("responses", {}))
            assert "401" in responses, f"{method.upper()} {path} omits 401"
            assert "503" in responses, f"{method.upper()} {path} omits 503"


def test_write_operations_document_the_conflict_and_validation_codes(client):
    paths = _spec(client)["paths"]
    writes = [
        (path, method)
        for path, operations in paths.items()
        for method in operations
        if method in ("patch", "post", "delete") and path != "/api/v1/history/prune"
    ]
    assert writes
    for path, method in writes:
        responses = set(paths[path][method]["responses"])
        assert "409" in responses, f"{method.upper()} {path} omits 409"
        assert "422" in responses, f"{method.upper()} {path} omits 422"


def test_the_description_holds_no_secret_or_real_value(client, monkeypatch):
    monkeypatch.setenv("AEMET_API_KEY", "the-real-aemet-key")
    text = client.get("/openapi.json", headers=AUTH).text
    for leak in (API_TOKEN, "the-real-aemet-key", "sqlite:///", "dtc.db"):
        assert leak not in text, f"the description leaked {leak!r}"


def test_the_description_says_the_api_switches_nothing(client):
    description = _spec(client)["info"]["description"]
    assert "switches an output" in description or "switches no output" in description
    assert "manual override" in description


def test_the_status_operation_explains_the_currency_rule(client):
    """The single most misusable field in the API deserves a warning in place."""
    operation = _spec(client)["paths"]["/api/v1/status"]["get"]
    text = (operation.get("description") or "").lower()
    assert "state_is_current" in text
    assert "last known" in text


def test_the_docs_page_renders(client):
    response = client.get("/docs", headers=AUTH)
    assert response.status_code == 200
    assert "swagger" in response.text.lower()
