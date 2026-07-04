"""Refinement suggestions (FR-D): profile a generated Dataset's canonical Parquet and propose
rules that TIGHTEN the Blueprint — low-cardinality columns -> enum, numeric spread -> range,
observed nulls -> max_null_rate. Suggestions are directly appendable to the Blueprint's rules.

Hand-built canonical fixture so the profiling assertions are exact and deterministic.
"""

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from seedwright_data_engine.engine import run_suggest_rules


def _fixture(tmp_path: Path) -> tuple[str, dict]:
    people = pa.table({
        "id": pa.array([1, 2, 3, 4, 5, 6], pa.int64()),
        "status": pa.array(["active", "active", "churned", "trial", "trial", "active"]),
        "score": pa.array([10, 55, 90, 42, 33, 71], pa.int64()),
        "note": pa.array(["hi", None, None, "x", None, "y"]),
        "account_id": pa.array([7, 8, 9, 10, 11, 12], pa.int64()),
    })
    pq.write_table(people, tmp_path / "people.parquet")  # type: ignore[no-untyped-call]
    plan = {
        "namespace": "ds_s",
        "tables": [{
            "name": "people",
            "row_count": 6,
            "columns": [
                {"name": "id", "canonical_kind": "INT64", "nullable": False},
                {"name": "status", "canonical_kind": "STRING", "nullable": False},
                {"name": "score", "canonical_kind": "INT64", "nullable": False},
                {"name": "note", "canonical_kind": "STRING", "nullable": True},
                {"name": "account_id", "canonical_kind": "INT64", "nullable": False},
            ],
        }],
    }
    return str(tmp_path), plan


def _by_col(suggestions: list[dict], column: str) -> dict | None:
    return next((s for s in suggestions if s["column"] == column), None)


def test_low_cardinality_string_suggests_enum(tmp_path: Path) -> None:
    canonical_dir, plan = _fixture(tmp_path)
    out = run_suggest_rules(canonical_dir=canonical_dir, load_plan=plan, existing_rules=[])
    status = _by_col(out["suggestions"], "status")
    assert status is not None
    assert status["kind"] == "enum"
    assert set(status["rule"]["enum"]) == {"active", "churned", "trial"}
    assert status["rule"]["table"] == "people" and status["rule"]["column"] == "status"


def test_numeric_column_suggests_observed_range(tmp_path: Path) -> None:
    canonical_dir, plan = _fixture(tmp_path)
    out = run_suggest_rules(canonical_dir=canonical_dir, load_plan=plan, existing_rules=[])
    score = _by_col(out["suggestions"], "score")
    assert score is not None and score["kind"] == "value_range"
    assert score["rule"]["min_value"] == "10" and score["rule"]["max_value"] == "90"


def test_nullable_column_with_nulls_suggests_null_rate(tmp_path: Path) -> None:
    canonical_dir, plan = _fixture(tmp_path)
    out = run_suggest_rules(canonical_dir=canonical_dir, load_plan=plan, existing_rules=[])
    note = _by_col(out["suggestions"], "note")
    assert note is not None and note["kind"] == "null_rate"
    # 3 of 6 null -> suggested cap rounds up from the observed 0.50, never below it
    assert note["rule"]["max_null_rate"] >= 0.5


def test_identifier_columns_are_skipped(tmp_path: Path) -> None:
    canonical_dir, plan = _fixture(tmp_path)
    out = run_suggest_rules(canonical_dir=canonical_dir, load_plan=plan, existing_rules=[])
    # 'id' and '*_id' are identifiers, never domain values -> no range/enum spam
    assert _by_col(out["suggestions"], "id") is None
    assert _by_col(out["suggestions"], "account_id") is None


def test_already_ruled_columns_are_not_resuggested(tmp_path: Path) -> None:
    canonical_dir, plan = _fixture(tmp_path)
    existing = [{"table": "people", "column": "status", "enum": ["active", "churned", "trial"]}]
    out = run_suggest_rules(canonical_dir=canonical_dir, load_plan=plan, existing_rules=existing)
    assert _by_col(out["suggestions"], "status") is None  # user already declared intent here
    assert _by_col(out["suggestions"], "score") is not None  # but this one is still open
