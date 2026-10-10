"""Structured results returned by the MCP tools."""

import sqlite3
from dataclasses import dataclass
from typing import Self

from podcast_mcp.text import html_to_text, parse_duration


@dataclass(frozen=True, slots=True)
class HistoryEpisode:
    """An episode from your Overcast listening history."""

    episode_id: str
    title: str
    podcast: str | None
    podcast_id: int | None
    played: bool
    progress_seconds: int | None
    starred: bool
    last_activity: str | None
    published: str | None
    duration_seconds: int | None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Self:
        """Build from a row of `LISTENING_HISTORY_SQL`."""
        return cls(
            episode_id=row["episode_id"],
            title=row["title"],
            podcast=row["podcast"],
            podcast_id=row["podcast_id"],
            played=bool(row["played"]),
            progress_seconds=row["progress_seconds"],
            starred=bool(row["starred"]),
            last_activity=row["last_activity"],
            published=row["published"],
            duration_seconds=parse_duration(row["duration"]),
        )


@dataclass(frozen=True, slots=True)
class EpisodeSearchResult:
    """An episode matching a search, with an excerpt of its description."""

    episode_id: str
    title: str
    podcast: str | None
    podcast_id: int | None
    published: str | None
    snippet: str
    played: bool
    starred: bool
    last_activity: str | None


@dataclass(frozen=True, slots=True)
class FeedEpisode:
    """An episode as published in a podcast's RSS feed."""

    episode_id: str
    title: str
    published: str | None
    duration_seconds: int | None
    played: bool

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Self:
        """Build from a row of `LATEST_FEED_EPISODES_SQL`."""
        return cls(
            episode_id=row["episode_id"],
            title=row["title"],
            published=row["published"],
            duration_seconds=parse_duration(row["duration"]),
            played=bool(row["played"]),
        )


@dataclass(frozen=True, slots=True)
class PodcastSummary:
    """A podcast in your Overcast library."""

    podcast_id: int
    title: str
    author: str | None
    subscribed: bool
    episodes_listened: int
    last_listened: str | None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Self:
        """Build from a row of `PODCASTS_SQL`."""
        return cls(
            podcast_id=row["podcast_id"],
            title=row["title"],
            author=row["author"],
            subscribed=bool(row["subscribed"]),
            episodes_listened=row["episodes_listened"],
            last_listened=row["last_listened"],
        )


@dataclass(frozen=True, slots=True)
class PodcastDetail:
    """Feed details for one podcast, with recent activity."""

    podcast_id: int
    title: str
    author: str | None
    description: str | None
    subscribed: bool
    added_to_overcast: str | None
    removed_from_overcast: str | None
    feed_url: str | None
    website: str | None
    language: str | None
    image_url: str | None
    feed_checked_at: str | None
    episodes_in_feed: int
    episodes_listened: int
    episodes_starred: int
    recently_listened: list[HistoryEpisode]
    latest_episodes: list[FeedEpisode]

    @classmethod
    def from_row(
        cls,
        row: sqlite3.Row,
        *,
        recently_listened: list[HistoryEpisode],
        latest_episodes: list[FeedEpisode],
    ) -> Self:
        """Build from a row of `PODCAST_DETAIL_SQL` plus episode lists."""
        return cls(
            podcast_id=row["podcast_id"],
            title=row["title"],
            author=row["author"],
            description=html_to_text(row["description"]) or None,
            subscribed=bool(row["subscribed"]),
            added_to_overcast=row["added_to_overcast"],
            removed_from_overcast=row["removed_from_overcast"],
            feed_url=row["feed_url"],
            website=row["website"],
            language=row["language"],
            image_url=row["image_url"],
            feed_checked_at=row["feed_checked_at"],
            episodes_in_feed=row["episodes_in_feed"],
            episodes_listened=row["episodes_listened"],
            episodes_starred=row["episodes_starred"],
            recently_listened=recently_listened,
            latest_episodes=latest_episodes,
        )


@dataclass(frozen=True, slots=True)
class EpisodeDetail:
    """Everything known about one episode."""

    episode_id: str
    title: str
    podcast: str | None
    podcast_id: int | None
    published: str | None
    duration_seconds: int | None
    episode_number: str | None
    season_number: str | None
    link: str | None
    overcast_url: str | None
    description: str | None
    has_transcript: bool
    played: bool
    progress_seconds: int | None
    starred: bool
    last_activity: str | None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Self:
        """Build from a row of either episode detail query."""
        return cls(
            episode_id=row["episode_id"],
            title=row["title"],
            podcast=row["podcast"],
            podcast_id=row["podcast_id"],
            published=row["published"],
            duration_seconds=parse_duration(row["duration"]),
            episode_number=row["episode_number"],
            season_number=row["season_number"],
            link=row["link"],
            overcast_url=row["overcast_url"],
            description=html_to_text(row["description"]) or None,
            has_transcript=bool(row["has_transcript"]),
            played=bool(row["played"]),
            progress_seconds=row["progress_seconds"],
            starred=bool(row["starred"]),
            last_activity=row["last_activity"],
        )


@dataclass(frozen=True, slots=True)
class TranscriptSource:
    """Where an episode's transcript can be fetched from or was cached to."""

    episode_id: str
    title: str
    podcast: str | None
    url: str | None
    mime_type: str | None
    cached_path: str | None


@dataclass(frozen=True, slots=True)
class Transcript:
    """A window of an episode transcript as plain text."""

    episode_id: str
    title: str
    podcast: str | None
    text: str
    offset: int
    total_chars: int
    next_offset: int | None


@dataclass(frozen=True, slots=True)
class RefreshStatus:
    """State of the most recent Overcast refresh."""

    running: bool
    has_overcast_credentials: bool
    last_started: str | None
    last_finished: str | None
    last_outcome: str | None
    last_error: str | None


@dataclass(frozen=True, slots=True)
class LibraryCounts:
    """Row counts summarizing the local library."""

    podcasts: int
    subscribed_podcasts: int
    episodes_listened: int
    episodes_starred: int
    episodes_in_feeds: int
    episodes_with_transcripts: int


@dataclass(frozen=True, slots=True)
class LibraryStatus:
    """Library size plus refresh state."""

    counts: LibraryCounts
    refresh: RefreshStatus
