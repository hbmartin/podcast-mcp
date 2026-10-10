"""SQLite schema preparation, connections and the refresh log."""

import sqlite3
from collections.abc import Generator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Self

from overcast_to_sqlite.datastore import Datastore

BUSY_TIMEOUT_SECONDS = 30

# RSS-derived columns are only created when some feed contains the tag, so they
# are added up front to keep every query static.
_OPTIONAL_COLUMNS: dict[str, tuple[str, ...]] = {
    "episodes_extended": (
        "pubDate",
        "itunes:duration",
        "itunes:episode",
        "itunes:season",
        "podcast:transcript:url",
        "podcast:transcript:type",
        "transcriptDownloadPath",
    ),
    "feeds_extended": (
        "itunes:author",
        "itunes:image:href",
        "language",
    ),
}

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS mcp_refresh_log (
    id INTEGER PRIMARY KEY,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    outcome TEXT NOT NULL,
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_episodes_feed_id ON episodes (feedId);
CREATE INDEX IF NOT EXISTS idx_episodes_enclosure ON episodes (enclosureUrl);
CREATE INDEX IF NOT EXISTS idx_episodes_extended_feed
    ON episodes_extended (feedXmlUrl);
"""


@dataclass(frozen=True, slots=True)
class RefreshRecord:
    """One row of the refresh log."""

    started_at: str
    finished_at: str | None
    outcome: str
    error: str | None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Self:
        """Build from a `mcp_refresh_log` row."""
        return cls(
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            outcome=row["outcome"],
            error=row["error"],
        )


def prepare_database(db_path: Path) -> None:
    """Create the overcast-to-sqlite schema plus the columns and tables we query."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    Datastore(str(db_path)).db.close()
    with connect(db_path, writable=True) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        for table, columns in _OPTIONAL_COLUMNS.items():
            existing = {
                row["name"] for row in conn.execute(f"PRAGMA table_info({table})")
            }
            for column in columns:
                if column not in existing:
                    conn.execute(f'ALTER TABLE {table} ADD COLUMN "{column}" TEXT')
        conn.executescript(_SCHEMA_SQL)


@contextmanager
def connect(db_path: Path, *, writable: bool = False) -> Generator[sqlite3.Connection]:
    """Open a connection that commits on success; read-only unless `writable`."""
    with closing(sqlite3.connect(db_path, timeout=BUSY_TIMEOUT_SECONDS)) as conn:
        conn.row_factory = sqlite3.Row
        if not writable:
            conn.execute("PRAGMA query_only = ON")
        with conn:
            yield conn


def record_refresh_start(db_path: Path, *, started_at: str) -> int:
    """Insert a running refresh and return its log id."""
    with connect(db_path, writable=True) as conn:
        cursor = conn.execute(
            "INSERT INTO mcp_refresh_log (started_at, outcome) VALUES (?, 'running')",
            (started_at,),
        )
        if (log_id := cursor.lastrowid) is None:
            msg = "SQLite did not return a refresh log id"
            raise RuntimeError(msg)
        return log_id


def record_refresh_finish(
    db_path: Path,
    *,
    log_id: int,
    outcome: str,
    error: str | None,
    finished_at: str,
) -> None:
    """Mark a refresh as finished."""
    with connect(db_path, writable=True) as conn:
        conn.execute(
            "UPDATE mcp_refresh_log SET finished_at = ?, outcome = ?, error = ? "
            "WHERE id = ?",
            (finished_at, outcome, error, log_id),
        )


def latest_refresh(db_path: Path) -> RefreshRecord | None:
    """Return the most recently started refresh, if any."""
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT started_at, finished_at, outcome, error FROM mcp_refresh_log "
            "ORDER BY id DESC LIMIT 1",
        ).fetchone()
    return RefreshRecord.from_row(row) if row else None
