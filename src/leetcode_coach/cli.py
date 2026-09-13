from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Iterable
from datetime import UTC, date, datetime
from pathlib import Path

from pydantic import ValidationError

from .coach import create_weekly_plan
from .leetcode import LeetCodeClient
from .log import (
    LOG_LEVEL_CHOICES,
    configure_logging,
    get_logger,
    logging_summary,
    register_secret,
    resolve_level,
)
from .models import Problem
from .settings import Settings

logger = get_logger(__name__)

#: Environment variables that may hold a credential, including the legacy aliases.
CREDENTIAL_ENV_VARS = (
    "LLM_API_KEY",
    "OPENAI_API_KEY",
    "LEETCODE_SESSION",
    "LEETCODE_CSRF_TOKEN",
)


def _candidate_secrets() -> Iterable[str]:
    """Yield credential values from the environment, whether or not settings parse."""
    return (value for name in CREDENTIAL_ENV_VARS if (value := os.environ.get(name)))


def _log_level_argument(value: str) -> str:
    """Reject an unknown ``--log-level`` at parse time, before any work happens."""
    try:
        resolve_level(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from error
    return value


def main() -> None:
    """Console-script entry point: run the CLI and log any failure before exiting.

    Schedulers only see the exit status and whatever was written to the log, so an
    unhandled error is recorded here (with a redacted traceback) rather than escaping as
    a raw traceback.
    """
    try:
        _run()
    except SystemExit:
        raise
    except KeyboardInterrupt:  # pragma: no cover - interactive only
        logger.warning("Interrupted")
        raise SystemExit(130) from None
    except Exception:
        logger.exception("leetcode-coach failed")
        raise SystemExit(1) from None


def _run() -> None:
    parser = argparse.ArgumentParser(
        description="Create a seven-day LeetCode study plan."
    )
    parser.add_argument(
        "--week-start", type=date.fromisoformat, default=datetime.now(UTC).date()
    )
    parser.add_argument(
        "--sync-only",
        action="store_true",
        help="Fetch LeetCode progress into the local cache, without calling the model.",
    )
    parser.add_argument(
        "--from-cache",
        action="store_true",
        help="Create the plan from the latest local progress cache.",
    )
    parser.add_argument(
        "--log-level",
        default=None,
        type=_log_level_argument,
        metavar="LEVEL",
        help=f"Verbosity for diagnostic output: {'|'.join(LOG_LEVEL_CHOICES)} "
        "(default: INFO, or LOG_LEVEL from .env).",
    )
    parser.add_argument(
        "--log-file",
        default=None,
        metavar="PATH",
        help="Also append log records to this file (default: LOG_FILE from .env).",
    )
    args = parser.parse_args()

    # Provisional configuration so a failure while loading settings stays visible.
    # stdout stays reserved for the user-facing result lines; logs go to stderr.
    configure_logging(
        args.log_level or os.environ.get("LOG_LEVEL") or "INFO",
        log_file=args.log_file,
        stream=sys.stderr,
    )
    logger.debug("Arguments: %s", vars(args))
    # Credentials from the environment are registered before parsing, because a settings
    # error is the most likely place for a value to be echoed back.
    register_secret(*(_candidate_secrets() or ()))
    try:
        settings = Settings()
    except ValidationError:
        logger.exception(
            "Could not load settings from the environment or .env; "
            "LEETCODE_USERNAME and LLM_API_KEY are required (see .env.example)"
        )
        raise SystemExit(2) from None

    # Settings refine the level only when the flag was not given explicitly.
    configure_logging(
        args.log_level or settings.log_level,
        log_file=args.log_file or settings.log_file,
        stream=sys.stderr,
    )
    # The values are already registered from the environment; this also catches a .env
    # file, whose contents pydantic reads without exporting to os.environ.
    offered = register_secret(
        settings.llm_api_key.get_secret_value(),
        settings.leetcode_username,
        *(
            token.get_secret_value()
            for token in (settings.leetcode_session, settings.leetcode_csrf_token)
            if token
        ),
    )
    if offered < len(CREDENTIAL_ENV_VARS) + 1:
        logger.debug(
            "Registered %s of %s credential value(s) for redaction",
            offered,
            len(CREDENTIAL_ENV_VARS) + 1,
        )
    logger.info(
        "leetcode-coach starting (username=%s, model=%s, provider=%s)",
        settings.leetcode_username,
        settings.llm_model,
        settings.llm_base_url or "OpenAI",
    )
    logger.debug("Logging configured: %s", logging_summary())
    output_dir = Path(settings.output_dir)
    cache_path = output_dir.parent / "progress.json"
    if args.from_cache:
        if not cache_path.exists():
            logger.error(
                "No progress cache at %s; run `leetcode-coach --sync-only` first.",
                cache_path,
            )
            raise RuntimeError(
                "No progress cache exists. Run `leetcode-coach --sync-only` first."
            )
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        solved = [Problem.model_validate(item) for item in cached["solved"]]
        catalog = [Problem.model_validate(item) for item in cached["catalog"]]
        logger.info(
            "Loaded cache %s: %s solved, %s catalog",
            cache_path,
            len(solved),
            len(catalog),
        )
    else:
        client = LeetCodeClient(
            session=settings.leetcode_session.get_secret_value()
            if settings.leetcode_session
            else None,
            csrf_token=settings.leetcode_csrf_token.get_secret_value()
            if settings.leetcode_csrf_token
            else None,
        )
        if not settings.leetcode_session:
            logger.warning(
                "No LEETCODE_SESSION configured; only public problem data will be visible."
            )
        solved, catalog = client.progress(settings.leetcode_username)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps(
                {
                    "solved": [item.model_dump() for item in solved],
                    "catalog": [item.model_dump() for item in catalog],
                }
            ),
            encoding="utf-8",
        )
        logger.debug(
            "Wrote progress cache %s (%s bytes)",
            cache_path,
            cache_path.stat().st_size,
        )
    if args.sync_only:
        logger.info(
            "Sync complete: %s solved, %s catalog problems cached.",
            len(solved),
            len(catalog),
        )
        print(f"Wrote {cache_path}")
        return
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"{args.week_start.isoformat()}.md"
    plan = create_weekly_plan(
        solved=solved,
        catalog=catalog,
        model=settings.llm_model,
        api_key=settings.llm_api_key.get_secret_value(),
        base_url=settings.llm_base_url,
        start_day=args.week_start,
    )
    output.write_text(plan, encoding="utf-8")
    logger.debug("Wrote %s (%s bytes)", output, output.stat().st_size)
    print(f"Wrote {output}")


if __name__ == "__main__":
    main()
