import asyncio
from unittest.mock import AsyncMock

import pytest
from app.core.config import Settings, get_settings
from app.main import app
from app.services import health
from fastapi.testclient import TestClient
from pydantic import ValidationError


@pytest.fixture
def probes(monkeypatch):
    mocks = {}
    for name in ("postgres", "qdrant", "redis"):
        mocks[name] = AsyncMock()
        monkeypatch.setattr(health, f"check_{name}", mocks[name])
    return mocks


def test_health_all_dependencies_ready(probes):
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["dependencies"] == {
        name: {"status": "ok"} for name in ("postgresql", "qdrant", "redis")
    }
    assert response.headers["cache-control"] == "no-store"
    for probe in probes.values():
        probe.assert_awaited_once()


@pytest.mark.parametrize("dependency", ["postgres", "qdrant", "redis"])
def test_dependency_failure_returns_503_without_leaking_secrets(probes, dependency):
    probes[dependency].side_effect = RuntimeError("postgresql://user:secret@private-host/db")
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 503
    assert response.json()["status"] == "degraded"
    key = "postgresql" if dependency == "postgres" else dependency
    assert response.json()["dependencies"][key]["status"] == "unavailable"
    assert "secret" not in response.text
    assert "private-host" not in response.text


async def test_slow_dependency_times_out(probes):
    async def slow(settings):
        await asyncio.sleep(1)

    probes["redis"].side_effect = slow
    result = await health.check_dependencies(Settings(_env_file=None, health_timeout_seconds=0.01))
    assert result.status == "degraded"
    assert result.dependencies["redis"].status == "unavailable"
    assert result.dependencies["postgresql"].status == "ok"


def test_configuration_uses_environment(monkeypatch):
    monkeypatch.setenv("HEALTH_TIMEOUT_SECONDS", "2.5")
    assert Settings(_env_file=None).health_timeout_seconds == 2.5


@pytest.mark.parametrize("timeout", [0, -1, 31])
def test_invalid_timeout_rejected(timeout):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, health_timeout_seconds=timeout)


def test_credentials_redacted_from_config():
    settings = Settings(_env_file=None, database_url="postgresql://user:private-password@host/db")
    assert "private-password" not in repr(settings)
    assert "private-password" not in settings.model_dump_json()


def test_openapi_documents_unavailable_response(probes):
    with TestClient(app) as client:
        responses = client.get("/openapi.json").json()["paths"]["/health"]["get"]["responses"]
    assert "200" in responses
    assert "503" in responses
    get_settings.cache_clear()
