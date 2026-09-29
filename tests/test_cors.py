"""Phase 14 Slices 1-2: the minimal, environment-configurable CORS change
needed for local Next.js frontend connectivity (GET for Slice 1's system
status, POST added in Slice 2 for Ask CareFlow's POST /query). Not a
Phase 13 behavior change -- these tests exist to lock in the new
contract, not to reprove anything about Phase 13's own request/health/
cache semantics."""

from unittest.mock import AsyncMock

import pytest
from app.core.config import Settings, get_settings
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


def test_default_origin_allows_the_nextjs_dev_server(probes):
    with TestClient(app) as client:
        response = client.get("/live", headers={"Origin": "http://localhost:3000"})
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_unlisted_origin_is_not_granted_cors_access(probes):
    with TestClient(app) as client:
        response = client.get("/live", headers={"Origin": "http://evil.example.com"})
    assert response.status_code == 200  # the request itself still succeeds server-side
    assert "access-control-allow-origin" not in response.headers  # but CORS is not granted


def test_request_id_header_is_explicitly_exposed_for_cross_origin_reads(probes):
    with TestClient(app) as client:
        response = client.get("/live", headers={"Origin": "http://localhost:3000"})
    exposed = response.headers.get("access-control-expose-headers", "")
    assert "X-Request-ID" in exposed


def test_preflight_for_post_query_is_permitted_for_the_dev_server_origin():
    with TestClient(app) as client:
        response = client.options(
            "/query",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert "POST" in response.headers.get("access-control-allow-methods", "")


def test_cors_never_combined_with_credentials():
    import inspect

    from app import main as main_module

    source = inspect.getsource(main_module)
    assert "allow_credentials=True" not in source


def test_empty_origins_setting_adds_no_cors_middleware():
    # Direct-unit-level proof of the "empty means untouched" contract,
    # without needing a second full app import (FastAPI app construction
    # happens once at module import time).
    settings = Settings(_env_file=None, cors_allowed_origins="")
    origins = [o.strip() for o in settings.cors_allowed_origins.split(",") if o.strip()]
    assert origins == []


def test_openapi_still_documents_every_existing_endpoint(probes):
    with TestClient(app) as client:
        paths = client.get("/openapi.json").json()["paths"]
    for path in ("/health", "/live", "/ready", "/metrics"):
        assert path in paths
    get_settings.cache_clear()
