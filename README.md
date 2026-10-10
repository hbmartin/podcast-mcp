# podcast-mcp

An MCP server that gives Claude read access to your [Overcast](https://overcast.fm)
listening history: what you played, starred and subscribed to, podcast feed
details, full-text search over episode titles and descriptions, and episode
transcripts.

Data comes from Overcast's OPML export via
[overcast-to-sqlite](https://github.com/hbmartin/overcast-to-sqlite) and is kept in a
local SQLite database.

**New here? Start with [QUICKSTART.md](QUICKSTART.md)**, which also covers reusing an
existing overcast-to-sqlite database.

## Tools

| Tool | What it does |
|---|---|
| `get_listening_history` | Listened, played, in-progress or starred episodes, filterable by podcast and date |
| `search_episodes` | Full-text search over titles and descriptions of every episode in your feeds |
| `list_podcasts` | Podcasts in your library, most recently heard first |
| `get_podcast` | Feed details, listening stats, recent and latest episodes for one podcast |
| `get_episode` | Full description, metadata and listening state for one episode |
| `get_transcript` | Plain-text transcript (VTT, SRT, JSON or HTML) when the podcast publishes one |
| `refresh_library` | Fetch the latest data from Overcast now |
| `get_library_status` | Library size and last refresh time/outcome |

## Refreshing

- When any data tool is called and the last refresh started over an hour ago, a
  refresh starts in the background. The call waits up to 20 seconds for your
  listening history; feed details keep updating in the background.
- `refresh_library` refreshes on demand.
- Transcripts are downloaded the first time they are requested, then cached.

A refresh runs `overcast-to-sqlite save` (OPML export) and then
`overcast-to-sqlite extend` (RSS feeds with new episodes).

## Setup

```sh
uv sync
mkdir -p ~/.podcast-mcp
uv run overcast-to-sqlite auth --auth ~/.podcast-mcp/auth.json
```

The auth command stores an Overcast session cookie, not your password. You can
instead set `OVERCAST_COOKIE` to the value of Overcast's `o` cookie.

| Environment variable | Default | Purpose |
|---|---|---|
| `PODCAST_MCP_DATA_DIR` | `~/.podcast-mcp` | Holds `overcast.db`, `auth.json` and the transcript cache |
| `PODCAST_MCP_REFRESH_INTERVAL` | `3600` | Seconds before data counts as stale |
| `PODCAST_MCP_PATH` | `/mcp` | HTTP endpoint path |
| `OVERCAST_COOKIE` | | Overcast cookie, instead of `auth.json` |

## Local use (Claude Code / Claude Desktop)

```sh
claude mcp add podcasts -- uv --directory /path/to/podcast-mcp run podcast-mcp
```

## Remote use from claude.ai (prototype via Tailscale Funnel)

claude.ai connects from Anthropic's cloud, so the server needs a public HTTPS URL.
Until real OAuth is added, the endpoint path acts as the password: anyone with the
full URL can read your listening history.

1. Pick a secret path and keep it somewhere safe:

   ```sh
   export PODCAST_MCP_PATH="/$(uv run python -c 'import secrets; print(secrets.token_urlsafe(24))')/mcp"
   echo "$PODCAST_MCP_PATH"
   ```

2. Start the server:

   ```sh
   uv run podcast-mcp --transport http --port 8000
   ```

3. In another terminal, expose it with [Tailscale Funnel](https://tailscale.com/kb/1223/funnel)
   (the first run links to enabling Funnel for your tailnet):

   ```sh
   tailscale funnel --bg 8000
   ```

4. In claude.ai, open **Settings → Connectors → Add custom connector** and enter
   `https://<machine>.<tailnet>.ts.net<PODCAST_MCP_PATH>`.

The connector only works while your Mac is awake and the server is running. Stop
exposing it with `tailscale funnel reset`; this clears all of this machine's Funnel
config, so check `tailscale funnel status` first if you use Funnel for anything else.

## Development

```sh
uv run ruff check src --fix; uv run ruff format src tests
uv run pyrefly check src tests; uv run ty check src tests
uv run pytest --cov=podcast_mcp
uv run lizard --languages python --CCN 15 --length 120 --arguments 8 src/podcast_mcp
```
