"""Cross-table generation: FK ordering, cardinality, referential integrity
(spec FR-A.3, FR-E.3, FR-O.1).

Parents are generated before children (topological order). A child's row count is derived
by expanding each parent key by a sampled per-parent cardinality ("each customer has 0-5
orders"). FKs into reference tables instead sample from a provided pool of existing keys.
Every FK value must resolve to a real parent key.
"""

from collections import Counter
from decimal import Decimal

import pytest

from seedwright_genlib.dataset import CycleError, generate_dataset, topological_order
from seedwright_genlib.generators import Categorical, DecimalRange, IntRange, Serial
from seedwright_genlib.rng import SeededRng
from seedwright_genlib.schema import (
    ColumnSpec,
    ForeignKeySpec,
    SchemaSpec,
    TableClass,
    TableSpec,
)
from seedwright_genlib.types import CanonicalType, TypeKind


def _int(kind: TypeKind = TypeKind.INT64) -> CanonicalType:
    return CanonicalType(kind)


def _customers_orders(min_pp: int = 0, max_pp: int = 5) -> SchemaSpec:
    customers = TableSpec(
        name="customers",
        primary_key=["id"],
        row_count=50,
        columns=[
            ColumnSpec("id", _int(), Serial()),
            ColumnSpec("tier", CanonicalType(TypeKind.STRING), Categorical(["free", "pro"])),
        ],
    )
    orders = TableSpec(
        name="orders",
        primary_key=["id"],
        foreign_keys=[
            ForeignKeySpec("customer_id", "customers", "id", min_per_parent=min_pp,
                           max_per_parent=max_pp),
        ],
        columns=[
            ColumnSpec("id", _int(), Serial()),
            ColumnSpec("customer_id", _int(), IntRange(0, 0)),  # generator unused; FK-filled
            ColumnSpec(
                "total",
                CanonicalType(TypeKind.DECIMAL, precision=10, scale=2),
                DecimalRange(Decimal("1.00"), Decimal("500.00"), scale=2),
            ),
        ],
    )
    return SchemaSpec(tables=[orders, customers])  # deliberately out of dependency order


# --- ordering -------------------------------------------------------------------------

def test_topological_order_puts_parents_before_children() -> None:
    order = topological_order(_customers_orders())
    assert order.index("customers") < order.index("orders")


def test_topological_order_detects_cycles() -> None:
    a = TableSpec(
        name="a",
        primary_key=["id"],
        row_count=5,
        columns=[ColumnSpec("id", _int(), Serial()), ColumnSpec("b_id", _int(), IntRange(0, 0))],
        foreign_keys=[ForeignKeySpec("b_id", "b", "id")],
    )
    b = TableSpec(
        name="b",
        primary_key=["id"],
        row_count=5,
        columns=[ColumnSpec("id", _int(), Serial()), ColumnSpec("a_id", _int(), IntRange(0, 0))],
        foreign_keys=[ForeignKeySpec("a_id", "a", "id")],
    )
    with pytest.raises(CycleError):
        topological_order(SchemaSpec(tables=[a, b]))


def test_excluded_table_is_not_generated() -> None:
    schema = _customers_orders()
    schema.table("orders").table_class = TableClass.EXCLUDED
    tables = generate_dataset(schema, SeededRng(1))
    assert "orders" not in tables
    assert "customers" in tables


# --- cardinality & referential integrity ----------------------------------------------

def test_child_rows_are_derived_by_cardinality_expansion() -> None:
    tables = generate_dataset(_customers_orders(min_pp=0, max_pp=5), SeededRng(1))
    n_customers = tables["customers"].num_rows
    n_orders = tables["orders"].num_rows
    assert 0 <= n_orders <= 5 * n_customers


def test_every_fk_value_resolves_to_a_parent_key() -> None:
    tables = generate_dataset(_customers_orders(), SeededRng(1))
    parent_keys = set(tables["customers"].column("id").to_pylist())
    child_fks = tables["orders"].column("customer_id").to_pylist()
    assert set(child_fks) <= parent_keys


def test_per_parent_cardinality_bounds_are_respected() -> None:
    tables = generate_dataset(_customers_orders(min_pp=1, max_pp=4), SeededRng(3))
    counts = Counter(tables["orders"].column("customer_id").to_pylist())
    # every customer appears, and within [1, 4]
    assert set(counts) == set(tables["customers"].column("id").to_pylist())
    assert all(1 <= c <= 4 for c in counts.values())


def test_dataset_generation_is_deterministic() -> None:
    a = generate_dataset(_customers_orders(), SeededRng(1))
    b = generate_dataset(_customers_orders(), SeededRng(1))
    assert a["orders"].equals(b["orders"])
    assert a["customers"].equals(b["customers"])


# --- reference tables (spec FR-O.1) ---------------------------------------------------

def test_reference_fk_samples_only_from_provided_pool() -> None:
    reviews = TableSpec(
        name="reviews",
        primary_key=["id"],
        row_count=100,
        foreign_keys=[ForeignKeySpec("product_id", "products", "id")],
        columns=[
            ColumnSpec("id", _int(), Serial()),
            ColumnSpec("product_id", _int(), IntRange(0, 0)),
            ColumnSpec("stars", _int(TypeKind.INT16), IntRange(1, 5)),
        ],
    )
    products = TableSpec(name="products", table_class=TableClass.REFERENCE, columns=[])
    schema = SchemaSpec(tables=[reviews, products])

    tables = generate_dataset(schema, SeededRng(1), reference_pools={"products": [10, 20, 30]})
    assert "products" not in tables  # reference tables aren't generated
    assert tables["reviews"].num_rows == 100
    assert set(tables["reviews"].column("product_id").to_pylist()) <= {10, 20, 30}
