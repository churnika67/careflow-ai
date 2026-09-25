import asyncio
import io
import json
import logging
from contextlib import contextmanager
from unittest.mock import AsyncMock

import pytest
from app.main import app
from app.observability.logging import get_request_id
from fastapi.testclient import TestClient


@pytest.fixture
def probes(monkeypatch):
    from app.services import health

    mocks = {}
    for name in ("postgres", "qdrant", "redis"):
        mocks[name] = AsyncMock()
        monkeypatch.setattr(health, f"check_{name}", mocks[name])
    return mocks


# --- one request ID per request, propagated and returned -----------------------


def test_request_receives_a_request_id_header(probes):
    with TestClient(app) as client:
        response = client.get("/health")
    assert "x-request-id" in response.headers
    assert len(response.headers["x-request-id"]) > 0


def test_generated_request_id_is_a_valid_uuid(probes):
    from uuid import UUID

    with TestClient(app) as client:
        response = client.get("/health")
    UUID(response.headers["x-request-id"])  # raises if not a valid UUID


def test_client_supplied_valid_uuid_request_id_is_honored(probes):
    supplied = "11111111-2222-3333-4444-555555555555"
    with TestClient(app) as client:
        response = client.get("/health", headers={"X-Request-ID": supplied})
    assert response.headers["x-request-id"] == supplied


def test_malformed_client_request_id_is_replaced_not_trusted(probes):
    with TestClient(app) as client:
        response = client.get("/health", headers={"X-Request-ID": "'; DROP TABLE reviews; --"})
    from uuid import UUID

    returned = response.headers["x-request-id"]
    assert returned != "'; DROP TABLE reviews; --"
    UUID(returned)


def test_overlong_client_request_id_is_replaced_not_trusted(probes):
    with TestClient(app) as client:
        response = client.get("/health", headers={"X-Request-ID": "a" * 5000})
    from uuid import UUID

    UUID(response.headers["x-request-id"])  # rejected the untrusted value, generated its own


# --- request/response success behavior unchanged --------------------------------


def test_success_response_body_and_status_unchanged(probes):
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_context_is_reset_after_a_successful_request(probes):
    with TestClient(app) as client:
        client.get("/health")
    # The test process's own ambient context must never carry a stale
    # request_id forward after the request completed.
    assert get_request_id() is None


# --- downstream logs correlate with the same ID ----------------------------------


@contextmanager
def _capture_app_log():
    """Attaches a fresh, dedicated handler to the "app" logger namespace
    for the duration of the block and yields the io.StringIO it writes to.

    Deliberately not caplog: Phase 13 Slice 4's configure_logging() sets
    propagate=False on "app" (by design -- see observability/config.py --
    so a future root-logger configuration can never cause a duplicate
    print of the same event), and caplog's default capture relies on
    root-logger propagation, so it never sees these records. Also
    deliberately not capsys: main.py's module-level configure_logging()
    call already bound the real StreamHandler to whatever `sys.stdout`
    was at import time, before any per-test capsys swap -- so capsys
    cannot observe it either in this test file (it works correctly in
    tests/test_observability_config.py, where configure_logging() runs
    freshly inside each test, after capsys has already swapped
    sys.stdout). Attaching our own handler directly sidesteps both
    timing issues and observes exactly what was actually logged."""
    buffer = io.StringIO()
    handler = logging.StreamHandler(buffer)
    handler.setFormatter(logging.Formatter("%(message)s"))
    app_logger = logging.getLogger("app")
    app_logger.addHandler(handler)
    try:
        yield buffer
    finally:
        app_logger.removeHandler(handler)


def test_downstream_structured_log_uses_the_same_request_id_as_the_response():
    with _capture_app_log() as buffer:
        with TestClient(app) as client:
            response = client.post("/orchestrate", json={"question": "what is the weather"})
    assert response.status_code in (200, 502, 503, 504)
    response_request_id = response.headers["x-request-id"]

    lines = [line for line in buffer.getvalue().splitlines() if line.strip()]
    matching = [
        json.loads(line)
        for line in lines
        if json.loads(line).get("event") == "orchestration_complete"
    ]
    assert len(matching) == 1
    assert matching[0]["request_id"] == response_request_id


# --- failure path clears context, logs once, never swallows ---------------------


def test_unhandled_exception_still_propagates_as_a_response_and_clears_context(monkeypatch):
    # /reviews (list) has no broad try/except around its DB call (unlike
    # /orchestrate, /multi-agent, /reviewable-query, which already catch
    # and convert every exception to a JSONResponse) -- a genuine
    # unhandled-exception path through the real ASGI stack.
    from app.api import reviews as reviews_module

    async def boom(*args, **kwargs):
        raise RuntimeError("simulated unhandled failure")

    monkeypatch.setattr(reviews_module, "list_reviews", boom)

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/reviews")
    # Starlette's default behavior for an unhandled exception is a 500;
    # this must not change.
    assert response.status_code == 500
    assert get_request_id() is None


def test_request_failed_event_logged_for_unhandled_exception():
    async def failing_call_next(request):
        raise RuntimeError("simulated infra failure")

    from app.observability.middleware import RequestContextMiddleware
    from starlette.requests import Request

    middleware = RequestContextMiddleware(app=None)
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/simulated",
        "headers": [],
        "query_string": b"",
    }
    request = Request(scope)

    with _capture_app_log() as buffer:
        with pytest.raises(RuntimeError):
            asyncio.run(middleware.dispatch(request, failing_call_next))

    lines = [line for line in buffer.getvalue().splitlines() if line.strip()]
    assert len(lines) == 1
    record = json.loads(lines[-1])
    assert record["event"] == "request_failed"
    assert record["error_category"] == "RuntimeError"
    assert record["path"] == "/simulated"
    assert record["method"] == "GET"
    assert "duration_ms" in record


# --- never logs request/response bodies or authorization headers ----------------


def test_middleware_never_accesses_request_body_or_authorization_header():
    # Checks actual access patterns, not just the absence of a word in the
    # module (which would also match the docstring/comments describing
    # this very guarantee).
    import inspect

    from app.observability import middleware as mod

    source = inspect.getsource(mod)
    assert "request.body" not in source
    assert "await request.json" not in source
    assert '"authorization"' not in source.lower()
    assert "'authorization'" not in source.lower()
    assert 'headers.get("authorization' not in source.lower()


def test_middleware_source_never_references_query_params_in_logging():
    import inspect

    from app.observability import middleware as mod

    source = inspect.getsource(mod)
    assert "query_params" not in source
    assert "request.url.query" not in source


# --- per-request ID distinctness via the real ASGI app --------------------------
# (True concurrent-task isolation is proven directly against the ContextVar
# mechanism itself in test_observability_logging.py via asyncio.gather --
# TestClient's sync interface does not exercise genuine concurrency here.)


def test_sequential_requests_each_receive_their_own_distinct_request_id(probes):
    with TestClient(app) as client:
        ids = set()
        for _ in range(5):
            response = client.get("/health")
            ids.add(response.headers["x-request-id"])
    assert len(ids) == 5  # every request got its own distinct ID, none reused


async def test_concurrent_requests_via_asgi_transport_do_not_cross_contaminate_ids(probes):
    import httpx

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        responses = await asyncio.gather(*(client.get("/health") for _ in range(5)))
    ids = {r.headers["x-request-id"] for r in responses}
    assert len(ids) == 5
