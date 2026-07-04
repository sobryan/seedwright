"""Preview / dry-run (FR-E.6) and paginated row reads (FR-G.1).

Preview generates a SMALL sample in memory from Generator Artifacts (no files, no full run) and
returns JSON-safe rows — fast feedback while authoring. read_rows pages through a generated
Dataset's canonical Parquet. Both must render decimals as exact strings and temporals as ISO
(the same fidelity conventions as the JSONL export).
"""

from seedwright_data_engine.engine import run_author, run_generate, run_preview, run_read_rows
from tests.test_engine import FOREIGN_KEYS, RULES, SCHEMA

TEMPORAL_SCHEMA = {
    "events": {
        "columns": [
            {"name": "id", "sql_type": "bigint"},
            {"name": "day", "sql_type": "date"},
            {"name": "amount", "sql_type": "numeric(10,2)"},
        ],
        "primary_key": ["id"],
    },
}


def _artifacts() -> dict:
    return run_author(schema=SCHEMA, rules=RULES, foreign_keys=FOREIGN_KEYS,
                      volumes={"customers": 40}, seed=11)


def test_preview_returns_small_json_safe_sample() -> None:
    result = run_preview(artifacts=_artifacts(), schema=SCHEMA, rows_per_table=5)
    assert set(result["tables"]) == {"customers", "orders"}
    customers = result["tables"]["customers"]
    assert 0 < len(customers) <= 5
    first = customers[0]
    assert isinstance(first["id"], int)
    assert isinstance(first["balance"], str)          # decimal as exact string
    assert result["sampled"] is True


def test_preview_is_deterministic() -> None:
    artifacts = _artifacts()
    a = run_preview(artifacts=artifacts, schema=SCHEMA, rows_per_table=5)
    b = run_preview(artifacts=artifacts, schema=SCHEMA, rows_per_table=5)
    assert a == b


def test_preview_renders_temporals_as_iso() -> None:
    artifacts = run_author(schema=TEMPORAL_SCHEMA, rules=[], volumes={"events": 10}, seed=2)
    result = run_preview(artifacts=artifacts, schema=TEMPORAL_SCHEMA, rows_per_table=3)
    day = result["tables"]["events"][0]["day"]
    assert isinstance(day, str) and day.startswith("20") and "-" in day


def test_read_rows_pages_through_canonical_parquet(tmp_path) -> None:
    artifacts = _artifacts()
    generated = run_generate(artifacts=artifacts, schema=SCHEMA,
                             out_dir=str(tmp_path), namespace="ds_rows")
    total = generated["row_counts"]["customers"]

    page1 = run_read_rows(canonical_dir=str(tmp_path), table="customers", offset=0, limit=10)
    assert page1["total_rows"] == total
    assert len(page1["rows"]) == 10
    assert page1["rows"][0]["id"] == 1
    assert isinstance(page1["rows"][0]["balance"], str)   # decimal fidelity

    page2 = run_read_rows(canonical_dir=str(tmp_path), table="customers", offset=10, limit=10)
    assert page2["rows"][0]["id"] == 11
    assert page1["rows"] != page2["rows"]

    tail = run_read_rows(canonical_dir=str(tmp_path), table="customers",
                         offset=total - 3, limit=10)
    assert len(tail["rows"]) == 3                          # clamped at the end


def test_read_rows_rejects_path_traversal(tmp_path) -> None:
    import pytest

    with pytest.raises(ValueError):
        run_read_rows(canonical_dir=str(tmp_path), table="../evil", offset=0, limit=5)
