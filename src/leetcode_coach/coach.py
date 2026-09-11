from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

from openai import OpenAI

from .log import get_logger, register_secret, timed
from .models import DayPlan, DraftWeeklyPlan, Problem, Recommendation, WeeklyPlan

logger = get_logger(__name__)
#: How much raw model output to keep in a DEBUG log line.
CONTENT_PREVIEW_CHARS = 500


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
        [p for p in problems if p.difficulty == difficulty]
        for difficulty in ("Easy", "Medium", "Hard")
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
            difficulty: sum(1 for p in sampled if p.difficulty == difficulty)
            for difficulty in ("Easy", "Medium", "Hard")
        },
    )
    return sampled


def create_weekly_plan(
    *,
    solved: list[Problem],
    catalog: list[Problem],
    model: str,
    api_key: str,
    base_url: str | None = None,
    start_day: date | None = None,
) -> WeeklyPlan:
    start_day = start_day or datetime.now(UTC).date()
    register_secret(api_key)
    solved_slugs = {p.title_slug for p in solved}
    unsolved = [p for p in catalog if p.title_slug not in solved_slugs]
    logger.info(
        "Building plan for week of %s: %s solved, %s catalog, %s unsolved",
        start_day.isoformat(),
        len(solved),
        len(catalog),
        len(unsolved),
    )
    if not solved:
        logger.warning("No solved problems supplied; review blocks will be unreliable.")
    instructions = """You are an empathetic LeetCode coach. Build a sustainable seven-day plan from the supplied data. Every day must include 1-3 review problems selected ONLY from solved_problems and 1-3 practice problems selected ONLY from unsolved_problems. Use exact titles. Prefer weak or underrepresented topics for practice and spaced, varied review. Do not invent problems. Keep each rationale brief. Return only valid JSON matching this shape: {learner_summary: string, strengths: string[], growth_areas: string[], days: [{day: YYYY-MM-DD, focus: string, review: string[], practice: string[], rationale: string}]}."""
    prompt = json.dumps(
        {
            "week_start": start_day.isoformat(),
            "solved_problems": _problem_data(_sample(solved, 100)),
            "unsolved_problems": _problem_data(_sample(unsolved, 150)),
        },
        ensure_ascii=False,
    )
    # Chat Completions is the most broadly supported OpenAI-compatible endpoint.
    client = OpenAI(api_key=api_key, base_url=base_url)
    logger.debug(
        "Prompt prepared for provider %s (model=%s, %s characters)",
        _host_of(base_url),
        model,
        len(prompt),
    )
    with timed(logger, "llm.chat_completion", model=model) as stats:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": instructions},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            max_tokens=1_800,
        )
        usage = response.usage
        stats["provider"] = _host_of(base_url)
        if usage:
            stats.update(
                {
                    "prompt_tokens": usage.prompt_tokens,
                    "completion_tokens": usage.completion_tokens,
                    "total_tokens": usage.total_tokens,
                }
            )
    content = response.choices[0].message.content
    logger.debug(
        "Model returned %s characters (finish_reason=%s)",
        len(content or ""),
        response.choices[0].finish_reason,
    )
    if not content:
        logger.error(
            "Model %s returned no content (finish_reason=%s)",
            model,
            response.choices[0].finish_reason,
        )
        raise RuntimeError("The model did not return a study plan.")
    try:
        draft = DraftWeeklyPlan.model_validate_json(content)
    except ValueError as error:
        logger.error(
            "Could not parse the model response as a DraftWeeklyPlan: %s\n--- response (first %s chars) ---\n%s",
            error,
            CONTENT_PREVIEW_CHARS,
            content[:CONTENT_PREVIEW_CHARS],
        )
        raise RuntimeError(
            "The model returned an invalid study plan; verify JSON-mode support for the configured provider."
        ) from error

    def enrich(titles: list[str], choices: list[Problem]) -> list[Recommendation]:
        lookup = {p.title: p for p in choices}
        missing = [title for title in titles if title not in lookup]
        if missing:
            logger.warning(
                "Model recommended %s title(s) absent from the supplied problems: %s",
                len(missing),
                missing,
            )
        return [
            Recommendation(
                title=title, lc_id=lookup[title].frontend_id, url=lookup[title].url
            )
            for title in titles
        ]

    plan = WeeklyPlan(
        learner_summary=draft.learner_summary,
        strengths=draft.strengths,
        growth_areas=draft.growth_areas,
        days=[
            DayPlan(
                day=entry.day,
                focus=entry.focus,
                review=enrich(entry.review, solved),
                practice=enrich(entry.practice, unsolved),
                rationale=entry.rationale,
            )
            for entry in draft.days
        ],
    )
    expected_days = [start_day + timedelta(days=index) for index in range(7)]
    if [entry.day for entry in plan.days] != expected_days:
        logger.error(
            "Model returned dates %s outside the requested window %s..%s",
            [entry.day.isoformat() for entry in plan.days],
            expected_days[0].isoformat(),
            expected_days[-1].isoformat(),
        )
        raise RuntimeError(
            "The model returned dates outside the requested seven-day window."
        )
    logger.info(
        "Plan built: %s review and %s practice recommendation(s)",
        sum(len(day.review) for day in plan.days),
        sum(len(day.practice) for day in plan.days),
    )
    return plan
