import asyncio
from typing import Any

import pytest
import requests
from fastmcp import Client
from fastmcp.exceptions import ToolError

from podcast_mcp import transcripts
from podcast_mcp.refresh import Refresher, RefreshSteps
from podcast_mcp.server import create_server
from tests.sample_library import EP_AGENTS, EP_CRYPTO

READ_ONLY_TOOLS = {
    "get_listening_history",
    "search_episodes",
    "list_podcasts",
    "get_podcast",
    "get_episode",
    "get_library_status",
    "get_transcript",
}


def _noop(settings) -> None:
    return None


def _call(
    settings,
    tool: str,
    arguments: dict[str, Any] | None = None,
) -> dict[str, Any]:
    refresher = Refresher(settings, steps=RefreshSteps(history=_noop, details=_noop))
    return asyncio.run(_call_async(create_server(settings, refresher), tool, arguments))


async def _call_async(
    server,
    tool: str,
    arguments: dict[str, Any] | None,
) -> dict[str, Any]:
    async with Client(server) as client:
        result = await client.call_tool(tool, arguments or {})
    assert result.structured_content is not None
    return result.structured_content


async def _list_tools(server) -> list:
    async with Client(server) as client:
        return await client.list_tools()


def test_tools_and_annotations(populated_settings):
    tools = {
        tool.name: tool
        for tool in asyncio.run(_list_tools(create_server(populated_settings)))
    }
    assert set(tools) == READ_ONLY_TOOLS | {"refresh_library"}
    for name in READ_ONLY_TOOLS:
        assert tools[name].annotations.read_only_hint is True
    assert tools["refresh_library"].annotations.read_only_hint is False
    assert "listening history" in tools["get_listening_history"].description


def test_history_and_search(populated_settings):
    history = _call(populated_settings, "get_listening_history", {"status": "starred"})
    assert [item["episode_id"] for item in history["result"]] == [EP_AGENTS]
    found = _call(populated_settings, "search_episodes", {"query": "bitcoin"})
    assert [item["episode_id"] for item in found["result"]] == [EP_CRYPTO]


def test_paging_is_clamped(populated_settings):
    history = _call(
        populated_settings,
        "get_listening_history",
        {"limit": 0, "offset": -5},
    )
    assert len(history["result"]) == 1


def test_podcasts_and_details(populated_settings):
    podcasts = _call(populated_settings, "list_podcasts", {"subscribed_only": False})
    assert [item["title"] for item in podcasts["result"]] == ["Hard Fork", "Old Show"]
    podcast = _call(populated_settings, "get_podcast", {"podcast_id": 1})
    assert podcast["author"] == "NYT"
    episode = _call(populated_settings, "get_episode", {"episode_id": EP_AGENTS})
    assert episode["has_transcript"] is True


@pytest.mark.parametrize(
    ("tool", "arguments", "message"),
    [
        ("search_episodes", {"query": "!!"}, "at least one word"),
        ("get_podcast", {"podcast_id": 42}, "No podcast with id 42"),
        ("get_episode", {"episode_id": "nope"}, "No episode with id nope"),
        ("get_transcript", {"episode_id": "nope"}, "No episode with id nope"),
        ("get_transcript", {"episode_id": EP_CRYPTO}, "No transcript is published"),
        ("refresh_library", {}, "No Overcast credentials"),
    ],
)
def test_tool_errors(populated_settings, tool, arguments, message):
    with pytest.raises(ToolError, match=message):
        _call(populated_settings, tool, arguments)


class FakeResponse:
    content = ("WEBVTT\n\n00:00.000 --> 00:01.000\n" + "abcdefghij" * 3).encode()

    def raise_for_status(self) -> None:
        return None


def test_transcript_windows(populated_settings, monkeypatch):
    monkeypatch.setattr(transcripts.requests, "get", lambda url, **_: FakeResponse())
    first = _call(
        populated_settings,
        "get_transcript",
        {"episode_id": EP_AGENTS, "max_chars": 25},
    )
    assert first["text"] == "abcdefghij" * 2 + "abcde"
    assert (first["total_chars"], first["next_offset"]) == (30, 25)
    rest = _call(
        populated_settings,
        "get_transcript",
        {"episode_id": EP_AGENTS, "offset": 25},
    )
    assert rest["text"] == "fghij"
    assert rest["next_offset"] is None


def test_transcript_download_failure(populated_settings, monkeypatch):
    def fail(url: str, **kwargs) -> None:
        msg = "connection refused"
        raise requests.ConnectionError(msg)

    monkeypatch.setattr(transcripts.requests, "get", fail)
    with pytest.raises(ToolError, match="Could not download the transcript"):
        _call(populated_settings, "get_transcript", {"episode_id": EP_AGENTS})


def test_refresh_and_status(populated_settings):
    populated_settings.auth_path.write_text("{}")
    refreshed = _call(populated_settings, "refresh_library")
    assert refreshed["last_outcome"] == "ok"
    status = _call(populated_settings, "get_library_status")
    assert status["counts"]["podcasts"] == 2
    assert status["refresh"]["has_overcast_credentials"] is True


def test_data_tools_trigger_stale_refresh(populated_settings):
    populated_settings.auth_path.write_text("{}")
    _call(populated_settings, "list_podcasts")
    status = _call(populated_settings, "get_library_status")
    assert status["refresh"]["last_started"] is not None
