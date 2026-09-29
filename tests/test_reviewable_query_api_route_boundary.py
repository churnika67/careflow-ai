"""Phase 16 Slice 2: API-level route-boundary exception mapping for
POST /reviewable-query.

tests/test_review_api.py's own tests are entirely gated behind
CAREFLOW_REVIEW_INTEGRATION=1 (a module-level pytest.mark.skipif) because
most of them genuinely need a live Postgres connection. This one test does
not -- both connect() and run_reviewable_query() are monkeypatched at the
exact points backend/app/api/reviews.py imports them -- so it lives in its
own file, deliberately unconditional and never skipped, to prove the route
handler's own GenerationError -> HTTP mapping without needing live
Postgres. Mirrors the equivalent pair already added for /orchestrate and
/multi-agent."""

from app.main import app
from fastapi.testclient import TestClient


class _FakeConnection:
    async def close(self):
        pass


def test_generation_error_maps_to_its_declared_status_code_through_the_route(monkeypatch):
    from app.generation.providers import GenerationError

    async def _fake_connect(settings):
        return _FakeConnection()

    async def _fake_run_reviewable_query(*args, **kwargs):
        raise GenerationError("provider_timeout", status_code=504)

    monkeypatch.setattr("app.api.reviews.connect", _fake_connect)
    monkeypatch.setattr("app.api.reviews.run_reviewable_query", _fake_run_reviewable_query)
    with TestClient(app) as client:
        response = client.post("/reviewable-query", json={"question": "does this time out"})
    assert response.status_code == 504
    assert response.json() == {"error": {"code": "provider_timeout"}}


def test_unexpected_infrastructure_failure_maps_to_503_never_exposing_internals(monkeypatch):
    async def _fake_connect(settings):
        return _FakeConnection()

    async def _fake_run_reviewable_query(*args, **kwargs):
        raise RuntimeError("connection refused: internal detail that must never leak")

    monkeypatch.setattr("app.api.reviews.connect", _fake_connect)
    monkeypatch.setattr("app.api.reviews.run_reviewable_query", _fake_run_reviewable_query)
    with TestClient(app) as client:
        response = client.post("/reviewable-query", json={"question": "does this fail"})
    assert response.status_code == 503
    assert response.json() == {"error": {"code": "reviewable_query_unavailable"}}
    assert "connection refused" not in response.text
