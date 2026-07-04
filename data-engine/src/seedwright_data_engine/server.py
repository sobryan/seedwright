"""The MCP server shim (ADR-0004): registers the engine functions as MCP tools over stdio.

Deliberately thin — every tool delegates to a unit-tested function in ``engine``/``export``.
The central Spring server spawns this process and speaks MCP to it on stdio.
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from . import __version__
from .engine import (
    run_author,
    run_generate,
    run_load_postgres,
    run_preview,
    run_read_rows,
    run_teardown_postgres,
    run_validate,
)
from .export import export_dataset as run_export


def create_server() -> FastMCP:
    mcp = FastMCP(
        name="seedwright-data-engine", instructions=f"seedwright data engine v{__version__}"
    )

    @mcp.tool()
    def author_generator(
        schema: dict[str, Any],
        rules: list[dict[str, Any]] | None = None,
        foreign_keys: dict[str, list[dict[str, Any]]] | None = None,
        volumes: dict[str, int] | None = None,
        seed: int = 42,
        max_iters: int = 4,
        provider: str = "heuristic",
    ) -> dict[str, Any]:
        """Author Generator Artifacts (evaluator-optimizer).

        provider: 'heuristic' (deterministic, no LLM) or 'copilot-cli' (GitHub Copilot CLI
        as the authoring model — requires an authenticated `copilot` on this host).
        """
        return run_author(schema=schema, rules=rules or [], foreign_keys=foreign_keys,
                          volumes=volumes, seed=seed, max_iters=max_iters, provider=provider)

    @mcp.tool()
    def generate_dataset(
        artifacts: dict[str, Any], schema: dict[str, Any], out_dir: str, namespace: str
    ) -> dict[str, Any]:
        """Execute Generator Artifacts deterministically -> canonical Parquet + Load Plan."""
        return run_generate(artifacts=artifacts, schema=schema, out_dir=out_dir,
                            namespace=namespace)

    @mcp.tool()
    def preview_dataset(
        artifacts: dict[str, Any], schema: dict[str, Any], rows_per_table: int = 10
    ) -> dict[str, Any]:
        """Preview a small in-memory sample from Generator Artifacts (dry-run, no files)."""
        return run_preview(artifacts=artifacts, schema=schema, rows_per_table=rows_per_table)

    @mcp.tool()
    def read_rows(
        canonical_dir: str, table: str, offset: int = 0, limit: int = 100
    ) -> dict[str, Any]:
        """Read a page of rows from a generated Dataset's canonical Parquet."""
        return run_read_rows(canonical_dir=canonical_dir, table=table, offset=offset, limit=limit)

    @mcp.tool()
    def validate_dataset(
        canonical_dir: str, load_plan: dict[str, Any], data_tests: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Run data-tests against the canonical Parquet (full-dataset validation)."""
        return run_validate(canonical_dir=canonical_dir, load_plan=load_plan,
                            data_tests=data_tests)

    @mcp.tool()
    def export_dataset(
        canonical_dir: str, load_plan: dict[str, Any], out_dir: str, formats: list[str]
    ) -> dict[str, Any]:
        """Export the canonical dataset to CSV / JSONL / SQL-INSERT files (the file sink)."""
        return run_export(canonical_dir, load_plan, out_dir, formats=formats)

    @mcp.tool()
    def load_postgres(
        canonical_dir: str,
        load_plan: dict[str, Any],
        dsn: str,
        namespace: str,
        mode: str = "replace",
    ) -> dict[str, Any]:
        """Materialize into a scoped Postgres namespace (gated, idempotent, verified)."""
        return run_load_postgres(canonical_dir=canonical_dir, load_plan=load_plan, dsn=dsn,
                                 namespace=namespace, mode=mode)

    @mcp.tool()
    def teardown_postgres(dsn: str, namespace: str) -> dict[str, Any]:
        """Tear down a Dataset's scoped Postgres namespace (idempotent, marker-guarded)."""
        return run_teardown_postgres(dsn=dsn, namespace=namespace)

    return mcp


def main() -> None:
    create_server().run(transport="stdio")


if __name__ == "__main__":
    main()
