## Workflow
- Always run `uv run ruff check src --fix; uv run ruff format src tests; uv run pyrefly check src; uv run ty check src` after making changes.
- Always run pytest and lizard after finishing implementation and make fixes

## Development Notes

- The project supports Python 3.13+
- Uses uv for dependency management instead of traditional pip/setuptools
- Use uv not python for running scripts.
- Code style uses Ruff formatter and linter

## Python Practices
- Always use or add type hints
- Prefer @dataclasses where applicable
- Always use f-string over string formatting or concatentation (except in logging strings)
- Use async generators and comprehensions when they might provide benefits
- Use underscores in large numeric literals
- Use walrus assignment := where applicable
- Prefer to use named arguments when calling a method with more than one argument
- Use "list" instead of "List" and "dict" instead of "Dict" and "|" instead of "Union" for types
- Use "Self" for applicable types
- Use Structural Pattern Matching (match...case) where applicable
- Always use pathlib.Path for file operations, never use os.path
- Keep Lizard's cyclomatic-complexity ceiling at 27 or lower; refactor code instead of raising it.
- Prefer Explicitness and Small Functions
- Use modern Python features e.g. assignment expressions and Structural Pattern Matching where applicable
-Use a parenthesized tuple of exception classes in the except clause

## Notes
- Add notes to this list in AGENTS.md as you learn information worth remembering
- overcast-to-sqlite creates `episodes_extended`/`feeds_extended` columns from RSS tags on the fly (`alter=True`), so a column like `"itunes:duration"` may not exist yet. `database.prepare_database` adds every optional column we query so all SQL stays static.
- Refreshes run the overcast-to-sqlite CLI in a subprocess: its `print`s would corrupt the MCP stdio channel, and its feed downloads have no timeout.
- FastMCP 4.x (MCP SDK v2): tool annotations can be passed as a camelCase dict, `Google-style Args:` docstrings become parameter descriptions, and the Host/Origin guard is off by default (needed behind Tailscale Funnel).
- `.github/workflows/lint-test.yml` was copied from another project (legolization/LDraw steps, Python 3.12) and needs adapting before CI can pass.
