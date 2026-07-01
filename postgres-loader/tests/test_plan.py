"""Load Plan parsing (spec FR-M).

The loader consumes the Load Plan as JSON (genlib's ``loadplan.to_dict()``), NOT as Python
objects — the seam is language-neutral (future MCP contract). Parsing validates the required
shape and defaults the optional fields, ignoring unknown keys so the contract can evolve.
"""

import pytest

from seedwright_pgloader.plan import InvalidLoadPlanError, parse_plan


def _genlib_style() -> dict:
    # Mirrors seedwright_genlib.loadplan.LoadPlan.to_dict()
    return {
        "namespace": "ds_1",
        "tables": [
            {
                "name": "customers",
                "row_count": 20,
                "columns": [
                    {"name": "id", "canonical_kind": "INT64", "source_sql": "bigint",
                     "precision": None, "scale": None, "length": None, "tz": False,
                     "nullable": False},
                    {"name": "email", "canonical_kind": "STRING", "source_sql": "varchar(255)",
                     "precision": None, "scale": None, "length": 255, "tz": False,
                     "nullable": True},
                ],
            },
            {
                "name": "orders",
                "row_count": 41,
                "columns": [
                    {"name": "total", "canonical_kind": "DECIMAL", "source_sql": "numeric(10,2)",
                     "precision": 10, "scale": 2, "length": None, "tz": False, "nullable": False},
                ],
            },
        ],
    }


def test_parses_namespace_and_table_order() -> None:
    plan = parse_plan(_genlib_style())
    assert plan.namespace == "ds_1"
    assert [t.name for t in plan.tables] == ["customers", "orders"]


def test_parses_row_counts() -> None:
    plan = parse_plan(_genlib_style())
    assert plan.table("orders").row_count == 41


def test_parses_column_hints() -> None:
    plan = parse_plan(_genlib_style())
    total = plan.table("orders").columns[0]
    assert (total.canonical_kind, total.precision, total.scale, total.nullable) == (
        "DECIMAL", 10, 2, False,
    )


def test_defaults_optional_column_fields() -> None:
    plan = parse_plan(
        {"namespace": "ds_x", "tables": [
            {"name": "t", "row_count": 0, "columns": [{"name": "c", "canonical_kind": "INT32"}]}
        ]}
    )
    col = plan.table("t").columns[0]
    assert (col.precision, col.scale, col.length, col.tz) == (None, None, None, False)
    assert col.nullable is True  # permissive default: no NOT NULL unless the plan says so


def test_ignores_unknown_fields_for_forward_compat() -> None:
    data = _genlib_style()
    data["tables"][0]["columns"][0]["future_field"] = "whatever"
    data["extra_top_level"] = 123
    plan = parse_plan(data)  # must not raise
    assert plan.table("customers").columns[0].name == "id"


def test_missing_namespace_raises() -> None:
    with pytest.raises(InvalidLoadPlanError):
        parse_plan({"tables": []})


def test_missing_table_name_raises() -> None:
    with pytest.raises(InvalidLoadPlanError):
        parse_plan({"namespace": "ds_1", "tables": [{"row_count": 1, "columns": []}]})


def test_missing_canonical_kind_raises() -> None:
    with pytest.raises(InvalidLoadPlanError):
        parse_plan({"namespace": "ds_1", "tables": [
            {"name": "t", "row_count": 1, "columns": [{"name": "c"}]}
        ]})


def test_unknown_table_lookup_raises() -> None:
    plan = parse_plan(_genlib_style())
    with pytest.raises(KeyError):
        plan.table("nope")
