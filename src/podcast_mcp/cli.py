"""Command-line entry point for the podcast MCP server."""

import argparse
import logging
import os

from podcast_mcp.config import Settings
from podcast_mcp.server import create_server

logger = logging.getLogger(__name__)

DEFAULT_HTTP_PATH = "/mcp"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="podcast-mcp",
        description="Serve Overcast listening history over MCP.",
    )
    parser.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8_000)
    parser.add_argument(
        "--path",
        default=os.getenv("PODCAST_MCP_PATH", DEFAULT_HTTP_PATH),
        help="HTTP endpoint path; use a hard-to-guess path when exposed publicly "
        "(default: $PODCAST_MCP_PATH or /mcp)",
    )
    return parser.parse_args()


def main() -> None:
    """Run the MCP server."""
    args = _parse_args()
    logging.basicConfig(level=logging.INFO)
    mcp = create_server(Settings.from_env())
    match args.transport:
        case "http":
            if args.path == DEFAULT_HTTP_PATH:
                logger.warning(
                    "Serving at the default path %s: anyone who can reach this "
                    "server can read your listening history",
                    DEFAULT_HTTP_PATH,
                )
            mcp.run(transport="http", host=args.host, port=args.port, path=args.path)
        case _:
            mcp.run(transport="stdio", show_banner=False)
