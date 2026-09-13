from __future__ import annotations

import json
from datetime import UTC, date, datetime
from math import ceil

from openai import OpenAI

from .log import get_logger, timed
from .models import Problem

logger = get_logger(__name__)
SOLVED_HISTORY_SAMPLE_FRACTION = 0.8


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
) -> str:
    start_day = start_day or datetime.now(UTC).date()
    logger.info(
        "Building plan for week of %s from %s solved problems",
        start_day.isoformat(),
        len(solved),
    )
    if not solved:
        logger.warning("No solved problems supplied; review blocks will be unreliable.")
    instructions = """You are an empathetic LeetCode coach. Build a sustainable seven-day plan from the learner's solved history. Return only Obsidian-compatible Markdown, not JSON and not a code fence. Start with a level-one title, followed by a short learner summary, strengths, and growth areas. Create one level-two heading for every date from week_start through the following six days. Under each day, include a short focus and rationale, then Markdown checklist tasks in exactly the form `- [ ] Review: [Problem title](URL)` or `- [ ] Practice: [Problem title](URL)`. Review tasks must use the supplied solved history with its exact titles and URLs. Select practice tasks yourself from your knowledge of real LeetCode problems: choose a distinct, not-yet-solved problem that develops a relevant gap or progressively builds toward the learner's level. `solved_problem_titles` is the complete exclusion list, including problems omitted from the representative history sample: never use any of those titles as practice. Do not reuse a practice problem during the week and do not substitute a second review for practice. Use canonical LeetCode problem URLs. Every day must include at least one review and one practice checklist task."""
    prompt = json.dumps(
        {
            "week_start": start_day.isoformat(),
            "solved_history": _problem_data(_solved_history_sample(solved)),
            "solved_problem_titles": [problem.title for problem in solved],
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
    plan = content.strip() + "\n"
    logger.info(
        "Plan built: %s checklist item(s)",
        sum(1 for line in plan.splitlines() if line.startswith("- [ ]")),
    )
    return plan
