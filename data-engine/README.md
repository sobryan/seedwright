# seedwright data engine

The **Python MCP server** (ADR-0004): all the Python data work behind MCP tools, called by the
central Spring server over **stdio**.

| Tool | Wraps | Purpose |
|---|---|---|
| `author_generator` | `seedwright_authoring.loop.author` | Evaluator-optimizer authors Generator Artifacts (mock provider for now) |
| `generate_dataset` | genlib `compile → generate → write` | Deterministic execution: canonical Parquet + Load Plan |
| `validate_dataset` | authoring data-tests over Parquet | Full-dataset validation against the canonical checkpoint |
| `export_dataset` | new export module | Canonical → CSV / JSONL / SQL-INSERT files (the file sink, FR-G.4) |
| `load_postgres` / `teardown_postgres` | `seedwright_pgloader.executor` | Scoped Postgres materialization + teardown |

Tool logic lives in plain, unit-tested functions (`engine.py`, `export.py`); the MCP layer
(`server.py`) is a thin registration shim — so the full suite runs offline with no MCP client.

## Development

```bash
cd data-engine
uv sync
uv run pytest            # full regression suite
uv run ruff check .
uv run mypy

uv run seedwright-data-engine   # run the MCP server on stdio
```
