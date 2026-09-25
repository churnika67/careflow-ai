import json
import logging

import pytest
from app.core.config import Settings
from app.observability.config import (
    _HANDLER_NAME,
    APP_LOGGER_NAME,
    configure_logging,
    reset_logging_for_tests,
)
from app.observability.logging import log_event


@pytest.fixture(autouse=True)
def _isolated_app_logger():
    """Captures and restores the "app" logger's level/handlers/propagate
    around every test in this file, so configuring logging here never
    leaks into unrelated tests (per Slice 4 section 12)."""
    logger = logging.getLogger(APP_LOGGER_NAME)
    saved_level = logger.level
    saved_handlers = list(logger.handlers)
    saved_propagate = logger.propagate
    reset_logging_for_tests()
    yield
    reset_logging_for_tests()
    logger.level = saved_level
    logger.handlers = saved_handlers
    logger.propagate = saved_propagate


def _configured_logger() -> logging.Logger:
    return logging.getLogger(f"{APP_LOGGER_NAME}.test_module")


# --- visibility ----------------------------------------------------------------


def test_configure_logging_makes_info_visible(capsys):
    # Deliberately not caplog: caplog's default capture handler is attached
    # via root-logger propagation, and this logger's propagate=False by
    # design (see config.py's docstring) -- so capsys, which reads the
    # real StreamHandler's actual stdout output, is the correct way to
    # observe this logger's real behavior, matching the live Uvicorn
    # verification in this slice's report.
    configure_logging(Settings(_env_file=None, log_level="INFO"))
    logger = _configured_logger()
    log_event(logger, "ok", status="ok")
    out = capsys.readouterr().out
    assert '"event": "ok"' in out


def test_configured_logger_level_matches_setting():
    configure_logging(Settings(_env_file=None, log_level="WARNING"))
    app_logger = logging.getLogger(APP_LOGGER_NAME)
    assert app_logger.level == logging.WARNING


@pytest.mark.parametrize(
    "level_name,level_value",
    [
        ("DEBUG", logging.DEBUG),
        ("INFO", logging.INFO),
        ("WARNING", logging.WARNING),
        ("ERROR", logging.ERROR),
        ("CRITICAL", logging.CRITICAL),
    ],
)
def test_each_supported_level_configures_correctly(level_name, level_value):
    configure_logging(Settings(_env_file=None, log_level=level_name))
    assert logging.getLogger(APP_LOGGER_NAME).level == level_value


# --- event stream integrity -----------------------------------------------------


def test_one_event_produces_exactly_one_output_record(capsys):
    configure_logging(Settings(_env_file=None, log_level="INFO"))
    logger = _configured_logger()
    log_event(logger, "ok", status="ok")
    out = capsys.readouterr().out
    lines = [line for line in out.splitlines() if line.strip()]
    assert len(lines) == 1


def test_event_remains_directly_parseable_json_via_the_real_handler(capsys):
    configure_logging(Settings(_env_file=None, log_level="INFO"))
    logger = _configured_logger()
    log_event(logger, "ok", status="ok", count=3)
    out = capsys.readouterr().out
    lines = [line for line in out.splitlines() if line.strip()]
    assert len(lines) == 1
    record = json.loads(lines[0])  # raises if this is not directly-parseable JSON
    assert record["event"] == "ok"
    assert record["status"] == "ok"
    assert record["count"] == 3


def test_no_nested_or_double_json_wrapping(capsys):
    configure_logging(Settings(_env_file=None, log_level="INFO"))
    logger = _configured_logger()
    log_event(logger, "ok", status="ok")
    out = capsys.readouterr().out.strip()
    # A double-encoded line would look like {"message": "{\"event\": ...}"}.
    assert not out.startswith('{"message"')
    parsed = json.loads(out)
    assert isinstance(parsed.get("event"), str)  # top-level key, not nested


def test_timestamp_present_and_iso8601_utc():
    configure_logging(Settings(_env_file=None, log_level="INFO"))
    logger = _configured_logger()
    import io

    captured = io.StringIO()
    handler = logging.StreamHandler(captured)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logging.getLogger(APP_LOGGER_NAME).addHandler(handler)
    try:
        log_event(logger, "ok", status="ok")
    finally:
        logging.getLogger(APP_LOGGER_NAME).removeHandler(handler)
    record = json.loads(captured.getvalue().strip().splitlines()[-1])
    from datetime import datetime

    parsed_ts = datetime.fromisoformat(record["timestamp"])
    assert parsed_ts.tzinfo is not None  # explicit timezone, not naive


def test_duration_ms_remains_a_separate_monotonic_field_not_confused_with_timestamp():
    configure_logging(Settings(_env_file=None, log_level="INFO"))
    logger = _configured_logger()
    import io

    captured = io.StringIO()
    handler = logging.StreamHandler(captured)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logging.getLogger(APP_LOGGER_NAME).addHandler(handler)
    try:
        log_event(logger, "ok", status="ok", duration_ms=12.5)
    finally:
        logging.getLogger(APP_LOGGER_NAME).removeHandler(handler)
    record = json.loads(captured.getvalue().strip().splitlines()[-1])
    assert record["duration_ms"] == 12.5
    assert "timestamp" in record
    assert record["duration_ms"] != record["timestamp"]


# --- idempotency -----------------------------------------------------------------


def test_calling_configure_logging_twice_does_not_duplicate_handlers():
    configure_logging(Settings(_env_file=None, log_level="INFO"))
    configure_logging(Settings(_env_file=None, log_level="INFO"))
    app_logger = logging.getLogger(APP_LOGGER_NAME)
    matching = [h for h in app_logger.handlers if h.name == _HANDLER_NAME]
    assert len(matching) == 1


def test_calling_configure_logging_twice_does_not_duplicate_output(capsys):
    configure_logging(Settings(_env_file=None, log_level="INFO"))
    configure_logging(Settings(_env_file=None, log_level="INFO"))
    logger = _configured_logger()
    log_event(logger, "ok", status="ok")
    out = capsys.readouterr().out
    lines = [line for line in out.splitlines() if line.strip()]
    assert len(lines) == 1


def test_reconfiguring_with_a_new_level_takes_effect():
    configure_logging(Settings(_env_file=None, log_level="INFO"))
    configure_logging(Settings(_env_file=None, log_level="ERROR"))
    assert logging.getLogger(APP_LOGGER_NAME).level == logging.ERROR


# --- level filtering ---------------------------------------------------------------


def test_warning_visible_at_info_level(capsys):
    configure_logging(Settings(_env_file=None, log_level="INFO"))
    logger = _configured_logger()
    log_event(logger, "degraded", level=logging.WARNING, status="degraded")
    out = capsys.readouterr().out
    assert "degraded" in out


def test_error_visible_at_info_level(capsys):
    configure_logging(Settings(_env_file=None, log_level="INFO"))
    logger = _configured_logger()
    log_event(logger, "failed", level=logging.ERROR, error_category="Boom")
    out = capsys.readouterr().out
    assert "failed" in out


def test_higher_configured_level_suppresses_info(capsys):
    configure_logging(Settings(_env_file=None, log_level="WARNING"))
    logger = _configured_logger()
    log_event(logger, "should_not_appear", status="ok")
    out = capsys.readouterr().out
    assert out.strip() == ""


def test_higher_configured_level_still_allows_warning_and_above(capsys):
    configure_logging(Settings(_env_file=None, log_level="WARNING"))
    logger = _configured_logger()
    log_event(logger, "should_appear", level=logging.WARNING, status="degraded")
    out = capsys.readouterr().out
    assert "should_appear" in out


# --- invalid level rejected --------------------------------------------------------


@pytest.mark.parametrize("bad_level", ["TRACE", "info", "verbose", "", "99"])
def test_invalid_log_level_rejected(bad_level):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Settings(_env_file=None, log_level=bad_level)


# --- scope: uvicorn/root/third-party untouched --------------------------------------


def test_uvicorn_logger_configuration_not_mutated():
    uvicorn_logger = logging.getLogger("uvicorn")
    before_handlers = list(uvicorn_logger.handlers)
    before_level = uvicorn_logger.level
    configure_logging(Settings(_env_file=None, log_level="INFO"))
    assert uvicorn_logger.handlers == before_handlers
    assert uvicorn_logger.level == before_level


def test_uvicorn_access_and_error_loggers_not_mutated():
    for name in ("uvicorn.access", "uvicorn.error"):
        logger = logging.getLogger(name)
        before_handlers = list(logger.handlers)
        before_level = logger.level
        configure_logging(Settings(_env_file=None, log_level="INFO"))
        assert logger.handlers == before_handlers
        assert logger.level == before_level


def test_bare_root_logger_not_mutated():
    root = logging.getLogger()
    before_handlers = list(root.handlers)
    before_level = root.level
    configure_logging(Settings(_env_file=None, log_level="INFO"))
    assert root.handlers == before_handlers
    assert root.level == before_level


def test_third_party_library_loggers_not_raised_to_debug():
    for name in ("httpx", "psycopg", "qdrant_client"):
        logger = logging.getLogger(name)
        before_level = logger.level
        configure_logging(Settings(_env_file=None, log_level="DEBUG"))
        assert logger.level == before_level  # unaffected even when app is set to DEBUG


def test_app_logger_does_not_propagate_to_root():
    configure_logging(Settings(_env_file=None, log_level="INFO"))
    assert logging.getLogger(APP_LOGGER_NAME).propagate is False


# --- safe-field / redaction contract remains intact under real config -------------


def test_forbidden_field_still_redacted_through_the_real_handler(capsys):
    configure_logging(Settings(_env_file=None, log_level="INFO"))
    logger = _configured_logger()
    log_event(logger, "ok", query="raw sensitive question text", status="ok")
    out = capsys.readouterr().out
    assert "raw sensitive question text" not in out
    record = json.loads(out.strip())
    assert "query" not in record
    assert record["_redacted_fields"] == ["query"]
