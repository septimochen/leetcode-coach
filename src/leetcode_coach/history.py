from __future__ import annotations

import asyncio
import json

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.types import CallToolResult, TextContent
from pydantic import BaseModel, ConfigDict, Field

from .log import get_logger, timed
from .models import Problem

logger = get_logger(__name__)
PAGE_SIZE = 100


class MCPHistoryError(RuntimeError):
    """An actionable history failure that is safe to include in logs."""


class _Submission(BaseModel):
    model_config = ConfigDict(strict=True)

    title: str = Field(min_length=1)
    titleSlug: str = Field(min_length=1)
    timestamp: int = Field(ge=0)


class _Page(BaseModel):
    model_config = ConfigDict(strict=True)

    submissions: list[_Submission]
    nextCursor: str | None = Field(..., min_length=1)


def _parse_page(result: CallToolResult) -> _Page:
    if result.is_error:
        raise MCPHistoryError("MCP list_ac_submissions reported an error.")
    try:
        payload = result.structured_content
        if payload is None:
            payload = json.loads(
                "".join(
                    item.text
                    for item in result.content
                    if isinstance(item, TextContent)
                )
            )
        return _Page.model_validate(payload)
    except ValueError:
        # Provider content and validation input can contain private data.
        raise MCPHistoryError("MCP returned invalid accepted history.") from None


class MCPHistoryClient:
    def __init__(self, *, url: str, token: str) -> None:
        self._url = url
        self._token = token

    def progress(self) -> list[Problem]:
        """Read all stored accepted problems; this does not refresh LeetCode."""
        with timed(logger, "mcp.history") as stats:
            try:
                solved = asyncio.run(self._fetch())
            except MCPHistoryError:
                raise
            except Exception:  # noqa: BLE001 - sanitize all SDK/transport failures
                # Transport exceptions can include headers, URLs or response bodies.
                raise MCPHistoryError(
                    "MCP history request failed. Check MCP_URL, MCP_AUTH_TOKEN "
                    "and server availability."
                ) from None
            if not solved:
                raise MCPHistoryError("MCP returned no accepted problems.")
            stats["solved"] = len(solved)
            return solved

    async def _fetch(self) -> list[Problem]:
        async with (
            httpx2.AsyncClient(
                headers={"Authorization": f"Bearer {self._token}"},
                timeout=httpx2.Timeout(30, read=300),
            ) as http_client,
            Client(
                streamable_http_client(self._url, http_client=http_client),
                read_timeout_seconds=300,
            ) as client,
        ):
            cursor: str | None = None
            seen_cursors: set[str] = set()
            by_slug: dict[str, _Submission] = {}
            while True:
                arguments: dict[str, object] = {"limit": PAGE_SIZE}
                if cursor is not None:
                    arguments["cursor"] = cursor
                page = _parse_page(
                    await client.call_tool("list_ac_submissions", arguments)
                )
                for submission in page.submissions:
                    previous = by_slug.get(submission.titleSlug)
                    if previous is None or submission.timestamp > previous.timestamp:
                        by_slug[submission.titleSlug] = submission
                cursor = page.nextCursor
                if cursor is None:
                    break
                if cursor in seen_cursors:
                    raise MCPHistoryError("MCP history pagination repeated a cursor.")
                seen_cursors.add(cursor)
        return [
            Problem(
                title=row.title,
                title_slug=row.titleSlug,
                timestamp=row.timestamp,
            )
            for row in sorted(
                by_slug.values(), key=lambda row: (-row.timestamp, row.titleSlug)
            )
        ]
