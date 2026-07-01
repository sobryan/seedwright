"""psycopg executor (spec FR-G, FR-L, FR-F.1c) — the only layer that touches a live DB.

Everything here composes the tested pure builders and runs them in one transaction with
``search_path = ''`` (any unqualified reference errors — a leak guard) and ``TimeZone = 'UTC'``.
The safety-critical decision (refuse to drop a schema seedwright didn't create) is the pure
``drop_is_forbidden`` below, unit-tested offline; the DB orchestration is exercised by the
``@pytest.mark.integration`` tests (skipped without ``SEEDWRIGHT_TEST_PG_DSN``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
from psycopg import sql

from .copy import copy_sql, encode_batch
from .ddl import (
    create_schema_sql,
    create_table_sql,
    drop_schema_sql,
    is_seedwright_schema,
    schema_marker_sql,
)
from .plan import PlanTable, parse_plan
from .results import (
    LoadResult,
    TableLoadResult,
    TableVerification,
    TeardownResult,
    VerificationResult,
)
from .safesql import UnsafeTableNameError, qualified, validate_namespace, validate_relname
from .typecheck import assert_parquet_matches_plan

VALID_MODES = ("create", "replace")


class ForeignSchemaError(RuntimeError):
    """Refused to drop a schema that exists but is not marked seedwright-owned (FR-L.3)."""


class MaterializationError(RuntimeError):
    """Loaded row counts didn't match what was streamed — the load is rolled back (FR-F.1c)."""


def resolve_table_parquet(canonical_dir: Path, table_name: str) -> Path:
    """Resolve ``<canonical_dir>/<table>.parquet`` safely.

    ``table_name`` is untrusted; validate it as a path segment and confirm the resolved path
    stays inside ``canonical_dir`` (belt-and-suspenders against separators, ``..``, symlinks).
    """
    validate_relname(table_name)
    path = canonical_dir / f"{table_name}.parquet"
    if not path.resolve().is_relative_to(canonical_dir.resolve()):
        raise UnsafeTableNameError(f"table {table_name!r} escapes the canonical directory")
    return path


def drop_is_forbidden(*, exists: bool, comment: str | None) -> bool:
    """Pure safety decision: may we drop this schema?

    Forbidden only when the schema exists and is not seedwright-marked. An absent schema is a
    safe no-op (drop-if-exists); a marked schema is ours to drop.
    """
    if not exists:
        return False
    return not is_seedwright_schema(comment)


# --- DB orchestration (integration) ---------------------------------------------------

def load_dataset(
    conn: Any,
    canonical_dir: str | Path,
    plan_dict: dict[str, Any],
    namespace: str,
    mode: str = "replace",
) -> LoadResult:
    """Load a Canonical Dataset into an isolated ``ds_`` schema, one transaction.

    ``create`` fails loud if the schema exists; ``replace`` drops (marker-guarded) + recreates.
    """
    validate_namespace(namespace)
    if mode not in VALID_MODES:
        raise ValueError(f"mode must be one of {VALID_MODES}, got {mode!r}")
    plan = parse_plan(plan_dict)
    canonical_dir = Path(canonical_dir)

    table_results: list[TableLoadResult] = []
    with conn.transaction(), conn.cursor() as cur:
        cur.execute(sql.SQL("SET LOCAL search_path = ''"))
        cur.execute(sql.SQL("SET LOCAL TimeZone = 'UTC'"))

        if mode == "replace":
            _guard_and_drop(cur, namespace)
        cur.execute(create_schema_sql(namespace))
        cur.execute(schema_marker_sql(namespace))

        for table in plan.tables:
            cur.execute(create_table_sql(namespace, table))
        for table in plan.tables:
            rows = _copy_table(cur, canonical_dir, namespace, table)
            table_results.append(TableLoadResult(table.name, rows))

        # Verify BEFORE the transaction commits, so a mismatch rolls the whole load back
        # rather than leaving partial/committed data (FR-F.1c, ADR-0002 decision 9).
        _verify_before_commit(cur, namespace, table_results)

    return LoadResult(namespace=namespace, mode=mode, tables=tuple(table_results))


def _verify_before_commit(
    cur: Any, namespace: str, table_results: list[TableLoadResult]
) -> None:
    for result in table_results:
        cur.execute(
            sql.SQL("SELECT count(*) FROM {}").format(qualified(namespace, result.name))
        )
        row = cur.fetchone()
        actual = int(row[0]) if row else 0
        if actual != result.rows_loaded:
            raise MaterializationError(
                f"{result.name}: {actual} rows landed but {result.rows_loaded} were streamed"
            )


def teardown_dataset(conn: Any, namespace: str) -> TeardownResult:
    """Drop the Dataset's schema (marker-guarded, idempotent). Absent namespace -> no-op."""
    validate_namespace(namespace)
    with conn.transaction(), conn.cursor() as cur:
        exists = _schema_exists(cur, namespace)
        if exists:
            _refuse_if_foreign(cur, namespace)
            cur.execute(drop_schema_sql(namespace))
    return TeardownResult(namespace=namespace, existed=exists)


def verify_materialization(
    conn: Any, canonical_dir: str | Path, plan_dict: dict[str, Any], namespace: str
) -> VerificationResult:
    """Compare loaded row counts to the Parquet (the source of truth, not plan.row_count)."""
    validate_namespace(namespace)
    plan = parse_plan(plan_dict)
    canonical_dir = Path(canonical_dir)

    verifications: list[TableVerification] = []
    with conn.cursor() as cur:
        for table in plan.tables:
            expected = pq.ParquetFile(  # type: ignore[no-untyped-call]
                resolve_table_parquet(canonical_dir, table.name)
            ).metadata.num_rows
            cur.execute(sql.SQL("SELECT count(*) FROM {}").format(qualified(namespace, table.name)))
            row = cur.fetchone()
            actual = int(row[0]) if row else 0
            verifications.append(TableVerification(table.name, expected, actual))
    return VerificationResult(namespace=namespace, tables=tuple(verifications))


# --- internals ------------------------------------------------------------------------

def _copy_table(cur: Any, canonical_dir: Path, namespace: str, table: PlanTable) -> int:
    path = resolve_table_parquet(canonical_dir, table.name)
    parquet = pq.ParquetFile(path)  # type: ignore[no-untyped-call]
    assert_parquet_matches_plan(parquet.schema_arrow, table)

    names = [c.name for c in table.columns]
    kinds = [c.canonical_kind for c in table.columns]
    rows = 0
    with cur.copy(copy_sql(namespace, table.name, names)) as copier:
        for batch in parquet.iter_batches():  # type: ignore[no-untyped-call]
            projected = batch.select(names)  # enforce plan column order == COPY column list
            data = encode_batch(projected, kinds)
            if data:
                copier.write(data)
            rows += projected.num_rows
    return rows


def _guard_and_drop(cur: Any, namespace: str) -> None:
    if not _schema_exists(cur, namespace):
        return
    _refuse_if_foreign(cur, namespace)
    cur.execute(drop_schema_sql(namespace))


def _refuse_if_foreign(cur: Any, namespace: str) -> None:
    comment = _schema_comment(cur, namespace)
    if drop_is_forbidden(exists=True, comment=comment):
        raise ForeignSchemaError(
            f"refusing to drop schema {namespace!r}: not marked seedwright-owned "
            f"(comment={comment!r})"
        )


def _schema_exists(cur: Any, namespace: str) -> bool:
    cur.execute(
        "SELECT 1 FROM information_schema.schemata WHERE schema_name = %s", (namespace,)
    )
    return cur.fetchone() is not None


def _schema_comment(cur: Any, namespace: str) -> str | None:
    cur.execute(
        "SELECT obj_description(oid, 'pg_namespace') FROM pg_namespace WHERE nspname = %s",
        (namespace,),
    )
    row = cur.fetchone()
    return row[0] if row else None
