import json
import logging
from uuid import UUID, uuid4

import pytest
from app.observability.logging import (
    FORBIDDEN_FIELD_NAMES,
    get_request_id,
    log_event,
    request_id_context,
    reset_request_id,
    set_request_id,
)


class WorkflowLike(str):
    """A str-Enum-shaped stand-in without importing a real domain enum --
    the normalization contract is tested against the general shape, not a
    specific model."""


def _emit(caplog, **fields):
    logger = logging.getLogger("test.observability")
    with caplog.at_level(logging.INFO, logger="test.observability"):
        log_event(logger, "test_event", **fields)
    return json.loads(caplog.records[-1].message)


# --- basic envelope -----------------------------------------------------------


def test_event_and_request_id_present(caplog):
    record = _emit(caplog, request_id="req-1")
    assert record["event"] == "test_event"
    assert record["request_id"] == "req-1"


def test_request_id_defaults_to_none_outside_any_context(caplog):
    record = _emit(caplog)
    assert record["request_id"] is None


def test_request_id_taken_from_context_when_not_passed_explicitly(caplog):
    token = set_request_id("ctx-request-id")
    try:
        record = _emit(caplog)
    finally:
        reset_request_id(token)
    assert record["request_id"] == "ctx-request-id"


def test_explicit_request_id_overrides_context(caplog):
    token = set_request_id("ctx-id")
    try:
        record = _emit(caplog, request_id="explicit-id")
    finally:
        reset_request_id(token)
    assert record["request_id"] == "explicit-id"


# --- value normalization -------------------------------------------------------


def test_numeric_bool_and_none_fields_preserved(caplog):
    record = _emit(caplog, count=3, ratio=0.5, ok=True, missing=None)
    assert record["count"] == 3
    assert record["ratio"] == 0.5
    assert record["ok"] is True
    assert record["missing"] is None


def test_uuid_normalized_to_string(caplog):
    value = uuid4()
    record = _emit(caplog, review_id=value)
    assert record["review_id"] == str(value)
    assert isinstance(record["review_id"], str)


def test_uuid_round_trips_as_valid_uuid_string(caplog):
    value = uuid4()
    record = _emit(caplog, review_id=value)
    assert UUID(record["review_id"]) == value


def test_str_enum_normalized_to_its_value(caplog):
    from enum import StrEnum

    class Status(StrEnum):
        OK = "ok"
        ERROR = "error"

    record = _emit(caplog, status=Status.OK)
    assert record["status"] == "ok"


def test_int_enum_normalized_to_its_int_value(caplog):
    # Field named "priority", not "level" -- "level" is log_event()'s own
    # reserved keyword for the log severity, not an ordinary field name.
    from enum import IntEnum

    class Priority(IntEnum):
        LOW = 1
        HIGH = 2

    record = _emit(caplog, priority=Priority.HIGH)
    assert record["priority"] == 2


def test_list_of_scalars_preserved(caplog):
    record = _emit(caplog, validation_issue=["code_a", "code_b"])
    assert record["validation_issue"] == ["code_a", "code_b"]


def test_list_of_enums_normalized(caplog):
    from enum import StrEnum

    class Code(StrEnum):
        A = "a"
        B = "b"

    record = _emit(caplog, codes=[Code.A, Code.B])
    assert record["codes"] == ["a", "b"]


def test_nested_dict_of_scalars_preserved(caplog):
    record = _emit(caplog, meta={"a": 1, "b": "x"})
    assert record["meta"] == {"a": 1, "b": "x"}


def test_unsupported_complex_object_becomes_bounded_placeholder_not_stringified(caplog):
    class DomainRecord:
        def __str__(self):
            return "SENSITIVE-PATIENT-DATA-12345"

    record = _emit(caplog, thing=DomainRecord())
    assert record["thing"] == "<unsupported:DomainRecord>"
    assert "SENSITIVE-PATIENT-DATA-12345" not in json.dumps(record)


def test_deeply_nested_structure_is_bounded_not_dumped_in_full(caplog):
    nested = {"a": {"b": {"c": {"d": "too deep"}}}}
    record = _emit(caplog, thing=nested)
    # depth is bounded -- the exact cutoff value is an implementation
    # detail, but the payload must never grow unbounded.
    assert json.dumps(record["thing"]).count("too deep") == 0 or "max_depth_exceeded" in json.dumps(
        record["thing"]
    )


# --- forbidden field policy -----------------------------------------------------


@pytest.mark.parametrize("field", sorted(FORBIDDEN_FIELD_NAMES))
def test_every_forbidden_field_name_is_redacted(caplog, field):
    record = _emit(caplog, **{field: "this must never appear"})
    assert field not in record
    assert "this must never appear" not in json.dumps(record)
    assert field in record["_redacted_fields"]


def test_raw_query_cannot_be_logged_through_the_query_field(caplog):
    record = _emit(caplog, query="does medicare cover a wheelchair for jane doe")
    assert "wheelchair" not in json.dumps(record)
    assert "jane doe" not in json.dumps(record)


def test_forbidden_field_does_not_suppress_other_fields_in_the_same_call(caplog):
    record = _emit(caplog, query="secret", status="ok", record_count=3)
    assert record["status"] == "ok"
    assert record["record_count"] == 3
    assert "query" not in record


def test_no_redacted_fields_key_when_nothing_was_redacted(caplog):
    record = _emit(caplog, status="ok")
    assert "_redacted_fields" not in record


def test_answer_evidence_reviewer_text_cache_value_all_forbidden():
    # Explicit, named coverage of the specific fields called out in the
    # Slice 3 directive, beyond the parametrized sweep above.
    for name in (
        "answer",
        "evidence",
        "evidence_snapshot",
        "reviewer_reason",
        "cache_value",
        "redis_url",
        "database_url",
        "authorization",
        "password",
        "api_key",
    ):
        assert name in FORBIDDEN_FIELD_NAMES


# --- credential / secret leakage -------------------------------------------------


def test_no_credentials_emitted_through_error_metadata(caplog):
    record = _emit(
        caplog,
        error_category="ConnectionError",
        # A caller must never be able to smuggle a raw exception message
        # (which could contain a connection string) through an ordinary
        # field either -- error_category is a bounded class name, and
        # nothing here accepts a raw message field.
    )
    assert record["error_category"] == "ConnectionError"
    assert "postgresql://" not in json.dumps(record)


# --- cache status enum support (Slice 2 interop, no cache calls made) -----------


def test_cache_status_enum_serializes_safely(caplog):
    from app.infrastructure.cache import CacheReadStatus

    record = _emit(caplog, cache_status=CacheReadStatus.HIT)
    assert record["cache_status"] == "hit"


# --- duration / numeric type -----------------------------------------------------


def test_duration_ms_remains_numeric(caplog):
    record = _emit(caplog, duration_ms=12.345)
    assert isinstance(record["duration_ms"], float)
    assert record["duration_ms"] == 12.345


# --- log level mapping -----------------------------------------------------------


def test_default_level_is_info(caplog):
    logger = logging.getLogger("test.observability.level")
    with caplog.at_level(logging.INFO, logger="test.observability.level"):
        log_event(logger, "ok_event", status="ok")
    assert caplog.records[-1].levelno == logging.INFO


def test_explicit_warning_level_honored(caplog):
    logger = logging.getLogger("test.observability.level")
    with caplog.at_level(logging.INFO, logger="test.observability.level"):
        log_event(logger, "degraded_event", level=logging.WARNING, status="degraded")
    assert caplog.records[-1].levelno == logging.WARNING


def test_explicit_error_level_honored(caplog):
    logger = logging.getLogger("test.observability.level")
    with caplog.at_level(logging.INFO, logger="test.observability.level"):
        log_event(logger, "failed_event", level=logging.ERROR, error_category="Boom")
    assert caplog.records[-1].levelno == logging.ERROR


def test_abstention_is_not_forced_to_error_level(caplog):
    # An expected abstention must not be logged as an error merely because
    # it exists -- callers choose the level; the helper never infers it.
    logger = logging.getLogger("test.observability.level")
    with caplog.at_level(logging.INFO, logger="test.observability.level"):
        log_event(logger, "abstained", status="abstained", abstention_reason="no_evidence")
    assert caplog.records[-1].levelno == logging.INFO


# --- ContextVar lifecycle (pure) --------------------------------------------------


def test_request_id_set_and_get():
    token = set_request_id("abc-123")
    try:
        assert get_request_id() == "abc-123"
    finally:
        reset_request_id(token)


def test_reset_clears_context():
    assert get_request_id() is None
    token = set_request_id("abc-123")
    reset_request_id(token)
    assert get_request_id() is None


def test_nested_reset_restores_previous_value():
    outer_token = set_request_id("outer")
    inner_token = set_request_id("inner")
    assert get_request_id() == "inner"
    reset_request_id(inner_token)
    assert get_request_id() == "outer"
    reset_request_id(outer_token)
    assert get_request_id() is None


def test_request_id_context_manager_sets_and_restores():
    assert get_request_id() is None
    with request_id_context("scoped-id") as returned:
        assert returned == "scoped-id"
        assert get_request_id() == "scoped-id"
    assert get_request_id() is None


def test_request_id_context_manager_restores_even_on_exception():
    with pytest.raises(ValueError):
        with request_id_context("scoped-id"):
            assert get_request_id() == "scoped-id"
            raise ValueError("boom")
    assert get_request_id() is None


async def test_two_concurrent_async_tasks_maintain_distinct_request_ids():
    import asyncio

    results = {}

    async def worker(name: str, request_id: str):
        with request_id_context(request_id):
            await asyncio.sleep(0.01)
            results[name] = get_request_id()

    await asyncio.gather(worker("a", "req-a"), worker("b", "req-b"))
    assert results == {"a": "req-a", "b": "req-b"}


async def test_no_request_id_leaks_after_task_completion():
    import asyncio

    async def worker():
        with request_id_context("temporary"):
            return get_request_id()

    result = await asyncio.create_task(worker())
    assert result == "temporary"
    assert get_request_id() is None  # never leaked into the caller's own context


async def test_contextvar_propagates_across_asyncio_to_thread():
    # This is the specific mechanism relevant to reranking/service.py (a
    # sync function with no request_id parameter) picking up the correct
    # ID if it is ever invoked via asyncio.to_thread -- verified directly
    # rather than assumed, per Python's documented (and here re-confirmed)
    # contextvars.copy_context() behavior for to_thread.
    import asyncio

    with request_id_context("thread-propagated-id"):

        def sync_fn():
            return get_request_id()

        result = await asyncio.to_thread(sync_fn)
    assert result == "thread-propagated-id"
