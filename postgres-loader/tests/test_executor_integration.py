"""Live-Postgres integration tests (spec FR-G, FR-L, FR-F.1c).

Exercise the real load→verify→teardown path, idempotency, the foreign-schema refusal, and the
type-agreement guard. All marked ``integration`` and skipped unless ``SEEDWRIGHT_TEST_PG_DSN``
points at a reachable server. Fixtures are hand-built Parquet + Load-Plan dicts (no genlib
dependency), matching the canonical seam the loader consumes.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from seedwright_pgloader.executor import (
    ForeignSchemaError,
    load_dataset,
    teardown_dataset,
    verify_materialization,
)
from seedwright_pgloader.typecheck import TypeAgreementError

pytestmark = pytest.mark.integration


def _write_fixtures(tmp_path: Path) -> dict[str, Any]:
    customers = pa.table(
        {
            "id": pa.array([1, 2, 3], pa.int64()),
            "email": pa.array(["a@x.io", "b@x.io", None], pa.string()),
            "balance": pa.array(
                [Decimal("1.00"), Decimal("2.50"), Decimal("3.99")], pa.decimal128(12, 2)
            ),
        }
    )
    pq.write_table(customers, tmp_path / "customers.parquet")
    return {
        "namespace": "ds_advisory",  # advisory; the load_dataset arg is authoritative
        "tables": [
            {
                "name": "customers",
                "row_count": 3,
                "columns": [
                    {"name": "id", "canonical_kind": "INT64", "nullable": False},
                    {"name": "email", "canonical_kind": "STRING", "length": 255,
                     "nullable": True},
                    {"name": "balance", "canonical_kind": "DECIMAL", "precision": 12,
                     "scale": 2, "nullable": False},
                ],
            }
        ],
    }


def _drop(conn: Any, namespace: str) -> None:
    with conn.cursor() as cur:
        cur.execute(f'DROP SCHEMA IF EXISTS "{namespace}" CASCADE')


def test_load_verify_teardown_roundtrip(pg_conn: Any, tmp_path: Path) -> None:
    ns = "ds_it_roundtrip"
    plan = _write_fixtures(tmp_path)
    _drop(pg_conn, ns)
    try:
        result = load_dataset(pg_conn, tmp_path, plan, ns, mode="replace")
        assert result.total_rows == 3

        verification = verify_materialization(pg_conn, tmp_path, plan, ns)
        assert verification.ok

        # data actually landed, scoped to the namespace
        with pg_conn.cursor() as cur:
            cur.execute(f'SELECT count(*) FROM "{ns}"."customers"')
            assert cur.fetchone()[0] == 3

        teardown = teardown_dataset(pg_conn, ns)
        assert teardown.existed is True

        with pg_conn.cursor() as cur:
            cur.execute("SELECT 1 FROM information_schema.schemata WHERE schema_name = %s", (ns,))
            assert cur.fetchone() is None  # schema is gone
    finally:
        _drop(pg_conn, ns)


def test_replace_is_idempotent(pg_conn: Any, tmp_path: Path) -> None:
    ns = "ds_it_idempotent"
    plan = _write_fixtures(tmp_path)
    _drop(pg_conn, ns)
    try:
        load_dataset(pg_conn, tmp_path, plan, ns, mode="replace")
        again = load_dataset(pg_conn, tmp_path, plan, ns, mode="replace")
        assert again.total_rows == 3  # not doubled
        assert verify_materialization(pg_conn, tmp_path, plan, ns).ok
    finally:
        _drop(pg_conn, ns)


def test_teardown_absent_namespace_is_noop(pg_conn: Any) -> None:
    ns = "ds_it_absent"
    _drop(pg_conn, ns)
    result = teardown_dataset(pg_conn, ns)
    assert result.existed is False  # idempotent no-op, no error


def test_refuses_to_drop_foreign_schema(pg_conn: Any, tmp_path: Path) -> None:
    ns = "ds_it_foreign"
    plan = _write_fixtures(tmp_path)
    _drop(pg_conn, ns)
    with pg_conn.cursor() as cur:
        cur.execute(f'CREATE SCHEMA "{ns}"')  # unmarked — simulates a pre-existing real schema
    try:
        with pytest.raises(ForeignSchemaError):
            load_dataset(pg_conn, tmp_path, plan, ns, mode="replace")
        with pytest.raises(ForeignSchemaError):
            teardown_dataset(pg_conn, ns)
    finally:
        _drop(pg_conn, ns)


def test_type_agreement_failure_blocks_load(pg_conn: Any, tmp_path: Path) -> None:
    plan = _write_fixtures(tmp_path)
    plan["tables"][0]["columns"][2]["canonical_kind"] = "INT64"  # lie: balance is decimal
    ns = "ds_it_typeguard"
    _drop(pg_conn, ns)
    try:
        with pytest.raises(TypeAgreementError):
            load_dataset(pg_conn, tmp_path, plan, ns, mode="replace")
    finally:
        _drop(pg_conn, ns)
