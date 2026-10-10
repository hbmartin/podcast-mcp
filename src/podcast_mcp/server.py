"""FastMCP server exposing Overcast listening history."""

from dataclasses import dataclass

import requests
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from podcast_mcp.config import Settings
from podcast_mcp.database import prepare_database
from podcast_mcp.library import EmptySearchQueryError, HistoryStatus, Library, Page
from podcast_mcp.models import (
    EpisodeDetail,
    EpisodeSearchResult,
    HistoryEpisode,
    LibraryStatus,
    PodcastDetail,
    PodcastSummary,
    RefreshStatus,
    Transcript,
)
from podcast_mcp.refresh import Refresher
from podcast_mcp.transcripts import TranscriptStore, TranscriptUnavailableError

MAX_PAGE_SIZE = 200
MAX_TRANSCRIPT_CHARS = 100_000
DEFAULT_TRANSCRIPT_CHARS = 40_000
PODCAST_DETAIL_EPISODES = 10
EXPLICIT_REFRESH_WAIT_SECONDS = 45.0

INSTRUCTIONS = """\
Read-only access to the user's podcast listening history from the Overcast app.

- `episode_id` is an episode's audio (enclosure) URL; `podcast_id` is Overcast's
  numeric podcast id. Get them from other tools' results.
- "Listened" means finished or more than 5 minutes heard.
- Data refreshes from Overcast automatically when it is more than an hour old.
  Use `refresh_library` only when the user says the data is out of date.
"""

_READ_ONLY = {"readOnlyHint": True, "openWorldHint": False}
_READ_ONLY_NETWORK = {"readOnlyHint": True, "openWorldHint": True}
_REFRESH = {
    "readOnlyHint": False,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": True,
}


def _page(limit: int, offset: int) -> Page:
    return Page(limit=min(max(limit, 1), MAX_PAGE_SIZE), offset=max(offset, 0))


@dataclass(frozen=True, slots=True)
class PodcastTools:
    """Tool implementations; each public method is registered as an MCP tool."""

    library: Library
    refresher: Refresher
    transcripts: TranscriptStore

    def get_listening_history(  # noqa: PLR0913 - one parameter per filter
        self,
        *,
        status: HistoryStatus = "listened",
        podcast_id: int | None = None,
        since: str | None = None,
        until: str | None = None,
        limit: int = 25,
        offset: int = 0,
    ) -> list[HistoryEpisode]:
        """List episodes from the user's listening history, most recent first.

        Args:
            status: "listened" (finished or >5 min heard), "played" (finished),
                "in_progress" (started, not finished) or "starred".
            podcast_id: Only episodes of this podcast.
            since: Only activity on or after this ISO date/time, e.g. "2026-01-01".
            until: Only activity before this ISO date/time.
            limit: Maximum episodes to return (1-200).
            offset: Episodes to skip, for paging.

        """
        self.refresher.ensure_fresh()
        return self.library.listening_history(
            status=status,
            podcast_id=podcast_id,
            since=since,
            until=until,
            page=_page(limit, offset),
        )

    def search_episodes(
        self,
        query: str,
        *,
        listened_only: bool = False,
        podcast_id: int | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[EpisodeSearchResult]:
        """Search episode titles and descriptions across the user's podcasts.

        Covers every episode in the feeds the user follows, not only ones they
        played. Results are ranked by relevance and require every word.

        Args:
            query: Words to search for.
            listened_only: Only episodes the user has listened to.
            podcast_id: Only episodes of this podcast.
            limit: Maximum results to return (1-200).
            offset: Results to skip, for paging.

        """
        self.refresher.ensure_fresh()
        try:
            return self.library.search_episodes(
                query,
                listened_only=listened_only,
                podcast_id=podcast_id,
                page=_page(limit, offset),
            )
        except EmptySearchQueryError as exc:
            raise ToolError(str(exc)) from exc

    def list_podcasts(
        self,
        *,
        subscribed_only: bool = True,
        name_contains: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[PodcastSummary]:
        """List podcasts in the user's Overcast library, most recently heard first.

        Args:
            subscribed_only: Only podcasts the user is currently subscribed to.
            name_contains: Only podcasts whose title contains this text.
            limit: Maximum podcasts to return (1-200).
            offset: Podcasts to skip, for paging.

        """
        self.refresher.ensure_fresh()
        return self.library.podcasts(
            subscribed_only=subscribed_only,
            name_contains=name_contains,
            page=_page(limit, offset),
        )

    def get_podcast(self, podcast_id: int) -> PodcastDetail:
        """Get a podcast's feed details, listening stats and recent episodes.

        Args:
            podcast_id: Overcast podcast id from another tool's results.

        """
        self.refresher.ensure_fresh()
        if detail := self.library.podcast_detail(
            podcast_id,
            episodes=PODCAST_DETAIL_EPISODES,
        ):
            return detail
        msg = f"No podcast with id {podcast_id}"
        raise ToolError(msg)

    def get_episode(self, episode_id: str) -> EpisodeDetail:
        """Get an episode's full description, metadata and listening state.

        Args:
            episode_id: Episode id (audio URL) from another tool's results.

        """
        self.refresher.ensure_fresh()
        if detail := self.library.episode_detail(episode_id):
            return detail
        msg = f"No episode with id {episode_id}"
        raise ToolError(msg)

    def get_transcript(
        self,
        episode_id: str,
        offset: int = 0,
        max_chars: int = DEFAULT_TRANSCRIPT_CHARS,
    ) -> Transcript:
        """Get an episode's transcript as plain text, when the podcast publishes one.

        Long transcripts are returned in windows; pass `next_offset` back as
        `offset` to continue.

        Args:
            episode_id: Episode id (audio URL) from another tool's results.
            offset: Character position to start from.
            max_chars: Maximum characters to return (up to 100,000).

        """
        if (source := self.library.transcript_source(episode_id)) is None:
            msg = f"No episode with id {episode_id}"
            raise ToolError(msg)
        try:
            text = self.transcripts.text(source)
        except TranscriptUnavailableError as exc:
            raise ToolError(str(exc)) from exc
        except (requests.RequestException, OSError) as exc:
            msg = f"Could not download the transcript: {exc}"
            raise ToolError(msg) from exc
        start = max(offset, 0)
        end = start + min(max(max_chars, 1), MAX_TRANSCRIPT_CHARS)
        return Transcript(
            episode_id=source.episode_id,
            title=source.title,
            podcast=source.podcast,
            text=text[start:end],
            offset=start,
            total_chars=len(text),
            next_offset=end if end < len(text) else None,
        )

    def refresh_library(self) -> RefreshStatus:
        """Fetch the latest listening history and feed details from Overcast now.

        Waits up to 45 seconds. Feed details for many podcasts can take longer
        and continue in the background; check `get_library_status` later.
        """
        if not self.refresher.status().has_overcast_credentials:
            msg = (
                "No Overcast credentials: run `overcast-to-sqlite auth` into the "
                "data directory or set OVERCAST_COOKIE on the server"
            )
            raise ToolError(msg)
        self.refresher.start()
        self.refresher.wait_until_finished(timeout=EXPLICIT_REFRESH_WAIT_SECONDS)
        return self.refresher.status()

    def get_library_status(self) -> LibraryStatus:
        """Report library size and when data was last refreshed from Overcast."""
        return LibraryStatus(
            counts=self.library.counts(),
            refresh=self.refresher.status(),
        )


def create_server(settings: Settings, refresher: Refresher | None = None) -> FastMCP:
    """Prepare the database and build the MCP server."""
    prepare_database(settings.db_path)
    library = Library(db_path=settings.db_path)
    tools = PodcastTools(
        library=library,
        refresher=refresher or Refresher(settings=settings),
        transcripts=TranscriptStore(
            library=library, cache_dir=settings.transcripts_dir
        ),
    )
    mcp = FastMCP(name="podcast-history", instructions=INSTRUCTIONS)
    for method in (
        tools.get_listening_history,
        tools.search_episodes,
        tools.list_podcasts,
        tools.get_podcast,
        tools.get_episode,
        tools.get_library_status,
    ):
        mcp.tool(method, annotations=_READ_ONLY)
    mcp.tool(tools.get_transcript, annotations=_READ_ONLY_NETWORK)
    mcp.tool(tools.refresh_library, annotations=_REFRESH)
    return mcp
