"""Phase 13 Slice 2: bounded Redis client abstraction + cache failure
semantics.

Infrastructure only. Nothing in this module is wired into any request
path yet -- no RAG stage, structured tool, or answer is cached. This slice
builds the contract every future cache candidate will share.

Redis is an OPTIONAL PERFORMANCE DEPENDENCY for caching: Redis being slow,
unreachable, or returning malformed data must never fail an otherwise-valid
request. The authoritative source of truth remains Qdrant / Postgres /
deterministic computation / the generation provider -- never Redis, and
Redis must never become the sole copy of application data. This is a
deliberate, documented scope boundary (see
docs/phase13_reliability_observability_design.md) and is distinct from
/health's current required-dependency treatment of Redis, which this
module does not change.

Every public read/write method returns a typed result instead of raising
for an ordinary operational failure (unreachable Redis, a Redis-side
error, or a malformed cached payload) -- ambiguous ``None`` is never used
to mean "no value AND no error". The three classes of failure a caller may
need to react to differently are kept distinct:

    connection/unavailable  -- Redis could not be reached or timed out
    other Redis error       -- Redis was reached but rejected the operation
    malformed cached value  -- Redis returned data this process cannot parse

A caller-side contract violation (a non-positive TTL, a non-JSON-
serializable value) is a programming error, not an operational cache
failure, and is raised, not returned as a status."""

import json
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from typing import Any

from redis import Redis as SyncRedis
from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import RedisError
from redis.exceptions import TimeoutError as RedisTimeoutError

from app.core.config import Settings, get_settings
from ingestion.models import digest

CACHE_KEY_NAMESPACE = "careflow"


class CacheReadStatus(StrEnum):
    HIT = "hit"
    MISS = "miss"
    UNAVAILABLE = "unavailable"
    READ_ERROR = "read_error"
    MALFORMED = "malformed"


class CacheWriteStatus(StrEnum):
    WRITTEN = "written"
    UNAVAILABLE = "unavailable"
    WRITE_ERROR = "write_error"


@dataclass(frozen=True)
class CacheReadResult:
    status: CacheReadStatus
    value: Any = None


@dataclass(frozen=True)
class CacheWriteResult:
    status: CacheWriteStatus


class InvalidCacheTTLError(ValueError):
    """Raised when a caller supplies a non-positive TTL. No cache entry may
    ever be written without an explicit, positive expiry -- there is no
    permanent-by-accidental-omission path through this module."""


def build_cache_key(
    *,
    operation: str,
    config_fingerprint: dict,
    input_fingerprint: dict,
    schema_version: str,
) -> str:
    """Deterministic, namespaced cache key:

        careflow:<schema_version>:<operation>:<config_digest>:<input_digest>

    Raw query text, record contents, or any other potentially sensitive or
    high-cardinality input is never placed in the key directly -- only a
    stable digest of it. Reuses ingestion.models.digest() (the same
    canonical-JSON -- sort_keys, compact separators -- SHA-256 convention
    already used for content addressing throughout Phase 1-12) rather than
    inventing a second, incompatible hashing scheme. Dict key ordering does
    not affect the result: digest() sorts keys before hashing.

    `config_fingerprint` should capture everything that changes what a
    cached value MEANS (e.g. retrieval_mode, embedding model+revision,
    corpus fingerprint, rerank settings -- see
    docs/phase13_reliability_observability_design.md's "Cache key
    requirements"). `input_fingerprint` captures the request-specific input
    (e.g. the normalized query, or a tool's validated arguments). Neither is
    required to be flat; both are canonically digested as-is."""
    if not operation:
        raise ValueError("operation must be a non-empty string")
    if not schema_version:
        raise ValueError("schema_version must be a non-empty string")
    config_digest = digest(config_fingerprint)
    input_digest = digest(input_fingerprint)
    return f"{CACHE_KEY_NAMESPACE}:{schema_version}:{operation}:{config_digest}:{input_digest}"


class CacheClient:
    """One process-level reusable Redis client wrapper.

    redis-py's async Redis.from_url() already returns a client backed by
    its own internal connection pool -- verified directly against the
    installed redis==6.4.0 -- and is safe to share across concurrent
    coroutines within one event loop. This class does not build a second,
    redundant pool on top of it; it constructs exactly one such client per
    CacheClient instance and reuses it for every operation. One instance is
    created per process via get_cache_client() below (the same @lru_cache
    singleton pattern already used by get_settings()/load_embedding()/
    load_reranker() elsewhere in this codebase) -- never a fresh client per
    cache call.

    No automatic multi-attempt retry loop: one bounded operation, governed
    by the configured connect/socket timeouts, is enough for Slice 2. A
    failed operation is classified and returned; retrying, if ever wanted,
    is a caller-level decision for a later slice, not built in here."""

    def __init__(
        self,
        settings: Settings,
        *,
        connect_timeout_seconds: float | None = None,
        socket_timeout_seconds: float | None = None,
    ) -> None:
        self._redis = Redis.from_url(
            settings.redis_url.get_secret_value(),
            socket_connect_timeout=connect_timeout_seconds
            if connect_timeout_seconds is not None
            else settings.cache_connect_timeout_seconds,
            socket_timeout=socket_timeout_seconds
            if socket_timeout_seconds is not None
            else settings.cache_socket_timeout_seconds,
        )

    async def get(self, key: str) -> CacheReadResult:
        try:
            raw = await self._redis.get(key)
        except (RedisConnectionError, RedisTimeoutError):
            return CacheReadResult(CacheReadStatus.UNAVAILABLE)
        except RedisError:
            return CacheReadResult(CacheReadStatus.READ_ERROR)
        if raw is None:
            return CacheReadResult(CacheReadStatus.MISS)
        try:
            value = json.loads(raw)
        except (ValueError, TypeError):
            # Never crash the request, and never silently delete the
            # malformed value here -- that is a separate, deliberate
            # decision a future slice may make, not an automatic side
            # effect of a read.
            return CacheReadResult(CacheReadStatus.MALFORMED)
        return CacheReadResult(CacheReadStatus.HIT, value)

    async def set(self, key: str, value: Any, *, ttl_seconds: int) -> CacheWriteResult:
        if ttl_seconds <= 0:
            raise InvalidCacheTTLError(f"ttl_seconds must be positive, got {ttl_seconds}")
        # JSON-only serialization -- never pickle/eval/marshal. A
        # non-serializable value is a caller programming error, raised
        # immediately, not silently coerced or swallowed as a write failure.
        payload = json.dumps(value, sort_keys=True, ensure_ascii=False)
        try:
            await self._redis.set(key, payload, ex=ttl_seconds)
        except (RedisConnectionError, RedisTimeoutError):
            return CacheWriteResult(CacheWriteStatus.UNAVAILABLE)
        except RedisError:
            return CacheWriteResult(CacheWriteStatus.WRITE_ERROR)
        return CacheWriteResult(CacheWriteStatus.WRITTEN)

    async def delete(self, key: str) -> CacheWriteResult:
        try:
            await self._redis.delete(key)
        except (RedisConnectionError, RedisTimeoutError):
            return CacheWriteResult(CacheWriteStatus.UNAVAILABLE)
        except RedisError:
            return CacheWriteResult(CacheWriteStatus.WRITE_ERROR)
        return CacheWriteResult(CacheWriteStatus.WRITTEN)

    async def aclose(self) -> None:
        await self._redis.aclose()


@lru_cache
def get_cache_client() -> CacheClient:
    return CacheClient(get_settings())


def reset_cache_client() -> None:
    """Test-only hook, matching get_settings.cache_clear()'s existing
    convention elsewhere in this codebase: clears the process-level
    singleton so a fresh client (or a fake/mock) is constructed on next
    use, instead of reusing whatever get_cache_client() built earlier."""
    get_cache_client.cache_clear()


class SyncCacheClient:
    """A synchronous counterpart to CacheClient, sharing its exact result
    types, key format, and failure classification.

    Why this exists (Phase 13 Slice 5): the one call site that first needs
    caching -- query embedding generation, reached from
    generation/runtime.py::retrieve() through the fully synchronous
    NCDIndex.search() -- may run inside a LangGraph-offloaded worker thread
    with no ambient asyncio event loop (the same threading characteristic
    already documented for reranking/service.py's logging in Slice 3).
    Driving CacheClient's `redis.asyncio.Redis` from there would require an
    `asyncio.run()` per call, and a redis-py async client's connection pool
    is bound to the event loop active when it first connects -- reusing one
    process-level async client across many independently-created event
    loops is a known source of "Future attached to a different loop"
    failures. Rather than risk that fragility, this class uses redis-py's
    plain synchronous `Redis` client, which has no such constraint. It is
    deliberately *not* a general replacement for CacheClient -- any future
    cache candidate reached from genuinely async code should keep using the
    async client."""

    def __init__(
        self,
        settings: Settings,
        *,
        connect_timeout_seconds: float | None = None,
        socket_timeout_seconds: float | None = None,
    ) -> None:
        self._redis = SyncRedis.from_url(
            settings.redis_url.get_secret_value(),
            socket_connect_timeout=connect_timeout_seconds
            if connect_timeout_seconds is not None
            else settings.cache_connect_timeout_seconds,
            socket_timeout=socket_timeout_seconds
            if socket_timeout_seconds is not None
            else settings.cache_socket_timeout_seconds,
        )

    def get(self, key: str) -> CacheReadResult:
        try:
            raw = self._redis.get(key)
        except (RedisConnectionError, RedisTimeoutError):
            return CacheReadResult(CacheReadStatus.UNAVAILABLE)
        except RedisError:
            return CacheReadResult(CacheReadStatus.READ_ERROR)
        if raw is None:
            return CacheReadResult(CacheReadStatus.MISS)
        try:
            value = json.loads(raw)
        except (ValueError, TypeError):
            return CacheReadResult(CacheReadStatus.MALFORMED)
        return CacheReadResult(CacheReadStatus.HIT, value)

    def set(self, key: str, value: Any, *, ttl_seconds: int) -> CacheWriteResult:
        if ttl_seconds <= 0:
            raise InvalidCacheTTLError(f"ttl_seconds must be positive, got {ttl_seconds}")
        payload = json.dumps(value, sort_keys=True, ensure_ascii=False)
        try:
            self._redis.set(key, payload, ex=ttl_seconds)
        except (RedisConnectionError, RedisTimeoutError):
            return CacheWriteResult(CacheWriteStatus.UNAVAILABLE)
        except RedisError:
            return CacheWriteResult(CacheWriteStatus.WRITE_ERROR)
        return CacheWriteResult(CacheWriteStatus.WRITTEN)

    def delete(self, key: str) -> CacheWriteResult:
        try:
            self._redis.delete(key)
        except (RedisConnectionError, RedisTimeoutError):
            return CacheWriteResult(CacheWriteStatus.UNAVAILABLE)
        except RedisError:
            return CacheWriteResult(CacheWriteStatus.WRITE_ERROR)
        return CacheWriteResult(CacheWriteStatus.WRITTEN)

    def close(self) -> None:
        self._redis.close()


@lru_cache
def get_sync_cache_client() -> SyncCacheClient:
    return SyncCacheClient(get_settings())


def reset_sync_cache_client() -> None:
    """Test-only hook, matching reset_cache_client()'s convention."""
    get_sync_cache_client.cache_clear()
