"""File-export sink (spec FR-G.4): canonical Parquet -> CSV / JSONL / SQL-INSERT files.

The always-available sink — a small shop can use seedwright with no database at all. Fidelity
rules mirror the loader: decimals stay exact (never through float), NULL vs empty string is
preserved, SQL string literals escape quotes, output is deterministic.
"""

import json
from decimal import Decimal
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from seedwright_data_engine.export import export_dataset


@pytest.fixture
def canonical(tmp_path: Path) -> tuple[Path, dict]:
    table = pa.table(
        {
            "id": pa.array([1, 2, 3], pa.int64()),
            "name": pa.array(["Ann", "O'Brien", None], pa.string()),
            "balance": pa.array(
                [Decimal("0.10"), Decimal("1000.00"), Decimal("3.99")], pa.decimal128(12, 2)
            ),
            "active": pa.array([True, False, True], pa.bool_()),
        }
    )
    canonical_dir = tmp_path / "canonical"
    canonical_dir.mkdir()
    pq.write_table(table, canonical_dir / "customers.parquet")
    load_plan = {
        "namespace": "ds_x",
        "tables": [
            {"name": "customers", "row_count": 3, "columns": [
                {"name": "id", "canonical_kind": "INT64", "nullable": False},
                {"name": "name", "canonical_kind": "STRING", "nullable": True},
                {"name": "balance", "canonical_kind": "DECIMAL", "precision": 12, "scale": 2,
                 "nullable": False},
                {"name": "active", "canonical_kind": "BOOLEAN", "nullable": False},
            ]},
        ],
    }
    return canonical_dir, load_plan


def test_csv_export_roundtrips(canonical: tuple[Path, dict], tmp_path: Path) -> None:
    canonical_dir, plan = canonical
    out = tmp_path / "out"
    result = export_dataset(canonical_dir, plan, out, formats=["csv"])
    csv_path = out / "customers.csv"
    assert csv_path.exists()
    assert result["files"]["csv"] == [str(csv_path)]
    text = csv_path.read_text()
    assert "1000.00" in text  # decimal scale preserved, not 1000.0
    assert text.splitlines()[0] == '"id","name","balance","active"'


def test_jsonl_export_preserves_types(canonical: tuple[Path, dict], tmp_path: Path) -> None:
    canonical_dir, plan = canonical
    export_dataset(canonical_dir, plan, tmp_path / "out", formats=["jsonl"])
    lines = (tmp_path / "out" / "customers.jsonl").read_text().splitlines()
    rows = [json.loads(line) for line in lines]
    assert len(rows) == 3
    assert rows[0] == {"id": 1, "name": "Ann", "balance": "0.10", "active": True}
    assert rows[2]["name"] is None  # NULL survives


def test_sql_export_escapes_and_types(canonical: tuple[Path, dict], tmp_path: Path) -> None:
    canonical_dir, plan = canonical
    export_dataset(canonical_dir, plan, tmp_path / "out", formats=["sql"])
    sql = (tmp_path / "out" / "customers.sql").read_text()
    assert 'INSERT INTO "customers" ("id", "name", "balance", "active") VALUES' in sql
    assert "'O''Brien'" in sql        # single-quote doubled
    assert "1000.00" in sql           # decimal bare literal, exact scale
    assert "NULL" in sql              # null rendered
    assert "TRUE" in sql and "FALSE" in sql


def test_export_is_deterministic(canonical: tuple[Path, dict], tmp_path: Path) -> None:
    canonical_dir, plan = canonical
    export_dataset(canonical_dir, plan, tmp_path / "a", formats=["csv", "jsonl", "sql"])
    export_dataset(canonical_dir, plan, tmp_path / "b", formats=["csv", "jsonl", "sql"])
    for name in ("customers.csv", "customers.jsonl", "customers.sql"):
        assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes()


def test_unknown_format_rejected(canonical: tuple[Path, dict], tmp_path: Path) -> None:
    canonical_dir, plan = canonical
    with pytest.raises(ValueError):
        export_dataset(canonical_dir, plan, tmp_path / "out", formats=["xlsx"])


def test_table_name_path_safety(canonical: tuple[Path, dict], tmp_path: Path) -> None:
    canonical_dir, plan = canonical
    plan["tables"][0]["name"] = "../evil"
    with pytest.raises(ValueError):
        export_dataset(canonical_dir, plan, tmp_path / "out", formats=["csv"])
