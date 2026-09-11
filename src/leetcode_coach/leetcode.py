from __future__ import annotations

from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from typing import cast

import httpx

from .log import get_logger, timed
from .models import Problem

logger = get_logger(__name__)

GRAPHQL_URL = "https://leetcode.com/graphql"
#: Matches the ``ThreadPoolExecutor`` width used by :meth:`LeetCodeClient._all_rows`.
PAGE_SIZE = 100
MAX_CONCURRENT_REQUESTS = 8

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
    def __init__(
        self, session: str | None = None, csrf_token: str | None = None
    ) -> None:
        self.cookies = {
            k: v
            for k, v in {"LEETCODE_SESSION": session, "csrftoken": csrf_token}.items()
            if v
        }
        self.headers = {
            "Content-Type": "application/json",
            "Referer": "https://leetcode.com/",
            "User-Agent": "leetcode-coach/0.1",
        }
        if csrf_token:
            self.headers["x-csrftoken"] = csrf_token
        # Log cookie names only: their values are credentials.
        logger.debug(
            "LeetCodeClient initialised (authenticated=%s, cookies=%s)",
            bool(self.cookies),
            sorted(self.cookies) or "none",
        )

    def _query(self, query: str, variables: dict[str, object]) -> dict[str, object]:
        label = " ".join(query.split())[:60]
        logger.debug("POST %s variables=%s query=%r", GRAPHQL_URL, variables, label)
        try:
            response = httpx.post(
                GRAPHQL_URL,
                json={"query": query, "variables": variables},
                headers=self.headers,
                cookies=self.cookies,
                timeout=30,
            )
        except httpx.HTTPError as error:
            logger.error("LeetCode request to %s failed: %s", GRAPHQL_URL, error)
            raise
        logger.debug(
            "LeetCode responded %s (%s bytes) for variables=%s",
            response.status_code,
            len(response.content),
            variables,
        )
        if response.is_error:
            logger.error(
                "LeetCode request failed (%s) for variables=%s: %s",
                response.status_code,
                variables,
                response.text,
            )
            raise RuntimeError(
                f"LeetCode request failed ({response.status_code}): {response.text}"
            )
        payload = response.json()
        if payload.get("errors"):
            logger.error(
                "LeetCode GraphQL error for variables=%s: %s",
                variables,
                payload["errors"],
            )
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
                raise TypeError(
                    "LeetCode returned a problem with an invalid acceptance rate."
                )
            if not isinstance(topic_tags, list) or not all(
                isinstance(tag, dict) and isinstance(tag.get("name"), str)
                for tag in topic_tags
            ):
                raise RuntimeError(
                    "LeetCode returned a problem with invalid topic tags."
                )
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

    def _questions(
        self, query: str, variables: dict[str, object]
    ) -> tuple[list[dict[str, object]], int]:
        problem_set = self._query(query, variables).get("problemsetQuestionListV2")
        if not isinstance(problem_set, dict):
            raise TypeError("LeetCode GraphQL response did not include a problem set.")
        questions = problem_set.get("questions")
        total_length = problem_set.get("totalLength")
        if not isinstance(questions, list) or not isinstance(total_length, int):
            raise TypeError(
                "LeetCode GraphQL response contained an invalid problem set."
            )
        if not all(isinstance(question, dict) for question in questions):
            raise RuntimeError(
                "LeetCode GraphQL response contained an invalid question."
            )
        return [
            cast("dict[str, object]", question) for question in questions
        ], total_length

    def _all_rows(self, query: str) -> list[dict[str, object]]:
        """LeetCode currently caps each problem-set request at 100 rows."""
        first_page, total_length = self._questions(
            query, {"skip": 0, "limit": PAGE_SIZE}
        )
        pages = [first_page]
        offsets = range(PAGE_SIZE, total_length, PAGE_SIZE)
        logger.debug(
            "Fetched first page (%s rows, %s total reported); %s page(s) remaining",
            len(first_page),
            total_length,
            len(list(offsets)),
        )

        def fetch_page(skip: int) -> list[dict[str, object]]:
            return self._questions(query, {"skip": skip, "limit": PAGE_SIZE})[0]

        # Eight concurrent requests keeps the weekly sync quick without hammering LeetCode.
        with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_REQUESTS) as executor:
            pages.extend(executor.map(fetch_page, offsets))
        rows = [row for page in pages for row in page]
        if len(rows) != total_length:
            logger.warning(
                "LeetCode reported %s questions but returned %s; the catalog may be incomplete.",
                total_length,
                len(rows),
            )
        return rows

    def solved_problems(self, username: str, limit: int = 5000) -> list[Problem]:
        """Return accepted questions visible to the signed-in LeetCode account."""
        with timed(logger, "leetcode.solved_problems", username=username) as stats:
            accepted = [
                row
                for row in self._all_rows(SOLVED_QUERY)
                if str(row.get("status")).upper() in {"AC", "SOLVED"}
            ]
            if not accepted:
                message = (
                    "LeetCode returned no accepted problems. Check that the LEETCODE_SESSION "
                    "cookie belongs to the configured account."
                )
                logger.error("%s (username=%s)", message, username)
                raise RuntimeError(message)
            stats["accepted"] = len(accepted)
            return self._problems(accepted)

    def catalog(self, limit: int = 5000) -> list[Problem]:
        with timed(logger, "leetcode.catalog") as stats:
            problems = self._problems(self._all_rows(CATALOG_QUERY))
            stats["problems"] = len(problems)
            return problems

    def progress(self, username: str) -> tuple[list[Problem], list[Problem]]:
        """Fetch the catalog once, then partition it using account-visible status."""
        with timed(logger, "leetcode.progress", username=username) as stats:
            rows = self._all_rows(CATALOG_QUERY)
            solved = self._problems(
                row
                for row in rows
                if str(row.get("status")).upper() in {"AC", "SOLVED"}
            )
            if not solved:
                message = (
                    "LeetCode returned no accepted problems. Check that the LEETCODE_SESSION "
                    "cookie belongs to the configured account."
                )
                logger.error("%s (username=%s)", message, username)
                raise RuntimeError(message)
            catalog = self._problems(rows)
            stats.update({"solved": len(solved), "catalog": len(catalog)})
            return solved, catalog
