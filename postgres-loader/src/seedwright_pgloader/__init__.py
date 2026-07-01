"""seedwright Postgres loader (spec FR-G, FR-L, FR-M.4).

Turns a Canonical Dataset (Parquet) + Load Plan (JSON) into a scoped, idempotent,
reversible Postgres load + teardown. A pure SQL-generation layer (offline-testable) plus a
thin psycopg executor (integration, skippable). Shaped to become an MCP loader.
"""

__version__ = "0.0.1"
