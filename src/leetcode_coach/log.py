"""Logging setup for LeetCode Coach.

The CLI is usually run from a scheduler (cron, a weekly task), where stdout is easy to
lose. This module gives every module a child logger under ``leetcode_coach`` and makes
it safe to log diagnostic detail from a run that handles credentials:

* :func:`register_secret` records credential values; every record produced by a logger
  from :func:`get_logger` has them replaced with ``***`` before any handler formats it,
  including rendered tracebacks.
* third-party request loggers stay quiet unless the level is explicitly lowered.

Only the standard library is used so the dependency footprint does not grow.
"""

from __future__ import annotations

import logging
import os
import sys
import time
import traceback
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
REDACTED = "***"

#: Levels accepted by ``--log-level``.
LOG_LEVEL_CHOICES = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")

#: ``LOG_LEVEL``/``--log-level`` text to level, built once (``getLevelName`` for a str
#: argument is deprecated on 3.10+).
LEVELS: dict[str, int] = {name: getattr(logging, name) for name in LOG_LEVEL_CHOICES}
LEVEL_NAMES: dict[int, str] = {value: name for name, value in LEVELS.items()}

#: Request loggers that are useful at DEBUG but far too chatty at INFO.
THIRD_PARTY_LOGGERS = ("httpx", "httpcore", "openai")

#: Values shorter than this are not redacted, to avoid mangling ordinary prose.
MIN_SECRET_LENGTH = 6

_secrets: set[str] = set()


def register_secret(*values: str | None) -> int:
    """Remember credential values so they never reach a log line.

    Call this as early as possible: values are only redacted from the moment they are
    registered, so anything logged beforehand is emitted verbatim. Returns the number of
    values accepted.
    """
    accepted = 0
    for value in values:
        if value and len(value) >= MIN_SECRET_LENGTH:
            _secrets.add(value)
            accepted += 1
    return accepted


def redact(text: str) -> str:
    """Replace every registered credential occurrence with :data:`REDACTED`."""
    for secret in _secrets:
        if secret in text:
            text = text.replace(secret, REDACTED)
    return text


def _interpolate(record: logging.LogRecord) -> str:
    """Format ``record`` defensively: bad arguments must not break the caller."""
    try:
        return str(record.getMessage())
    except TypeError, ValueError:
        return f"{record.msg!r} (formatting error with args {record.args!r})"


def _redact_record(record: logging.LogRecord) -> None:
    """Redact a record in place, before any handler formats it.

    Interpolation happens here and ``exc_info`` is replaced by pre-rendered text, so the
    redacted result is what every downstream handler sees -- including handlers this
    package does not own, such as pytest's or an embedding application's.
    """
    record.msg = redact(_interpolate(record))
    record.args = ()
    if record.exc_info:
        rendered = "".join(traceback.format_exception(*record.exc_info))
        record.exc_text = redact(rendered).rstrip()
        record.exc_info = None
    elif record.exc_text:
        record.exc_text = redact(record.exc_text)
    if record.stack_info:
        record.stack_info = redact(record.stack_info)


class RecordRedactionFilter(logging.Filter):
    """Redact records at the logger, so they stay clean whatever handler receives them."""

    def filter(self, record: logging.LogRecord) -> bool:
        _redact_record(record)
        return True


class RedactingFormatter(logging.Formatter):
    """Final line of defence: redact the fully formatted output too.

    Formatting happens at emit time, so this also covers output assembled by a formatter
    rather than by a record field.
    """

    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))


_REDACTION_FILTER = RecordRedactionFilter()


def _install_filter(logger: logging.Logger) -> None:
    """Add the redaction filter to ``logger`` and its ancestors, at most once each."""
    current: logging.Logger | None = logger
    while current is not None:
        if not any(isinstance(f, RecordRedactionFilter) for f in current.filters):
            current.filters.append(_REDACTION_FILTER)
        if current.name == LOGGER_NAME:
            break
        current = current.parent


def resolve_level(level: int | str | None, *, strict: bool = True) -> int:
    """Turn a CLI/env/setting value such as ``debug`` or ``10`` into a log level.

    ``strict`` raises on an unknown value; pass ``strict=False`` for ambient sources,
    where an unrelated shell variable should not abort a run.
    """
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
        # ``LOG_LEVEL=10`` is the conventional numeric spelling.
        return int(candidate)
    if strict:
        raise ValueError(
            f"Invalid log level {level!r}; expected one of "
            f"{', '.join(LOG_LEVEL_CHOICES)}."
        )
    return LEVELS[DEFAULT_LEVEL]


def get_logger(name: str | None = None) -> logging.Logger:
    """Return a redaction-aware logger namespaced under :data:`LOGGER_NAME`.

    Safe to call at module import time, before :func:`configure_logging`: the returned
    logger inherits whatever level and handlers are configured later.
    """
    if not name or name == LOGGER_NAME:
        logger = logging.getLogger(LOGGER_NAME)
    elif name.startswith(f"{LOGGER_NAME}."):
        logger = logging.getLogger(name)
    else:
        suffix = name.removeprefix(f"{LOGGER_NAME}.")
        logger = logging.getLogger(f"{LOGGER_NAME}.{suffix}")
    # Filters are not inherited, so each logger in the chain carries its own.
    _install_filter(logger)
    return logger


def configure_logging(
    level: int | str | None = None,
    *,
    log_file: str | os.PathLike[str] | None = None,
    stream: IO[str] | None = None,
) -> logging.Logger:
    """Install handlers for the ``leetcode_coach`` logger and return it.

    Safe to call more than once: previous handlers are removed, so the CLI can configure
    a provisional level before settings load and refine it afterwards. ``log_file`` is
    added alongside the stream rather than replacing it, so scheduler output and the
    local log file both stay useful.

    When ``level`` or ``log_file`` is omitted they are read from
    ``LEETCODE_COACH_LOG_LEVEL``/``LOG_LEVEL`` and ``LEETCODE_COACH_LOG_FILE``.
    """
    logger = logging.getLogger(LOGGER_NAME)
    _install_filter(logger)
    from_environment = level is None
    if from_environment:
        # Ambient values are advisory: an unrelated LOG_LEVEL already exported in the
        # shell should not abort a run, so an unparseable one falls back to the default.
        level = os.environ.get(LOG_LEVEL_ENV) or os.environ.get("LOG_LEVEL") or None
    if log_file is None:
        log_file = os.environ.get(LOG_FILE_ENV) or None

    resolved = resolve_level(level, strict=not from_environment)
    if resolved == logging.NOTSET:
        resolved = LEVELS[DEFAULT_LEVEL]
    formatter = RedactingFormatter(DEFAULT_FORMAT, datefmt=DATE_FORMAT)

    logger.handlers.clear()
    logger.setLevel(resolved)
    # The root logger belongs to whoever embeds us; keep our records on our own handlers.
    logger.propagate = False

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
    """Describe the active configuration; used in the CLI's startup DEBUG line."""
    logger = logging.getLogger(LOGGER_NAME)
    return {
        "level": LEVEL_NAMES.get(logger.level, logging.getLevelName(logger.level)),
        "handlers": [type(handler).__name__ for handler in logger.handlers],
        "redacted_secrets": len(_secrets),
    }


@contextmanager
def timed(
    logger: logging.Logger,
    label: str,
    *,
    level: int = logging.INFO,
    **fields: object,
) -> Iterator[dict[str, object]]:
    """Log the start, outcome, and duration of a stage.

    The yielded dict lets callers report counts that appear in the completion line::

        with timed(logger, "leetcode.sync") as stats:
            stats["rows"] = len(rows)

    Failures are logged at ERROR and then re-raised unchanged.
    """
    suffix = f" {fields}" if fields else ""
    logger.log(level, "%s: started%s", label, suffix)
    started = time.perf_counter()
    reported: dict[str, object] = dict(fields)
    try:
        yield reported
    except Exception as error:
        logger.log(
            logging.ERROR,
            "%s: failed after %.2fs: %s",
            label,
            time.perf_counter() - started,
            error,
        )
        raise
    detail = f" {reported}" if reported else ""
    logger.log(
        level,
        "%s: completed in %.2fs%s",
        label,
        time.perf_counter() - started,
        detail,
    )
