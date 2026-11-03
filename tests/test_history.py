from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Any

import httpx2
import pytest
from mcp.types import CallToolResult, TextContent

from leetcode_coach import history
from leetcode_coach.history import MCPHistoryClient, MCPHistoryError, _parse_page

TOKEN = "private-mcp-token"
URL = "https://worker.example/mcp"


@pytest.fixture(autouse=True)
def no_proxy_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(name.lower(), raising=False)


def _row(slug: str = "two-sum", timestamp: int = 123) -> dict[str, object]:
    return {
        "title": slug.replace("-", " ").title(),
        "titleSlug": slug,
        "timestamp": timestamp,
    }


def _result(rows: list[dict[str, object]], cursor: str | None = None) -> CallToolResult:
    return CallToolResult(
        content=[], structured_content={"submissions": rows, "nextCursor": cursor}
    )


def _stub_client(
    monkeypatch: pytest.MonkeyPatch, results: list[CallToolResult]
) -> list[Any]:
    calls: list[Any] = []

    @asynccontextmanager
    async def transport(url: str, *, http_client: httpx2.AsyncClient):
        assert url == URL
        assert http_client.headers["Authorization"] == f"Bearer {TOKEN}"
        assert http_client.follow_redirects is False
        yield object()

    class Client:
        def __init__(self, transport: Any, **kwargs: Any) -> None:
            self.transport = transport

        async def __aenter__(self):
            await self.transport.__aenter__()
            return self

        async def __aexit__(self, *args: object):
            await self.transport.__aexit__(*args)

        async def call_tool(self, name: str, arguments: dict[str, object]):
            calls.append((name, arguments))
            return results.pop(0)

    monkeypatch.setattr(history, "Client", Client)
    monkeypatch.setattr(history, "streamable_http_client", transport)
    return calls


def test_fetches_every_page_and_keeps_latest_problem(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _stub_client(
        monkeypatch,
        [
            _result([_row(timestamp=400)], "next-page"),
            _result([_row("three-sum", 300), _row(timestamp=200)]),
        ],
    )
    solved = MCPHistoryClient(url=URL, token=TOKEN).progress()
    assert calls == [
        ("list_ac_submissions", {"limit": 100}),
        ("list_ac_submissions", {"limit": 100, "cursor": "next-page"}),
    ]
    assert [p.title_slug for p in solved] == ["two-sum", "three-sum"]
    assert solved[0].timestamp == 400
    assert solved[0].frontend_id is None
    assert solved[0].difficulty is None
    assert solved[0].topic_tags == []
    assert solved[0].url == "https://leetcode.com/problems/two-sum/"


def test_accepts_json_text_result() -> None:
    page = _parse_page(
        CallToolResult(
            content=[
                TextContent(
                    type="text",
                    text=json.dumps({"submissions": [_row()], "nextCursor": None}),
                )
            ]
        )
    )
    assert page.submissions[0].timestamp == 123
    assert page.nextCursor is None


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"submissions": [], "nextCursor": 3},
        {"submissions": [], "nextCursor": ""},
        {
            "submissions": [{"title": "Private", "titleSlug": "private"}],
            "nextCursor": None,
        },
        {"submissions": [_row(timestamp=-1)], "nextCursor": None},
        {"submissions": [{**_row(), "timestamp": "123"}], "nextCursor": None},
        {"submissions": [{**_row(), "title": ""}], "nextCursor": None},
    ],
)
def test_rejects_invalid_pages_without_disclosing_payload(payload: Any) -> None:
    with pytest.raises(MCPHistoryError, match="invalid accepted history") as error:
        _parse_page(CallToolResult(content=[], structured_content=payload))
    assert "Private" not in str(error.value)


def test_rejects_invalid_json_text() -> None:
    with pytest.raises(MCPHistoryError, match="invalid accepted history"):
        _parse_page(
            CallToolResult(content=[TextContent(type="text", text="private body")])
        )


def test_tool_error_does_not_disclose_content(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_client(
        monkeypatch,
        [CallToolResult(content=[TextContent(type="text", text=TOKEN)], is_error=True)],
    )
    with pytest.raises(MCPHistoryError, match="reported an error") as error:
        MCPHistoryClient(url=URL, token=TOKEN).progress()
    assert TOKEN not in str(error.value)


def test_empty_history_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_client(monkeypatch, [_result([])])
    with pytest.raises(MCPHistoryError, match="no accepted problems"):
        MCPHistoryClient(url=URL, token=TOKEN).progress()


def test_repeated_cursor_fails_instead_of_truncating(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_client(monkeypatch, [_result([_row()], "cursor"), _result([], "cursor")])
    with pytest.raises(MCPHistoryError, match="repeated a cursor"):
        MCPHistoryClient(url=URL, token=TOKEN).progress()


def test_transport_failure_is_sanitized(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fail(self: Any):
        raise RuntimeError(f"Authorization: Bearer {TOKEN}; private response")

    monkeypatch.setattr(MCPHistoryClient, "_fetch", fail)
    with pytest.raises(MCPHistoryError, match="Check MCP_URL") as error:
        MCPHistoryClient(url=URL, token=TOKEN).progress()
    assert TOKEN not in str(error.value)
    assert error.value.__suppress_context__


def test_real_sdk_uses_streamable_http_with_bearer_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise SDK negotiation and tools/call over an in-memory HTTP transport."""
    methods: list[str] = []
    tool_calls: list[dict[str, Any]] = []

    def handle(request: httpx2.Request) -> httpx2.Response:
        assert str(request.url) == URL
        assert request.headers["Authorization"] == f"Bearer {TOKEN}"
        if request.method != "POST":
            return httpx2.Response(405)
        body = json.loads(request.content)
        method = body["method"]
        methods.append(method)
        if "id" not in body:
            return httpx2.Response(202)
        envelope: dict[str, Any] = {"jsonrpc": "2.0", "id": body["id"]}
        if method == "initialize":
            envelope["result"] = {
                "protocolVersion": "2025-06-18",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "leetcode-worker", "version": "1"},
            }
        elif method == "tools/call":
            tool_calls.append(body["params"])
            result = (
                _result([_row(timestamp=400)], "page-2")
                if "cursor" not in body["params"]["arguments"]
                else _result([_row("three-sum", 300)])
            )
            envelope["result"] = result.model_dump(by_alias=True)
        elif method == "tools/list":
            envelope["result"] = {
                "tools": [
                    {
                        "name": "list_ac_submissions",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "cursor": {"type": "string"},
                                "limit": {"type": "integer"},
                            },
                        },
                    }
                ]
            }
        else:
            envelope["error"] = {"code": -32601, "message": "Method not found"}
        return httpx2.Response(200, json=envelope)

    original_client = httpx2.AsyncClient

    def http_client(**kwargs: Any):
        return original_client(transport=httpx2.MockTransport(handle), **kwargs)

    monkeypatch.setattr(history.httpx2, "AsyncClient", http_client)
    solved = MCPHistoryClient(url=URL, token=TOKEN).progress()
    assert "initialize" in methods
    assert "notifications/initialized" in methods
    assert len(tool_calls) == 2
    assert tool_calls[0]["name"] == "list_ac_submissions"
    assert tool_calls[0]["arguments"] == {"limit": 100}
    assert tool_calls[1]["arguments"] == {"limit": 100, "cursor": "page-2"}
    assert [p.title_slug for p in solved] == ["two-sum", "three-sum"]
