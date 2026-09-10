from __future__ import annotations

from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from typing import cast

import httpx

from .models import Problem

GRAPHQL_URL = "https://leetcode.com/graphql"

SOLVED_QUERY = """
query solvedProblems($skip: Int!, $limit: Int!) {
  problemsetQuestionListV2(
    filters: { filterCombineType: ALL }
    limit: $limit skip: $skip searchKeyword: ""
  ) {
    questions { title titleSlug questionFrontendId difficulty acRate status topicTags { name } }
    totalLength
    hasMore
  }
}
"""

CATALOG_QUERY = """
query catalog($skip: Int!, $limit: Int!) {
  problemsetQuestionListV2(
    filters: { filterCombineType: ALL }
    limit: $limit skip: $skip searchKeyword: ""
  ) {
    questions { title titleSlug questionFrontendId difficulty acRate status topicTags { name } }
    totalLength
    hasMore
  }
}
"""


class LeetCodeClient:
    def __init__(self, session: str | None = None, csrf_token: str | None = None) -> None:
        self.cookies = {k: v for k, v in {"LEETCODE_SESSION": session, "csrftoken": csrf_token}.items() if v}
        self.headers = {
            "Content-Type": "application/json",
            "Referer": "https://leetcode.com/",
            "User-Agent": "leetcode-coach/0.1",
        }
        if csrf_token:
            self.headers["x-csrftoken"] = csrf_token

    def _query(self, query: str, variables: dict[str, object]) -> dict[str, object]:
        response = httpx.post(GRAPHQL_URL, json={"query": query, "variables": variables}, headers=self.headers, cookies=self.cookies, timeout=30)
        if response.is_error:
            raise RuntimeError(f"LeetCode request failed ({response.status_code}): {response.text}")
        payload = response.json()
        if payload.get("errors"):
            raise RuntimeError(f"LeetCode GraphQL error: {payload['errors']}")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise TypeError("LeetCode GraphQL response did not include data.")
        return cast("dict[str, object]", data)

    @staticmethod
    def _problems(rows: Iterable[dict[str, object]]) -> list[Problem]:
        problems: list[Problem] = []
        for row in rows:
            title = row.get("title")
            title_slug = row.get("titleSlug")
            frontend_id = row.get("questionFrontendId")
            difficulty = row.get("difficulty")
            ac_rate = row.get("acRate")
            topic_tags = row.get("topicTags", [])
            if not isinstance(title, str):
                raise TypeError("LeetCode returned a problem with invalid text fields.")
            if not isinstance(title_slug, str):
                raise TypeError("LeetCode returned a problem with invalid text fields.")
            if not isinstance(frontend_id, str):
                raise TypeError("LeetCode returned a problem with invalid text fields.")
            if not isinstance(difficulty, str):
                raise TypeError("LeetCode returned a problem with invalid text fields.")
            if ac_rate is not None and not isinstance(ac_rate, int | float):
                raise TypeError("LeetCode returned a problem with an invalid acceptance rate.")
            if not isinstance(topic_tags, list) or not all(isinstance(tag, dict) and isinstance(tag.get("name"), str) for tag in topic_tags):
                raise RuntimeError("LeetCode returned a problem with invalid topic tags.")
            problems.append(
                Problem(
                    title=title,
                    title_slug=title_slug,
                    frontend_id=frontend_id,
                    difficulty=difficulty,
                    ac_rate=ac_rate,
                    topic_tags=[tag["name"] for tag in topic_tags],
                )
            )
        return problems

    def _questions(self, query: str, variables: dict[str, object]) -> tuple[list[dict[str, object]], int]:
        problem_set = self._query(query, variables).get("problemsetQuestionListV2")
        if not isinstance(problem_set, dict):
            raise TypeError("LeetCode GraphQL response did not include a problem set.")
        questions = problem_set.get("questions")
        total_length = problem_set.get("totalLength")
        if not isinstance(questions, list) or not isinstance(total_length, int):
            raise TypeError("LeetCode GraphQL response contained an invalid problem set.")
        if not all(isinstance(question, dict) for question in questions):
            raise RuntimeError("LeetCode GraphQL response contained an invalid question.")
        return [cast("dict[str, object]", question) for question in questions], total_length

    def _all_rows(self, query: str) -> list[dict[str, object]]:
        """LeetCode currently caps each problem-set request at 100 rows."""
        first_page, total_length = self._questions(query, {"skip": 0, "limit": 100})
        pages = [first_page]
        offsets = range(100, total_length, 100)

        def fetch_page(skip: int) -> list[dict[str, object]]:
            questions, _ = self._questions(query, {"skip": skip, "limit": 100})
            return questions

        # Eight concurrent requests keeps the weekly sync quick without hammering LeetCode.
        with ThreadPoolExecutor(max_workers=8) as executor:
            pages.extend(executor.map(fetch_page, offsets))
        return [row for page in pages for row in page]

    def solved_problems(self, username: str, limit: int = 5000) -> list[Problem]:
        """Return accepted questions visible to the signed-in LeetCode account."""
        accepted = [row for row in self._all_rows(SOLVED_QUERY) if str(row.get("status")).upper() in {"AC", "SOLVED"}]
        if not accepted:
            raise RuntimeError("LeetCode returned no accepted problems. Check that the LEETCODE_SESSION cookie belongs to the configured account.")
        return self._problems(accepted)

    def catalog(self, limit: int = 5000) -> list[Problem]:
        return self._problems(self._all_rows(CATALOG_QUERY))

    def progress(self, username: str) -> tuple[list[Problem], list[Problem]]:
        """Fetch the catalog once, then partition it using account-visible status."""
        rows = self._all_rows(CATALOG_QUERY)
        solved = self._problems(row for row in rows if str(row.get("status")).upper() in {"AC", "SOLVED"})
        if not solved:
            raise RuntimeError("LeetCode returned no accepted problems. Check that the LEETCODE_SESSION cookie belongs to the configured account.")
        return solved, self._problems(rows)
