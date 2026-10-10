import pytest

from podcast_mcp.database import connect
from podcast_mcp.library import EmptySearchQueryError, HistoryStatus, Library, Page
from tests.sample_library import (
    EP_AGENTS,
    EP_CRYPTO,
    EP_FEED_ONLY,
    EP_NOT_EXTENDED,
    EP_OLD,
    EP_UNHEARD,
    TRANSCRIPT_URL,
)


def _history(  # noqa: PLR0913 - mirrors Library.listening_history
    library: Library,
    *,
    status: HistoryStatus = "listened",
    podcast_id: int | None = None,
    since: str | None = None,
    until: str | None = None,
    page: Page | None = None,
) -> list[str]:
    episodes = library.listening_history(
        status=status,
        podcast_id=podcast_id,
        since=since,
        until=until,
        page=page or Page(limit=50),
    )
    return [episode.episode_id for episode in episodes]


def test_history_lists_listened_episodes_newest_first(library):
    assert _history(library) == [EP_NOT_EXTENDED, EP_CRYPTO, EP_AGENTS, EP_OLD]


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("played", [EP_NOT_EXTENDED, EP_AGENTS, EP_OLD]),
        ("in_progress", [EP_UNHEARD, EP_CRYPTO]),
        ("starred", [EP_AGENTS]),
    ],
)
def test_history_status_filters(library, status, expected):
    assert _history(library, status=status) == expected


def test_history_date_window_normalizes_timezones(library):
    # EP_AGENTS was touched at 14:00 UTC (10:00-04:00).
    assert _history(library, since="2026-09-01T13:59:00Z", until="2026-09-02") == [
        EP_AGENTS,
    ]
    assert _history(library, since="2026-09-01T14:01:00Z", until="2026-09-02") == []


def test_history_podcast_filter_and_paging(library):
    assert _history(library, podcast_id=2) == [EP_OLD]
    assert _history(library, page=Page(limit=2, offset=1)) == [EP_CRYPTO, EP_AGENTS]


def test_history_episode_fields(library):
    episode = library.listening_history(
        status="starred",
        podcast_id=None,
        since=None,
        until=None,
        page=Page(limit=1),
    )[0]
    assert episode.title == "AI Agents Everywhere"
    assert episode.podcast == "Hard Fork"
    assert episode.podcast_id == 1
    assert episode.played is True
    assert episode.starred is True
    assert episode.duration_seconds == 3_723


def _search(
    library: Library,
    query: str,
    *,
    listened_only: bool = False,
    podcast_id: int | None = None,
) -> list[str]:
    results = library.search_episodes(
        query,
        listened_only=listened_only,
        podcast_id=podcast_id,
        page=Page(limit=20),
    )
    return [result.episode_id for result in results]


def test_search_matches_titles_and_descriptions_with_prefixes(library):
    assert set(_search(library, "agent")) == {EP_AGENTS, EP_FEED_ONLY, EP_OLD}
    assert _search(library, "bitcoin market") == [EP_CRYPTO]


def test_search_filters(library):
    assert set(_search(library, "agents", listened_only=True)) == {EP_AGENTS, EP_OLD}
    assert _search(library, "agents", podcast_id=2) == [EP_OLD]


def test_search_tolerates_fts_syntax_characters(library):
    assert _search(library, 'bitcoin: "OR" (market*') == []
    assert _search(library, "bitcoin-market") == [EP_CRYPTO]


def test_search_rejects_queries_without_words(library):
    with pytest.raises(EmptySearchQueryError):
        _search(library, ' "*" ')


def test_search_result_fields_use_plain_text_snippets(library):
    result = library.search_episodes(
        "autonomous",
        listened_only=False,
        podcast_id=None,
        page=Page(limit=1),
    )[0]
    assert result.snippet == "We talk about autonomous agents and do interviews."
    assert result.played is True
    assert result.starred is True
    assert result.podcast == "Hard Fork"


def test_podcasts_subscribed_only_and_all(library):
    subscribed = library.podcasts(
        subscribed_only=True,
        name_contains=None,
        page=Page(limit=10),
    )
    assert [podcast.title for podcast in subscribed] == ["Hard Fork"]
    assert subscribed[0].episodes_listened == 3
    assert subscribed[0].author == "NYT"
    every = library.podcasts(subscribed_only=False, name_contains="", page=Page(10))
    assert [podcast.title for podcast in every] == ["Hard Fork", "Old Show"]
    named = library.podcasts(subscribed_only=False, name_contains="old", page=Page(10))
    assert [podcast.podcast_id for podcast in named] == [2]


def test_podcasts_compare_last_listened_across_utc_offsets(library):
    # 10:00-04:00 is 14:00 UTC, later than 13:00+00:00 though it sorts first as text.
    with connect(library.db_path, writable=True) as conn:
        conn.execute(
            "UPDATE episodes SET userUpdatedDate = ? WHERE overcastId = ?",
            ("2026-09-07T10:00:00-04:00", 104),
        )
        conn.execute(
            "UPDATE episodes SET userUpdatedDate = ? WHERE overcastId = ?",
            ("2026-09-07T13:00:00+00:00", 201),
        )
    podcasts = library.podcasts(
        subscribed_only=False, name_contains=None, page=Page(10)
    )
    assert [(podcast.title, podcast.last_listened) for podcast in podcasts] == [
        ("Hard Fork", "2026-09-07T14:00:00Z"),
        ("Old Show", "2026-09-07T13:00:00Z"),
    ]


def test_podcast_detail(library):
    detail = library.podcast_detail(1, episodes=2)
    assert detail is not None
    assert detail.description == "A show about tech & the future."
    assert detail.website == "https://hardfork.example.com"
    assert detail.language == "en"
    assert detail.subscribed is True
    assert (detail.episodes_in_feed, detail.episodes_listened) == (4, 3)
    assert detail.episodes_starred == 1
    assert [e.episode_id for e in detail.recently_listened] == [
        EP_NOT_EXTENDED,
        EP_CRYPTO,
    ]
    assert [e.episode_id for e in detail.latest_episodes] == [EP_FEED_ONLY, EP_UNHEARD]
    assert detail.latest_episodes[0].played is False
    assert library.podcast_detail(999, episodes=2) is None


def test_episode_detail_from_feed(library):
    detail = library.episode_detail(EP_AGENTS)
    assert detail is not None
    assert detail.description == "We talk about autonomous agents and do interviews."
    assert detail.has_transcript is True
    assert detail.episode_number == "101"
    assert detail.overcast_url == "https://overcast.fm/+101"
    assert detail.duration_seconds == 3_723


def test_episode_detail_falls_back_to_history(library):
    detail = library.episode_detail(EP_NOT_EXTENDED)
    assert detail is not None
    assert detail.title == "Not In Feed Yet"
    assert detail.description is None
    assert detail.has_transcript is False
    assert library.episode_detail("https://unknown.example/ep.mp3") is None


def test_transcript_source_and_cache_path(library, tmp_path):
    source = library.transcript_source(EP_AGENTS)
    assert source is not None
    assert (source.url, source.mime_type) == (TRANSCRIPT_URL, "text/vtt")
    assert source.cached_path is None
    library.record_transcript_path(EP_AGENTS, tmp_path / "t.vtt")
    cached = library.transcript_source(EP_AGENTS)
    assert cached is not None
    assert cached.cached_path == str(tmp_path / "t.vtt")
    assert library.transcript_source("https://unknown.example/ep.mp3") is None


def test_counts(library):
    counts = library.counts()
    assert counts.podcasts == 2
    assert counts.subscribed_podcasts == 1
    assert counts.episodes_listened == 4
    assert counts.episodes_starred == 1
    assert counts.episodes_in_feeds == 5
    assert counts.episodes_with_transcripts == 1
