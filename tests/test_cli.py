import logging
import sys

import pytest
from fastmcp import FastMCP

from podcast_mcp import cli


class FakeRun:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def __call__(self, **kwargs) -> None:
        self.calls.append(kwargs)


@pytest.fixture
def fake_run(monkeypatch, tmp_path) -> FakeRun:
    monkeypatch.setenv("PODCAST_MCP_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("PODCAST_MCP_PATH", raising=False)
    fake = FakeRun()
    monkeypatch.setattr(FastMCP, "run", fake)
    return fake


def test_defaults_to_stdio(monkeypatch, fake_run):
    monkeypatch.setattr(sys, "argv", ["podcast-mcp"])
    cli.main()
    assert fake_run.calls == [{"transport": "stdio", "show_banner": False}]


def test_http_with_secret_path(monkeypatch, fake_run, caplog):
    monkeypatch.setattr(
        sys,
        "argv",
        ["podcast-mcp", "--transport", "http", "--port", "9000", "--path", "/s3/mcp"],
    )
    with caplog.at_level(logging.WARNING):
        cli.main()
    assert fake_run.calls == [
        {"transport": "http", "host": "127.0.0.1", "port": 9000, "path": "/s3/mcp"},
    ]
    assert "default path" not in caplog.text


def test_http_default_path_warns(monkeypatch, fake_run, caplog):
    monkeypatch.setattr(sys, "argv", ["podcast-mcp", "--transport", "http"])
    with caplog.at_level(logging.WARNING):
        cli.main()
    assert fake_run.calls[0]["path"] == "/mcp"
    assert "default path" in caplog.text


def test_path_from_environment(monkeypatch, fake_run):
    monkeypatch.setenv("PODCAST_MCP_PATH", "/from-env/mcp")
    monkeypatch.setattr(sys, "argv", ["podcast-mcp", "--transport", "http"])
    cli.main()
    assert fake_run.calls[0]["path"] == "/from-env/mcp"
