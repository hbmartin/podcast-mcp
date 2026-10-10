import sqlite3
import subprocess
import threading
import time
from pathlib import Path

import pytest

from podcast_mcp import refresh
from podcast_mcp.config import DEFAULT_DATA_DIR, Settings
from podcast_mcp.database import prepare_database, record_refresh_start
from podcast_mcp.refresh import Refresher, RefreshStepError, RefreshSteps, utc_now

WAIT = 5.0


class RecordingSteps:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.history_error: Exception | None = None
        self.details_error: Exception | None = None
        self.release_details = threading.Event()
        self.release_details.set()

    def history(self, settings: Settings) -> None:
        self.calls.append("history")
        if self.history_error:
            raise self.history_error

    def details(self, settings: Settings) -> None:
        self.release_details.wait(timeout=WAIT)
        self.calls.append("details")
        if self.details_error:
            raise self.details_error

    def as_steps(self) -> RefreshSteps:
        return RefreshSteps(history=self.history, details=self.details)


@pytest.fixture
def credentialed(settings: Settings) -> Settings:
    prepare_database(settings.db_path)
    settings.auth_path.write_text('{"overcast": {"o": "cookie"}}')
    return settings


def test_ensure_fresh_refreshes_when_never_refreshed(credentialed):
    steps = RecordingSteps()
    refresher = Refresher(credentialed, steps=steps.as_steps())
    refresher.ensure_fresh()
    assert refresher.wait_until_finished(timeout=WAIT)
    assert steps.calls == ["history", "details"]
    status = refresher.status()
    assert status.last_outcome == "ok"
    assert status.last_finished is not None
    assert status.last_error is None
    assert status.running is False
    assert status.has_overcast_credentials is True


def test_ensure_fresh_skips_recent_refresh(credentialed):
    steps = RecordingSteps()
    refresher = Refresher(credentialed, steps=steps.as_steps())
    refresher.ensure_fresh()
    refresher.wait_until_finished(timeout=WAIT)
    refresher.ensure_fresh()
    refresher.wait_until_finished(timeout=WAIT)
    assert steps.calls == ["history", "details"]


def test_zero_interval_always_refreshes(credentialed):
    settings = Settings(data_dir=credentialed.data_dir, refresh_interval_seconds=0)
    steps = RecordingSteps()
    refresher = Refresher(settings, steps=steps.as_steps())
    for _ in range(2):
        refresher.ensure_fresh()
        refresher.wait_until_finished(timeout=WAIT)
    assert steps.calls == ["history", "details", "history", "details"]


def test_no_credentials_never_refreshes(settings):
    prepare_database(settings.db_path)
    steps = RecordingSteps()
    refresher = Refresher(settings, steps=steps.as_steps())
    refresher.ensure_fresh(wait_seconds=0)
    assert steps.calls == []
    assert refresher.status().last_started is None


def test_cookie_env_counts_as_credentials(settings, monkeypatch):
    monkeypatch.setenv("OVERCAST_COOKIE", "cookie")
    assert settings.has_overcast_credentials()


def test_history_failure_is_recorded(credentialed):
    steps = RecordingSteps()
    steps.history_error = RefreshStepError("save", "line 1\nOpmlFetchError: 429\n")
    refresher = Refresher(credentialed, steps=steps.as_steps())
    refresher.ensure_fresh()
    refresher.wait_until_finished(timeout=WAIT)
    status = refresher.status()
    assert steps.calls == ["history"]
    assert status.last_outcome == "failed"
    assert (
        status.last_error
        == "overcast-to-sqlite save failed: line 1\nOpmlFetchError: 429"
    )


def test_details_failure_keeps_history(credentialed):
    steps = RecordingSteps()
    steps.details_error = RuntimeError("feed broke")
    refresher = Refresher(credentialed, steps=steps.as_steps())
    refresher.ensure_fresh()
    refresher.wait_until_finished(timeout=WAIT)
    status = refresher.status()
    assert status.last_outcome == "history_only"
    assert status.last_error == "feed broke"


def test_callers_wait_only_for_history(credentialed):
    steps = RecordingSteps()
    steps.release_details.clear()
    refresher = Refresher(credentialed, steps=steps.as_steps())
    refresher.ensure_fresh(wait_seconds=WAIT)
    assert steps.calls == ["history"]
    assert refresher.running
    assert refresher.start() is False
    assert refresher.status().last_outcome == "running"
    steps.release_details.set()
    assert refresher.wait_until_finished(timeout=WAIT)
    assert steps.calls == ["history", "details"]


def _database_locked(*args, **kwargs) -> None:
    msg = "database is locked"
    raise sqlite3.OperationalError(msg)


def test_failed_finish_log_write_releases_waiters(credentialed, monkeypatch):
    # A locked database breaks the refresh and its log write together.
    monkeypatch.setattr(refresh, "record_refresh_finish", _database_locked)
    steps = RecordingSteps()
    steps.history_error = RuntimeError("database is locked")
    refresher = Refresher(credentialed, steps=steps.as_steps())
    started = time.monotonic()
    refresher.ensure_fresh(wait_seconds=WAIT)
    assert refresher.wait_until_finished(timeout=WAIT)
    refresher.ensure_fresh(wait_seconds=WAIT)
    assert time.monotonic() - started < WAIT
    status = refresher.status()
    assert status.running is False
    assert status.last_outcome == "interrupted"


def test_failed_start_log_write_serves_current_data(credentialed, monkeypatch):
    monkeypatch.setattr(refresh, "record_refresh_start", _database_locked)
    steps = RecordingSteps()
    refresher = Refresher(credentialed, steps=steps.as_steps())
    started = time.monotonic()
    refresher.ensure_fresh(wait_seconds=WAIT)
    assert time.monotonic() - started < WAIT
    assert steps.calls == []
    assert refresher.running is False
    with pytest.raises(sqlite3.OperationalError):
        refresher.start()


def _cannot_start_thread(self: threading.Thread) -> None:
    msg = "can't start new thread"
    raise RuntimeError(msg)


def test_thread_start_failure_releases_waiters_and_allows_retry(
    credentialed,
    monkeypatch,
):
    steps = RecordingSteps()
    refresher = Refresher(credentialed, steps=steps.as_steps())
    with monkeypatch.context() as patch:
        patch.setattr(threading.Thread, "start", _cannot_start_thread)
        started = time.monotonic()
        refresher.ensure_fresh(wait_seconds=WAIT)
        assert time.monotonic() - started < WAIT
        with pytest.raises(RuntimeError, match="can't start new thread"):
            refresher.start()
    status = refresher.status()
    assert status.running is False
    assert status.last_outcome == "failed"
    assert (
        status.last_error
        == "Could not start the refresh thread: can't start new thread"
    )
    assert steps.calls == []
    assert refresher.start() is True
    assert refresher.wait_until_finished(timeout=WAIT)
    assert steps.calls == ["history", "details"]


def test_refresh_left_running_by_a_previous_process_is_interrupted(credentialed):
    record_refresh_start(credentialed.db_path, started_at=utc_now())
    status = Refresher(credentialed).status()
    assert status.running is False
    assert status.last_outcome == "interrupted"


def test_settings_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("PODCAST_MCP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PODCAST_MCP_REFRESH_INTERVAL", "60")
    settings = Settings.from_env()
    assert settings.db_path == tmp_path / "overcast.db"
    assert settings.auth_path == tmp_path / "auth.json"
    assert settings.transcripts_dir == tmp_path / "archive" / "transcripts"
    assert settings.refresh_interval_seconds == 60


def test_settings_defaults(monkeypatch):
    monkeypatch.delenv("PODCAST_MCP_DATA_DIR", raising=False)
    monkeypatch.delenv("PODCAST_MCP_REFRESH_INTERVAL", raising=False)
    settings = Settings.from_env()
    assert settings.data_dir == DEFAULT_DATA_DIR
    assert settings.refresh_interval_seconds == 3_600


class FakeRun:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.result = subprocess.CompletedProcess([], returncode, stdout, stderr)
        self.commands: list[list[str]] = []

    def __call__(self, command: list[str], **kwargs) -> subprocess.CompletedProcess:
        self.commands.append(command)
        return self.result


def test_fetch_steps_invoke_overcast_to_sqlite(monkeypatch, settings):
    fake = FakeRun(returncode=0, stdout="ok")
    monkeypatch.setattr(subprocess, "run", fake)
    refresh.fetch_listening_history(settings)
    refresh.fetch_feed_details(settings)
    save, extend = fake.commands
    assert save[1:4] == ["-m", "overcast_to_sqlite.cli", "save"]
    assert save[4:] == [
        str(settings.db_path),
        "--auth",
        str(settings.auth_path),
        "--no-archive",
    ]
    assert extend[3:] == ["extend", str(settings.db_path), "--no-archive"]


def test_fetch_step_failure_reports_output_tail(monkeypatch, settings):
    stderr = "\n".join(f"line {n}" for n in range(10))
    monkeypatch.setattr(subprocess, "run", FakeRun(returncode=1, stderr=stderr))
    with pytest.raises(RefreshStepError, match=r"(?s)save failed: line 5\n.*line 9$"):
        refresh.fetch_listening_history(settings)


def test_fetch_step_failure_falls_back_to_stdout(monkeypatch, settings):
    monkeypatch.setattr(subprocess, "run", FakeRun(returncode=2, stdout="boom"))
    with pytest.raises(RefreshStepError, match="extend failed: boom"):
        refresh.fetch_feed_details(settings)


def test_prepare_database_is_idempotent(settings):
    prepare_database(settings.db_path)
    prepare_database(settings.db_path)
    assert Path(settings.db_path).exists()
