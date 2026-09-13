"""Logging behaviour of the CLI: useful events without credential values."""

from __future__ import annotations

import io
import json
import logging
import sys
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from leetcode_coach import cli
from leetcode_coach import log as log_module
from leetcode_coach.models import Problem
from leetcode_coach.settings import Settings

API_KEY = "sk-cli-secret-key"
SESSION = "leetcode-session-cookie-value"
CSRF = "csrf-token-value-1234"
USERNAME = "ada"


@pytest.fixture
def cli_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Callable[..., tuple[int, str, str]]]:
    """Run the CLI in a sandbox, returning ``(exit_code, stdout, log_output)``.

    Settings come from the test environment and ``sys.stderr`` is redirected, so the
    configured handler captures each run's records. ``progress`` is always stubbed: a
    logging test must never reach LeetCode or a model provider.
    """
    logger = logging.getLogger(log_module.LOGGER_NAME)
    saved_state = (logger.level, logger.handlers[:], logger.propagate)
    output_dir = tmp_path / "data" / "plans"
    output_dir.mkdir(parents=True)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "Settings", Settings)
    for name, value in {
        "LEETCODE_USERNAME": USERNAME,
        "LLM_API_KEY": API_KEY,
        "LEETCODE_SESSION": SESSION,
        "LEETCODE_CSRF_TOKEN": CSRF,
        "OUTPUT_DIR": str(output_dir),
        "LOG_LEVEL": "DEBUG",
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("LEETCODE_COACH_LOG_FILE", raising=False)

    def run(
        argv: list[str],
        *,
        rows: list[dict[str, Any]] | None = None,
        progress: Callable[..., tuple[list[Problem], list[Problem]]] | None = None,
        cache: dict[str, Any] | None = None,
        plan: str | None = None,
    ) -> tuple[int, str, str]:
        """``rows`` stubs the progress fetch; ``progress`` stubs the whole client.

        Either way, no request leaves the test process.
        """
        stream = io.StringIO()
        stdout = io.StringIO()
        monkeypatch.setattr(sys, "stderr", stream)
        monkeypatch.setattr(sys, "stdout", stdout)
        monkeypatch.setattr(cli.sys, "argv", ["leetcode-coach", *argv])
        if rows is not None:
            monkeypatch.setattr(
                cli.LeetCodeClient, "_progress_rows", lambda self: list(rows)
            )
        if progress is not None:
            monkeypatch.setattr(cli.LeetCodeClient, "progress", progress)
        if plan is not None:
            monkeypatch.setattr(cli, "create_weekly_plan", lambda **_: plan)
        if cache is not None:
            (output_dir.parent / "progress.json").write_text(
                json.dumps(cache), encoding="utf-8"
            )
        code = 0
        try:
            cli.main()
        except SystemExit as request:
            code = int(request.code or 0)
        finally:
            for handler in logger.handlers[:]:
                handler.close()
                logger.removeHandler(handler)
            logger.handlers.clear()
            logger.setLevel(saved_state[0])
            logger.handlers.extend(saved_state[1])
            logger.propagate = saved_state[2]
        return code, stdout.getvalue(), stream.getvalue()

    yield run


def _problem(title: str = "Two Sum") -> Problem:
    return Problem(
        title=title,
        title_slug=title.lower().replace(" ", "-"),
        frontend_id="1",
        difficulty="Easy",
        topic_tags=["Array"],
    )


def _rows() -> list[dict[str, Any]]:
    """Raw progress rows, so the real ``progress()`` partitioning and timing still run."""
    return [
        {
            "title": "Two Sum",
            "titleSlug": "two-sum",
            "frontendId": "1",
            "difficulty": "Easy",
            "questionStatus": "SOLVED",
            "topicTags": [{"name": "Array"}],
        },
        {
            "title": "Two Sum II",
            "titleSlug": "two-sum-ii",
            "frontendId": "167",
            "difficulty": "Medium",
            "questionStatus": "NOT_AC",
            "topicTags": [{"name": "Two Pointers"}],
        },
    ]


def test_sync_only_logs_stages_and_keeps_stdout_clean(cli_run: Any) -> None:
    code, stdout, logs = cli_run(["--sync-only"], rows=_rows())

    assert code == 0
    # stdout still contains exactly the human-facing line the CLI has always printed.
    assert stdout.startswith("Wrote ") and stdout.strip().endswith("progress.json")
    assert f"{USERNAME}" in logs and "leetcode-coach starting" in logs
    assert "leetcode.progress: started" in logs
    assert "leetcode.progress: completed in" in logs
    assert "'solved': 1, 'catalog': 2" in logs
    assert "Sync complete: 1 solved, 2 catalog problems cached." in logs
    assert "Wrote progress cache" in logs  # DEBUG-only detail


def test_credentials_never_reach_the_log(cli_run: Any) -> None:
    code, _, logs = cli_run(["--sync-only"], rows=_rows())
    assert code == 0
    for secret in (API_KEY, SESSION, CSRF):
        assert secret not in logs, f"{secret!r} leaked into the log"
    # Credentials are still described, just not disclosed.
    assert "cookies=['LEETCODE_SESSION', 'csrftoken']" in logs


def test_missing_settings_is_logged_with_guidance(
    cli_run: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("LEETCODE_USERNAME")
    code, stdout, logs = cli_run(["--sync-only"])
    assert code == 2
    assert stdout == ""
    assert "Could not load settings" in logs
    assert "see .env.example" in logs
    assert API_KEY not in logs and SESSION not in logs


def test_unknown_log_level_is_rejected_by_argparse(cli_run: Any) -> None:
    code, _, logs = cli_run(["--sync-only", "--log-level", "chatty"])
    assert code == 2
    assert "Invalid log level" in logs


def test_missing_cache_reports_the_problem_before_the_traceback(cli_run: Any) -> None:
    code, stdout, logs = cli_run(["--from-cache"])
    assert code == 1
    assert stdout == ""
    assert "No progress cache at" in logs
    assert "run `leetcode-coach --sync-only` first" in logs
    assert "leetcode-coach failed" in logs
    assert "Traceback" in logs
    # The message is logged once by the CLI and once by the top-level handler only.
    assert logs.count("No progress cache at") == 1


def test_cache_path_reports_what_it_loaded(cli_run: Any) -> None:
    cache = {"solved": [_problem().model_dump()], "catalog": [_problem().model_dump()]}
    code, _, logs = cli_run(["--from-cache"], cache=cache)
    # Exit 1 afterwards: building the plan needs a provider, which this test never calls.
    assert code == 1
    assert "Loaded cache" in logs
    assert "Building plan for week of" in logs
    assert "provider " in logs or "provider=" in logs
    assert API_KEY not in logs


def test_plan_is_saved_as_an_obsidian_markdown_file(cli_run: Any, tmp_path: Path) -> None:
    week_start = datetime.now(UTC).date()
    cache = {"solved": [_problem().model_dump()], "catalog": [_problem().model_dump()]}
    markdown = "# Weekly Plan\n\n- [ ] Review: [Two Sum](https://leetcode.com/problems/two-sum/)\n"
    code, stdout, _ = cli_run(
        ["--from-cache", "--week-start", week_start.isoformat()],
        cache=cache,
        plan=markdown,
    )
    output = tmp_path / "data" / "plans" / f"{week_start.isoformat()}.md"
    assert code == 0
    assert stdout.strip() == f"Wrote {output}"
    assert output.read_text(encoding="utf-8") == markdown


def test_log_file_is_written_in_addition_to_stderr(
    cli_run: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log_file = tmp_path / "logs" / "coach.log"
    monkeypatch.setenv("LEETCODE_COACH_LOG_FILE", str(log_file))
    code, _, logs = cli_run(["--sync-only"], rows=_rows())

    written = log_file.read_text(encoding="utf-8")
    assert code == 0
    assert "Sync complete" in written and "Sync complete" in logs
    assert API_KEY not in written and SESSION not in written


def test_unusable_log_file_degrades_to_stderr_only(
    cli_run: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    monkeypatch.setenv("LEETCODE_COACH_LOG_FILE", str(blocker / "coach.log"))
    code, _, logs = cli_run(["--sync-only"], rows=_rows())
    assert code == 0
    assert "logging to stderr only" in logs


def test_request_detail_is_debug_only(
    cli_run: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    def offline(self: Any, username: str) -> tuple[list[Problem], list[Problem]]:
        raise RuntimeError("LeetCode request failed (503): service unavailable")

    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    code, _, logs = cli_run(["--sync-only"], progress=offline)
    assert code == 1
    # The failure still surfaces at ERROR, but the startup chatter does not.
    assert "leetcode-coach failed" in logs
    assert "leetcode-coach starting" not in logs
    assert "progress: started" not in logs
