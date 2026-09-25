from unittest.mock import AsyncMock

import pytest
from app.core.config import get_settings
from app.main import app
from app.services import health
from fastapi.testclient import TestClient


@pytest.fixture
def probes(monkeypatch):
    mocks = {}
    for name in ("postgres", "qdrant", "redis"):
        mocks[name] = AsyncMock()
        monkeypatch.setattr(health, f"check_{name}", mocks[name])
    return mocks


# --- /live ------------------------------------------------------------------------


def test_live_returns_200_with_all_external_checks_mocked_unavailable(probes):
    for mock in probes.values():
        mock.side_effect = RuntimeError("unreachable")
    with TestClient(app) as client:
        response = client.get("/live")
    assert response.status_code == 200
    assert response.json() == {"status": "alive", "service": "careflow-ai"}


def test_live_never_calls_any_dependency_check(probes):
    with TestClient(app) as client:
        client.get("/live")
    for probe in probes.values():
        probe.assert_not_awaited()


def test_live_does_not_expose_internal_configuration(probes):
    with TestClient(app) as client:
        response = client.get("/live")
    body = response.text
    assert "postgres" not in body.lower()
    assert "redis" not in body.lower()
    assert "qdrant" not in body.lower()


# --- /ready -------------------------------------------------------------------------


def test_ready_all_authoritative_dependencies_healthy_returns_200(probes):
    with TestClient(app) as client:
        response = client.get("/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["dependencies"] == {
        name: {"status": "ok"} for name in ("postgresql", "qdrant", "redis")
    }
    assert response.headers["cache-control"] == "no-store"


def test_postgres_unavailable_fails_readiness(probes):
    probes["postgres"].side_effect = RuntimeError("down")
    with TestClient(app) as client:
        response = client.get("/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "unready"
    assert body["dependencies"]["postgresql"]["status"] == "unavailable"


def test_qdrant_unavailable_fails_readiness(probes):
    probes["qdrant"].side_effect = RuntimeError("down")
    with TestClient(app) as client:
        response = client.get("/ready")
    assert response.status_code == 503
    assert response.json()["status"] == "unready"


def test_redis_unavailable_alone_does_not_fail_readiness(probes):
    probes["redis"].side_effect = RuntimeError("down")
    with TestClient(app) as client:
        response = client.get("/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    # Still reported, for operational visibility -- just not authoritative.
    assert body["dependencies"]["redis"]["status"] == "unavailable"


def test_postgres_and_redis_both_down_qdrant_up_still_unready(probes):
    probes["postgres"].side_effect = RuntimeError("down")
    probes["redis"].side_effect = RuntimeError("down")
    with TestClient(app) as client:
        response = client.get("/ready")
    assert response.status_code == 503
    assert response.json()["status"] == "unready"


def test_ready_does_not_leak_credentials(probes):
    probes["postgres"].side_effect = RuntimeError("postgresql://user:secret@private-host/db")
    with TestClient(app) as client:
        response = client.get("/ready")
    assert "secret" not in response.text
    assert "private-host" not in response.text


# --- /health backward compatibility --------------------------------------------------


def test_health_still_requires_all_three_dependencies_including_redis(probes):
    probes["redis"].side_effect = RuntimeError("down")
    with TestClient(app) as client:
        response = client.get("/health")
    # Unchanged legacy contract: /health treats Redis as required, unlike /ready.
    assert response.status_code == 503
    assert response.json()["status"] == "degraded"


def test_health_route_and_ready_route_are_independent_endpoints(probes):
    probes["redis"].side_effect = RuntimeError("down")
    with TestClient(app) as client:
        health_response = client.get("/health")
        ready_response = client.get("/ready")
    assert health_response.status_code == 503
    assert ready_response.status_code == 200


def test_openapi_documents_all_three_endpoints(probes):
    with TestClient(app) as client:
        paths = client.get("/openapi.json").json()["paths"]
    assert "/health" in paths
    assert "/live" in paths
    assert "/ready" in paths
    get_settings.cache_clear()
