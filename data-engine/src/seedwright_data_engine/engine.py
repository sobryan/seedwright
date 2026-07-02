"""Engine tool functions — the JSON-in/JSON-out surface behind the MCP tools (ADR-0004).

Each function takes plain JSON-able inputs (what crosses the MCP boundary) and delegates to the
proven libraries: the authoring loop, the deterministic generation library, the data-test judge,
and the Postgres loader. No logic of its own beyond conversion — everything load-bearing is
already tested where it lives.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
from seedwright_authoring.compile import compile_to_genlib
from seedwright_authoring.datatests import DataTest, run_data_tests
from seedwright_authoring.genspec import parse_genspec
from seedwright_authoring.imported import ImportedSchema
from seedwright_authoring.loop import author
from seedwright_authoring.rules import RuleSet
from seedwright_genlib.dataset import generate_dataset
from seedwright_genlib.loadplan import build_load_plan
from seedwright_genlib.parquet import write_dataset
from seedwright_genlib.rng import SeededRng
from seedwright_pgloader.safesql import validate_relname

from .copilot_provider import CopilotCliProvider
from .heuristic import HeuristicProvider

LOAD_PLAN_FILENAME = "load_plan.json"

PROVIDERS = ("heuristic", "copilot-cli")


class UnknownProviderError(ValueError):
    """An authoring provider name not in this engine's registry (FR-H.7: fail explicitly)."""


def _imported_schema(schema: dict[str, Any]) -> ImportedSchema:
    columns_by_table = {
        table: [(c["name"], c["sql_type"]) for c in spec["columns"]]
        for table, spec in schema.items()
    }
    primary_keys = {table: spec.get("primary_key", []) for table, spec in schema.items()}
    return ImportedSchema.from_sql_columns(columns_by_table, primary_keys=primary_keys)


def run_author(
    *,
    schema: dict[str, Any],
    rules: list[dict[str, Any]],
    foreign_keys: dict[str, list[dict[str, Any]]] | None = None,
    volumes: dict[str, int] | None = None,
    seed: int = 42,
    max_iters: int = 4,
    provider: str = "heuristic",
    _copilot_runner: Any = None,  # test seam: injected in tests, None in production
) -> dict[str, Any]:
    """Author Generator Artifacts via the evaluator-optimizer loop.

    ``provider``: 'heuristic' (deterministic, no LLM — the default) or 'copilot-cli' (the
    GitHub Copilot CLI as the authoring model; requires an authenticated ``copilot``).
    """
    if provider == "heuristic":
        chosen: Any = HeuristicProvider(foreign_keys=foreign_keys, volumes=volumes, seed=seed)
    elif provider == "copilot-cli":
        chosen = CopilotCliProvider(foreign_keys=foreign_keys, volumes=volumes, seed=seed,
                                    runner=_copilot_runner)
    else:
        raise UnknownProviderError(
            f"unknown authoring provider {provider!r}; available: {list(PROVIDERS)}")
    artifacts = author(
        _imported_schema(schema), RuleSet.from_dicts(rules), chosen, max_iters=max_iters
    )
    return artifacts.to_dict()


def run_generate(
    *,
    artifacts: dict[str, Any],
    schema: dict[str, Any],
    out_dir: str,
    namespace: str,
) -> dict[str, Any]:
    """Execute Generator Artifacts deterministically: canonical Parquet + Load Plan on disk."""
    genspec = parse_genspec(artifacts["genspec"])
    compiled = compile_to_genlib(genspec, _imported_schema(schema))
    tables = generate_dataset(compiled, SeededRng(genspec.seed))
    out = Path(out_dir)
    paths = write_dataset(tables, out)
    load_plan = build_load_plan(compiled, tables, namespace=namespace).to_dict()
    (out / LOAD_PLAN_FILENAME).write_text(json.dumps(load_plan, indent=2), encoding="utf-8")
    return {
        "canonical_dir": str(out),
        "load_plan_path": str(out / LOAD_PLAN_FILENAME),
        "load_plan": load_plan,
        "row_counts": {name: table.num_rows for name, table in tables.items()},
        "files": {name: str(path) for name, path in paths.items()},
        "seed": genspec.seed,
        "artifacts_version": artifacts.get("version"),
    }


def run_validate(
    *,
    canonical_dir: str,
    load_plan: dict[str, Any],
    data_tests: list[dict[str, Any]],
) -> dict[str, Any]:
    """Run data-tests against the canonical Parquet (full-dataset validation, FR-F.1b)."""
    directory = Path(canonical_dir)
    tables = {
        t["name"]: pq.read_table(  # type: ignore[no-untyped-call]
            directory / f"{validate_relname(t['name'])}.parquet"
        )
        for t in load_plan["tables"]
    }
    tests = [
        DataTest(kind=d["kind"], table=d["table"], column=d.get("column"),
                 params=dict(d.get("params", {})))
        for d in data_tests
    ]
    failures = run_data_tests(tests, tables)
    return {
        "passed": not failures,
        "tests_run": len(tests),
        "failures": [f.to_dict() for f in failures],
    }


def run_load_postgres(
    *,
    canonical_dir: str,
    load_plan: dict[str, Any],
    dsn: str,
    namespace: str,
    mode: str = "replace",
) -> dict[str, Any]:
    """Materialize the canonical dataset into a scoped Postgres namespace (gated sink)."""
    import psycopg
    from seedwright_pgloader.executor import load_dataset, verify_materialization

    with psycopg.connect(dsn, autocommit=True) as conn:
        result = load_dataset(conn, canonical_dir, load_plan, namespace, mode=mode)
        verification = verify_materialization(conn, canonical_dir, load_plan, namespace)
    return {"load": result.to_dict(), "verification": verification.to_dict()}


def run_teardown_postgres(*, dsn: str, namespace: str) -> dict[str, Any]:
    """Tear down a Dataset's scoped namespace (idempotent, marker-guarded)."""
    import psycopg
    from seedwright_pgloader.executor import teardown_dataset

    with psycopg.connect(dsn, autocommit=True) as conn:
        return teardown_dataset(conn, namespace).to_dict()
