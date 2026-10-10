from pathlib import Path

import pytest

from podcast_mcp.config import Settings
from podcast_mcp.database import prepare_database
from podcast_mcp.library import Library
from tests.sample_library import populate


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path / "data")


@pytest.fixture
def populated_settings(settings: Settings) -> Settings:
    prepare_database(settings.db_path)
    populate(settings.db_path)
    return settings


@pytest.fixture
def library(populated_settings: Settings) -> Library:
    return Library(db_path=populated_settings.db_path)


@pytest.fixture(autouse=True)
def _no_overcast_cookie(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OVERCAST_COOKIE", raising=False)
