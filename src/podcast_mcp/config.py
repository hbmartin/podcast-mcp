"""Runtime configuration, read from environment variables."""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Self

DEFAULT_DATA_DIR = Path.home() / ".podcast-mcp"
DEFAULT_REFRESH_INTERVAL_SECONDS = 3_600
OVERCAST_COOKIE_ENV = "OVERCAST_COOKIE"


@dataclass(frozen=True, slots=True)
class Settings:
    """Where the library lives and how often it is refreshed from Overcast."""

    data_dir: Path
    refresh_interval_seconds: int = DEFAULT_REFRESH_INTERVAL_SECONDS

    @classmethod
    def from_env(cls) -> Self:
        """Build settings from `PODCAST_MCP_*` environment variables."""
        data_dir = Path(os.getenv("PODCAST_MCP_DATA_DIR", str(DEFAULT_DATA_DIR)))
        interval = os.getenv("PODCAST_MCP_REFRESH_INTERVAL")
        return cls(
            data_dir=data_dir.expanduser(),
            refresh_interval_seconds=(
                int(interval) if interval else DEFAULT_REFRESH_INTERVAL_SECONDS
            ),
        )

    @property
    def db_path(self) -> Path:
        """SQLite database written by overcast-to-sqlite."""
        return self.data_dir / "overcast.db"

    @property
    def auth_path(self) -> Path:
        """Cookie file written by `overcast-to-sqlite auth`."""
        return self.data_dir / "auth.json"

    @property
    def transcripts_dir(self) -> Path:
        """Cache directory for downloaded transcripts."""
        return self.data_dir / "archive" / "transcripts"

    def has_overcast_credentials(self) -> bool:
        """Return whether an Overcast cookie is available for refreshing."""
        return bool(os.getenv(OVERCAST_COOKIE_ENV)) or self.auth_path.exists()
