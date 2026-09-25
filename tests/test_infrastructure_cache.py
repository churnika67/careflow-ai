import inspect
import os
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.core.config import Settings
from app.infrastructure.cache import (
    CacheClient,
    CacheReadResult,
    CacheReadStatus,
    CacheWriteResult,
    CacheWriteStatus,
    InvalidCacheTTLError,
    SyncCacheClient,
    build_cache_key,
    get_cache_client,
    get_sync_cache_client,
    reset_cache_client,
    reset_sync_cache_client,
)
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import ResponseError
from redis.exceptions import TimeoutError as RedisTimeoutError

pytestmark_live = pytest.mark.skipif(
    os.environ.get("CAREFLOW_CACHE_INTEGRATION") != "1",
    reason="Set CAREFLOW_CACHE_INTEGRATION=1 with Compose running (Redis) to exercise the "
    "real Redis client contract",
)


@pytest.fixture(autouse=True)
def _reset_singleton():
    reset_cache_client()
    reset_sync_cache_client()
    yield
    reset_cache_client()
    reset_sync_cache_client()


def _client_with_fake_redis() -> tuple[CacheClient, AsyncMock]:
    client = CacheClient(Settings(_env_file=None))
    fake = AsyncMock()
    client._redis = fake
    return client, fake


def _sync_client_with_fake_redis() -> tuple[SyncCacheClient, MagicMock]:
    client = SyncCacheClient(Settings(_env_file=None))
    fake = MagicMock()
    client._redis = fake
    return client, fake


# --- cache key determinism ---------------------------------------------------


def test_same_structured_input_produces_same_key():
    a = build_cache_key(
        operation="policy",
        config_fingerprint={"mode": "hybrid"},
        input_fingerprint={"q": "x"},
        schema_version="v1",
    )
    b = build_cache_key(
        operation="policy",
        config_fingerprint={"mode": "hybrid"},
        input_fingerprint={"q": "x"},
        schema_version="v1",
    )
    assert a == b


def test_dict_key_ordering_does_not_change_key():
    a = build_cache_key(
        operation="policy",
        config_fingerprint={"a": 1, "b": 2},
        input_fingerprint={"q": "x"},
        schema_version="v1",
    )
    b = build_cache_key(
        operation="policy",
        config_fingerprint={"b": 2, "a": 1},
        input_fingerprint={"q": "x"},
        schema_version="v1",
    )
    assert a == b


def test_different_retrieval_configuration_produces_different_key():
    a = build_cache_key(
        operation="policy",
        config_fingerprint={"mode": "dense"},
        input_fingerprint={"q": "x"},
        schema_version="v1",
    )
    b = build_cache_key(
        operation="policy",
        config_fingerprint={"mode": "hybrid"},
        input_fingerprint={"q": "x"},
        schema_version="v1",
    )
    assert a != b


def test_different_input_produces_different_key():
    a = build_cache_key(
        operation="policy",
        config_fingerprint={"mode": "dense"},
        input_fingerprint={"q": "x"},
        schema_version="v1",
    )
    b = build_cache_key(
        operation="policy",
        config_fingerprint={"mode": "dense"},
        input_fingerprint={"q": "y"},
        schema_version="v1",
    )
    assert a != b


def test_different_schema_version_produces_different_key():
    a = build_cache_key(
        operation="policy",
        config_fingerprint={"mode": "dense"},
        input_fingerprint={"q": "x"},
        schema_version="v1",
    )
    b = build_cache_key(
        operation="policy",
        config_fingerprint={"mode": "dense"},
        input_fingerprint={"q": "x"},
        schema_version="v2",
    )
    assert a != b
    assert ":v1:" in a
    assert ":v2:" in b


def test_raw_query_text_not_present_in_key():
    key = build_cache_key(
        operation="policy",
        config_fingerprint={"mode": "dense"},
        input_fingerprint={"query": "does medicare cover a wheelchair for grandma jones"},
        schema_version="v1",
    )
    assert "grandma" not in key
    assert "wheelchair" not in key
    assert "medicare" not in key.lower().replace(
        "careflow", ""
    )  # 'medicare' shares no substring with 'careflow'


def test_key_does_not_use_python_hash():
    # Python's hash() is process-randomized for str/bytes -- confirmed the
    # implementation never calls it by construction: digest() is SHA-256 over
    # canonical JSON, not hash().
    source = inspect.getsource(build_cache_key)
    assert "hash(" not in source


def test_key_format_is_namespaced_and_versioned():
    key = build_cache_key(
        operation="reranker", config_fingerprint={}, input_fingerprint={}, schema_version="v1"
    )
    parts = key.split(":")
    assert parts[0] == "careflow"
    assert parts[1] == "v1"
    assert parts[2] == "reranker"
    assert len(parts) == 5  # namespace, version, operation, config_digest, input_digest


def test_empty_operation_rejected():
    with pytest.raises(ValueError):
        build_cache_key(
            operation="", config_fingerprint={}, input_fingerprint={}, schema_version="v1"
        )


# --- read statuses (pure, mocked redis client) -------------------------------


async def test_read_hit_returns_deserialized_value():
    client, fake = _client_with_fake_redis()
    fake.get.return_value = b'{"a": 1, "b": [1, 2, 3]}'
    result = await client.get("some-key")
    assert result.status == CacheReadStatus.HIT
    assert result.value == {"a": 1, "b": [1, 2, 3]}


async def test_read_miss_when_key_absent():
    client, fake = _client_with_fake_redis()
    fake.get.return_value = None
    result = await client.get("missing-key")
    assert result.status == CacheReadStatus.MISS
    assert result.value is None


async def test_read_unavailable_on_connection_error():
    client, fake = _client_with_fake_redis()
    fake.get.side_effect = RedisConnectionError("could not connect")
    result = await client.get("some-key")
    assert result.status == CacheReadStatus.UNAVAILABLE


async def test_read_unavailable_on_timeout_error():
    client, fake = _client_with_fake_redis()
    fake.get.side_effect = RedisTimeoutError("timed out")
    result = await client.get("some-key")
    assert result.status == CacheReadStatus.UNAVAILABLE


async def test_read_error_on_other_redis_error():
    client, fake = _client_with_fake_redis()
    fake.get.side_effect = ResponseError("WRONGTYPE")
    result = await client.get("some-key")
    assert result.status == CacheReadStatus.READ_ERROR


async def test_read_malformed_on_invalid_json():
    client, fake = _client_with_fake_redis()
    fake.get.return_value = b"not-json{{{"
    result = await client.get("some-key")
    assert result.status == CacheReadStatus.MALFORMED
    assert result.value is None


# --- write statuses (pure, mocked redis client) ------------------------------


async def test_write_written_on_success():
    client, fake = _client_with_fake_redis()
    result = await client.set("some-key", {"a": 1}, ttl_seconds=60)
    assert result.status == CacheWriteStatus.WRITTEN
    fake.set.assert_awaited_once()


async def test_write_unavailable_on_connection_error():
    client, fake = _client_with_fake_redis()
    fake.set.side_effect = RedisConnectionError("could not connect")
    result = await client.set("some-key", {"a": 1}, ttl_seconds=60)
    assert result.status == CacheWriteStatus.UNAVAILABLE


async def test_write_error_on_other_redis_error():
    client, fake = _client_with_fake_redis()
    fake.set.side_effect = ResponseError("OOM")
    result = await client.set("some-key", {"a": 1}, ttl_seconds=60)
    assert result.status == CacheWriteStatus.WRITE_ERROR


async def test_valid_ttl_forwarded_to_redis():
    client, fake = _client_with_fake_redis()
    await client.set("some-key", {"a": 1}, ttl_seconds=42)
    _, kwargs = fake.set.call_args
    assert kwargs["ex"] == 42


@pytest.mark.parametrize("ttl", [0, -1, -100])
async def test_invalid_ttl_rejected_without_touching_redis(ttl):
    client, fake = _client_with_fake_redis()
    with pytest.raises(InvalidCacheTTLError):
        await client.set("some-key", {"a": 1}, ttl_seconds=ttl)
    fake.set.assert_not_awaited()


async def test_non_serializable_value_raises_not_written_as_error_status():
    client, fake = _client_with_fake_redis()
    with pytest.raises((TypeError, ValueError)):
        await client.set("some-key", object(), ttl_seconds=60)
    fake.set.assert_not_awaited()


# --- serialization round-trip -------------------------------------------------


async def test_serialization_round_trip_through_the_same_client():
    client, fake = _client_with_fake_redis()
    captured = {}

    async def fake_set(key, payload, ex=None):
        captured["payload"] = payload

    fake.set.side_effect = fake_set
    value = {"nested": {"a": [1, 2, {"b": "c"}]}, "n": 3.5}
    await client.set("k", value, ttl_seconds=60)

    fake.get.return_value = (
        captured["payload"].encode()
        if isinstance(captured["payload"], str)
        else captured["payload"]
    )
    result = await client.get("k")
    assert result.status == CacheReadStatus.HIT
    assert result.value == value


# --- client/factory reuse -----------------------------------------------------


def test_get_cache_client_returns_the_same_instance():
    a = get_cache_client()
    b = get_cache_client()
    assert a is b


def test_reset_cache_client_forces_a_new_instance():
    a = get_cache_client()
    reset_cache_client()
    b = get_cache_client()
    assert a is not b


# --- security / privacy structural checks ------------------------------------


def test_credentials_never_appear_in_returned_error_metadata():
    read_fields = {f for f in CacheReadResult.__dataclass_fields__}
    write_fields = {f for f in CacheWriteResult.__dataclass_fields__}
    # Only status (+ value, for reads) exist -- no message/error/url field
    # exists at all for an exception string or connection string to leak into.
    assert read_fields == {"status", "value"}
    assert write_fields == {"status"}


async def test_credentials_do_not_leak_even_when_the_exception_message_contains_them():
    client, fake = _client_with_fake_redis()
    fake.get.side_effect = RedisConnectionError("redis://user:s3cr3t@evil-host:6379")
    result = await client.get("k")
    assert "s3cr3t" not in str(result)
    assert "s3cr3t" not in repr(result)


def test_module_never_uses_pickle_eval_or_marshal():
    # Checks actual usage (import/call), not the word appearing in a comment
    # explaining that pickle is deliberately NOT used.
    import app.infrastructure.cache as mod

    source = inspect.getsource(mod)
    assert "import pickle" not in source
    assert "pickle.loads" not in source
    assert "pickle.dumps" not in source
    assert "import marshal" not in source
    assert "marshal.loads" not in source
    assert "marshal.dumps" not in source
    assert " eval(" not in source


def test_module_never_calls_flushdb_or_flushall():
    import app.infrastructure.cache as mod

    source = inspect.getsource(mod)
    assert "flushdb" not in source.lower()
    assert "flushall" not in source.lower()


def test_module_does_not_log_values_or_keys():
    # Slice 2 deliberately keeps this module logging-free -- typed results
    # are returned so a future observability layer decides what to emit,
    # rather than this module logging keys/values/queries itself.
    import app.infrastructure.cache as mod

    source = inspect.getsource(mod)
    assert "logger." not in source
    assert "logging.getLogger" not in source


def test_settings_do_not_expose_redis_credentials_in_repr_or_dump():
    settings = Settings(_env_file=None, redis_url="redis://user:hunter2@host:6379/0")
    assert "hunter2" not in repr(settings)
    assert "hunter2" not in settings.model_dump_json()


# --- config timeouts are bounded and explicit --------------------------------


@pytest.mark.parametrize("value", [0, -1, 5.01, 100])
def test_invalid_cache_timeouts_rejected(value):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Settings(_env_file=None, cache_connect_timeout_seconds=value)


def test_cache_schema_version_defaults_to_v1():
    settings = Settings(_env_file=None)
    assert settings.cache_schema_version == "v1"


# --- SyncCacheClient: same contract, synchronous transport (Phase 13 Slice 5) -

# Built for the one call site (query embedding generation) that runs inside a
# fully synchronous call stack with no ambient asyncio event loop -- see
# backend/app/generation/embedding_cache.py's module docstring for why a
# second, synchronous client exists alongside CacheClient rather than
# reusing it there.


def test_sync_read_hit_returns_deserialized_value():
    client, fake = _sync_client_with_fake_redis()
    fake.get.return_value = b'{"a": 1, "b": [1, 2, 3]}'
    result = client.get("some-key")
    assert result.status == CacheReadStatus.HIT
    assert result.value == {"a": 1, "b": [1, 2, 3]}


def test_sync_read_miss_when_key_absent():
    client, fake = _sync_client_with_fake_redis()
    fake.get.return_value = None
    result = client.get("missing-key")
    assert result.status == CacheReadStatus.MISS


def test_sync_read_unavailable_on_connection_error():
    client, fake = _sync_client_with_fake_redis()
    fake.get.side_effect = RedisConnectionError("could not connect")
    result = client.get("some-key")
    assert result.status == CacheReadStatus.UNAVAILABLE


def test_sync_read_unavailable_on_timeout_error():
    client, fake = _sync_client_with_fake_redis()
    fake.get.side_effect = RedisTimeoutError("timed out")
    result = client.get("some-key")
    assert result.status == CacheReadStatus.UNAVAILABLE


def test_sync_read_error_on_other_redis_error():
    client, fake = _sync_client_with_fake_redis()
    fake.get.side_effect = ResponseError("WRONGTYPE")
    result = client.get("some-key")
    assert result.status == CacheReadStatus.READ_ERROR


def test_sync_read_malformed_on_invalid_json():
    client, fake = _sync_client_with_fake_redis()
    fake.get.return_value = b"not-json{{{"
    result = client.get("some-key")
    assert result.status == CacheReadStatus.MALFORMED


def test_sync_write_written_on_success():
    client, fake = _sync_client_with_fake_redis()
    result = client.set("some-key", {"a": 1}, ttl_seconds=60)
    assert result.status == CacheWriteStatus.WRITTEN
    fake.set.assert_called_once()


def test_sync_write_unavailable_on_connection_error():
    client, fake = _sync_client_with_fake_redis()
    fake.set.side_effect = RedisConnectionError("could not connect")
    result = client.set("some-key", {"a": 1}, ttl_seconds=60)
    assert result.status == CacheWriteStatus.UNAVAILABLE


def test_sync_write_error_on_other_redis_error():
    client, fake = _sync_client_with_fake_redis()
    fake.set.side_effect = ResponseError("OOM")
    result = client.set("some-key", {"a": 1}, ttl_seconds=60)
    assert result.status == CacheWriteStatus.WRITE_ERROR


def test_sync_valid_ttl_forwarded_to_redis():
    client, fake = _sync_client_with_fake_redis()
    client.set("some-key", {"a": 1}, ttl_seconds=42)
    _, kwargs = fake.set.call_args
    assert kwargs["ex"] == 42


@pytest.mark.parametrize("ttl", [0, -1, -100])
def test_sync_invalid_ttl_rejected_without_touching_redis(ttl):
    client, fake = _sync_client_with_fake_redis()
    with pytest.raises(InvalidCacheTTLError):
        client.set("some-key", {"a": 1}, ttl_seconds=ttl)
    fake.set.assert_not_called()


def test_get_sync_cache_client_returns_the_same_instance():
    a = get_sync_cache_client()
    b = get_sync_cache_client()
    assert a is b


def test_reset_sync_cache_client_forces_a_new_instance():
    a = get_sync_cache_client()
    reset_sync_cache_client()
    b = get_sync_cache_client()
    assert a is not b


def test_sync_client_credentials_do_not_leak_even_when_the_exception_message_contains_them():
    client, fake = _sync_client_with_fake_redis()
    fake.get.side_effect = RedisConnectionError("redis://user:s3cr3t@evil-host:6379")
    result = client.get("k")
    assert "s3cr3t" not in str(result)
    assert "s3cr3t" not in repr(result)


# --- live: real Redis contract ------------------------------------------------


@pytestmark_live
async def test_live_ping_write_read_hit_and_expiry():
    from app.core.config import get_settings

    client = CacheClient(get_settings())
    key = build_cache_key(
        operation="phase13_slice2_live_test",
        config_fingerprint={"slice": 2},
        input_fingerprint={"nonce": "cache-integration-check"},
        schema_version="v1",
    )
    try:
        miss = await client.get(key)
        assert miss.status == CacheReadStatus.MISS

        value = {"hello": "world", "n": [1, 2, 3]}
        written = await client.set(key, value, ttl_seconds=30)
        assert written.status == CacheWriteStatus.WRITTEN

        hit = await client.get(key)
        assert hit.status == CacheReadStatus.HIT
        assert hit.value == value

        short_key = key + ":expiry"
        await client.set(short_key, {"x": 1}, ttl_seconds=1)
        import asyncio

        await asyncio.sleep(1.5)
        expired = await client.get(short_key)
        assert expired.status == CacheReadStatus.MISS
    finally:
        await client.delete(key)
        await client.delete(key + ":expiry")
        await client.aclose()


@pytestmark_live
async def test_live_invalid_endpoint_reports_unavailable_not_an_uncaught_exception():
    # A deliberately unreachable local port -- no real dependency is
    # touched or stopped; this proves the classification path, not
    # connectivity to the real Redis container.
    bad_settings = Settings(
        _env_file=None,
        redis_url="redis://127.0.0.1:1/0",
        cache_connect_timeout_seconds=0.3,
        cache_socket_timeout_seconds=0.3,
    )
    client = CacheClient(bad_settings)
    try:
        result = await client.get("k")
        assert result.status == CacheReadStatus.UNAVAILABLE
        write_result = await client.set("k", {"a": 1}, ttl_seconds=5)
        assert write_result.status == CacheWriteStatus.UNAVAILABLE
    finally:
        await client.aclose()
