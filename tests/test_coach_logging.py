"""Logging of the model call, including the case where the provider echoes our key."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from leetcode_coach import coach
from leetcode_coach.coach import create_weekly_plan
from leetcode_coach.log import get_logger
from leetcode_coach.models import Problem

API_KEY = "sk-coach-secret-key"
START = datetime.now(UTC).date()


def _problem(title: str) -> Problem:
    return Problem(
        title=title,
        title_slug=title.lower().replace(" ", "-"),
        frontend_id="1",
        difficulty="Easy",
        topic_tags=["Array"],
    )


def _markdown(days: list[str]) -> str:
    return "\n".join(
        ["# Ada's LeetCode Plan", "", "## Learner Summary", "Ada likes arrays."]
        + [
            line
            for day in days
            for line in (
                "",
                f"## {day} — Arrays",
                "Focus: Arrays. Spaced review.",
                "- [ ] Review: [Two Sum](https://leetcode.com/problems/two-sum/)",
                "- [ ] Practice: [Two Sum II](https://leetcode.com/problems/two-sum-ii/)",
            )
        ]
    )


class _Client:
    """Minimal stand-in for ``openai.OpenAI`` that returns canned chat content."""

    def __init__(self, content: str) -> None:
        self.calls: list[dict[str, object]] = []
        message = SimpleNamespace(content=content)
        choice = SimpleNamespace(message=message, finish_reason="length")
        usage = SimpleNamespace(
            prompt_tokens=1200, completion_tokens=800, total_tokens=2000
        )
        response = SimpleNamespace(choices=[choice], usage=usage)
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(
                create=lambda **kwargs: self.calls.append(kwargs) or response
            )
        )


@pytest.fixture
def cap_coach(
    caplog: pytest.LogCaptureFixture,
) -> Iterator[pytest.LogCaptureFixture]:
    """Capture ``leetcode_coach`` records as a handler on our own logger.

    This also proves redaction happens before formatting: the capturing handler is not
    ours, so credentials can only be absent from it because records are sanitised first.
    """
    with caplog.at_level(logging.DEBUG, logger="leetcode_coach"):
        yield caplog


def test_plan_call_logs_tokens_and_returns_checklist(
    cap_coach: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    days = [(START + timedelta(days=offset)).isoformat() for offset in range(7)]
    monkeypatch.setattr(
        coach, "OpenAI", lambda **kwargs: _Client(_markdown(days)), raising=True
    )
    plan = create_weekly_plan(
        solved=[_problem("Two Sum")],
        catalog=[_problem("Two Sum"), _problem("Two Sum II")],
        model="gpt-5-mini",
        api_key=API_KEY,
        start_day=START,
    )
    text = "\n".join(cap_coach.messages)
    assert "Building plan for week of" in text
    assert "llm.chat_completion: started {'model': 'gpt-5-mini'}" in text
    assert "'total_tokens': 2000" in text
    assert "Plan built: 14 checklist item(s)" in text
    assert API_KEY not in text
    assert plan.count("- [ ]") == 14


def test_markdown_mode_does_not_request_json_output(
    cap_coach: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    days = [(START + timedelta(days=offset)).isoformat() for offset in range(7)]
    client = _Client(_markdown(days))
    monkeypatch.setattr(
        coach,
        "OpenAI",
        lambda **kwargs: client,
        raising=True,
    )
    create_weekly_plan(
        solved=[_problem("Two Sum")],
        catalog=[_problem("Two Sum"), _problem("Two Sum II")],
        model="gpt-5-mini",
        api_key=API_KEY,
        start_day=START,
    )
    assert "response_format" not in client.calls[0]


def test_non_json_markdown_is_accepted(
    cap_coach: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        coach, "OpenAI", lambda **kwargs: _Client("# A plan\n\n- [ ] Practice"), raising=True
    )
    plan = create_weekly_plan(
        solved=[_problem("Two Sum")],
        catalog=[_problem("Two Sum"), _problem("Two Sum II")],
        model="gpt-5-mini",
        api_key=API_KEY,
        start_day=START,
    )
    assert plan == "# A plan\n\n- [ ] Practice\n"


def test_empty_model_output_is_reported(
    cap_coach: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(coach, "OpenAI", lambda **kwargs: _Client(""), raising=True)
    with pytest.raises(RuntimeError, match="did not return a study plan"):
        create_weekly_plan(
            solved=[_problem("Two Sum")],
            catalog=[_problem("Two Sum"), _problem("Two Sum II")],
            model="gpt-5-mini",
            api_key=API_KEY,
            start_day=START,
        )
    assert "returned no content" in "\n".join(cap_coach.messages)


def test_module_logger_is_namespaced() -> None:
    assert get_logger(coach.__name__).name == "leetcode_coach.coach"
