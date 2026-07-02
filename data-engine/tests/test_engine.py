"""Engine tool functions — the JSON-in/JSON-out surface the MCP tools expose.

End-to-end offline: author (heuristic provider) -> generate (deterministic, canonical Parquet +
Load Plan on disk) -> validate (data-tests against the Parquet) -> export. This is the exact
sequence the central Spring server will drive over MCP.
"""

import json
from pathlib import Path

import pyarrow.parquet as pq

from seedwright_data_engine.engine import run_author, run_generate, run_validate

SCHEMA = {
    "customers": {
        "columns": [
            {"name": "id", "sql_type": "bigint"},
            {"name": "email", "sql_type": "varchar(255)"},
            {"name": "tier", "sql_type": "varchar(20)"},
            {"name": "balance", "sql_type": "numeric(12,2)"},
        ],
        "primary_key": ["id"],
    },
    "orders": {
        "columns": [
            {"name": "id", "sql_type": "bigint"},
            {"name": "customer_id", "sql_type": "bigint"},
            {"name": "total", "sql_type": "numeric(10,2)"},
        ],
        "primary_key": ["id"],
    },
}
FOREIGN_KEYS = {
    "orders": [{"column": "customer_id", "references_table": "customers",
                "references_column": "id", "min_per_parent": 1, "max_per_parent": 3}],
}
RULES = [
    {"table": "customers", "column": "tier", "enum": ["free", "pro"]},
    {"table": "orders", "column": "total", "min_value": "1.00", "max_value": "500.00"},
]


def _author() -> dict:
    return run_author(schema=SCHEMA, rules=RULES, foreign_keys=FOREIGN_KEYS,
                      volumes={"customers": 40}, seed=11)


def test_author_returns_pending_artifacts_with_version() -> None:
    artifacts = _author()
    assert artifacts["version"].startswith("ga_")
    assert artifacts["provenance"]["approval_status"] == "pending_approval"
    assert artifacts["provenance"]["provider_id"] == "heuristic"
    assert artifacts["data_tests"]  # derived tests travel with the artifact


def test_generate_writes_canonical_and_load_plan(tmp_path: Path) -> None:
    artifacts = _author()
    result = run_generate(artifacts=artifacts, schema=SCHEMA,
                          out_dir=str(tmp_path), namespace="ds_t1")
    assert (tmp_path / "customers.parquet").exists()
    assert (tmp_path / "orders.parquet").exists()
    plan = json.loads((tmp_path / "load_plan.json").read_text())
    assert plan["namespace"] == "ds_t1"
    assert result["row_counts"]["customers"] == 40
    assert 40 <= result["row_counts"]["orders"] <= 120  # 1..3 per parent
    # referential integrity in the actual files
    parents = set(pq.read_table(tmp_path / "customers.parquet").column("id").to_pylist())
    children = set(pq.read_table(tmp_path / "orders.parquet").column("customer_id").to_pylist())
    assert children <= parents


def test_generate_is_deterministic(tmp_path: Path) -> None:
    artifacts = _author()
    run_generate(artifacts=artifacts, schema=SCHEMA, out_dir=str(tmp_path / "a"), namespace="ds_a")
    run_generate(artifacts=artifacts, schema=SCHEMA, out_dir=str(tmp_path / "b"), namespace="ds_b")
    a = pq.read_table(tmp_path / "a" / "orders.parquet")
    b = pq.read_table(tmp_path / "b" / "orders.parquet")
    assert a.equals(b)


def test_validate_passes_on_generated_dataset(tmp_path: Path) -> None:
    artifacts = _author()
    result = run_generate(artifacts=artifacts, schema=SCHEMA,
                          out_dir=str(tmp_path), namespace="ds_v")
    report = run_validate(canonical_dir=str(tmp_path), load_plan=result["load_plan"],
                          data_tests=artifacts["data_tests"])
    assert report["passed"] is True
    assert report["failures"] == []
    assert report["tests_run"] == len(artifacts["data_tests"])


def test_validate_flags_a_violated_rule(tmp_path: Path) -> None:
    artifacts = _author()
    result = run_generate(artifacts=artifacts, schema=SCHEMA,
                          out_dir=str(tmp_path), namespace="ds_f")
    # tighten the enum after the fact -> generated 'pro' values must fail it
    tests = list(artifacts["data_tests"]) + [
        {"kind": "enum", "table": "customers", "column": "tier", "params": {"values": ["free"]}}
    ]
    report = run_validate(canonical_dir=str(tmp_path), load_plan=result["load_plan"],
                          data_tests=tests)
    assert report["passed"] is False
    assert any(f["column"] == "tier" for f in report["failures"])
