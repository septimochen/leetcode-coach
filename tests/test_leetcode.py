import logging

import httpx
import pytest

from leetcode_coach.leetcode import PROGRESS_FILTERS, PROGRESS_QUERY, LeetCodeClient


def test_converts_graphql_problem_shape() -> None:
    problems = LeetCodeClient._problems(
        [
            {
                "title": "Two Sum",
                "titleSlug": "two-sum",
                "frontendId": "1",
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
        client._query(PROGRESS_QUERY, {"filters": PROGRESS_FILTERS})
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
        LeetCodeClient()._query(PROGRESS_QUERY, {"filters": PROGRESS_FILTERS})
    assert "invalid query" in _record(caplog)


def test_progress_response_is_returned_without_pagination(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def fake_query(
        self: LeetCodeClient, query: str, variables: dict[str, object]
    ) -> dict[str, object]:
        assert query == PROGRESS_QUERY
        assert variables == {"filters": {"skip": 0, "limit": 300}}
        return {
            "userProgressQuestionList": {
                "totalNum": 1,
                "questions": [{"titleSlug": "two-sum"}],
            }
        }

    monkeypatch.setattr(LeetCodeClient, "_query", fake_query)
    with caplog.at_level(logging.DEBUG, logger="leetcode_coach"):
        rows = LeetCodeClient()._progress_rows()
    assert rows == [{"titleSlug": "two-sum"}]
    assert "progress questions but returned" not in _record(caplog)


def test_progress_logs_counts_and_fails_loudly_when_nothing_is_solved(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def rows_without_ac(self: LeetCodeClient) -> list[dict[str, object]]:
        return [
            {
                "title": "Two Sum",
                "titleSlug": "two-sum",
                "frontendId": "1",
                "difficulty": "Easy",
                "questionStatus": "NOT_AC",
                "topicTags": [],
            }
        ]

    monkeypatch.setattr(LeetCodeClient, "_progress_rows", rows_without_ac)
    with (
        caplog.at_level(logging.INFO, logger="leetcode_coach"),
        pytest.raises(RuntimeError, match="no accepted problems"),
    ):
        LeetCodeClient().progress("ada")
    assert "no accepted problems" in _record(caplog)
    assert "username=ada" in _record(caplog)
