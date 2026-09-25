"""Logging and structured-output behaviour of the model call."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from openai.types.chat import ChatCompletion

from leetcode_coach import coach
from leetcode_coach.coach import (
    _AMDOpenAIChatModel,
    create_weekly_plan,
)
from leetcode_coach.log import get_logger
from leetcode_coach.models import DayPlan, Problem, Recommendation, WeeklyPlan
from leetcode_coach.render import render_weekly_plan

API_KEY = "sk-coach-secret-key"
START = datetime.now(UTC).date()


def _problem(title: str, *, frontend_id: str = "1") -> Problem:
    return Problem(
        title=title,
        title_slug=title.lower().replace(" ", "-"),
        frontend_id=frontend_id,
        difficulty="Easy",
        topic_tags=["Array"],
    )


def _plan(start: date = START, *, solved_title: str = "Two Sum") -> WeeklyPlan:
    review = Recommendation(
        title=solved_title,
        lc_id="1" if solved_title == "Two Sum" else "0",
        url=(
            "https://leetcode.com/problems/two-sum/"
            if solved_title == "Two Sum"
            else "https://leetcode.com/problems/solved-0/"
        ),
    )
    return WeeklyPlan(
        learner_summary="Ada likes arrays.",
        strengths=["Array fundamentals"],
        growth_areas=["Two pointers"],
        days=[
            DayPlan(
                day=start + timedelta(days=offset),
                focus="Arrays",
                review=[review],
                practice=[
                    Recommendation(
                        title=f"Two Sum II {offset}",
                        lc_id="167",
                        url="https://leetcode.com/problems/two-sum-ii/",
                    )
                ],
                rationale="Spaced review and a small progression step.",
            )
            for offset in range(7)
        ],
    )


class _Agent:
    def __init__(self, output: WeeklyPlan | Exception) -> None:
        self.output = output
        self.prompts: list[str] = []
        self.kwargs: dict[str, Any] = {}

    def run_sync(self, prompt: str) -> Any:
        self.prompts.append(prompt)
        if isinstance(self.output, Exception):
            raise self.output
        return SimpleNamespace(
            output=self.output,
            usage=SimpleNamespace(input_tokens=1200, output_tokens=800),
        )


@pytest.fixture
def cap_coach(
    caplog: pytest.LogCaptureFixture,
) -> Iterator[pytest.LogCaptureFixture]:
    with caplog.at_level(logging.DEBUG, logger="leetcode_coach"):
        yield caplog


def _patch_agent(monkeypatch: pytest.MonkeyPatch, output: WeeklyPlan | Exception) -> _Agent:
    agent = _Agent(output)
    monkeypatch.setattr(coach, "OpenAIProvider", lambda **kwargs: object())
    monkeypatch.setattr(coach, "_AMDOpenAIChatModel", lambda *args, **kwargs: object())

    def create_agent(*args: Any, **kwargs: Any) -> _Agent:
        agent.kwargs = kwargs
        return agent

    monkeypatch.setattr(coach, "Agent", create_agent)
    return agent


def test_plan_call_logs_tokens_and_returns_structured_plan(
    cap_coach: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_agent(monkeypatch, _plan())
    plan = create_weekly_plan(
        solved=[_problem("Two Sum")],
        model="gpt-5-mini",
        api_key=API_KEY,
        start_day=START,
    )
    text = "\n".join(cap_coach.messages)
    assert "Building plan for week of" in text
    assert "llm.structured_plan: started {'model': 'gpt-5-mini'}" in text
    assert "'total_tokens': 2000" in text
    assert "Plan built: 14 checklist item(s)" in text
    assert API_KEY not in text
    assert isinstance(plan, WeeklyPlan)
    assert len(render_weekly_plan(plan).splitlines()) > 14


def test_structured_output_uses_tool_schema_without_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _patch_agent(monkeypatch, _plan())
    create_weekly_plan(
        solved=[_problem("Two Sum")],
        model="gpt-5-mini",
        api_key=API_KEY,
        start_day=START,
    )
    assert agent.kwargs["output_type"] is WeeklyPlan
    assert agent.kwargs["retries"] == 0


def test_structured_prompt_contains_full_exclusion_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _patch_agent(monkeypatch, _plan())
    solved = [_problem("Two Sum")]
    create_weekly_plan(
        solved=solved,
        model="gpt-5-mini",
        api_key=API_KEY,
        start_day=START,
    )
    input_data = json.loads(agent.prompts[0])
    assert set(input_data) == {"week_start", "solved_history", "solved_problem_titles"}
    assert input_data["solved_problem_titles"] == ["Two Sum"]


def test_model_errors_are_logged_and_propagated(
    cap_coach: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_agent(monkeypatch, RuntimeError("provider failed"))
    with pytest.raises(RuntimeError, match="provider failed"):
        create_weekly_plan(
            solved=[_problem("Two Sum")],
            model="gpt-5-mini",
            api_key=API_KEY,
            start_day=START,
        )
    assert "llm.structured_plan: failed" in "\n".join(cap_coach.messages)


def test_semantic_issues_are_warnings_not_failures(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan()
    plan.days[0].practice[0].title = "Two Sum"
    _patch_agent(monkeypatch, plan)
    with caplog.at_level(logging.WARNING, logger="leetcode_coach.coach"):
        create_weekly_plan(
            solved=[_problem("Two Sum")],
            model="gpt-5-mini",
            api_key=API_KEY,
            start_day=START,
        )
    assert "Practice recommendation 'Two Sum' is already solved" in caplog.text


def test_full_solved_history_and_titles_are_sent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    solved = [
        Problem(
            title=f"Solved {index}",
            title_slug=f"solved-{index}",
            frontend_id=str(index),
            difficulty="HARD",
        )
        for index in range(206)
    ]
    agent = _patch_agent(monkeypatch, _plan(solved_title="Solved 0"))
    create_weekly_plan(
        solved=solved,
        model="gpt-5-mini",
        api_key=API_KEY,
        start_day=START,
    )
    input_data = json.loads(agent.prompts[0])
    assert len(input_data["solved_history"]) == len(solved)
    assert input_data["solved_history"][-1]["title"] == "Solved 205"
    assert input_data["solved_problem_titles"] == [problem.title for problem in solved]


def test_module_logger_is_namespaced() -> None:
    assert get_logger(coach.__name__).name == "leetcode_coach.coach"


def test_amd_metadata_is_ignored_during_response_validation() -> None:
    response = ChatCompletion.model_construct(
        id="completion-1",
        choices=[
            {
                "finish_reason": "stop",
                "index": 0,
                "message": {"content": "ok", "role": "assistant"},
            }
        ],
        created=1,
        model="DeepSeek-V4-Flash-Vision-Exp",
        object="chat.completion",
        metadata={
            "requested_provider": None,
            "routing": [{"provider": "self-deployed"}],
            "discount": None,
        },
    )
    model = object.__new__(_AMDOpenAIChatModel)

    validated = model._validate_completion(response)

    assert validated.metadata is None
    assert validated.choices[0].message.content == "ok"
