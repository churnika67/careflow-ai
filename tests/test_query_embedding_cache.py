import io
import json
import logging
import os
from contextlib import contextmanager

import numpy as np
import pytest
from app.core.config import Settings
from app.generation.embedding_cache import (
    QUERY_EMBEDDING_OPERATION,
    QUERY_EMBEDDING_PAYLOAD_SCHEMA_VERSION,
    CachingQueryEmbedding,
    _validate_query_embedding_payload,
)
from app.infrastructure.cache import (
    CacheReadResult,
    CacheReadStatus,
    CacheWriteResult,
    CacheWriteStatus,
    build_cache_key,
)

# Importing app.main (not otherwise used directly by the pure tests below)
# runs configure_logging() as an import-time side effect -- the same
# convention tests/test_observability_middleware.py relies on -- so the
# "app" logger namespace is guaranteed configured (INFO, one handler,
# propagate=False) regardless of which other test files pytest has already
# collected, making the log-capture tests below reliable even if this file
# is run in complete isolation.
from app.main import app  # noqa: F401
from app.observability.metrics import (
    query_embedding_cache_duration_ms,
    query_embedding_cache_reads_total,
    query_embedding_cache_writes_total,
    reset_metrics_for_tests,
)

pytestmark_live = pytest.mark.skipif(
    os.environ.get("CAREFLOW_CACHE_INTEGRATION") != "1",
    reason="Set CAREFLOW_CACHE_INTEGRATION=1 with Compose running (Redis) to exercise the "
    "real query-embedding cache round trip",
)

pytestmark_orchestration_live = pytest.mark.skipif(
    os.environ.get("CAREFLOW_ORCHESTRATION_INTEGRATION") != "1",
    reason="Set CAREFLOW_ORCHESTRATION_INTEGRATION=1 with Compose running and the Phase 8 "
    "dev-subset ingestion already applied to exercise the real request path",
)


@pytest.fixture(autouse=True)
def _reset_metrics():
    reset_metrics_for_tests()
    yield
    reset_metrics_for_tests()


class FakeProvider:
    """A minimal stand-in for SentenceTransformerEmbedding: same
    describe()/embed()/tokenizer surface, no real model load."""

    def __init__(self, *, dimension=3, model="fake-model", revision="rev1", vector_fn=None):
        self.calls: list[list[str]] = []
        self.tokenizer = object()
        self.dimension = dimension
        self.model = model
        self.revision = revision
        self._vector_fn = vector_fn or (lambda text: [float(len(text) % 7)] * dimension)

    def describe(self) -> dict:
        return {
            "provider": "fake",
            "model": self.model,
            "revision": self.revision,
            "dimension": self.dimension,
        }

    def embed(self, texts: list[str]) -> np.ndarray:
        self.calls.append(list(texts))
        return np.array([self._vector_fn(t) for t in texts], dtype=np.float32)


class RecordingCache:
    """A tiny in-memory stand-in for SyncCacheClient -- records every
    key touched so keying behavior is directly observable, and lets a test
    pre-seed or force any CacheReadStatus/CacheWriteStatus."""

    def __init__(self, *, seed: dict | None = None, read_status=None, write_status=None):
        self._store = dict(seed or {})
        self._forced_read_status = read_status
        self._forced_write_status = write_status
        self.get_calls: list[str] = []
        self.set_calls: list[tuple[str, object, int]] = []

    def get(self, key: str) -> CacheReadResult:
        self.get_calls.append(key)
        if self._forced_read_status is not None:
            return CacheReadResult(self._forced_read_status)
        if key in self._store:
            return CacheReadResult(CacheReadStatus.HIT, self._store[key])
        return CacheReadResult(CacheReadStatus.MISS)

    def set(self, key: str, value: object, *, ttl_seconds: int) -> CacheWriteResult:
        self.set_calls.append((key, value, ttl_seconds))
        if self._forced_write_status is not None:
            return CacheWriteResult(self._forced_write_status)
        self._store[key] = value
        return CacheWriteResult(CacheWriteStatus.WRITTEN)


def _payload(vector: list[float], *, model="fake-model", dimension=3) -> dict:
    return {
        "schema_version": QUERY_EMBEDDING_PAYLOAD_SCHEMA_VERSION,
        "model": model,
        "revision": "rev1",
        "dimension": dimension,
        "embedding": vector,
    }


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, query_embedding_cache_enabled=True, **overrides)


@contextmanager
def _capture_app_log():
    buffer = io.StringIO()
    handler = logging.StreamHandler(buffer)
    handler.setFormatter(logging.Formatter("%(message)s"))
    app_logger = logging.getLogger("app")
    app_logger.addHandler(handler)
    try:
        yield buffer
    finally:
        app_logger.removeHandler(handler)


def _events(buffer: io.StringIO, event: str) -> list[dict]:
    lines = [line for line in buffer.getvalue().splitlines() if line.strip()]
    return [json.loads(line) for line in lines if json.loads(line).get("event") == event]


# --- keying (section 16) ------------------------------------------------------


def test_same_query_and_config_produce_same_key():
    provider = FakeProvider()
    cache = RecordingCache()
    settings = _settings()
    wrapper = CachingQueryEmbedding(provider, settings, cache)
    wrapper.embed(["hospital bed"])
    wrapper.embed(["hospital bed"])
    assert cache.get_calls[0] == cache.get_calls[1]


def test_different_query_produces_different_key():
    provider = FakeProvider()
    cache = RecordingCache()
    settings = _settings()
    wrapper = CachingQueryEmbedding(provider, settings, cache)
    wrapper.embed(["hospital bed"])
    wrapper.embed(["power wheelchair"])
    assert cache.get_calls[0] != cache.get_calls[1]


def test_different_model_produces_different_key():
    cache_a, cache_b = RecordingCache(), RecordingCache()
    settings = _settings()
    CachingQueryEmbedding(FakeProvider(model="model-a"), settings, cache_a).embed(["x"])
    CachingQueryEmbedding(FakeProvider(model="model-b"), settings, cache_b).embed(["x"])
    assert cache_a.get_calls[0] != cache_b.get_calls[0]


def test_different_revision_produces_different_key():
    cache_a, cache_b = RecordingCache(), RecordingCache()
    settings = _settings()
    CachingQueryEmbedding(FakeProvider(revision="rev-a"), settings, cache_a).embed(["x"])
    CachingQueryEmbedding(FakeProvider(revision="rev-b"), settings, cache_b).embed(["x"])
    assert cache_a.get_calls[0] != cache_b.get_calls[0]


def test_raw_query_text_absent_from_key():
    provider = FakeProvider()
    cache = RecordingCache()
    settings = _settings()
    CachingQueryEmbedding(provider, settings, cache).embed(
        ["does medicare cover a wheelchair for grandma jones"]
    )
    key = cache.get_calls[0]
    assert "grandma" not in key
    assert "wheelchair" not in key
    assert "medicare" not in key.lower().replace("careflow", "")


def test_key_schema_version_present():
    provider = FakeProvider()
    cache = RecordingCache()
    settings = _settings(cache_schema_version="v7")
    CachingQueryEmbedding(provider, settings, cache).embed(["x"])
    key = cache.get_calls[0]
    assert key.startswith("careflow:v7:")
    assert f":{QUERY_EMBEDDING_OPERATION}:" in key


# --- HIT behavior (section 17) -------------------------------------------------


def test_hit_returns_cached_vector_without_calling_the_model():
    provider = FakeProvider()
    settings = _settings()
    key = build_cache_key(
        operation=QUERY_EMBEDDING_OPERATION,
        config_fingerprint=provider.describe(),
        input_fingerprint={"query": "hospital bed"},
        schema_version=settings.cache_schema_version,
    )
    cache = RecordingCache(seed={key: _payload([1.0, 2.0, 3.0])})
    wrapper = CachingQueryEmbedding(provider, settings, cache)
    with _capture_app_log() as buffer:
        result = wrapper.embed(["hospital bed"])
    assert provider.calls == []
    assert np.allclose(result[0], [1.0, 2.0, 3.0])
    assert cache.set_calls == []
    events = _events(buffer, "query_embedding_cache")
    assert len(events) == 1
    assert events[0]["cache_status"] == "hit"
    assert events[0]["cache_write_status"] is None
    log_text = buffer.getvalue()
    assert "hospital bed" not in log_text
    # Vector values must never leak into the log. Checked against every
    # field except `timestamp` and `duration_ms`: both are genuine,
    # non-deterministic wall-clock values (real time, not mocked), and
    # their own digits can coincidentally contain a "N.0"-shaped
    # substring purely by chance -- e.g. a timestamp second ending in 1
    # followed by a fractional part starting with 0 produces "...1.0..."
    # with no relation whatsoever to the cached [1.0, 2.0, 3.0] vector.
    # This was a real, rare (order of a few percent per run), reproduced
    # flake, not a false alarm -- see docs/phase16_testing_ci_design.md's
    # flaky-test audit for how it was caught and confirmed.
    safe_text = json.dumps(
        {k: v for k, v in events[0].items() if k not in ("timestamp", "duration_ms")}
    )
    assert "1.0" not in safe_text and "2.0" not in safe_text and "3.0" not in safe_text


# --- MISS behavior (section 18) ------------------------------------------------


def test_miss_computes_writes_exactly_once_with_explicit_ttl():
    provider = FakeProvider()
    cache = RecordingCache()
    settings = _settings(query_embedding_cache_ttl_seconds=1234)
    wrapper = CachingQueryEmbedding(provider, settings, cache)
    with _capture_app_log() as buffer:
        result = wrapper.embed(["hospital bed"])
    assert len(provider.calls) == 1
    assert len(cache.set_calls) == 1
    written_key, written_value, ttl = cache.set_calls[0]
    assert written_key == cache.get_calls[0]
    assert ttl == 1234
    assert written_value["embedding"] == list(result[0].astype(float))
    events = _events(buffer, "query_embedding_cache")
    assert events[0]["cache_status"] == "miss"
    assert events[0]["cache_write_status"] == "written"


# --- Redis failure (section 19) ------------------------------------------------


@pytest.mark.parametrize("status", [CacheReadStatus.UNAVAILABLE, CacheReadStatus.READ_ERROR])
def test_read_failure_falls_back_to_computing_and_skips_the_write(status):
    provider = FakeProvider()
    cache = RecordingCache(read_status=status)
    settings = _settings()
    wrapper = CachingQueryEmbedding(provider, settings, cache)
    with _capture_app_log() as buffer:
        result = wrapper.embed(["hospital bed"])
    assert len(provider.calls) == 1
    assert result.shape == (1, 3)
    assert cache.set_calls == []
    events = _events(buffer, "query_embedding_cache")
    assert events[0]["cache_status"] == status.value
    assert events[0]["cache_write_status"] is None


def test_write_error_still_returns_the_freshly_computed_vector():
    provider = FakeProvider()
    cache = RecordingCache(write_status=CacheWriteStatus.WRITE_ERROR)
    settings = _settings()
    wrapper = CachingQueryEmbedding(provider, settings, cache)
    with _capture_app_log() as buffer:
        result = wrapper.embed(["hospital bed"])
    assert len(provider.calls) == 1
    assert result.shape == (1, 3)
    events = _events(buffer, "query_embedding_cache")
    assert events[0]["cache_status"] == "miss"
    assert events[0]["cache_write_status"] == "write_error"


def test_no_redis_exception_ever_escapes_the_request_path():
    class ExplodingCache(RecordingCache):
        def get(self, key):
            raise AssertionError("must never be reached by a real Redis exception")

    # A real Redis failure never raises out of SyncCacheClient -- it is
    # always classified into a CacheReadResult/CacheWriteResult first, so
    # there is nothing for embed() to catch here. This test documents that
    # invariant by construction: the wrapper never wraps cache.get()/set()
    # in a try/except of its own, matching Slice 2's "no ambiguous swallow"
    # contract at this layer too.
    import inspect

    from app import generation

    source = inspect.getsource(generation.embedding_cache)
    assert "except" not in source


# --- MALFORMED (section 20) ----------------------------------------------------


def test_malformed_json_from_slice2_layer_is_recomputed_and_replaced():
    provider = FakeProvider()
    cache = RecordingCache(read_status=CacheReadStatus.MALFORMED)
    settings = _settings()
    wrapper = CachingQueryEmbedding(provider, settings, cache)
    with _capture_app_log() as buffer:
        result = wrapper.embed(["hospital bed"])
    assert len(provider.calls) == 1
    assert result.shape == (1, 3)
    assert len(cache.set_calls) == 1  # best-effort replace
    events = _events(buffer, "query_embedding_cache")
    assert events[0]["cache_status"] == "malformed"
    assert events[0]["cache_write_status"] == "written"


@pytest.mark.parametrize(
    "bad_payload",
    [
        {"not": "the expected shape"},
        {**_payload([1.0, 2.0, 3.0]), "schema_version": "v99"},
        {**_payload([1.0, 2.0, 3.0]), "dimension": 4},
        {**_payload([1.0, 2.0]), "dimension": 3},  # wrong actual length
        {**_payload(["a", "b", "c"])},
        {**_payload([1.0, float("nan"), 3.0])},
        {**_payload([1.0, float("inf"), 3.0])},
        {**_payload([1.0, float("-inf"), 3.0])},
        {**_payload([1.0, 2.0, 3.0]), "embedding": None},
        {**_payload([1.0, 2.0, 3.0]), "embedding": {"unexpected": "structure"}},
        {**_payload([1.0, 2.0, 3.0]), "embedding": [1.0, [2.0], 3.0]},
    ],
)
def test_schema_invalid_hit_payloads_are_recomputed_and_replaced(bad_payload):
    provider = FakeProvider()
    settings = _settings()
    key = build_cache_key(
        operation=QUERY_EMBEDDING_OPERATION,
        config_fingerprint=provider.describe(),
        input_fingerprint={"query": "hospital bed"},
        schema_version=settings.cache_schema_version,
    )
    cache = RecordingCache(seed={key: bad_payload})
    wrapper = CachingQueryEmbedding(provider, settings, cache)
    with _capture_app_log() as buffer:
        result = wrapper.embed(["hospital bed"])
    assert len(provider.calls) == 1  # never trusted, always recomputed
    assert result.shape == (1, 3)
    assert len(cache.set_calls) == 1  # best-effort replace, not crashed
    events = _events(buffer, "query_embedding_cache")
    assert events[0]["cache_status"] == "malformed"


def test_validator_rejects_boolean_masquerading_as_numeric():
    assert (
        _validate_query_embedding_payload(
            {**_payload([True, 1.0, 1.0])}, expected_model="fake-model", expected_dimension=3
        )
        is None
    )


def test_validator_accepts_a_well_formed_payload():
    result = _validate_query_embedding_payload(
        _payload([1.0, 2.0, 3.0]), expected_model="fake-model", expected_dimension=3
    )
    assert result == [1.0, 2.0, 3.0]


# --- cache metrics (Phase 13 Slice 6, section 26) --------------------------------


def test_hit_increments_hit_counter_only():
    provider = FakeProvider()
    settings = _settings()
    key = build_cache_key(
        operation=QUERY_EMBEDDING_OPERATION,
        config_fingerprint=provider.describe(),
        input_fingerprint={"query": "hospital bed"},
        schema_version=settings.cache_schema_version,
    )
    cache = RecordingCache(seed={key: _payload([1.0, 2.0, 3.0])})
    CachingQueryEmbedding(provider, settings, cache).embed(["hospital bed"])
    assert query_embedding_cache_reads_total.snapshot() == {("hit",): 1}
    assert query_embedding_cache_writes_total.snapshot() == {}
    assert query_embedding_cache_duration_ms.snapshot()[()]["count"] == 1


def test_miss_increments_miss_and_written_counters():
    provider = FakeProvider()
    cache = RecordingCache()
    settings = _settings()
    CachingQueryEmbedding(provider, settings, cache).embed(["hospital bed"])
    assert query_embedding_cache_reads_total.snapshot() == {("miss",): 1}
    assert query_embedding_cache_writes_total.snapshot() == {("written",): 1}


@pytest.mark.parametrize("status", [CacheReadStatus.UNAVAILABLE, CacheReadStatus.READ_ERROR])
def test_unavailable_and_read_error_increment_matching_counter_with_no_write(status):
    provider = FakeProvider()
    cache = RecordingCache(read_status=status)
    settings = _settings()
    CachingQueryEmbedding(provider, settings, cache).embed(["hospital bed"])
    assert query_embedding_cache_reads_total.snapshot() == {(status.value,): 1}
    assert query_embedding_cache_writes_total.snapshot() == {}


def test_malformed_increments_malformed_and_write_status_counter():
    provider = FakeProvider()
    cache = RecordingCache(read_status=CacheReadStatus.MALFORMED)
    settings = _settings()
    CachingQueryEmbedding(provider, settings, cache).embed(["hospital bed"])
    assert query_embedding_cache_reads_total.snapshot() == {("malformed",): 1}
    assert query_embedding_cache_writes_total.snapshot() == {("written",): 1}


def test_write_error_status_recorded_in_write_counter():
    provider = FakeProvider()
    cache = RecordingCache(write_status=CacheWriteStatus.WRITE_ERROR)
    settings = _settings()
    CachingQueryEmbedding(provider, settings, cache).embed(["hospital bed"])
    assert query_embedding_cache_reads_total.snapshot() == {("miss",): 1}
    assert query_embedding_cache_writes_total.snapshot() == {("write_error",): 1}


def test_metrics_never_retain_query_key_or_vector():
    provider = FakeProvider()
    cache = RecordingCache()
    settings = _settings()
    CachingQueryEmbedding(provider, settings, cache).embed(
        ["does medicare cover a wheelchair for grandma jones"]
    )
    from app.observability.metrics import snapshot_metrics

    dumped = str(snapshot_metrics())
    assert "grandma" not in dumped
    assert "wheelchair" not in dumped
    assert cache.get_calls[0] not in dumped  # the cache key itself


# --- disabled (section 21) ------------------------------------------------------


def test_disabled_setting_never_wraps_the_embedding_provider_in_runtime(monkeypatch):
    from app.generation.runtime import load_embedding, retrieve

    def boom():
        raise AssertionError("get_sync_cache_client must not be called when caching is disabled")

    monkeypatch.setattr("app.infrastructure.cache.get_sync_cache_client", boom)
    load_embedding.cache_clear()

    class Client:
        def __init__(self, **kwargs):
            pass

        def close(self):
            pass

    class Retrieval:
        def __init__(self, *args):
            pass

        def search(self, query, mode, depth, **kwargs):
            return [{"chunk_id": "a"}]

    monkeypatch.setattr("qdrant_client.QdrantClient", Client)
    monkeypatch.setattr("app.retrieval.search.Retriever", Retrieval)
    monkeypatch.setattr("app.generation.runtime.load_embedding", lambda *args: FakeProvider())

    settings = Settings(_env_file=None, query_embedding_cache_enabled=False, rerank_enabled=False)
    hits = retrieve("hospital bed", settings)
    assert hits == [{"chunk_id": "a"}]


def test_disabled_setting_matches_pre_cache_behavior_exactly(monkeypatch):
    # When disabled, generation/runtime.py must use load_embedding()'s
    # return value completely unwrapped -- not merely "equivalent" but the
    # exact same object, so there is no wrapper-introduced behavior at all.
    from app.generation.runtime import retrieve

    provider = FakeProvider()
    seen_providers = []

    class Client:
        def __init__(self, **kwargs):
            pass

        def close(self):
            pass

    class Retrieval:
        def __init__(self, index, embedding, *args):
            seen_providers.append(embedding)

        def search(self, query, mode, depth, **kwargs):
            return []

    monkeypatch.setattr("qdrant_client.QdrantClient", Client)
    monkeypatch.setattr("app.retrieval.search.Retriever", Retrieval)
    monkeypatch.setattr("app.generation.runtime.load_embedding", lambda *args: provider)

    settings = Settings(_env_file=None, query_embedding_cache_enabled=False, rerank_enabled=False)
    retrieve("hospital bed", settings)
    assert seen_providers == [provider]  # the raw provider, not a wrapper


# --- concurrency (section 22): accepted limitation, documented not tested -----

# Concurrent MISSes for the same key may each compute and write independently
# (no distributed lock / single-flight is built in this slice, matching the
# explicit instruction not to add that complexity here). This is a deliberate,
# documented limitation -- see docs/phase13_reliability_observability_design.md.


# --- security / privacy (section 32) -------------------------------------------


def test_module_never_uses_pickle_eval_or_marshal():
    import inspect

    from app.generation import embedding_cache as mod

    source = inspect.getsource(mod)
    assert "pickle" not in source
    assert "marshal" not in source
    assert " eval(" not in source


def test_settings_bounds_are_explicit_and_enforced():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Settings(_env_file=None, query_embedding_cache_ttl_seconds=0)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, query_embedding_cache_ttl_seconds=-1)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, query_embedding_cache_ttl_seconds=604801)


def test_cache_disabled_by_default():
    assert Settings(_env_file=None).query_embedding_cache_enabled is False


def test_default_ttl_is_one_day():
    assert Settings(_env_file=None).query_embedding_cache_ttl_seconds == 86400


# --- live Redis round trip (section 23) -----------------------------------------


@pytestmark_live
def test_live_second_identical_call_hits_without_recomputing():
    from app.core.config import get_settings
    from app.infrastructure.cache import SyncCacheClient

    settings = get_settings().model_copy(
        update={"query_embedding_cache_enabled": True, "query_embedding_cache_ttl_seconds": 30}
    )
    cache = SyncCacheClient(settings)
    calls = []

    def vector_fn(text):
        calls.append(text)
        return [0.1, 0.2, 0.3]

    provider = FakeProvider(
        dimension=3, model="phase13-slice5-live-model", revision="live-rev", vector_fn=vector_fn
    )
    wrapper = CachingQueryEmbedding(provider, settings, cache)
    unique_query = "phase13-slice5-live-query-do-not-reuse"
    key = build_cache_key(
        operation=QUERY_EMBEDDING_OPERATION,
        config_fingerprint=provider.describe(),
        input_fingerprint={"query": unique_query},
        schema_version=settings.cache_schema_version,
    )
    try:
        cache.delete(key)  # start from a known-clean state for this one key

        first = wrapper.embed([unique_query])
        assert len(calls) == 1

        second = wrapper.embed([unique_query])
        assert len(calls) == 1  # no second computation -- served from Redis
        assert np.allclose(first, second)

        ttl = cache._redis.ttl(key)
        assert ttl > 0

        stored = cache.get(key)
        assert stored.status == CacheReadStatus.HIT
        dumped = json.dumps(stored.value)
        assert unique_query not in dumped
        assert "query" not in stored.value
    finally:
        cache.delete(key)
        cache.close()


# --- real request-path verification (section 24) --------------------------------


@pytestmark_orchestration_live
def test_second_identical_orchestrate_request_uses_the_embedding_cache(monkeypatch):
    from app.core.config import get_settings
    from app.generation.runtime import load_embedding
    from app.infrastructure.cache import get_sync_cache_client, reset_sync_cache_client
    from fastapi.testclient import TestClient

    monkeypatch.setenv("QUERY_EMBEDDING_CACHE_ENABLED", "true")
    get_settings.cache_clear()
    reset_sync_cache_client()

    question = "Does Medicare cover hospital beds?"
    try:
        with _capture_app_log() as buffer:
            with TestClient(app) as client:
                response_1 = client.post("/orchestrate", json={"question": question})
                response_2 = client.post("/orchestrate", json={"question": question})

        assert response_1.status_code == 200
        assert response_2.status_code == 200
        body_1, body_2 = response_1.json(), response_2.json()
        assert body_1["route"] == body_2["route"] == "policy"
        assert body_1["status"] == body_2["status"]
        assert body_1.get("answer") == body_2.get("answer")
        assert body_1.get("citations") == body_2.get("citations")

        request_id_1 = response_1.headers["x-request-id"]
        request_id_2 = response_2.headers["x-request-id"]
        assert request_id_1 != request_id_2

        cache_events = _events(buffer, "query_embedding_cache")
        by_request: dict[str, list[dict]] = {}
        for event in cache_events:
            by_request.setdefault(event["request_id"], []).append(event)
        assert any(e["cache_status"] == "miss" for e in by_request.get(request_id_1, []))
        assert any(e["cache_status"] == "hit" for e in by_request.get(request_id_2, []))
    finally:
        settings = get_settings()
        provider = load_embedding(settings.rag_model_cache, settings.rag_embedding_offline)
        key = build_cache_key(
            operation=QUERY_EMBEDDING_OPERATION,
            config_fingerprint=provider.describe(),
            input_fingerprint={"query": question},
            schema_version=settings.cache_schema_version,
        )
        get_sync_cache_client().delete(key)
        get_settings.cache_clear()
        reset_sync_cache_client()


# --- retrieval equivalence (section 25) ------------------------------------------


@pytestmark_orchestration_live
def test_retrieval_chunk_order_identical_disabled_cold_and_warm():
    from app.core.config import get_settings
    from app.generation.runtime import load_embedding, retrieve
    from app.infrastructure.cache import get_sync_cache_client, reset_sync_cache_client

    questions = [
        "Does Medicare cover hospital beds?",
        "What is required for a power wheelchair?",
    ]
    base = get_settings()
    disabled = base.model_copy(update={"query_embedding_cache_enabled": False})
    enabled = base.model_copy(update={"query_embedding_cache_enabled": True})
    provider = load_embedding(base.rag_model_cache, base.rag_embedding_offline)
    keys = [
        build_cache_key(
            operation=QUERY_EMBEDDING_OPERATION,
            config_fingerprint=provider.describe(),
            input_fingerprint={"query": question},
            schema_version=base.cache_schema_version,
        )
        for question in questions
    ]
    reset_sync_cache_client()
    cache = get_sync_cache_client()
    for key in keys:
        cache.delete(key)
    try:
        for question in questions:
            disabled_ids = [h["chunk_id"] for h in retrieve(question, disabled)]
            cold_ids = [h["chunk_id"] for h in retrieve(question, enabled)]
            warm_ids = [h["chunk_id"] for h in retrieve(question, enabled)]
            assert disabled_ids == cold_ids == warm_ids
    finally:
        for key in keys:
            cache.delete(key)
        reset_sync_cache_client()
