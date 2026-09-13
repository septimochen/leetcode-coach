from __future__ import annotations

from collections.abc import Iterable
from typing import cast

import httpx

from .log import get_logger, timed
from .models import Problem

logger = get_logger(__name__)

GRAPHQL_URL = "https://leetcode.com/graphql"
PROGRESS_FILTERS: dict[str, int] = {"skip": 0, "limit": 300}

PROGRESS_QUERY = """
query userProgressQuestionList($filters: UserProgressQuestionListInput) {
  userProgressQuestionList(filters: $filters) {
    totalNum
    questions {
      translatedTitle
      frontendId
      title
      titleSlug
      difficulty
      lastSubmittedAt
      numSubmitted
      questionStatus
      lastResult
      topicTags {
        name
        nameTranslated
        slug
      }
    }
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
            frontend_id = row.get("frontendId")
            difficulty = row.get("difficulty")
            topic_tags = row.get("topicTags", [])
            if not isinstance(title, str):
                raise TypeError("LeetCode returned a problem with invalid text fields.")
            if not isinstance(title_slug, str):
                raise TypeError("LeetCode returned a problem with invalid text fields.")
            if not isinstance(frontend_id, str):
                raise TypeError("LeetCode returned a problem with invalid text fields.")
            if not isinstance(difficulty, str):
                raise TypeError("LeetCode returned a problem with invalid text fields.")
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
                    topic_tags=[tag["name"] for tag in topic_tags],
                )
            )
        return problems

    def _progress_rows(self) -> list[dict[str, object]]:
        progress = self._query(PROGRESS_QUERY, {"filters": PROGRESS_FILTERS}).get(
            "userProgressQuestionList"
        )
        if not isinstance(progress, dict):
            raise TypeError("LeetCode GraphQL response did not include user progress.")
        questions = progress.get("questions")
        total_num = progress.get("totalNum")
        if not isinstance(questions, list) or not isinstance(total_num, int):
            raise TypeError("LeetCode GraphQL response contained invalid user progress.")
        if not all(isinstance(question, dict) for question in questions):
            raise RuntimeError("LeetCode GraphQL response contained an invalid question.")
        if len(questions) != total_num:
            logger.warning(
                "LeetCode reported %s progress questions but returned %s.",
                total_num,
                len(questions),
            )
        return [cast("dict[str, object]", question) for question in questions]

    def progress(self, username: str) -> list[Problem]:
        """Fetch accepted account progress and topic categories once."""
        with timed(logger, "leetcode.progress", username=username) as stats:
            rows = self._progress_rows()
            solved = self._problems(
                row
                for row in rows
                if str(row.get("questionStatus")).upper() in {"AC", "SOLVED"}
            )
            if not solved:
                message = (
                    "LeetCode returned no accepted problems. Check that the LEETCODE_SESSION "
                    "cookie belongs to the configured account."
                )
                logger.error("%s (username=%s)", message, username)
                raise RuntimeError(message)
            stats["solved"] = len(solved)
            return solved
