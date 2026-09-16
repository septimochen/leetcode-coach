from __future__ import annotations

import json
import os
from datetime import UTC, date, datetime
from math import ceil

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from .log import get_logger, timed
from .models import Problem, WeeklyPlan

logger = get_logger(__name__)
SOLVED_HISTORY_SAMPLE_FRACTION = 0.8


class _AMDOpenAIChatModel(OpenAIChatModel):
    """Accept AMD's extra routing metadata on Chat Completions responses.

    AMD's gateway returns optional ``metadata`` values that do not match the
    OpenAI SDK's declared ``dict[str, str]`` shape. PydanticAI validates the
    response again, so discard this non-essential provider metadata while
    preserving choices, tool calls, usage, and structured output.
    """

    def _validate_completion(self, response):  # type: ignore[no-untyped-def]
        return super()._validate_completion(
            response.model_copy(update={"metadata": None})
        )


def _host_of(base_url: str | None) -> str:
    """Describe the provider endpoint without repeating the whole URL in every line."""
    if not base_url:
        return "api.openai.com (default)"
    return base_url.removeprefix("https://").removeprefix("http://").rstrip("/")


def _problem_data(problems: list[Problem]) -> list[dict[str, object]]:
    return [
        {
            "title": p.title,
            "lc_id": p.frontend_id,
            "slug": p.title_slug,
            "difficulty": p.difficulty,
            "topics": p.topic_tags,
            "url": p.url,
        }
        for p in problems
    ]


def _sample(problems: list[Problem], maximum: int) -> list[Problem]:
    """Keep model context bounded while preserving each difficulty level."""
    if len(problems) <= maximum:
        logger.debug("Using all %s problem(s) without sampling", len(problems))
        return problems
    buckets = [
        [p for p in problems if p.difficulty.casefold() == difficulty]
        for difficulty in ("easy", "medium", "hard")
    ]
    selected: list[Problem] = []
    for bucket in buckets:
        count = max(1, round(maximum * len(bucket) / len(problems)))
        step = max(1, len(bucket) // count)
        selected.extend(bucket[::step][:count])
    sampled = selected[:maximum]
    logger.debug(
        "Sampled %s of %s problems (%s)",
        len(sampled),
        len(problems),
        {
            difficulty.title(): sum(
                1 for p in sampled if p.difficulty.casefold() == difficulty
            )
            for difficulty in ("easy", "medium", "hard")
        },
    )
    return sampled


def _solved_history_sample(problems: list[Problem]) -> list[Problem]:
    """Keep rich prompt context for 80% of a learner's solved history."""
    return _sample(problems, ceil(len(problems) * SOLVED_HISTORY_SAMPLE_FRACTION))


def create_weekly_plan(
    *,
    solved: list[Problem],
    model: str,
    api_key: str,
    base_url: str | None = None,
    start_day: date | None = None,
) -> WeeklyPlan:
    start_day = start_day or datetime.now(UTC).date()
    logger.info(
        "Building plan for week of %s from %s solved problems",
        start_day.isoformat(),
        len(solved),
    )
    if not solved:
        logger.warning("No solved problems supplied; review blocks will be unreliable.")

    instructions = """You are an empathetic LeetCode coach. Build a sustainable
    seven-day plan from the learner's solved history. Return a structured
    WeeklyPlan. Include a concise learner summary, strengths, growth areas, and
    exactly seven consecutive days starting at week_start. Every day needs a
    focus, rationale, one to three review recommendations, and one to three
    practice recommendations. Review recommendations must use the supplied
    solved history with exact titles, lc_id values, and canonical URLs. Select
    practice problems yourself from your knowledge of real LeetCode problems:
    choose distinct, not-yet-solved problems that develop relevant gaps or
    progressively build toward the learner's level. `solved_problem_titles` is
    the complete exclusion list, including problems omitted from the
    representative history sample: never use any of those titles as practice.
    Do not reuse a practice problem during the week. Use canonical LeetCode
    problem URLs and the corresponding numeric problem id as lc_id."""

    prompt = json.dumps(
        {
            "week_start": start_day.isoformat(),
            "solved_history": _problem_data(_solved_history_sample(solved)),
            "solved_problem_titles": [problem.title for problem in solved],
        },
        ensure_ascii=False,
    )
    llm_model = _AMDOpenAIChatModel(
        model_name=model,
        provider=OpenAIProvider(api_key=api_key, base_url=base_url),
    )
    agent = Agent(
        llm_model,
        output_type=WeeklyPlan,
        instructions=instructions,
        retries=0,
    )
    logger.debug(
        "Prompt prepared for provider %s (model=%s, %s characters)",
        _host_of(base_url),
        model,
        len(prompt),
    )
    with timed(logger, "llm.structured_plan", model=model) as stats:
        result = agent.run_sync(prompt)
        usage = result.usage
        stats["provider"] = _host_of(base_url)
        if usage:
            stats.update(
                {
                    "prompt_tokens": usage.input_tokens,
                    "completion_tokens": usage.output_tokens,
                    "total_tokens": usage.input_tokens + usage.output_tokens,
                }
            )
            requests = getattr(usage, "requests", None)
            if requests is not None:
                stats["requests"] = requests
    plan = result.output
    _warn_plan_issues(plan, solved=solved, start_day=start_day)
    logger.info(
        "Plan built: %s checklist item(s)",
        sum(len(day.review) + len(day.practice) for day in plan.days),
    )
    return plan


def _warn_plan_issues(
    plan: WeeklyPlan, *, solved: list[Problem], start_day: date
) -> None:
    """Report soft semantic issues without discarding an otherwise valid plan."""
    expected_days = {
        start_day.fromordinal(start_day.toordinal() + offset) for offset in range(7)
    }
    actual_days = {day.day for day in plan.days}
    if actual_days != expected_days:
        logger.warning("Model plan dates do not match the requested week")

    solved_by_title = {problem.title.casefold(): problem for problem in solved}
    practice_titles: set[str] = set()
    for day in plan.days:
        for recommendation in day.review:
            problem = solved_by_title.get(recommendation.title.casefold())
            if problem is None or recommendation.title != problem.title:
                logger.warning(
                    "Review recommendation %r is not in solved history",
                    recommendation.title,
                )
                continue
            if (
                recommendation.lc_id != problem.frontend_id
                or recommendation.url != problem.url
            ):
                logger.warning(
                    "Review recommendation %r does not match solved metadata",
                    recommendation.title,
                )
        for recommendation in day.practice:
            title_key = recommendation.title.casefold()
            if title_key in solved_by_title:
                logger.warning(
                    "Practice recommendation %r is already solved",
                    recommendation.title,
                )
            if title_key in practice_titles:
                logger.warning(
                    "Practice recommendation %r is repeated during the week",
                    recommendation.title,
                )
            practice_titles.add(title_key)
