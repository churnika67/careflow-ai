"""Phase 13 Slice 4: the smallest explicit logging configuration needed to
make app.observability.logging.log_event()'s structured JSON events
actually observable under the real launch command
(`uvicorn app.main:app --log-level info`).

Root cause this module fixes (empirically confirmed in Slice 3, and
re-confirmed at the start of this slice via direct introspection of the
real import chain): the Python root logger has zero handlers and its
default effective level is WARNING; only `logging.lastResort` (a fixed
WARNING-level stderr handler) exists as a fallback. `uvicorn --log-level
info` configures only uvicorn's own `uvicorn`/`uvicorn.access`/
`uvicorn.error` loggers -- never the root logger or any `app.*` logger.
INFO-level events from `log_event()` were therefore filtered out before
reaching anything that could print them.

Scope, deliberately narrow: this module configures exactly one logger --
the "app" namespace (the common parent of every `logging.getLogger(__name__)`
call in this codebase, since every application module lives under the
`app.` package) -- with one StreamHandler and a pass-through formatter. It
never touches the bare root logger, never touches `uvicorn`/`uvicorn.access`/
`uvicorn.error`, and never raises third-party library loggers to DEBUG."""

import logging
import sys

from app.core.config import Settings, get_settings

APP_LOGGER_NAME = "app"
_HANDLER_NAME = "careflow-app-handler"

_LEVELS: dict[str, int] = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


def configure_logging(settings: Settings | None = None) -> None:
    """Configures the "app" logger namespace once, idempotently.

    - Handler: a single StreamHandler to stdout (a deliberate, documented
      choice -- structured operational JSON is treated as ordinary
      application output for container log collection, distinct from
      uvicorn's own access/error stream, which this module does not touch).
    - Formatter: exactly "%(message)s" -- log_event() already produces a
      complete JSON string as the log message; wrapping it in any other
      format (a prefix, a second JSON envelope, an embedded timestamp
      *outside* the JSON) would either break direct parseability or
      duplicate the `timestamp` field log_event() already puts *inside*
      the JSON envelope itself. This is why the fix belongs at the
      formatter layer, not by changing log_event()'s call sites.
    - Level: settings.log_level (bounded to the 5 standard names by
      Settings' own Literal type; an invalid value is rejected by Pydantic
      before this function ever runs).
    - Propagation: explicitly set to False on the "app" logger after
      attaching its handler -- deliberate, not an accidental default (see
      Slice 4 instructions section 9). This guarantees each event is
      emitted exactly once through this one handler, and prevents a
      future, unrelated root-logger configuration from ever causing a
      second, duplicate print of the same event.
    - Idempotency: safe to call more than once (e.g. once at import time
      and again in a test) -- any handler this function previously
      attached (identified by name, not by identity) is removed before a
      fresh one is added, so handlers never accumulate."""
    settings = settings or get_settings()
    app_logger = logging.getLogger(APP_LOGGER_NAME)

    for existing in list(app_logger.handlers):
        if existing.name == _HANDLER_NAME:
            app_logger.removeHandler(existing)

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.name = _HANDLER_NAME
    handler.setFormatter(logging.Formatter("%(message)s"))

    app_logger.addHandler(handler)
    app_logger.setLevel(_LEVELS[settings.log_level])
    app_logger.propagate = False


def reset_logging_for_tests() -> None:
    """Test-only hook: removes this module's handler and restores the
    "app" logger to its unconfigured (WARNING, no handler, propagate=True)
    state, so one test's logging configuration never leaks into another."""
    app_logger = logging.getLogger(APP_LOGGER_NAME)
    for existing in list(app_logger.handlers):
        if existing.name == _HANDLER_NAME:
            app_logger.removeHandler(existing)
    app_logger.setLevel(logging.NOTSET)
    app_logger.propagate = True
