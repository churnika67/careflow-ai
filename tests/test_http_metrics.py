from unittest.mock import AsyncMock

import pytest
from app.main import app
from app.observability.metrics import (
    http_errors_total,
    http_request_duration_ms,
    http_requests_total,
    reset_metrics_for_tests,
    snapshot_metrics,
)
from app.services import health
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _reset():
    reset_metrics_for_tests()
    yield
    reset_metrics_for_tests()


@pytest.fixture
def probes(monkeypatch):
    mocks = {}
    for name in ("postgres", "qdrant", "redis"):
        mocks[name] = AsyncMock()
        monkeypatch.setattr(health, f"check_{name}", mocks[name])
    return mocks


def test_request_counter_increments():
    with TestClient(app) as client:
        client.post("/orchestrate", json={"question": "what is the weather"})
    assert http_requests_total.snapshot()[("POST", "/orchestrate", "2xx")] == 1


def test_duration_aggregate_increments():
    with TestClient(app) as client:
        client.post("/orchestrate", json={"question": "what is the weather"})
    entry = http_request_duration_ms.snapshot()[("POST", "/orchestrate")]
    assert entry["count"] == 1
    assert entry["sum_ms"] >= 0


def test_5xx_error_counter_increments(monkeypatch):
    from app.api import reviews as reviews_module

    async def boom(*args, **kwargs):
        raise RuntimeError("simulated")

    monkeypatch.setattr(reviews_module, "list_reviews", boom)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/reviews")
    assert response.status_code == 500
    assert http_errors_total.snapshot()[("GET", "/reviews")] == 1


def test_successful_request_does_not_increment_error_counter():
    with TestClient(app) as client:
        client.post("/orchestrate", json={"question": "what is the weather"})
    assert http_errors_total.snapshot() == {}


def test_validation_error_does_not_increment_error_counter():
    with TestClient(app) as client:
        response = client.post("/orchestrate", json={})  # missing required field -> 422
    assert response.status_code == 422
    assert http_errors_total.snapshot() == {}


def test_abstention_is_a_200_and_does_not_count_as_internal_error():
    with TestClient(app) as client:
        response = client.post("/orchestrate", json={"question": "what is the weather"})
    body = response.json()
    assert body["status"] == "abstained"
    assert response.status_code == 200
    assert http_errors_total.snapshot() == {}
    assert http_requests_total.snapshot()[("POST", "/orchestrate", "2xx")] == 1


def test_dynamic_review_id_becomes_the_route_template_not_the_raw_id(monkeypatch):
    # This test's real subject is metrics route-templating, not review
    # lookup -- it needs some real 4xx response from GET /reviews/{id}, and
    # a non-UUID-shaped id naturally produces one via the same
    # InvalidTextRepresentation path get_review() already handles (see
    # app/api/reviews.py::get_review_detail). Mocking connect()/get_review()
    # here reproduces that exact response without a real database
    # connection, so this stays a true unit test rather than silently
    # depending on Compose being up (which it always incidentally was on
    # every machine this suite had previously been run on, masking the
    # dependency).
    import psycopg
    from app.api import reviews as reviews_module

    class _FakeConnection:
        async def close(self):
            pass

    async def _fake_connect(_settings):
        return _FakeConnection()

    async def _fake_get_review(_connection, _review_id):
        raise psycopg.errors.InvalidTextRepresentation()

    monkeypatch.setattr(reviews_module, "connect", _fake_connect)
    monkeypatch.setattr(reviews_module, "get_review", _fake_get_review)

    distinctive_id = "totally-unique-review-id-marker-98765"
    with TestClient(app) as client:
        client.get(f"/reviews/{distinctive_id}")
    labels = list(http_requests_total.snapshot().keys())
    assert ("GET", "/reviews/{review_id}", "4xx") in labels
    for _method, route, _status_class in labels:
        assert distinctive_id not in route


def test_unmatched_path_falls_back_to_bounded_label():
    with TestClient(app) as client:
        client.get("/this-route-does-not-exist-anywhere")
    labels = list(http_requests_total.snapshot().keys())
    assert ("GET", "unmatched", "4xx") in labels


def test_request_id_never_appears_as_a_metric_label():
    with TestClient(app) as client:
        response = client.post("/orchestrate", json={"question": "what is the weather"})
    request_id = response.headers["x-request-id"]
    snap = snapshot_metrics()
    dumped = str(snap)
    assert request_id not in dumped


def test_raw_query_text_never_appears_in_metrics():
    distinctive_query = "does-medicare-cover-a-wheelchair-for-grandma-marker-xyz"
    with TestClient(app) as client:
        client.post("/orchestrate", json={"question": distinctive_query})
    dumped = str(snapshot_metrics())
    assert distinctive_query not in dumped


def test_authorization_header_never_appears_in_metrics():
    with TestClient(app) as client:
        client.post(
            "/orchestrate",
            json={"question": "what is the weather"},
            headers={"Authorization": "Bearer super-secret-token-marker"},
        )
    dumped = str(snapshot_metrics())
    assert "super-secret-token-marker" not in dumped
    assert "Bearer" not in dumped


def test_health_live_ready_metrics_endpoints_excluded_from_request_metrics(probes):
    with TestClient(app) as client:
        client.get("/health")
        client.get("/live")
        client.get("/ready")
        client.get("/metrics")
    snap = http_requests_total.snapshot()
    for _method, route, _status_class in snap:
        assert route not in ("/health", "/live", "/ready", "/metrics")


def test_metrics_endpoint_itself_returns_bounded_json():
    with TestClient(app) as client:
        client.post("/orchestrate", json={"question": "what is the weather"})
        response = client.get("/metrics")
    assert response.status_code == 200
    body = response.json()
    assert "http_requests_total" in body
    assert isinstance(body["http_requests_total"], list)
