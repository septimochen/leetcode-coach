from __future__ import annotations

from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor

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
        return payload["data"]

    @staticmethod
    def _problems(rows: Iterable[dict[str, object]]) -> list[Problem]:
        return [Problem(title=row["title"], title_slug=row["titleSlug"], frontend_id=row["questionFrontendId"], difficulty=row["difficulty"], ac_rate=row.get("acRate"), topic_tags=[tag["name"] for tag in row.get("topicTags", [])]) for row in rows]

    def _all_rows(self, query: str) -> list[dict[str, object]]:
        """LeetCode currently caps each problem-set request at 100 rows."""
        first = self._query(query, {"skip": 0, "limit": 100})["problemsetQuestionListV2"]
        pages = [first["questions"]]
        offsets = range(100, int(first["totalLength"]), 100)

        def fetch_page(skip: int) -> list[dict[str, object]]:
            return self._query(query, {"skip": skip, "limit": 100})["problemsetQuestionListV2"]["questions"]

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
