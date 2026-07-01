"""Load Plan emitter (spec FR-M).

The Load Plan is the small structured recipe emitted with the Canonical Dataset: FK-topo
table order, the target namespace, per-table row counts, and per-column type hints
(canonical kind + original source SQL type/precision/scale/length/nullability) that let a
sink loader produce faithful dialect DDL and bulk-load.
"""

import json
from decimal import Decimal

from seedwright_genlib.dataset import generate_dataset
from seedwright_genlib.generators import DecimalRange, FakerField, IntRange, Serial
from seedwright_genlib.loadplan import build_load_plan
from seedwright_genlib.rng import SeededRng
from seedwright_genlib.schema import ColumnSpec, ForeignKeySpec, SchemaSpec, TableSpec
from seedwright_genlib.types import TypeKind, from_sql


def _schema() -> SchemaSpec:
    customers = TableSpec(
        name="customers",
        primary_key=["id"],
        row_count=20,
        columns=[
            ColumnSpec("id", from_sql("bigint"), Serial()),
            ColumnSpec("email", from_sql("character varying(255)"), FakerField("email")),
        ],
    )
    orders = TableSpec(
        name="orders",
        primary_key=["id"],
        foreign_keys=[ForeignKeySpec("customer_id", "customers", "id", 1, 3)],
        columns=[
            ColumnSpec("id", from_sql("bigint"), Serial()),
            ColumnSpec("customer_id", from_sql("bigint"), IntRange(0, 0)),
            ColumnSpec("total", from_sql("numeric(10,2)"),
                       DecimalRange(Decimal("1"), Decimal("9"), scale=2)),
        ],
    )
    return SchemaSpec(tables=[orders, customers])


def test_table_order_is_topological() -> None:
    plan = build_load_plan(_schema(), generate_dataset(_schema(), SeededRng(1)), namespace="ds_1")
    names = [t.name for t in plan.tables]
    assert names.index("customers") < names.index("orders")


def test_row_counts_match_generated_results() -> None:
    schema = _schema()
    results = generate_dataset(schema, SeededRng(1))
    plan = build_load_plan(schema, results, namespace="ds_1")
    by_name = {t.name: t.row_count for t in plan.tables}
    assert by_name["customers"] == results["customers"].num_rows
    assert by_name["orders"] == results["orders"].num_rows


def test_column_hints_carry_source_sql_and_canonical_kind() -> None:
    schema = _schema()
    plan = build_load_plan(schema, generate_dataset(schema, SeededRng(1)), namespace="ds_1")
    orders = next(t for t in plan.tables if t.name == "orders")
    total = next(c for c in orders.columns if c.name == "total")
    assert total.source_sql == "numeric(10,2)"
    assert total.canonical_kind == TypeKind.DECIMAL.name
    assert (total.precision, total.scale) == (10, 2)


def test_pk_column_is_not_nullable() -> None:
    schema = _schema()
    plan = build_load_plan(schema, generate_dataset(schema, SeededRng(1)), namespace="ds_1")
    customers = next(t for t in plan.tables if t.name == "customers")
    id_hint = next(c for c in customers.columns if c.name == "id")
    assert id_hint.nullable is False


def test_namespace_is_recorded() -> None:
    schema = _schema()
    plan = build_load_plan(schema, generate_dataset(schema, SeededRng(1)), namespace="ds_abc")
    assert plan.namespace == "ds_abc"


def test_load_plan_serializes_to_json() -> None:
    schema = _schema()
    plan = build_load_plan(schema, generate_dataset(schema, SeededRng(1)), namespace="ds_1")
    blob = json.dumps(plan.to_dict())
    restored = json.loads(blob)
    assert restored["namespace"] == "ds_1"
    assert restored["tables"][0]["name"] == "customers"
