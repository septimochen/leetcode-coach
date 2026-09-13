"""Small, application-wide logging helpers."""

from __future__ import annotations

import logging
import os
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import IO, Any

LOGGER_NAME = "leetcode_coach"
LOG_LEVEL_ENV = "LEETCODE_COACH_LOG_LEVEL"
LOG_FILE_ENV = "LEETCODE_COACH_LOG_FILE"

DEFAULT_LEVEL = "INFO"
DEFAULT_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S%z"

LOG_LEVEL_CHOICES = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
LEVELS: dict[str, int] = {name: getattr(logging, name) for name in LOG_LEVEL_CHOICES}
LEVEL_NAMES: dict[int, str] = {value: name for name, value in LEVELS.items()}

# These libraries are useful at DEBUG but too chatty for normal operation.
THIRD_PARTY_LOGGERS = ("httpx", "httpcore", "openai")


def resolve_level(level: int | str | None, *, strict: bool = True) -> int:
    """Turn a log-level name or number into a logging level."""
    if level is None:
        return LEVELS[DEFAULT_LEVEL]
    if isinstance(level, int):
        return level
    candidate = level.strip().upper()
    if not candidate:
        return LEVELS[DEFAULT_LEVEL]
    if candidate in LEVELS:
        return LEVELS[candidate]
    if candidate.isdigit():
        return int(candidate)
    if strict:
        raise ValueError(
            f"Invalid log level {level!r}; expected one of "
            f"{', '.join(LOG_LEVEL_CHOICES)}."
        )
    return LEVELS[DEFAULT_LEVEL]


def get_logger(name: str | None = None) -> logging.Logger:
    """Return a logger under the application's namespace."""
    if not name or name == LOGGER_NAME:
        return logging.getLogger(LOGGER_NAME)
    if name.startswith(f"{LOGGER_NAME}."):
        return logging.getLogger(name)
    return logging.getLogger(f"{LOGGER_NAME}.{name}")


def configure_logging(
    level: int | str | None = None,
    *,
    log_file: str | os.PathLike[str] | None = None,
    stream: IO[str] | None = None,
) -> logging.Logger:
    """Configure stderr logging and optionally a second file handler."""
    logger = logging.getLogger(LOGGER_NAME)
    from_environment = level is None
    if from_environment:
        level = os.environ.get(LOG_LEVEL_ENV) or os.environ.get("LOG_LEVEL") or None
    if log_file is None:
        log_file = os.environ.get(LOG_FILE_ENV) or None

    resolved = resolve_level(level, strict=not from_environment)
    if resolved == logging.NOTSET:
        resolved = LEVELS[DEFAULT_LEVEL]

    logger.handlers.clear()
    logger.setLevel(resolved)
    logger.propagate = False
    formatter = logging.Formatter(DEFAULT_FORMAT, datefmt=DATE_FORMAT)

    stream_handler = logging.StreamHandler(stream or sys.stderr)
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    if log_file:
        path = Path(log_file)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(path, encoding="utf-8")
        except OSError:
            logger.warning("Could not open log file %s; logging to stderr only", path)
        else:
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
            logger.debug("Logging to %s as well", path)

    if resolved > logging.DEBUG:
        for name in THIRD_PARTY_LOGGERS:
            logging.getLogger(name).setLevel(max(resolved, logging.WARNING))
    return logger


def logging_summary() -> dict[str, Any]:
    """Describe the active logging configuration."""
    logger = logging.getLogger(LOGGER_NAME)
    return {
        "level": LEVEL_NAMES.get(logger.level, logging.getLevelName(logger.level)),
        "handlers": [type(handler).__name__ for handler in logger.handlers],
    }


@contextmanager
def timed(
    logger: logging.Logger,
    label: str,
    *,
    level: int = logging.INFO,
    **fields: object,
) -> Iterator[dict[str, object]]:
    """Log a stage's start, duration, outcome, and optional result counts."""
    suffix = f" {fields}" if fields else ""
    logger.log(level, "%s: started%s", label, suffix)
    started = time.perf_counter()
    reported: dict[str, object] = dict(fields)
    try:
        yield reported
    except Exception as error:
        logger.error(
            "%s: failed after %.2fs: %s", label, time.perf_counter() - started, error
        )
        raise
    detail = f" {reported}" if reported else ""
    logger.log(
        level, "%s: completed in %.2fs%s", label, time.perf_counter() - started, detail
    )
