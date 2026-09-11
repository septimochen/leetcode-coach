from __future__ import annotations

import io
import logging
from collections.abc import Iterator
from pathlib import Path

import pytest

from leetcode_coach import log
from leetcode_coach.log import (
    LOGGER_NAME,
    configure_logging,
    get_logger,
    logging_summary,
    register_secret,
    resolve_level,
    timed,
)


@pytest.fixture
def logs() -> Iterator[io.StringIO]:
    """Give one test an isolated in-memory ``leetcode_coach`` logger."""
    logger = logging.getLogger(LOGGER_NAME)
    saved = (logger.level, logger.handlers[:], logger.propagate)
    saved_secrets = set(log._secrets)
    stream = io.StringIO()
    log._secrets.clear()
    configure_logging("DEBUG", stream=stream)
    try:
        yield stream
    finally:
        logger.handlers.clear()
        logger.setLevel(saved[0])
        logger.handlers.extend(saved[1])
        logger.propagate = saved[2]
        log._secrets.clear()
        log._secrets.update(saved_secrets)


def test_resolve_level_accepts_names_in_any_case() -> None:
    assert resolve_level("debug") == logging.DEBUG
    assert resolve_level(" Warning ") == logging.WARNING
    assert resolve_level(7) == 7
    assert resolve_level(None) == logging.INFO
    assert resolve_level("") == logging.INFO


def test_resolve_level_strictness_controls_env_typos() -> None:
    with pytest.raises(ValueError, match="Invalid log level"):
        resolve_level("verbose")
    # An unrelated LOG_LEVEL already exported in the shell must not abort a run.
    assert resolve_level("verbose", strict=False) == logging.INFO


def test_get_logger_namespaces_every_child() -> None:
    assert get_logger().name == LOGGER_NAME
    assert get_logger("coach").name == "leetcode_coach.coach"
    assert get_logger("leetcode_coach.coach").name == "leetcode_coach.coach"


def test_configure_logging_owns_only_its_own_logger(logs: io.StringIO) -> None:
    logger = logging.getLogger(LOGGER_NAME)
    assert logger.level == logging.DEBUG
    assert logger.propagate is False
    # Reconfiguring (provisional, then final, level) must not stack handlers.
    configure_logging("INFO", stream=logs)
    assert len(logger.handlers) == 1
    assert logging_summary()["level"] == "INFO"


def test_request_loggers_stay_quiet_above_debug(logs: io.StringIO) -> None:
    configure_logging("INFO", stream=logs)
    for name in log.THIRD_PARTY_LOGGERS:
        assert logging.getLogger(name).level == logging.WARNING


def test_secrets_are_redacted_in_messages_and_tracebacks(logs: io.StringIO) -> None:
    register_secret("sk-secret-value-123")
    logger = get_logger("coach")
    logger.info("calling provider with sk-secret-value-123")
    try:
        raise ValueError("auth failed for sk-secret-value-123")
    except ValueError:
        logger.exception("provider call failed")
    emitted = logs.getvalue()
    assert "sk-secret-value-123" not in emitted
    assert emitted.count("***") >= 2
    assert "Traceback" in emitted


def test_short_values_are_not_redacted(logs: io.StringIO) -> None:
    register_secret("abc")
    register_secret(None)
    assert logging_summary()["redacted_secrets"] == 0
    get_logger().info("ability to abstract")
    assert "ability to abstract" in logs.getvalue()


def test_broken_format_arguments_still_log_something(logs: io.StringIO) -> None:
    # Interpolation is skipped when args are empty, so the failure mode is *too many*.
    get_logger("coach").info("expected one %s argument", 1, 2)
    emitted = logs.getvalue()
    assert "formatting error" in emitted
    assert "expected one %s argument" in emitted


def test_log_file_receives_redacted_records(tmp_path: Path) -> None:
    log_path = tmp_path / "logs" / "coach.log"
    stream = io.StringIO()
    configure_logging("INFO", log_file=log_path, stream=stream)
    try:
        register_secret("session-cookie-value")
        get_logger().error("rejected cookie session-cookie-value")
    finally:
        for handler in logging.getLogger(LOGGER_NAME).handlers[:]:
            handler.close()
            logging.getLogger(LOGGER_NAME).removeHandler(handler)
    written = log_path.read_text(encoding="utf-8")
    assert "session-cookie-value" not in written
    assert "rejected cookie ***" in written


def test_timed_logs_duration_and_reported_stats(logs: io.StringIO) -> None:
    with timed(get_logger("leetcode"), "leetcode.catalog") as stats:
        stats["problems"] = 42
    emitted = logs.getvalue()
    assert "leetcode.catalog: started" in emitted
    assert "leetcode.catalog: completed in" in emitted
    assert "'problems': 42" in emitted


def test_timed_logs_failure_and_reraises(logs: io.StringIO) -> None:
    with (
        pytest.raises(RuntimeError, match="boom"),
        timed(get_logger("llm"), "llm.chat_completion", model="gpt-5-mini"),
    ):
        raise RuntimeError("boom")
    emitted = logs.getvalue()
    assert "llm.chat_completion: started {'model': 'gpt-5-mini'}" in emitted
    assert "llm.chat_completion: failed after" in emitted
    assert "boom" in emitted


def test_records_are_clean_before_any_handler_formats_them() -> None:
    """A handler this package does not own must still receive redacted records.

    Records are sanitised by a filter on the logger, not only by our formatter, so an
    embedding application that attaches its own handler cannot leak a credential.
    """
    logger = logging.getLogger(LOGGER_NAME)
    saved = (logger.level, logger.handlers[:], logger.propagate)
    saved_secrets = set(log._secrets)
    foreign = io.StringIO()
    handler = logging.StreamHandler(foreign)
    handler.setFormatter(logging.Formatter("%(message)s | %(levelname)s"))
    log._secrets.clear()
    register_secret("foreign-handler-secret")
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        get_logger("coach").info("token foreign-handler-secret accepted")
    finally:
        handler.close()
        logger.handlers.clear()
        logger.setLevel(saved[0])
        logger.handlers.extend(saved[1])
        logger.propagate = saved[2]
        log._secrets.clear()
        log._secrets.update(saved_secrets)
    assert "foreign-handler-secret" not in foreign.getvalue()
    assert "token *** accepted" in foreign.getvalue()
