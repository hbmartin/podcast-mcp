"""Download-on-demand transcript cache."""

import hashlib
import mimetypes
import re
from dataclasses import dataclass
from pathlib import Path

import requests

from podcast_mcp.library import Library
from podcast_mcp.models import TranscriptSource
from podcast_mcp.text import transcript_to_text

DOWNLOAD_TIMEOUT_SECONDS = 30
USER_AGENT = "podcast-mcp (+https://github.com/hbmartin/podcast-mcp)"
_UNSAFE_PATH_CHARS = re.compile(r'[:/\\#?%*|"<>]')


class TranscriptUnavailableError(LookupError):
    """The episode has no published transcript."""


def _safe_name(value: str | None, fallback: str) -> str:
    name = _UNSAFE_PATH_CHARS.sub("", value or "").strip(" .")
    return name[:120] or fallback


def _extension(mime_type: str | None, url: str) -> str:
    if mime_type and (guessed := mimetypes.guess_extension(mime_type.split(";")[0])):
        return guessed
    return Path(url.split("?", maxsplit=1)[0]).suffix or ".txt"


@dataclass(frozen=True, slots=True)
class TranscriptStore:
    """Fetches transcripts on first use and caches them on disk."""

    library: Library
    cache_dir: Path

    def text(self, source: TranscriptSource) -> str:
        """Return the transcript as plain text, downloading it if needed."""
        if source.cached_path and (cached := Path(source.cached_path)).is_file():
            path = cached
        else:
            path = self._download(source)
        return transcript_to_text(path.read_text(encoding="utf-8", errors="replace"))

    def _download(self, source: TranscriptSource) -> Path:
        if not source.url:
            msg = f"No transcript is published for {source.title!r}"
            raise TranscriptUnavailableError(msg)
        response = requests.get(
            source.url,
            headers={"User-Agent": USER_AGENT},
            timeout=DOWNLOAD_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        # The digest keeps episodes with identical titles from sharing a file.
        digest = hashlib.sha256(source.episode_id.encode()).hexdigest()[:10]
        folder = self.cache_dir / _safe_name(source.podcast, fallback="unknown")
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / (
            f"{_safe_name(source.title, fallback='episode')}-{digest}"
            f"{_extension(source.mime_type, source.url)}"
        )
        path.write_bytes(response.content)
        self.library.record_transcript_path(source.episode_id, path)
        return path
