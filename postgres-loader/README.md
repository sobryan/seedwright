# seedwright Postgres loader

Turns a **Canonical Dataset** (Parquet, one file/table) + a **Load Plan** (JSON) into a
**scoped, idempotent, reversible** Postgres load and a matching teardown (spec FR-G, FR-L,
FR-M.4). Consumes only Parquet + Load-Plan JSON — it does **not** import the generation
library. Shaped to become an MCP loader (`load_dataset` / `teardown_dataset` /
`introspect_schema`).

Two layers:
- **Pure SQL generation** (offline, deterministic, unit-tested) — canonical→Postgres DDL,
  COPY-format encoding, namespace-scoped DDL/teardown. Renders SQL via `psycopg.sql`
  Composables offline (`.as_string(None)`) — injection-safe, **no DB server needed**.
- **psycopg executor** (integration, skippable) — runs the generated SQL against a live
  Postgres. Gated on `SEEDWRIGHT_TEST_PG_DSN` pointing at a reachable server.

## Development

Uses [`uv`](https://docs.astral.sh/uv/), pinned to Python 3.12. `psycopg[binary]` bundles
libpq, so the offline unit tests run without any system Postgres.

```bash
cd postgres-loader
uv sync                      # installs everything (psycopg[binary] + pyarrow + dev tools)
uv run pytest                # full suite; integration tests auto-skip without a live DB
uv run ruff check .
uv run mypy

# to run integration tests against a real Postgres:
SEEDWRIGHT_TEST_PG_DSN=postgresql://user:pass@localhost/db uv run pytest -m integration
```

**Safety, non-negotiable (FR-L):** data lands only in an isolated namespace; a bare
`DROP TABLE`/`DELETE FROM <table>` is never emitted; untrusted identifiers are always
safely composed, never interpolated.
