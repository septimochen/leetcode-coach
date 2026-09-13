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
    resolve_level,
    timed,
)


@pytest.fixture
def logs() -> Iterator[io.StringIO]:
    """Give one test an isolated in-memory ``leetcode_coach`` logger."""
    logger = logging.getLogger(LOGGER_NAME)
    saved = (logger.level, logger.handlers[:], logger.propagate)
    stream = io.StringIO()
    configure_logging("DEBUG", stream=stream)
    try:
        yield stream
    finally:
        logger.handlers.clear()
        logger.setLevel(saved[0])
        logger.handlers.extend(saved[1])
        logger.propagate = saved[2]


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


def test_log_file_receives_records(tmp_path: Path) -> None:
    log_path = tmp_path / "logs" / "coach.log"
    stream = io.StringIO()
    configure_logging("INFO", log_file=log_path, stream=stream)
    try:
        get_logger().error("rejected cookie session-cookie-value")
    finally:
        for handler in logging.getLogger(LOGGER_NAME).handlers[:]:
            handler.close()
            logging.getLogger(LOGGER_NAME).removeHandler(handler)
    written = log_path.read_text(encoding="utf-8")
    assert "rejected cookie session-cookie-value" in written


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
