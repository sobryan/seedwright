"""Loader result records (spec FR-G, FR-F.1c).

Structured, JSON-serializable results describing what landed where — the machine-readable
output a CI/CD caller (and the future MCP contract) consumes.
"""

import json

from seedwright_pgloader.results import (
    LoadResult,
    TableLoadResult,
    TableVerification,
    TeardownResult,
    VerificationResult,
)


def test_load_result_totals_and_to_dict() -> None:
    result = LoadResult(
        namespace="ds_1",
        mode="replace",
        tables=(TableLoadResult("customers", 10), TableLoadResult("orders", 31)),
    )
    assert result.total_rows == 41
    d = result.to_dict()
    assert d["namespace"] == "ds_1"
    assert d["mode"] == "replace"
    assert d["total_rows"] == 41
    assert d["tables"][0] == {"name": "customers", "rows_loaded": 10}


def test_teardown_result_to_dict() -> None:
    assert TeardownResult(namespace="ds_1", existed=True).to_dict() == {
        "namespace": "ds_1",
        "existed": True,
    }


def test_verification_ok_when_all_tables_match() -> None:
    result = VerificationResult(
        namespace="ds_1",
        tables=(TableVerification("customers", 10, 10), TableVerification("orders", 31, 31)),
    )
    assert result.ok is True
    assert result.mismatches == ()


def test_verification_flags_mismatch() -> None:
    result = VerificationResult(
        namespace="ds_1",
        tables=(TableVerification("customers", 10, 9),),
    )
    assert result.ok is False
    assert "customers" in result.mismatches[0]


def test_all_results_are_json_serializable() -> None:
    for obj in (
        LoadResult("ds_1", "create", (TableLoadResult("t", 1),)),
        TeardownResult("ds_1", False),
        VerificationResult("ds_1", (TableVerification("t", 1, 1),)),
    ):
        json.dumps(obj.to_dict())  # must not raise
