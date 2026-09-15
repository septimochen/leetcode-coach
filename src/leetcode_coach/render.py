"""Render validated weekly plans as Obsidian-compatible Markdown."""

from __future__ import annotations

from .models import WeeklyPlan


def render_weekly_plan(plan: WeeklyPlan) -> str:
    """Convert a structured weekly plan into the repository's Markdown format."""
    lines = ["# Weekly LeetCode Plan", "", "## Learner Summary", plan.learner_summary]
    if plan.strengths:
        lines.extend(["", "### Strengths", *[f"- {item}" for item in plan.strengths]])
    if plan.growth_areas:
        lines.extend(["", "### Growth Areas", *[f"- {item}" for item in plan.growth_areas]])
    for day in sorted(plan.days, key=lambda item: item.day):
        lines.extend(["", f"## {day.day.isoformat()} — {day.focus}", day.rationale])
        lines.extend(
            f"- [ ] Review: [{item.title}]({item.url})" for item in day.review
        )
        lines.extend(
            f"- [ ] Practice: [{item.title}]({item.url})" for item in day.practice
        )
    return "\n".join(lines) + "\n"
