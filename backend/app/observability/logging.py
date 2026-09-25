"""Phase 13 Slice 3: one central structured-event helper + request-ID
correlation, replacing the seven independently duplicated `_log`/`_log_event`
helpers previously scattered across agents/graph.py,
agents/structured_specialist.py, agents/validator.py,
api/multi_agent.py, api/orchestrate.py, api/reviews.py, and
reranking/service.py.

This module owns LOG STRUCTURE and REQUEST CORRELATION only. It is not a
logging framework, not a metrics system, and not distributed tracing --
standard library `logging` is used exactly as before; this module only
standardizes the JSON envelope and where `request_id` comes from.

Safe-field policy (enforced, not just documented): a caller must never be
able to place raw query/answer/prompt/evidence/citation-excerpt/reviewer-text/
cache-value/credential content into a structured event through a
recognizably-named field -- see FORBIDDEN_FIELD_NAMES. A caller may still
log IDs, counts, durations, and reason/status codes, exactly as the six
migrated call sites already did."""

import json
import logging
from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import UUID

# --- request-id context propagation -----------------------------------------

_request_id_var: ContextVar[str | None] = ContextVar("careflow_request_id", default=None)


def get_request_id() -> str | None:
    """The current request's correlation ID, if one has been set -- e.g. by
    RequestContextMiddleware, or explicitly by a caller/test. None outside
    any request context (this is expected and safe; log_event() simply
    omits request_id in that case unless one is passed explicitly)."""
    return _request_id_var.get()


def set_request_id(request_id: str) -> Token:
    """Sets the current context's request_id and returns a Token that MUST
    be passed to reset_request_id() (typically in a finally block) to
    restore whatever was set before -- never leaving a stale ID visible to
    unrelated later code in the same context."""
    return _request_id_var.set(request_id)


def reset_request_id(token: Token) -> None:
    _request_id_var.reset(token)


@contextmanager
def request_id_context(request_id: str) -> Generator[str, None, None]:
    """Convenience context manager wrapping set_request_id()/reset_request_id()
    -- the preferred way to scope a request_id for a block of code (e.g. in
    tests, or anywhere middleware is not already doing this)."""
    token = set_request_id(request_id)
    try:
        yield request_id
    finally:
        reset_request_id(token)


# --- safe field policy --------------------------------------------------------

# Field NAMES that must never appear in a structured event, regardless of
# their value -- a bounded, explicit list, not a heuristic. A caller
# supplying one of these has its value dropped (never its presence silently
# ignored -- see _redacted_fields below), not the whole event discarded.
FORBIDDEN_FIELD_NAMES: frozenset[str] = frozenset(
    {
        "query",
        "question",
        "answer",
        "generated_answer",
        "final_summary",
        "prompt",
        "evidence",
        "context",
        "context_text",
        "citation_excerpt",
        "citation_text",
        "evidence_snapshot",
        "reviewer_reason",
        "reason_text",
        "free_text",
        "cache_value",
        "value",
        "redis_url",
        "database_url",
        "connection_string",
        "authorization",
        "password",
        "api_key",
        "access_token",
        "refresh_token",
    }
)

_MAX_NORMALIZE_DEPTH = 3


def _normalize(value: Any, *, depth: int = 0) -> Any:
    """Safe, explicit, narrowly-scoped serialization -- never `default=str`
    on an arbitrary object, which could silently stringify (and therefore
    leak the full contents of) a domain object nobody intended to log.
    Supports exactly: str, int, float, bool, None, Enum (-> its own value,
    if that is itself JSON-safe, else str()), UUID (-> str()), and list/dict
    containers of the same, recursively, up to a bounded depth. Anything
    else fails safely to a bounded placeholder naming only the Python type,
    never the value's content."""
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Enum):
        inner = value.value
        return inner if isinstance(inner, str | int | float | bool) else str(value)
    if depth >= _MAX_NORMALIZE_DEPTH:
        return "<max_depth_exceeded>"
    if isinstance(value, list | tuple):
        return [_normalize(item, depth=depth + 1) for item in value]
    if isinstance(value, dict):
        return {str(k): _normalize(v, depth=depth + 1) for k, v in value.items()}
    return f"<unsupported:{type(value).__name__}>"


def log_event(
    logger: logging.Logger,
    event: str,
    *,
    level: int = logging.INFO,
    request_id: str | None = None,
    **fields: object,
) -> None:
    """Emits one structured JSON log line through the caller's own logger.

    request_id: if not explicitly passed, taken from the current
    request-id context (get_request_id()) -- callers deep in the call
    stack (e.g. reranking/service.py, which has no request_id parameter at
    all) automatically correlate without it being threaded through every
    function signature, as long as they run within a context a request-id
    was set for.

    level: logging.INFO for successful operational events (including an
    expected abstention or a cache MISS -- neither is a warning or an
    error), logging.WARNING for recoverable degraded conditions,
    logging.ERROR for request/component failures. Never inferred
    automatically from field content -- always the caller's explicit
    choice, matching each of the seven migrated call sites' own existing
    judgment about its own event.

    Every field is passed through _normalize() -- no field's value is ever
    serialized via an arbitrary `default=str` fallback. A field whose NAME
    is in FORBIDDEN_FIELD_NAMES has its value dropped entirely (never
    logged, regardless of type) and is listed by name (never by value) in
    `_redacted_fields`, so a caller mistake is visible in the log output
    itself rather than silently disappearing.

    Existing convention preserved exactly: fields are emitted as given,
    including explicit None values -- this module does not newly introduce
    sparse (null-omitting) events, since the seven migrated call sites all
    already emitted explicit nulls for absent optional fields.

    `timestamp` (Phase 13 Slice 4): generated once per event, UTC,
    ISO-8601, timezone-explicit (via datetime.now(UTC).isoformat()) --
    matching the exact convention already used throughout
    evaluation/*.py. Lives inside the JSON envelope itself, not at the
    logging-handler/formatter layer, so the event remains one
    self-contained, directly parseable JSON object regardless of handler
    configuration -- see observability/config.py's formatter, which is
    deliberately just "%(message)s" for exactly this reason. `duration_ms`
    (where a caller supplies it) remains a separate, perf_counter-derived
    monotonic measurement -- timestamp is wall-clock identity, never a
    duration."""
    envelope: dict[str, object] = {
        "event": event,
        "request_id": request_id if request_id is not None else get_request_id(),
        "timestamp": datetime.now(UTC).isoformat(),
    }
    redacted: list[str] = []
    for name, value in fields.items():
        if name in FORBIDDEN_FIELD_NAMES:
            redacted.append(name)
            continue
        envelope[name] = _normalize(value)
    if redacted:
        envelope["_redacted_fields"] = sorted(redacted)
    logger.log(level, "%s", json.dumps(envelope, sort_keys=False, ensure_ascii=False))
