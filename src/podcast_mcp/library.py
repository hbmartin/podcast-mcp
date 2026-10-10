"""Read queries over the overcast-to-sqlite database."""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from podcast_mcp.database import connect
from podcast_mcp.models import (
    EpisodeDetail,
    EpisodeSearchResult,
    FeedEpisode,
    HistoryEpisode,
    LibraryCounts,
    PodcastDetail,
    PodcastSummary,
    TranscriptSource,
)
from podcast_mcp.text import fts_query, html_to_text, search_terms, snippet

type HistoryStatus = Literal["listened", "played", "in_progress", "starred"]

# "Listened" matches overcast-to-sqlite's episodes_played view: finished, or more
# than 5 minutes heard. Queries spell it out to stay plain (non f-string) SQL.

LISTENING_HISTORY_SQL = """
SELECT
    ep.enclosureUrl AS episode_id,
    ep.title AS title,
    feeds.title AS podcast,
    feeds.overcastId AS podcast_id,
    ep.played AS played,
    ep.progress AS progress_seconds,
    ep.userRecommendedDate IS NOT NULL AS starred,
    ep.userUpdatedDate AS last_activity,
    ep.pubDate AS published,
    ee."itunes:duration" AS duration
FROM episodes AS ep
LEFT JOIN feeds ON feeds.overcastId = ep.feedId
LEFT JOIN episodes_extended AS ee ON ee.enclosureUrl = ep.enclosureUrl
WHERE CASE :status
        WHEN 'played' THEN ep.played = 1
        WHEN 'in_progress' THEN ep.played = 0 AND ep.progress > 0
        WHEN 'starred' THEN ep.userRecommendedDate IS NOT NULL
        ELSE (ep.played = 1 OR ep.progress > 300)
    END
    AND (:podcast_id IS NULL OR ep.feedId = :podcast_id)
    AND (:since IS NULL OR datetime(ep.userUpdatedDate) >= datetime(:since))
    AND (:until IS NULL OR datetime(ep.userUpdatedDate) < datetime(:until))
ORDER BY datetime(ep.userUpdatedDate) DESC
LIMIT :limit OFFSET :offset
"""

SEARCH_EPISODES_SQL = """
SELECT
    ee.enclosureUrl AS episode_id,
    ee.title AS title,
    COALESCE(fe.title, feeds.title) AS podcast,
    feeds.overcastId AS podcast_id,
    ee.pubDate AS published,
    ee.description AS description,
    ep.played AS played,
    ep.userRecommendedDate IS NOT NULL AS starred,
    ep.userUpdatedDate AS last_activity
FROM episodes_extended_fts
JOIN episodes_extended AS ee ON ee.rowid = episodes_extended_fts.rowid
LEFT JOIN feeds_extended AS fe ON fe.xmlUrl = ee.feedXmlUrl
LEFT JOIN feeds ON feeds.xmlUrl = ee.feedXmlUrl
LEFT JOIN episodes AS ep ON ep.enclosureUrl = ee.enclosureUrl
WHERE episodes_extended_fts MATCH :query
    AND (:listened_only = 0 OR (ep.played = 1 OR ep.progress > 300))
    AND (:podcast_id IS NULL OR feeds.overcastId = :podcast_id)
ORDER BY episodes_extended_fts.rank
LIMIT :limit OFFSET :offset
"""

PODCASTS_SQL = """
SELECT
    feeds.overcastId AS podcast_id,
    feeds.title AS title,
    fe."itunes:author" AS author,
    feeds.subscribed AS subscribed,
    COUNT(ep.overcastId) FILTER (WHERE (ep.played = 1 OR ep.progress > 300))
        AS episodes_listened,
    -- Overcast dates carry differing UTC offsets, so compare them as datetimes
    -- and return UTC; a plain MAX() would compare the strings.
    strftime(
        '%Y-%m-%dT%H:%M:%SZ',
        MAX(datetime(ep.userUpdatedDate))
            FILTER (WHERE (ep.played = 1 OR ep.progress > 300))
    ) AS last_listened
FROM feeds
LEFT JOIN feeds_extended AS fe ON fe.xmlUrl = feeds.xmlUrl
LEFT JOIN episodes AS ep ON ep.feedId = feeds.overcastId
WHERE (:subscribed_only = 0 OR feeds.subscribed = 1)
    AND (:name_contains IS NULL OR feeds.title LIKE '%' || :name_contains || '%')
GROUP BY feeds.overcastId
ORDER BY last_listened IS NULL, last_listened DESC, feeds.title
LIMIT :limit OFFSET :offset
"""

PODCAST_DETAIL_SQL = """
SELECT
    feeds.overcastId AS podcast_id,
    feeds.title AS title,
    fe."itunes:author" AS author,
    fe.description AS description,
    feeds.subscribed AS subscribed,
    feeds.overcastAddedDate AS added_to_overcast,
    feeds.dateRemoveDetected AS removed_from_overcast,
    feeds.xmlUrl AS feed_url,
    COALESCE(feeds.htmlUrl, fe.link) AS website,
    fe.language AS language,
    fe."itunes:image:href" AS image_url,
    fe.lastUpdated AS feed_checked_at,
    (SELECT COUNT(*) FROM episodes_extended WHERE feedXmlUrl = feeds.xmlUrl)
        AS episodes_in_feed,
    (SELECT COUNT(*) FROM episodes AS ep
        WHERE ep.feedId = feeds.overcastId
            AND (ep.played = 1 OR ep.progress > 300)) AS episodes_listened,
    (SELECT COUNT(*) FROM episodes
        WHERE feedId = feeds.overcastId AND userRecommendedDate IS NOT NULL)
        AS episodes_starred
FROM feeds
LEFT JOIN feeds_extended AS fe ON fe.xmlUrl = feeds.xmlUrl
WHERE feeds.overcastId = :podcast_id
"""

LATEST_FEED_EPISODES_SQL = """
SELECT
    ee.enclosureUrl AS episode_id,
    ee.title AS title,
    ee.pubDate AS published,
    ee."itunes:duration" AS duration,
    ep.played AS played
FROM episodes_extended AS ee
JOIN feeds ON feeds.xmlUrl = ee.feedXmlUrl
LEFT JOIN episodes AS ep ON ep.enclosureUrl = ee.enclosureUrl
WHERE feeds.overcastId = :podcast_id
ORDER BY datetime(ee.pubDate) DESC
LIMIT :limit
"""

EPISODE_DETAIL_SQL = """
SELECT
    ee.enclosureUrl AS episode_id,
    ee.title AS title,
    COALESCE(fe.title, feeds.title) AS podcast,
    feeds.overcastId AS podcast_id,
    COALESCE(ee.pubDate, ep.pubDate) AS published,
    ee."itunes:duration" AS duration,
    ee."itunes:episode" AS episode_number,
    ee."itunes:season" AS season_number,
    COALESCE(ee.link, ep.url) AS link,
    ep.overcastUrl AS overcast_url,
    ee.description AS description,
    ee."podcast:transcript:url" IS NOT NULL AS has_transcript,
    ep.played AS played,
    ep.progress AS progress_seconds,
    ep.userRecommendedDate IS NOT NULL AS starred,
    ep.userUpdatedDate AS last_activity
FROM episodes_extended AS ee
LEFT JOIN feeds_extended AS fe ON fe.xmlUrl = ee.feedXmlUrl
LEFT JOIN feeds ON feeds.xmlUrl = ee.feedXmlUrl
LEFT JOIN episodes AS ep ON ep.enclosureUrl = ee.enclosureUrl
WHERE ee.enclosureUrl = :episode_id
"""

# Fallback for history episodes whose feed has not been fetched by `extend` yet.
HISTORY_EPISODE_DETAIL_SQL = """
SELECT
    ep.enclosureUrl AS episode_id,
    ep.title AS title,
    feeds.title AS podcast,
    feeds.overcastId AS podcast_id,
    ep.pubDate AS published,
    NULL AS duration,
    NULL AS episode_number,
    NULL AS season_number,
    ep.url AS link,
    ep.overcastUrl AS overcast_url,
    NULL AS description,
    0 AS has_transcript,
    ep.played AS played,
    ep.progress AS progress_seconds,
    ep.userRecommendedDate IS NOT NULL AS starred,
    ep.userUpdatedDate AS last_activity
FROM episodes AS ep
LEFT JOIN feeds ON feeds.overcastId = ep.feedId
WHERE ep.enclosureUrl = :episode_id
"""

TRANSCRIPT_SOURCE_SQL = """
SELECT
    ee.enclosureUrl AS episode_id,
    ee.title AS title,
    fe.title AS podcast,
    ee."podcast:transcript:url" AS url,
    ee."podcast:transcript:type" AS mime_type,
    ee.transcriptDownloadPath AS cached_path
FROM episodes_extended AS ee
LEFT JOIN feeds_extended AS fe ON fe.xmlUrl = ee.feedXmlUrl
WHERE ee.enclosureUrl = :episode_id
"""

COUNTS_SQL = """
SELECT
    (SELECT COUNT(*) FROM feeds) AS podcasts,
    (SELECT COUNT(*) FROM feeds WHERE subscribed = 1) AS subscribed_podcasts,
    (SELECT COUNT(*) FROM episodes AS ep WHERE (ep.played = 1 OR ep.progress > 300))
        AS episodes_listened,
    (SELECT COUNT(*) FROM episodes WHERE userRecommendedDate IS NOT NULL)
        AS episodes_starred,
    (SELECT COUNT(*) FROM episodes_extended) AS episodes_in_feeds,
    (SELECT COUNT(*) FROM episodes_extended
        WHERE "podcast:transcript:url" IS NOT NULL) AS episodes_with_transcripts
"""


class EmptySearchQueryError(ValueError):
    """Raised when a search query contains no searchable words."""

    def __init__(self) -> None:
        super().__init__("Search query must contain at least one word")


@dataclass(frozen=True, slots=True)
class Page:
    """Pagination window."""

    limit: int
    offset: int = 0

    def params(self) -> dict[str, int]:
        """Return SQL parameters for the window."""
        return {"limit": self.limit, "offset": self.offset}


@dataclass(frozen=True, slots=True)
class Library:
    """Queries against one overcast-to-sqlite database."""

    db_path: Path

    def listening_history(
        self,
        *,
        status: HistoryStatus,
        podcast_id: int | None,
        since: str | None,
        until: str | None,
        page: Page,
    ) -> list[HistoryEpisode]:
        """Episodes you have interacted with, most recent activity first."""
        params = {
            "status": status,
            "podcast_id": podcast_id,
            "since": since,
            "until": until,
            **page.params(),
        }
        with connect(self.db_path) as conn:
            rows = conn.execute(LISTENING_HISTORY_SQL, params).fetchall()
        return [HistoryEpisode.from_row(row) for row in rows]

    def search_episodes(
        self,
        query: str,
        *,
        listened_only: bool,
        podcast_id: int | None,
        page: Page,
    ) -> list[EpisodeSearchResult]:
        """Full-text search over episode titles and descriptions."""
        if not (terms := search_terms(query)):
            raise EmptySearchQueryError
        params = {
            "query": fts_query(terms),
            "listened_only": listened_only,
            "podcast_id": podcast_id,
            **page.params(),
        }
        with connect(self.db_path) as conn:
            rows = conn.execute(SEARCH_EPISODES_SQL, params).fetchall()
        return [
            EpisodeSearchResult(
                episode_id=row["episode_id"],
                title=row["title"],
                podcast=row["podcast"],
                podcast_id=row["podcast_id"],
                published=row["published"],
                snippet=snippet(html_to_text(row["description"]), terms),
                played=bool(row["played"]),
                starred=bool(row["starred"]),
                last_activity=row["last_activity"],
            )
            for row in rows
        ]

    def podcasts(
        self,
        *,
        subscribed_only: bool,
        name_contains: str | None,
        page: Page,
    ) -> list[PodcastSummary]:
        """Podcasts in the library, most recently listened first."""
        params = {
            "subscribed_only": subscribed_only,
            "name_contains": name_contains or None,
            **page.params(),
        }
        with connect(self.db_path) as conn:
            rows = conn.execute(PODCASTS_SQL, params).fetchall()
        return [PodcastSummary.from_row(row) for row in rows]

    def podcast_detail(self, podcast_id: int, *, episodes: int) -> PodcastDetail | None:
        """Feed details for one podcast, or None if it is not in the library."""
        with connect(self.db_path) as conn:
            row = conn.execute(
                PODCAST_DETAIL_SQL, {"podcast_id": podcast_id}
            ).fetchone()
            latest = conn.execute(
                LATEST_FEED_EPISODES_SQL,
                {"podcast_id": podcast_id, "limit": episodes},
            ).fetchall()
        if row is None:
            return None
        return PodcastDetail.from_row(
            row,
            recently_listened=self.listening_history(
                status="listened",
                podcast_id=podcast_id,
                since=None,
                until=None,
                page=Page(limit=episodes),
            ),
            latest_episodes=[FeedEpisode.from_row(item) for item in latest],
        )

    def episode_detail(self, episode_id: str) -> EpisodeDetail | None:
        """Everything known about one episode, or None if it is unknown."""
        params = {"episode_id": episode_id}
        with connect(self.db_path) as conn:
            row = (
                conn.execute(EPISODE_DETAIL_SQL, params).fetchone()
                or conn.execute(HISTORY_EPISODE_DETAIL_SQL, params).fetchone()
            )
        return EpisodeDetail.from_row(row) if row else None

    def transcript_source(self, episode_id: str) -> TranscriptSource | None:
        """Transcript URL and cache path for an episode, or None if unknown."""
        with connect(self.db_path) as conn:
            row = conn.execute(
                TRANSCRIPT_SOURCE_SQL,
                {"episode_id": episode_id},
            ).fetchone()
        if row is None:
            return None
        return TranscriptSource(
            episode_id=row["episode_id"],
            title=row["title"],
            podcast=row["podcast"],
            url=row["url"],
            mime_type=row["mime_type"],
            cached_path=row["cached_path"],
        )

    def record_transcript_path(self, episode_id: str, path: Path) -> None:
        """Remember where an episode's transcript was cached."""
        with connect(self.db_path, writable=True) as conn:
            conn.execute(
                "UPDATE episodes_extended SET transcriptDownloadPath = ? "
                "WHERE enclosureUrl = ?",
                (str(path), episode_id),
            )

    def counts(self) -> LibraryCounts:
        """Row counts summarizing the library."""
        with connect(self.db_path) as conn:
            row = conn.execute(COUNTS_SQL).fetchone()
        return LibraryCounts(**dict(row))
