"""Text helpers: HTML and transcript conversion, search queries, snippets."""

import html
import json
import re
from collections.abc import Iterable, Sequence
from html.parser import HTMLParser

_BLOCK_TAGS = frozenset(
    {"br", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "ol", "p", "tr", "ul"},
)
_SKIPPED_TAGS = frozenset({"script", "style"})
_SEARCH_TERM = re.compile(r"\w+")
_PREFIX_MATCH_MIN_LENGTH = 4
_VTT_VOICE = re.compile(r"<v(?:\.[^\s>]*)?\s+([^>]+)>")
_TAG = re.compile(r"<[^>]+>")
_BLANK_LINES = re.compile(r"\n\s*\n")
_INLINE_SPACE = re.compile(r"[ \t\r\f\v]+")
_EXTRA_NEWLINES = re.compile(r"\n{3,}")

type Segment = tuple[str | None, str]


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag in _SKIPPED_TAGS:
            self._skip_depth += 1
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n- " if tag == "li" else "\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIPPED_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
        elif tag in _BLOCK_TAGS and tag != "li":
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self.parts.append(data)


def html_to_text(raw: str | None) -> str:
    """Convert an HTML fragment (or plain text) to readable plain text."""
    if not raw:
        return ""
    extractor = _TextExtractor()
    extractor.feed(raw)
    extractor.close()
    text = _INLINE_SPACE.sub(" ", "".join(extractor.parts))
    lines = (line.strip() for line in text.split("\n"))
    return _EXTRA_NEWLINES.sub("\n\n", "\n".join(lines)).strip()


def transcript_to_text(raw: str) -> str:
    """Convert a VTT, SRT, JSON, HTML or plain-text transcript to plain text."""
    body = raw.lstrip("﻿ \t\r\n")
    match body[:1]:
        case "{":
            return _json_transcript_to_text(body)
        case "<":
            return html_to_text(body)
        case _ if "-->" in body:
            return _cues_to_text(body)
        case _:
            return body.strip()


def _json_transcript_to_text(body: str) -> str:
    try:
        document = json.loads(body)
    except json.JSONDecodeError:
        return body.strip()
    segments = document.get("segments") if isinstance(document, dict) else None
    if not isinstance(segments, list):
        return body.strip()
    return _join_segments(
        (segment.get("speaker"), str(segment.get("body", "")).strip())
        for segment in segments
        if isinstance(segment, dict)
    )


def _cues_to_text(body: str) -> str:
    segments: list[Segment] = []
    for block in _BLANK_LINES.split(body.replace("\r\n", "\n")):
        lines = block.strip().split("\n")
        timing = next((i for i, line in enumerate(lines) if "-->" in line), None)
        if timing is None:
            continue  # WEBVTT header, NOTE or STYLE block
        segments.extend(_cue_line_to_segment(line) for line in lines[timing + 1 :])
    return _join_segments(segments)


def _cue_line_to_segment(line: str) -> Segment:
    speaker = voice.group(1).strip() if (voice := _VTT_VOICE.search(line)) else None
    return speaker, html.unescape(_TAG.sub("", line)).strip()


def _join_segments(segments: Iterable[Segment]) -> str:
    """Merge consecutive segments by the same speaker into paragraphs."""
    paragraphs: list[tuple[str | None, list[str]]] = []
    for speaker, text in segments:
        if not text:
            continue
        if paragraphs and speaker in {None, paragraphs[-1][0]}:
            paragraphs[-1][1].append(text)
        else:
            paragraphs.append((speaker, [text]))
    return "\n\n".join(
        f"{speaker}: {' '.join(texts)}" if speaker else " ".join(texts)
        for speaker, texts in paragraphs
    )


def search_terms(query: str) -> list[str]:
    """Split a free-text query into word terms."""
    return _SEARCH_TERM.findall(query)


def fts_query(terms: Sequence[str]) -> str:
    """Build an FTS5 query that requires every term.

    Each term is quoted so punctuation cannot be read as FTS syntax. Longer terms
    match as prefixes so "interview" also finds "interviews".
    """
    return " ".join(
        f'"{term}"*' if len(term) >= _PREFIX_MATCH_MIN_LENGTH else f'"{term}"'
        for term in terms
    )


def snippet(text: str, terms: Sequence[str], width: int = 280) -> str:
    """Return a window of `text` around the first matching term."""
    lowered = text.lower()
    positions = [pos for term in terms if (pos := lowered.find(term.lower())) >= 0]
    start = max(0, min(positions, default=0) - width // 4)
    end = start + width
    excerpt = " ".join(text[start:end].split())
    return f"{'…' if start else ''}{excerpt}{'…' if end < len(text) else ''}"


def parse_duration(value: str | float | None) -> int | None:
    """Parse an itunes:duration value (seconds, MM:SS or HH:MM:SS) to seconds."""
    if value is None:
        return None
    seconds = 0.0
    try:
        for part in str(value).strip().split(":"):
            seconds = seconds * 60 + float(part)
    except ValueError:
        return None
    return round(seconds)
