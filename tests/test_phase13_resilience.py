"""Phase 13 Slice 7: final failure-injection / resilience checkpoint.

Targets gaps the per-slice test files do not already cover -- this file
does not re-prove keying, HIT/MISS/MALFORMED status classification, or the
liveness/readiness contract; those already have dedicated coverage in
tests/test_query_embedding_cache.py, tests/test_infrastructure_cache.py,
and tests/test_liveness_readiness.py. This file specifically closes the
Slice 7 directive's called-out risk: that caching could mask or
misclassify an authoritative embedding-computation failure, and a
handful of cross-cutting concurrency/privacy checks spanning multiple
Phase 13 components at once."""

import threading

import numpy as np
import pytest
from app.core.config import Settings
from app.generation.embedding_cache import CachingQueryEmbedding
from app.infrastructure.cache import (
    CacheReadStatus,
)
from app.observability.logging import get_request_id, request_id_context

from tests.test_query_embedding_cache import FakeProvider, RecordingCache


class RaisingProvider(FakeProvider):
    def __init__(self, exc: Exception, **kwargs):
        super().__init__(**kwargs)
        self._exc = exc

    def embed(self, texts):
        self.calls.append(list(texts))
        raise self._exc


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, query_embedding_cache_enabled=True, **overrides)


# --- embedding failure is never masked or misclassified (section 9) -----------


def test_embedding_failure_propagates_unmodified_on_cache_miss():
    provider = RaisingProvider(RuntimeError("embedding model failure"))
    cache = RecordingCache()  # empty -> MISS
    wrapper = CachingQueryEmbedding(provider, _settings(), cache)
    with pytest.raises(RuntimeError, match="embedding model failure"):
        wrapper.embed(["hospital bed"])
    assert len(provider.calls) == 1
    # Never written -- there was no vector to write.
    assert cache.set_calls == []


def test_embedding_failure_propagates_when_cache_unavailable_not_misclassified():
    # This is the exact risk Slice 7 calls out: a Redis outage AND an
    # embedding-model failure happening together must surface as the real
    # RuntimeError, never silently absorbed as "just a cache miss" or any
    # cache-shaped result.
    provider = RaisingProvider(RuntimeError("embedding model failure"))
    cache = RecordingCache(read_status=CacheReadStatus.UNAVAILABLE)
    wrapper = CachingQueryEmbedding(provider, _settings(), cache)
    with pytest.raises(RuntimeError, match="embedding model failure"):
        wrapper.embed(["hospital bed"])
    assert len(provider.calls) == 1
    assert cache.set_calls == []  # UNAVAILABLE never attempts a write regardless


def test_embedding_failure_propagates_when_cache_read_error_not_misclassified():
    provider = RaisingProvider(RuntimeError("embedding model failure"))
    cache = RecordingCache(read_status=CacheReadStatus.READ_ERROR)
    wrapper = CachingQueryEmbedding(provider, _settings(), cache)
    with pytest.raises(RuntimeError, match="embedding model failure"):
        wrapper.embed(["hospital bed"])


def test_cache_hit_never_invokes_a_provider_that_would_raise():
    from app.generation.embedding_cache import (
        QUERY_EMBEDDING_OPERATION,
        QUERY_EMBEDDING_PAYLOAD_SCHEMA_VERSION,
    )
    from app.infrastructure.cache import build_cache_key

    provider = RaisingProvider(RuntimeError("must never be called"))
    settings = _settings()
    key = build_cache_key(
        operation=QUERY_EMBEDDING_OPERATION,
        config_fingerprint=provider.describe(),
        input_fingerprint={"query": "hospital bed"},
        schema_version=settings.cache_schema_version,
    )
    payload = {
        "schema_version": QUERY_EMBEDDING_PAYLOAD_SCHEMA_VERSION,
        "model": provider.model,
        "revision": provider.revision,
        "dimension": provider.dimension,
        "embedding": [1.0, 2.0, 3.0],
    }
    cache = RecordingCache(seed={key: payload})
    wrapper = CachingQueryEmbedding(provider, settings, cache)
    result = wrapper.embed(["hospital bed"])  # would raise if the provider were ever invoked
    assert np.allclose(result[0], [1.0, 2.0, 3.0])
    assert provider.calls == []


def test_retrieve_surfaces_embedding_failure_as_existing_generation_error(monkeypatch):
    # Locks in, at the pure-test level, exactly what was also verified live
    # against a real invalid-Qdrant-endpoint process in this slice: caching
    # (enabled or not) must never introduce a new failure mode for the
    # retrieval path -- an authoritative computation failure still becomes
    # the same pre-Phase-13 GenerationError("retrieval_unavailable", 503).
    from app.generation.providers import GenerationError
    from app.generation.runtime import retrieve

    class Client:
        def __init__(self, **kwargs):
            pass

        def close(self):
            pass

    class Retrieval:
        def __init__(self, *args):
            pass

        def search(self, *args, **kwargs):
            raise RuntimeError("embedding model failure")

    monkeypatch.setattr("qdrant_client.QdrantClient", Client)
    monkeypatch.setattr("app.retrieval.search.Retriever", Retrieval)
    monkeypatch.setattr("app.generation.runtime.load_embedding", lambda *args: FakeProvider())

    settings = Settings(_env_file=None, query_embedding_cache_enabled=True, rerank_enabled=False)
    with pytest.raises(GenerationError) as excinfo:
        retrieve("hospital bed", settings)
    assert excinfo.value.code == "retrieval_unavailable"
    assert excinfo.value.status_code == 503


# --- malformed cache data never becomes authoritative (section 10, reconfirmed) -


def test_malformed_cache_value_never_used_and_request_still_succeeds():
    provider = FakeProvider()
    cache = RecordingCache(read_status=CacheReadStatus.MALFORMED)
    wrapper = CachingQueryEmbedding(provider, _settings(), cache)
    result = wrapper.embed(["hospital bed"])  # must not crash, must compute fresh
    assert len(provider.calls) == 1
    assert result.shape == (1, provider.dimension)


# --- concurrency (section 13) ---------------------------------------------------


def test_concurrent_misses_never_produce_a_corrupted_cached_payload():
    provider = FakeProvider(dimension=3)
    lock = threading.Lock()

    class LockedCache(RecordingCache):
        def get(self, key):
            with lock:
                return super().get(key)

        def set(self, key, value, *, ttl_seconds):
            with lock:
                return super().set(key, value, ttl_seconds=ttl_seconds)

    locked_cache = LockedCache()
    settings = _settings()
    errors: list[Exception] = []

    def worker():
        try:
            CachingQueryEmbedding(provider, settings, locked_cache).embed(["hospital bed"])
        except Exception as exc:  # pragma: no cover - captured for assertion below
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    # Regardless of how many threads independently computed and wrote, the
    # stored payload is exactly one well-formed, valid entry -- never a
    # torn/partial write, never more than one key.
    assert len(locked_cache._store) == 1
    stored = next(iter(locked_cache._store.values()))
    assert stored["schema_version"] and isinstance(stored["embedding"], list)
    assert len(stored["embedding"]) == 3
    assert all(isinstance(v, int | float) for v in stored["embedding"])


# --- request-ID privacy across cache key/payload (section 14) -------------------


def test_request_id_never_appears_in_cache_key_or_stored_payload():
    provider = FakeProvider()
    cache = RecordingCache()
    settings = _settings()
    distinctive_request_id = "11111111-2222-3333-4444-555555555555"
    with request_id_context(distinctive_request_id):
        assert get_request_id() == distinctive_request_id
        CachingQueryEmbedding(provider, settings, cache).embed(["hospital bed"])
    assert distinctive_request_id not in cache.get_calls[0]
    written_key, written_value, _ttl = cache.set_calls[0]
    assert distinctive_request_id not in written_key
    assert distinctive_request_id not in str(written_value)


# --- metrics/logging cannot become a correctness dependency (sections 11-12) ----


def test_metrics_recording_never_raises_for_normal_bounded_inputs():
    from app.observability.metrics import (
        record_http_request,
        record_query_embedding_cache_read,
        record_query_embedding_cache_write,
    )

    # No exception path exists for well-typed, bounded inputs -- these are
    # plain dict/list mutations under a lock, nothing that can fail for
    # valid arguments.
    record_http_request(
        method="GET", route="/health", status_class="2xx", duration_ms=1.0, error=False
    )
    record_query_embedding_cache_read(cache_status="hit", duration_ms=1.0)
    record_query_embedding_cache_write(write_status="written")


def test_log_event_with_forbidden_and_unsupported_fields_still_succeeds(caplog):
    # Cross-references the already-dedicated coverage in
    # tests/test_observability_logging.py (forbidden-field redaction,
    # unsupported-type placeholder) by proving the two combine safely in
    # one call, exactly as a real cache/http event might.
    import logging as std_logging

    from app.observability.logging import log_event

    class Unsupported:
        def __str__(self):
            return "SHOULD NOT LEAK"

    logger = std_logging.getLogger("app.test_phase13_resilience")
    log_event(
        logger,
        "resilience_probe",
        level=std_logging.INFO,
        request_id="rid",
        query="must be redacted",
        thing=Unsupported(),
    )  # must not raise
