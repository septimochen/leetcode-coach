from __future__ import annotations

import argparse
import json
from datetime import UTC, date, datetime
from pathlib import Path

from .coach import create_weekly_plan
from .leetcode import LeetCodeClient
from .models import DayPlan, Problem, Recommendation, WeeklyPlan
from .settings import Settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a seven-day LeetCode study plan.")
    parser.add_argument("--week-start", type=date.fromisoformat, default=datetime.now(UTC).date())
    parser.add_argument("--sync-only", action="store_true", help="Fetch LeetCode progress into the local cache, without calling the model.")
    parser.add_argument("--from-cache", action="store_true", help="Create the plan from the latest local progress cache.")
    parser.add_argument("--upgrade-existing", action="store_true", help="Add IDs and URLs to an existing title-only plan; requires --from-cache.")
    args = parser.parse_args()
    settings = Settings()
    output_dir = Path(settings.output_dir)
    cache_path = output_dir.parent / "progress.json"
    if args.from_cache:
        if not cache_path.exists():
            raise RuntimeError("No progress cache exists. Run `leetcode-coach --sync-only` first.")
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        solved = [Problem.model_validate(item) for item in cached["solved"]]
        catalog = [Problem.model_validate(item) for item in cached["catalog"]]
    else:
        client = LeetCodeClient(
            session=settings.leetcode_session.get_secret_value() if settings.leetcode_session else None,
            csrf_token=settings.leetcode_csrf_token.get_secret_value() if settings.leetcode_csrf_token else None,
        )
        solved, catalog = client.progress(settings.leetcode_username)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps({"solved": [item.model_dump() for item in solved], "catalog": [item.model_dump() for item in catalog]}), encoding="utf-8")
    if args.sync_only:
        print(f"Wrote {cache_path}")
        return
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"{args.week_start.isoformat()}.json"
    if args.upgrade_existing:
        raw = json.loads(output.read_text(encoding="utf-8"))
        solved_by_title = {p.title: p for p in solved}
        catalog_by_title = {p.title: p for p in catalog}
        def recommendations(titles: list[str], lookup: dict[str, Problem]) -> list[Recommendation]:
            return [Recommendation(title=title, lc_id=lookup[title].frontend_id, url=lookup[title].url) for title in titles]
        plan = WeeklyPlan(learner_summary=raw["learner_summary"], strengths=raw["strengths"], growth_areas=raw["growth_areas"], days=[DayPlan(day=entry["day"], focus=entry["focus"], review=recommendations(entry["review"], solved_by_title), practice=recommendations(entry["practice"], catalog_by_title), rationale=entry["rationale"]) for entry in raw["days"]])
        output.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
        print(f"Upgraded {output}")
        return
    plan = create_weekly_plan(
        solved=solved,
        catalog=catalog,
        model=settings.llm_model,
        api_key=settings.llm_api_key.get_secret_value(),
        base_url=settings.llm_base_url,
        start_day=args.week_start,
    )
    output.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
    print(f"Wrote {output}")


if __name__ == "__main__":
    main()
