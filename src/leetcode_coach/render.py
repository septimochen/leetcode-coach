"""Render validated weekly plans as Obsidian-compatible Markdown."""

from __future__ import annotations

from html import escape

from .models import Recommendation, WeeklyPlan


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


def render_weekly_plan_email(plan: WeeklyPlan) -> str:
    """Convert a structured plan into a self-contained HTML email body.

    Inline styles are intentional: many email clients discard external stylesheets.
    Escape all model-provided fields before adding them to the document.
    """
    review_count = sum(len(day.review) for day in plan.days)
    practice_count = sum(len(day.practice) for day in plan.days)
    first_day = min(day.day for day in plan.days)
    last_day = max(day.day for day in plan.days)

    def item_html(item: Recommendation, label: str, accent: str) -> str:
        title = escape(item.title)
        url = escape(item.url, quote=True)
        lc_id = escape(item.lc_id)
        return (
            '<li style="margin:0 0 8px;line-height:1.45">'
            f'<span style="color:{accent};font-weight:700">{label}</span> '
            f'<a href="{url}" style="color:#2563eb;text-decoration:none">'
            f'{title}</a> <span style="color:#6b7280">#{lc_id}</span></li>'
        )

    day_sections: list[str] = []
    for day in sorted(plan.days, key=lambda item: item.day):
        review_items = "".join(item_html(item, "Review", "#047857") for item in day.review)
        practice_items = "".join(
            item_html(item, "Practice", "#b45309") for item in day.practice
        )
        day_sections.append(
            '<section style="margin:20px 0;padding:20px;background:#ffffff;'
            'border:1px solid #e5e7eb;border-radius:12px">'
            f'<div style="font-size:13px;font-weight:700;letter-spacing:.06em;'
            f'text-transform:uppercase;color:#6b7280">{day.day.strftime("%A, %B %-d")}</div>'
            f'<h2 style="margin:6px 0 10px;font-size:20px;color:#111827">'
            f'{escape(day.focus)}</h2>'
            f'<p style="margin:0 0 14px;line-height:1.55;color:#374151">'
            f'{escape(day.rationale)}</p>'
            f'<ul style="margin:0;padding-left:20px">{review_items}{practice_items}</ul>'
            '</section>'
        )

    def bullets(items: list[str]) -> str:
        return "".join(
            f'<li style="margin:0 0 6px;line-height:1.45">{escape(item)}</li>'
            for item in items
        )

    strengths = (
        '<div style="flex:1;min-width:220px;padding:16px;background:#ecfdf5;'
        'border-radius:10px"><h3 style="margin:0 0 8px;color:#065f46">Strengths</h3>'
        f'<ul style="margin:0;padding-left:20px;color:#065f46">{bullets(plan.strengths)}</ul></div>'
        if plan.strengths
        else ""
    )
    growth_areas = (
        '<div style="flex:1;min-width:220px;padding:16px;background:#fffbeb;'
        'border-radius:10px"><h3 style="margin:0 0 8px;color:#92400e">Growth areas</h3>'
        f'<ul style="margin:0;padding-left:20px;color:#92400e">{bullets(plan.growth_areas)}</ul></div>'
        if plan.growth_areas
        else ""
    )

    return (
        '<!doctype html><html lang="en"><body style="margin:0;padding:24px;'
        'background:#f3f4f6;font-family:Arial,sans-serif;color:#111827">'
        '<main style="max-width:680px;margin:0 auto">'
        '<header style="padding:28px;background:#111827;border-radius:14px;color:#fff">'
        '<p style="margin:0 0 8px;font-size:14px;color:#cbd5e1">YOUR WEEKLY STUDY PLAN</p>'
        '<h1 style="margin:0;font-size:30px">LeetCode Coach</h1>'
        f'<p style="margin:10px 0 0;color:#e5e7eb">{first_day.strftime("%B %-d")}–'
        f'{last_day.strftime("%B %-d, %Y")}</p></header>'
        '<section style="margin:20px 0;padding:20px;background:#ffffff;border-radius:12px">'
        '<h2 style="margin:0 0 8px;font-size:20px">This week at a glance</h2>'
        f'<p style="margin:0;line-height:1.55;color:#374151">{escape(plan.learner_summary)}</p>'
        '<div style="display:flex;gap:12px;margin-top:16px">'
        f'<div style="flex:1;padding:12px;background:#ecfdf5;border-radius:8px">'
        f'<strong style="font-size:22px;color:#065f46">{review_count}</strong><br>'
        '<span style="color:#065f46">reviews</span></div>'
        f'<div style="flex:1;padding:12px;background:#fff7ed;border-radius:8px">'
        f'<strong style="font-size:22px;color:#9a3412">{practice_count}</strong><br>'
        '<span style="color:#9a3412">practice problems</span></div></div></section>'
        f'<section style="display:flex;flex-wrap:wrap;gap:12px">{strengths}{growth_areas}</section>'
        f'{"".join(day_sections)}'
        '<footer style="padding:8px 0 0;text-align:center;color:#6b7280;font-size:13px">'
        'Your Obsidian-compatible Markdown checklist is attached.</footer>'
        '</main></body></html>'
    )
