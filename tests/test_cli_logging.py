"""Logging behaviour of the CLI: useful events without credential values."""

from __future__ import annotations

import io
import json
import logging
import sys
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from leetcode_coach import cli, coach
from leetcode_coach import log as log_module
from leetcode_coach.models import DayPlan, Problem, Recommendation, WeeklyPlan
from leetcode_coach.settings import Settings

API_KEY = "sk-cli-secret-key"
MCP_TOKEN = "private-mcp-auth-token"


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
        "LLM_API_KEY": API_KEY,
        "MCP_URL": "https://worker.example/mcp",
        "MCP_AUTH_TOKEN": MCP_TOKEN,
        "OUTPUT_DIR": str(output_dir),
        "LOG_LEVEL": "DEBUG",
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("LEETCODE_COACH_LOG_FILE", raising=False)
    monkeypatch.setattr(coach, "OpenAIProvider", lambda **_: object())
    monkeypatch.setattr(coach, "_AMDOpenAIChatModel", lambda **_: object())

    def offline_model(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("Model disabled in CLI tests")

    monkeypatch.setattr(coach, "Agent", offline_model)

    async def offline_mcp(self: Any) -> list[Problem]:
        raise RuntimeError("MCP disabled in CLI tests")

    monkeypatch.setattr(cli.MCPHistoryClient, "_fetch", offline_mcp)

    def run(
        argv: list[str],
        *,
        rows: list[dict[str, Any]] | None = None,
        progress: Callable[..., list[Problem]] | None = None,
        cache: dict[str, Any] | None = None,
        plan: WeeklyPlan | None = None,
        forwarded: dict[str, Any] | None = None,
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

            async def fetch(self: Any) -> list[Problem]:
                return [
                    Problem(
                        title=row["title"],
                        title_slug=row["titleSlug"],
                        timestamp=row["timestamp"],
                    )
                    for row in rows
                ]

            monkeypatch.setattr(cli.MCPHistoryClient, "_fetch", fetch)
        if progress is not None:
            monkeypatch.setattr(cli.MCPHistoryClient, "progress", progress)
        if plan is not None:

            def build_plan(**kwargs: Any) -> WeeklyPlan:
                if forwarded is not None:
                    forwarded.update(kwargs)
                return plan

            monkeypatch.setattr(cli, "create_weekly_plan", build_plan)
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
    """Stored MCP accepted history; the real progress timing still runs."""
    return [
        {
            "title": "Two Sum",
            "titleSlug": "two-sum",
            "timestamp": 1793696307,
        },
    ]


def test_sync_only_logs_stages_and_keeps_stdout_clean(cli_run: Any) -> None:
    code, stdout, logs = cli_run(["--sync-only"], rows=_rows())

    assert code == 0
    # stdout still contains exactly the human-facing line the CLI has always printed.
    assert stdout.startswith("Wrote ") and stdout.strip().endswith("progress.json")
    assert "leetcode-coach starting" in logs
    assert "mcp.history: started" in logs
    assert "mcp.history: completed in" in logs
    assert "'solved': 1" in logs
    assert "Sync complete: 1 solved problems cached." in logs
    assert "Wrote progress cache" in logs  # DEBUG-only detail


def test_fetch_progress_entrypoint_forces_sync_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received: dict[str, bool] = {}

    def run(*, sync_only: bool = False) -> None:
        received["sync_only"] = sync_only

    monkeypatch.setattr(cli, "_run", run)

    cli.fetch_progress()

    assert received == {"sync_only": True}


def test_cli_writes_progress_through_configured_storage(
    cli_run: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    class MemoryStorage:
        def __init__(self) -> None:
            self.objects: dict[str, str] = {}

        def read_text(self, key: str) -> str:
            return self.objects[str(key)]

        def write_text(self, key: str, content: str) -> None:
            self.objects[str(key)] = content

        def location(self, key: str) -> str:
            return f"memory://{key}"

    storage = MemoryStorage()
    monkeypatch.setattr(cli, "create_storage", lambda settings: storage)

    code, stdout, _ = cli_run(["--sync-only"], rows=_rows())

    assert code == 0
    assert any(key.endswith("data/progress.json") for key in storage.objects)
    assert stdout.strip().startswith("Wrote memory://")
    assert stdout.strip().endswith("data/progress.json")


def test_credentials_never_reach_the_log(cli_run: Any) -> None:
    code, _, logs = cli_run(["--sync-only"], rows=_rows())
    assert code == 0
    for secret in (API_KEY, MCP_TOKEN):
        assert secret not in logs, f"{secret!r} leaked into the log"


def test_missing_settings_is_logged_with_guidance(
    cli_run: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("LLM_API_KEY")
    code, stdout, logs = cli_run(["--sync-only"])
    assert code == 2
    assert stdout == ""
    assert "Could not load settings" in logs
    assert "see .env.example" in logs
    assert API_KEY not in logs and MCP_TOKEN not in logs


@pytest.mark.parametrize("missing", ["MCP_URL", "MCP_AUTH_TOKEN"])
def test_missing_mcp_settings_reports_how_to_configure(
    cli_run: Any,
    monkeypatch: pytest.MonkeyPatch,
    missing: str,
) -> None:
    monkeypatch.setenv(missing, "")
    code, stdout, logs = cli_run(["--sync-only"])
    assert code == 1
    assert stdout == ""
    assert "Set MCP_URL and MCP_AUTH_TOKEN in .env" in logs
    assert MCP_TOKEN not in logs


def test_cache_can_be_used_without_mcp_settings(
    cli_run: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MCP_URL")
    monkeypatch.delenv("MCP_AUTH_TOKEN")
    code, _, logs = cli_run(
        ["--from-cache", "--sync-only"], cache={"solved": [_problem().model_dump()]}
    )
    assert code == 0
    assert "Loaded cache" in logs


def test_failed_mcp_read_preserves_previous_cache(
    cli_run: Any,
    tmp_path: Path,
) -> None:
    cache = {"solved": [_problem().model_dump()]}
    code, stdout, logs = cli_run(["--sync-only"], cache=cache)
    assert code == 1
    assert stdout == ""
    assert "MCP history request failed" in logs
    assert json.loads((tmp_path / "data" / "progress.json").read_text()) == cache


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
    cache = {"solved": [_problem().model_dump()]}
    code, _, logs = cli_run(["--from-cache"], cache=cache)
    # Exit 1 afterwards: building the plan needs a provider, which this test never calls.
    assert code == 1
    assert "Loaded cache" in logs
    assert "Building plan for week of" in logs
    assert "provider " in logs or "provider=" in logs
    assert API_KEY not in logs


def test_plan_is_saved_as_an_obsidian_markdown_file(
    cli_run: Any, tmp_path: Path
) -> None:
    week_start = datetime.now(UTC).date()
    forwarded: dict[str, Any] = {}
    weekly_plan = WeeklyPlan(
        learner_summary="Ada likes arrays.",
        days=[
            DayPlan(
                day=week_start + timedelta(days=offset),
                focus="Arrays",
                rationale="Review and practice.",
                review=[
                    Recommendation(
                        title="Two Sum",
                        lc_id="1",
                        url="https://leetcode.com/problems/two-sum/",
                    )
                ],
                practice=[
                    Recommendation(
                        title=f"Two Sum II {offset}",
                        lc_id="167",
                        url="https://leetcode.com/problems/two-sum-ii/",
                    )
                ],
            )
            for offset in range(7)
        ],
    )
    code, stdout, _ = cli_run(
        ["--week-start", week_start.isoformat()],
        rows=_rows(),
        plan=weekly_plan,
        forwarded=forwarded,
    )
    output = tmp_path / "data" / "plans" / f"{week_start.isoformat()}.md"
    assert code == 0
    assert stdout.strip() == f"Wrote {output}"
    assert "# Weekly LeetCode Plan" in output.read_text(encoding="utf-8")
    assert "- [ ] Review: [Two Sum]" in output.read_text(encoding="utf-8")
    assert forwarded["solved"][0].timestamp == 1793696307
    assert forwarded["solved"][0].title_slug == "two-sum"
    cached = json.loads((tmp_path / "data" / "progress.json").read_text())
    assert cached["solved"][0]["timestamp"] == 1793696307


def test_log_file_is_written_in_addition_to_stderr(
    cli_run: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log_file = tmp_path / "logs" / "coach.log"
    monkeypatch.setenv("LEETCODE_COACH_LOG_FILE", str(log_file))
    code, _, logs = cli_run(["--sync-only"], rows=_rows())

    written = log_file.read_text(encoding="utf-8")
    assert code == 0
    assert "Sync complete" in written and "Sync complete" in logs
    assert API_KEY not in written and MCP_TOKEN not in written


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
    def offline(self: Any) -> list[Problem]:
        raise RuntimeError("MCP request failed (503): service unavailable")

    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    code, _, logs = cli_run(["--sync-only"], progress=offline)
    assert code == 1
    # The failure still surfaces at ERROR, but the startup chatter does not.
    assert "leetcode-coach failed" in logs
    assert "leetcode-coach starting" not in logs
    assert "progress: started" not in logs
