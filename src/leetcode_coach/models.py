from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class Problem(BaseModel):
    title: str
    title_slug: str
    frontend_id: str
    difficulty: str
    topic_tags: list[str] = Field(default_factory=list)
    ac_rate: float | None = None

    @property
    def url(self) -> str:
        return f"https://leetcode.com/problems/{self.title_slug}/"


class Recommendation(BaseModel):
    title: str
    lc_id: str
    url: str


class DayPlan(BaseModel):
    day: date
    focus: str
    review: list[Recommendation] = Field(
        default_factory=list, min_length=1, max_length=3
    )
    practice: list[Recommendation] = Field(
        default_factory=list, min_length=1, max_length=3
    )
    rationale: str


class WeeklyPlan(BaseModel):
    learner_summary: str
    strengths: list[str] = Field(default_factory=list)
    growth_areas: list[str] = Field(default_factory=list)
    days: list[DayPlan] = Field(min_length=7, max_length=7)


class DraftDayPlan(BaseModel):
    day: date
    focus: str
    review: list[str] = Field(min_length=1, max_length=3)
    practice: list[str] = Field(min_length=1, max_length=3)
    rationale: str


class DraftWeeklyPlan(BaseModel):
    learner_summary: str
    strengths: list[str] = Field(default_factory=list)
    growth_areas: list[str] = Field(default_factory=list)
    days: list[DraftDayPlan] = Field(min_length=7, max_length=7)
