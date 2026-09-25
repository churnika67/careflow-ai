"""Phase 13 Slice 5: optional Redis caching for QUERY embedding generation
only -- the first production integration of the Slice 2 cache abstraction
and Slice 3/4 observability foundation.

Scope (deliberately narrow): this module caches the numeric vector produced
by embedding a *query* string for retrieval. It never caches a final RAG
answer, retrieved chunks, BM25/hybrid results, reranker output, a
structured-tool result, or a document/corpus embedding -- see
docs/phase13_reliability_observability_design.md's "Slice 5" section for
why this specific boundary was chosen (query embedding generation is the
one stage every dense-mode production request already exercises,
deterministic for a fixed model/revision/config, and cheap to validate
before use).

Redis is an OPTIONAL PERFORMANCE DEPENDENCY here, matching Slice 2's
standing principle: Redis being unreachable, erroring, or returning a
malformed value must never prevent a query from being answered -- it only
ever falls back to computing the embedding directly against the real
model. A failure in the authoritative embedding computation itself
(the real model call) is never caught or reinterpreted as a cache
failure -- it propagates exactly as it did before this slice existed."""

import logging
import math
from time import perf_counter

import numpy as np

from app.core.config import Settings
from app.infrastructure.cache import CacheReadStatus, SyncCacheClient, build_cache_key
from app.observability.logging import log_event
from app.observability.metrics import (
    record_query_embedding_cache_read,
    record_query_embedding_cache_write,
)

logger = logging.getLogger(__name__)

QUERY_EMBEDDING_OPERATION = "query_embedding"

# Versions the cached VALUE's shape (distinct from Settings.cache_schema_version,
# which versions the KEY namespace via build_cache_key). Bumping this alone
# is enough to invalidate every previously cached payload without touching
# the key format.
QUERY_EMBEDDING_PAYLOAD_SCHEMA_VERSION = "v1"


def _validate_query_embedding_payload(
    payload: object, *, expected_model: object, expected_dimension: object
) -> list[float] | None:
    """Returns the validated embedding as a plain list[float], or None if
    the payload cannot be trusted for any reason -- never raises, since an
    untrusted cached value is exactly the MALFORMED case, not a bug."""
    if not isinstance(payload, dict):
        return None
    if payload.get("schema_version") != QUERY_EMBEDDING_PAYLOAD_SCHEMA_VERSION:
        return None
    if payload.get("model") != expected_model:
        return None
    if payload.get("dimension") != expected_dimension:
        return None
    vector = payload.get("embedding")
    if not isinstance(vector, list) or not vector:
        return None
    if expected_dimension is not None and len(vector) != expected_dimension:
        return None
    values: list[float] = []
    for item in vector:
        # bool is a subclass of int in Python -- excluded explicitly so a
        # stray `true`/`false` in the JSON array is never coerced into 1.0/0.0.
        if isinstance(item, bool) or not isinstance(item, int | float):
            return None
        value = float(item)
        if not math.isfinite(value):
            return None
        values.append(value)
    return values


class CachingQueryEmbedding:
    """Wraps a real EmbeddingProvider (ingestion.embeddings.providers.
    SentenceTransformerEmbedding, via generation/runtime.py::load_embedding())
    with an optional Redis-backed cache for query embeddings.

    Deliberately a wrapper around the provider, not a change to
    SentenceTransformerEmbedding itself -- the model implementation stays
    free of Redis-specific code, and this class is used only where
    generation/runtime.py::retrieve() opts into it (see there for how
    "enabled" is decided per call, not baked into the model singleton).

    describe() is proxied unchanged: NCDIndex.search() compares a
    provider's describe() against what is recorded on each indexed point,
    and this wrapper must remain invisible to that check.

    embed(texts) treats each text independently: a cache hit for one text
    and a miss for another (were this ever called with more than one text
    -- in practice the one real call site, NCDIndex.search(), always calls
    it with exactly one query) does not block or fail the other."""

    def __init__(self, provider, settings: Settings, cache_client: SyncCacheClient):
        self._provider = provider
        self._settings = settings
        self._cache = cache_client
        self.tokenizer = provider.tokenizer

    def describe(self) -> dict:
        return self._provider.describe()

    def embed(self, texts: list[str]) -> np.ndarray:
        described = self._provider.describe()
        expected_model = described.get("model")
        expected_dimension = described.get("dimension")
        vectors: list[np.ndarray] = []
        for text in texts:
            started = perf_counter()
            key = build_cache_key(
                operation=QUERY_EMBEDDING_OPERATION,
                config_fingerprint=described,
                input_fingerprint={"query": text},
                schema_version=self._settings.cache_schema_version,
            )
            read = self._cache.get(key)
            cache_status = read.status.value
            vector: list[float] | None = None
            if read.status == CacheReadStatus.HIT:
                vector = _validate_query_embedding_payload(
                    read.value, expected_model=expected_model, expected_dimension=expected_dimension
                )
                if vector is None:
                    # Valid JSON, wrong shape/content -- the same recompute
                    # + best-effort-replace treatment as Slice 2's own
                    # MALFORMED (invalid JSON) status.
                    cache_status = "malformed"

            write_status = None
            if vector is not None:
                fresh = np.array(vector, dtype=np.float32)
            else:
                fresh = self._provider.embed([text])[0]
                # Best-effort write only on MISS or MALFORMED (a value worth
                # having, or worth replacing). UNAVAILABLE/READ_ERROR already
                # demonstrated Redis is not answering -- a second round-trip
                # there would only add latency for no benefit, so no write
                # is attempted in that case; the request proceeds normally.
                if read.status in (CacheReadStatus.MISS, CacheReadStatus.MALFORMED) or (
                    cache_status == "malformed"
                ):
                    payload = {
                        "schema_version": QUERY_EMBEDDING_PAYLOAD_SCHEMA_VERSION,
                        "model": expected_model,
                        "revision": described.get("revision"),
                        "dimension": expected_dimension,
                        "embedding": [float(x) for x in fresh.tolist()],
                    }
                    write = self._cache.set(
                        key, payload, ttl_seconds=self._settings.query_embedding_cache_ttl_seconds
                    )
                    write_status = write.status.value
            vectors.append(fresh)

            duration_ms = (perf_counter() - started) * 1000
            log_event(
                logger,
                "query_embedding_cache",
                cache_status=cache_status,
                cache_write_status=write_status,
                operation=QUERY_EMBEDDING_OPERATION,
                duration_ms=duration_ms,
                embedding_dimension=expected_dimension,
            )
            # Phase 13 Slice 6: same bounded labels as the log event above
            # (cache_status/write_status are both fixed, small enums --
            # never the query, key, or vector).
            record_query_embedding_cache_read(cache_status=cache_status, duration_ms=duration_ms)
            if write_status is not None:
                record_query_embedding_cache_write(write_status=write_status)
        return np.array(vectors, dtype=np.float32)
