# Quickstart

You need [uv](https://docs.astral.sh/uv/) and an Overcast account. To use the
server from claude.ai you also need [Tailscale](https://tailscale.com).

## 1. Install

```sh
git clone https://github.com/hbmartin/podcast-mcp.git && cd podcast-mcp
uv sync
```

## 2. Set up your data

The server reads one directory, `$PODCAST_MCP_DATA_DIR` (default `~/.podcast-mcp`):

```text
overcast.db             your library (overcast-to-sqlite schema)
auth.json               Overcast session cookie (optional, enables refreshing)
archive/transcripts/    transcript cache
```

### Option A: start fresh

```sh
mkdir -p ~/.podcast-mcp
uv run overcast-to-sqlite auth -a ~/.podcast-mcp/auth.json   # asks for email/password; stores only a cookie

# Optional: load data now instead of on the first request (the first `extend` can take minutes)
uv run overcast-to-sqlite save ~/.podcast-mcp/overcast.db -a ~/.podcast-mcp/auth.json
uv run overcast-to-sqlite extend ~/.podcast-mcp/overcast.db
```

Instead of `auth.json`, you can `export OVERCAST_COOKIE=<value of Overcast's "o" cookie>`.

### Option B: use an existing overcast-to-sqlite database

Point the server at the directory that holds it:

```sh
export PODCAST_MCP_DATA_DIR=/path/to/dir    # must contain overcast.db
```

- **File name.** The database must be called `overcast.db`, the CLI's default. If yours has another
  name, symlink it: `ln -s /path/to/my.db "$PODCAST_MCP_DATA_DIR/overcast.db"`.
- **Refreshing.** The server refreshes from Overcast only if it finds credentials, either
  `$PODCAST_MCP_DATA_DIR/auth.json` (the CLI's default `auth.json` in that directory works) or
  `OVERCAST_COOKIE`. With neither, the server is read-only and you keep updating with the CLI or
  cron as before. It's safe to use both on the same database.
- **What needs `extend`.** `save` alone gives listening history. Search, descriptions, durations and
  transcripts also need `extend`, which the server runs on refresh, or run it yourself with
  `uv run overcast-to-sqlite extend overcast.db`.
- **Transcripts** you already downloaded with `overcast-to-sqlite transcripts` are reused. New ones
  are cached in `archive/transcripts/` next to the database, the same place the CLI uses.
- **Startup changes are additive only:** WAL journal mode (you'll see `overcast.db-wal` and
  `overcast.db-shm` files), missing nullable columns on `episodes_extended` and `feeds_extended`, an
  `mcp_refresh_log` table, three indexes, and any overcast-to-sqlite tables that are missing. The
  CLI keeps working. To be cautious, run `cp overcast.db overcast.db.bak` first.
- **Older databases** may lack the search index. If search fails with
  `no such table: episodes_extended_fts`, run:

  ```sh
  uv run sqlite-utils enable-fts "$PODCAST_MCP_DATA_DIR/overcast.db" episodes_extended title description --create-triggers
  ```

## 3. Connect Claude

### Claude Code

Run this from the repo directory:

```sh
claude mcp add podcasts -s user -e PODCAST_MCP_DATA_DIR="$HOME/.podcast-mcp" -- uv --directory "$PWD" run podcast-mcp
```

### Claude Desktop

Add this to `~/Library/Application Support/Claude/claude_desktop_config.json`, then restart the app.
Use the full path from `which uv`, because Desktop doesn't load your shell's `PATH`:

```json
{
  "mcpServers": {
    "podcasts": {
      "command": "/Users/you/.local/bin/uv",
      "args": ["--directory", "/path/to/podcast-mcp", "run", "podcast-mcp"],
      "env": { "PODCAST_MCP_DATA_DIR": "/Users/you/.podcast-mcp" }
    }
  }
}
```

### claude.ai (through Tailscale Funnel)

claude.ai connects from the internet, so the server has to be reachable over public HTTPS. The
secret URL path is the only access control, so treat the full URL like a password.

```sh
export PODCAST_MCP_PATH="/$(openssl rand -hex 16)/mcp"   # save this value; reuse it on every start
uv run podcast-mcp --transport http --port 8000
```

In a second terminal:

```sh
tailscale funnel --bg 8000   # the first run gives you a link to enable Funnel for your tailnet
tailscale funnel status      # shows https://<machine>.<tailnet>.ts.net
```

In claude.ai, open **Settings → Connectors → Add custom connector**. Enter
`https://<machine>.<tailnet>.ts.net` followed by your `$PODCAST_MCP_PATH`, then turn the connector
on in a chat.

The connector only works while your Mac is awake and the server is running. To stop exposing it,
run `tailscale funnel reset`; this clears all Funnel config on the machine.

## 4. Try it

- "What podcasts did I listen to this week?"
- "Find episodes about home espresso that I haven't heard."
- "Summarize the transcript of the last episode I starred."
- "Check my podcast library status." This shows counts and the last refresh time and outcome.

## Reference

| Setting | Default | Purpose |
|---|---|---|
| `PODCAST_MCP_DATA_DIR` | `~/.podcast-mcp` | Directory holding `overcast.db`, `auth.json` and `archive/` |
| `PODCAST_MCP_REFRESH_INTERVAL` | `3600` | Seconds before data counts as stale |
| `PODCAST_MCP_PATH` / `--path` | `/mcp` | HTTP endpoint path |
| `OVERCAST_COOKIE` | none | Cookie to use instead of `auth.json` |
| `--transport` | `stdio` | `stdio` for Claude Code and Desktop, `http` for claude.ai |
| `--host` / `--port` | `127.0.0.1` / `8000` | HTTP bind address |

**Refresh behavior.** A request that arrives more than `PODCAST_MCP_REFRESH_INTERVAL` after the
last refresh starts one in the background. That request waits up to 20 seconds for listening
history; feed details keep updating afterwards. `refresh_library` refreshes on demand.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `refresh_library` says "No Overcast credentials" | Put `auth.json` in the data directory or set `OVERCAST_COOKIE` |
| Status shows `last_outcome: failed` with `OpmlFetchError` | The cookie expired. Re-run `uv run overcast-to-sqlite auth -a "$PODCAST_MCP_DATA_DIR/auth.json"` |
| Status shows `last_outcome: history_only` | History updated but a feed download failed; the next refresh retries |
| Search finds nothing | Feed details haven't loaded yet. Run `extend` (see Option B) or wait for the refresh to finish |
| `no such table: episodes_extended_fts` | Run the `enable-fts` command from Option B |
| claude.ai can't connect | Check the server is running, the Mac is awake, `tailscale funnel status` is on, and the URL includes the path |
| Log warns "Serving at the default path" | Set `PODCAST_MCP_PATH` to a secret path |
