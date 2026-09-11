import logging

import httpx
import pytest

from leetcode_coach.leetcode import CATALOG_QUERY, LeetCodeClient


def test_converts_graphql_problem_shape() -> None:
    problems = LeetCodeClient._problems(
        [
            {
                "title": "Two Sum",
                "titleSlug": "two-sum",
                "questionFrontendId": "1",
                "difficulty": "Easy",
                "acRate": 55.3,
                "topicTags": [{"name": "Array"}, {"name": "Hash Table"}],
            }
        ]
    )
    assert problems[0].title_slug == "two-sum"
    assert problems[0].frontend_id == "1"
    assert problems[0].topic_tags == ["Array", "Hash Table"]
    assert problems[0].url == "https://leetcode.com/problems/two-sum/"


def _record(caplog: pytest.LogCaptureFixture) -> str:
    return "\n".join(caplog.messages)


def test_http_failure_is_logged_once_with_the_status(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    class Response:
        status_code = 503
        is_error = True
        text = "upstream blocked"
        content = b"upstream blocked"

    monkeypatch.setattr(httpx, "post", lambda *a, **k: Response())
    client = LeetCodeClient(session="session-cookie-value")
    with (
        caplog.at_level(logging.DEBUG, logger="leetcode_coach"),
        pytest.raises(RuntimeError, match="503"),
    ):
        client._query(CATALOG_QUERY, {"skip": 0, "limit": 100})
    messages = _record(caplog)
    assert "LeetCode request failed (503)" in messages
    assert "session-cookie-value" not in messages  # the cookie stays out of the log


def test_graphql_error_is_logged(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    class Response:
        status_code = 200
        is_error = False
        content = b"{}"

        def json(self) -> dict[str, object]:
            return {"errors": [{"message": "invalid query"}]}

    monkeypatch.setattr(httpx, "post", lambda *a, **k: Response())
    with (
        caplog.at_level(logging.DEBUG, logger="leetcode_coach"),
        pytest.raises(RuntimeError, match="GraphQL error"),
    ):
        LeetCodeClient()._query(CATALOG_QUERY, {"skip": 0, "limit": 100})
    assert "invalid query" in _record(caplog)


def test_short_catalog_is_reported_as_possibly_incomplete(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A page count that disagrees with totalLength is the classic silent-truncation bug."""

    def fake_questions(
        self: LeetCodeClient, query: str, variables: dict[str, object]
    ) -> tuple[list[dict[str, object]], int]:
        return [{"titleSlug": "two-sum"}], 300

    monkeypatch.setattr(LeetCodeClient, "_questions", fake_questions)
    with caplog.at_level(logging.DEBUG, logger="leetcode_coach"):
        rows = LeetCodeClient()._all_rows(CATALOG_QUERY)
    assert len(rows) == 3
    assert "reported 300 questions but returned 3" in _record(caplog)


def test_progress_logs_counts_and_fails_loudly_when_nothing_is_solved(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def rows_without_ac(self: LeetCodeClient, query: str) -> list[dict[str, object]]:
        return [
            {
                "title": "Two Sum",
                "titleSlug": "two-sum",
                "questionFrontendId": "1",
                "difficulty": "Easy",
                "status": "NOT_AC",
                "topicTags": [],
            }
        ]

    monkeypatch.setattr(LeetCodeClient, "_all_rows", rows_without_ac)
    with (
        caplog.at_level(logging.INFO, logger="leetcode_coach"),
        pytest.raises(RuntimeError, match="no accepted problems"),
    ):
        LeetCodeClient().progress("ada")
    assert "no accepted problems" in _record(caplog)
    assert "username=ada" in _record(caplog)
