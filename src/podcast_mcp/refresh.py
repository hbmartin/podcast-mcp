"""Background refresh of the library from Overcast via overcast-to-sqlite."""

import logging
import sqlite3
import subprocess
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from podcast_mcp.config import Settings
from podcast_mcp.database import (
    latest_refresh,
    record_refresh_finish,
    record_refresh_start,
)
from podcast_mcp.models import RefreshStatus

logger = logging.getLogger(__name__)

HISTORY_TIMEOUT_SECONDS = 300
DETAILS_TIMEOUT_SECONDS = 1_800
AUTO_REFRESH_WAIT_SECONDS = 20.0
_ERROR_TAIL_LINES = 5

type RefreshStep = Callable[[Settings], None]


class RefreshStepError(RuntimeError):
    """An overcast-to-sqlite command exited unsuccessfully."""

    def __init__(self, command: str, output: str) -> None:
        tail = "\n".join(output.strip().splitlines()[-_ERROR_TAIL_LINES:])
        super().__init__(f"overcast-to-sqlite {command} failed: {tail}")


def utc_now() -> str:
    """Return the current UTC time as an ISO 8601 string."""
    return datetime.now(tz=UTC).isoformat(timespec="seconds")


def _run_overcast_to_sqlite(*args: str, timeout: float) -> None:
    # A subprocess keeps the CLI's prints off the MCP stdio channel and lets a
    # hung feed download be killed by the timeout.
    command = [sys.executable, "-m", "overcast_to_sqlite.cli", *args]
    result = subprocess.run(  # noqa: S603 - fixed argv, no shell
        command,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    logger.debug("overcast-to-sqlite %s output:\n%s", args[0], result.stdout)
    if result.returncode != 0:
        raise RefreshStepError(args[0], result.stderr or result.stdout)


def fetch_listening_history(settings: Settings) -> None:
    """Download the Overcast OPML export (subscriptions and listening history)."""
    _run_overcast_to_sqlite(
        "save",
        str(settings.db_path),
        "--auth",
        str(settings.auth_path),
        "--no-archive",
        timeout=HISTORY_TIMEOUT_SECONDS,
    )


def fetch_feed_details(settings: Settings) -> None:
    """Download RSS feeds that have new episodes, for descriptions and transcripts."""
    _run_overcast_to_sqlite(
        "extend",
        str(settings.db_path),
        "--no-archive",
        timeout=DETAILS_TIMEOUT_SECONDS,
    )


@dataclass(frozen=True, slots=True)
class RefreshSteps:
    """The two refresh phases; replaceable in tests."""

    history: RefreshStep = fetch_listening_history
    details: RefreshStep = fetch_feed_details


class Refresher:
    """Runs at most one refresh at a time in a background thread.

    A refresh first fetches listening history (fast), then feed details (slow).
    Callers can wait for just the first phase.
    """

    def __init__(self, settings: Settings, steps: RefreshSteps | None = None) -> None:
        self._settings = settings
        self._steps = steps or RefreshSteps()
        self._lock = threading.Lock()
        self._history_ready = threading.Event()
        self._finished = threading.Event()
        self._history_ready.set()
        self._finished.set()

    @property
    def running(self) -> bool:
        """Whether a refresh is in progress."""
        return not self._finished.is_set()

    def is_stale(self) -> bool:
        """Whether the last refresh started longer ago than the refresh interval."""
        if (record := latest_refresh(self._settings.db_path)) is None:
            return True
        age = datetime.now(tz=UTC) - datetime.fromisoformat(record.started_at)
        return age.total_seconds() >= self._settings.refresh_interval_seconds

    def ensure_fresh(self, wait_seconds: float = AUTO_REFRESH_WAIT_SECONDS) -> None:
        """Start a refresh if the data is stale, then wait for listening history.

        Waits at most `wait_seconds` and only while history is being fetched; a
        refresh still downloading feed details does not block callers.
        """
        if self._settings.has_overcast_credentials() and self.is_stale():
            try:
                self.start()
            except (sqlite3.Error, RuntimeError):
                logger.exception("Could not start a refresh; serving current data")
        self._history_ready.wait(timeout=wait_seconds)

    def start(self) -> bool:
        """Start a refresh unless one is running. Returns whether one started."""
        with self._lock:
            if self.running:
                return False
            # Log first: if the write fails, no waiter is left blocked.
            log_id = record_refresh_start(self._settings.db_path, started_at=utc_now())
            self._history_ready.clear()
            self._finished.clear()
            thread = threading.Thread(
                target=self._run,
                kwargs={"log_id": log_id},
                name="overcast-refresh",
                daemon=True,
            )
            try:
                thread.start()
            except RuntimeError as exc:
                # No thread will ever set the events, so resolve the log row and
                # release waiters here, or `running` would stay true forever.
                self._finish(
                    log_id=log_id,
                    outcome="failed",
                    error=f"Could not start the refresh thread: {exc}",
                )
                raise
            return True

    def wait_until_finished(self, timeout: float) -> bool:
        """Wait for the current refresh to finish. Returns whether it finished."""
        return self._finished.wait(timeout=timeout)

    def status(self) -> RefreshStatus:
        """Describe the latest refresh."""
        # The lock keeps a refresh from starting between the two reads.
        with self._lock:
            running = self.running
            record = latest_refresh(self._settings.db_path)
        outcome = record.outcome if record else None
        if outcome == "running" and not running:
            # The server stopped mid-refresh or could not record the result.
            outcome = "interrupted"
        return RefreshStatus(
            running=running,
            has_overcast_credentials=self._settings.has_overcast_credentials(),
            last_started=record.started_at if record else None,
            last_finished=record.finished_at if record else None,
            last_outcome=outcome,
            last_error=record.error if record else None,
        )

    def _run(self, log_id: int) -> None:
        outcome, error = "failed", None
        try:
            self._steps.history(self._settings)
            outcome = "history_only"
            self._history_ready.set()
            self._steps.details(self._settings)
            outcome = "ok"
        except Exception as exc:
            logger.exception("Overcast refresh stopped with outcome %s", outcome)
            error = str(exc)
        finally:
            self._finish(log_id=log_id, outcome=outcome, error=error)

    def _finish(self, *, log_id: int, outcome: str, error: str | None) -> None:
        # Waiters must be released even when the log write fails (e.g. the
        # database is locked), or every tool call would stall until timeout.
        try:
            record_refresh_finish(
                self._settings.db_path,
                log_id=log_id,
                outcome=outcome,
                error=error,
                finished_at=utc_now(),
            )
        except sqlite3.Error:
            logger.exception("Could not record the end of refresh %d", log_id)
        finally:
            self._history_ready.set()
            self._finished.set()
