from pathlib import Path

import pytest
import requests

from podcast_mcp import transcripts
from podcast_mcp.models import TranscriptSource
from podcast_mcp.transcripts import (
    TranscriptStore,
    TranscriptUnavailableError,
    _extension,
    _safe_name,
)
from tests.sample_library import EP_AGENTS, EP_CRYPTO, TRANSCRIPT_URL

VTT = "WEBVTT\n\n00:00.000 --> 00:01.000\n<v Kevin>Hello agents.\n"


class FakeResponse:
    def __init__(self, content: bytes, status_code: int = 200) -> None:
        self.content = content
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            msg = f"{self.status_code} error"
            raise requests.HTTPError(msg)


class FakeGet:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.urls: list[str] = []

    def __call__(self, url: str, **kwargs) -> FakeResponse:
        self.urls.append(url)
        return self.response


@pytest.fixture
def fake_get(monkeypatch) -> FakeGet:
    fake = FakeGet(FakeResponse(VTT.encode()))
    monkeypatch.setattr(transcripts.requests, "get", fake)
    return fake


@pytest.fixture
def store(library, populated_settings) -> TranscriptStore:
    return TranscriptStore(
        library=library, cache_dir=populated_settings.transcripts_dir
    )


def test_downloads_once_then_uses_cache(store, library, fake_get):
    source = library.transcript_source(EP_AGENTS)
    assert store.text(source) == "Kevin: Hello agents."
    assert fake_get.urls == [TRANSCRIPT_URL]
    cached = library.transcript_source(EP_AGENTS)
    assert cached.cached_path is not None
    path = Path(cached.cached_path)
    assert path.parent.name == "Hard Fork"
    assert path.name.startswith("AI Agents Everywhere-")
    assert path.suffix == ".vtt"
    assert store.text(cached) == "Kevin: Hello agents."
    assert fake_get.urls == [TRANSCRIPT_URL]


def test_missing_cache_file_is_downloaded_again(store, library, fake_get, tmp_path):
    library.record_transcript_path(EP_AGENTS, tmp_path / "deleted.vtt")
    store.text(library.transcript_source(EP_AGENTS))
    assert fake_get.urls == [TRANSCRIPT_URL]


def test_episode_without_transcript(store, library, fake_get):
    with pytest.raises(TranscriptUnavailableError, match="Crypto Winter Returns"):
        store.text(library.transcript_source(EP_CRYPTO))
    assert fake_get.urls == []


def test_http_errors_propagate(store, library, monkeypatch):
    monkeypatch.setattr(transcripts.requests, "get", FakeGet(FakeResponse(b"", 404)))
    with pytest.raises(requests.HTTPError):
        store.text(library.transcript_source(EP_AGENTS))


def test_untitled_episode_uses_fallback_names(store, fake_get):
    source = TranscriptSource(
        episode_id="https://cdn.example.com/x.mp3",
        title="???",
        podcast=None,
        url="https://cdn.example.com/x.srt?token=1",
        mime_type=None,
        cached_path=None,
    )
    store.text(source)
    cached = next(store.cache_dir.rglob("*.srt"))
    assert cached.parent.name == "unknown"
    assert cached.name.startswith("episode-")


@pytest.mark.parametrize(
    ("mime_type", "url", "expected"),
    [
        ("text/vtt", "https://x/t", ".vtt"),
        ("application/json; charset=utf-8", "https://x/t", ".json"),
        (None, "https://x/t.srt?a=1", ".srt"),
        ("application/x-unknown-type", "https://x/t", ".txt"),
    ],
)
def test_extension(mime_type, url, expected):
    assert _extension(mime_type, url) == expected


def test_safe_name():
    assert _safe_name('a/b:c?"d"', fallback="f") == "abcd"
    assert _safe_name(" .. ", fallback="f") == "f"
    assert _safe_name(None, fallback="f") == "f"
    assert len(_safe_name("x" * 500, fallback="f")) == 120
