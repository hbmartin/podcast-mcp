import pytest

from podcast_mcp.text import (
    fts_query,
    html_to_text,
    parse_duration,
    search_terms,
    snippet,
    transcript_to_text,
)

VTT = """WEBVTT
Kind: captions

NOTE produced by a robot

1
00:00:00.000 --> 00:00:02.000
<v Alice>Hello &amp; welcome.</v>

2
00:00:02.000 --> 00:00:04.000
<v Alice>Today we talk agents.

3
00:00:04.000 --> 00:00:06.000
<v.loud Bob>Great to be here.
And thanks.
"""

SRT = """1
00:00:00,000 --> 00:00:02,000
First line.

2
00:00:02,000 --> 00:00:04,000
Second line.
"""


def test_html_to_text_strips_tags_and_keeps_structure():
    raw = (
        "<p>Intro &amp; <b>bold</b></p><ul><li>One</li><li>Two</li></ul>"
        "<script>alert(1)</script><style>p{}</style>Done"
    )
    assert html_to_text(raw) == "Intro & bold\n\n- One\n- Two\nDone"


@pytest.mark.parametrize("raw", [None, ""])
def test_html_to_text_empty(raw):
    assert html_to_text(raw) == ""


def test_html_to_text_plain_text_passthrough():
    assert html_to_text("  just   words  ") == "just words"


def test_vtt_merges_speakers_and_skips_headers():
    assert transcript_to_text(VTT) == (
        "Alice: Hello & welcome. Today we talk agents.\n\n"
        "Bob: Great to be here. And thanks."
    )


def test_srt_without_speakers_is_one_paragraph():
    assert transcript_to_text(SRT) == "First line. Second line."


def test_json_transcript_segments():
    raw = (
        '{"version": "1.0.0", "segments": ['
        '{"speaker": "Ann", "body": "Hi"}, {"speaker": "Ann", "body": "there"},'
        '{"speaker": "Ben", "body": "Hey"}, "junk", {"body": ""}]}'
    )
    assert transcript_to_text(raw) == "Ann: Hi there\n\nBen: Hey"


@pytest.mark.parametrize("raw", ['{"no": "segments"}', "{not json"])
def test_json_transcript_fallbacks_to_raw(raw):
    assert transcript_to_text(raw) == raw


def test_html_and_plain_transcripts():
    assert transcript_to_text("﻿<p>Hello</p><p>World</p>") == "Hello\n\nWorld"
    assert transcript_to_text("\n plain words \n") == "plain words"


def test_search_terms_and_fts_query_escape_syntax():
    terms = search_terms('agents: "AND" NEAR(ai) -crypto*')
    assert terms == ["agents", "AND", "NEAR", "ai", "crypto"]
    assert fts_query(terms) == '"agents"* "AND" "NEAR"* "ai" "crypto"*'


def test_snippet_centers_on_first_match():
    text = f"{'x' * 300} the agents arrive {'y' * 300}"
    result = snippet(text, ["agents"], width=100)
    assert result.startswith("…")
    assert result.endswith("…")
    assert "agents arrive" in result


def test_snippet_without_match_starts_at_beginning():
    assert snippet("short text", ["missing"]) == "short text"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("01:02:03", 3_723),
        ("62:03", 3_723),
        ("3600", 3_600),
        (90.4, 90),
        (None, None),
        ("", None),
        ("about an hour", None),
    ],
)
def test_parse_duration(value, expected):
    assert parse_duration(value) == expected
