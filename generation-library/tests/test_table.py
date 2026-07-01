"""Single-table generation (spec FR-E.3, FR-C.2).

Generate one table's columns into a typed Arrow table, honouring PK uniqueness, null
rate, not-null constraints, and the canonical type of each column.
"""

from decimal import Decimal

import pyarrow as pa
import pytest

from seedwright_genlib.generate import UniquenessError, generate_table
from seedwright_genlib.generators import Categorical, DecimalRange, FakerField, IntRange, Serial
from seedwright_genlib.rng import SeededRng
from seedwright_genlib.schema import ColumnSpec, TableSpec
from seedwright_genlib.types import CanonicalType, TypeKind


def _customers() -> TableSpec:
    return TableSpec(
        name="customers",
        primary_key=["id"],
        columns=[
            ColumnSpec("id", CanonicalType(TypeKind.INT64), Serial()),
            ColumnSpec("name", CanonicalType(TypeKind.STRING), FakerField("name")),
            ColumnSpec(
                "tier",
                CanonicalType(TypeKind.STRING),
                Categorical(["free", "pro"], weights=[0.7, 0.3]),
            ),
            ColumnSpec(
                "balance",
                CanonicalType(TypeKind.DECIMAL, precision=12, scale=2),
                DecimalRange(Decimal("0.00"), Decimal("9999.99"), scale=2),
            ),
            ColumnSpec(
                "note",
                CanonicalType(TypeKind.STRING),
                FakerField("sentence"),
                nullable=True,
                null_rate=0.5,
            ),
        ],
    )


def test_generate_table_has_requested_row_count() -> None:
    table = generate_table(_customers(), SeededRng(1), n=500)
    assert table.num_rows == 500


def test_primary_key_values_are_unique() -> None:
    table = generate_table(_customers(), SeededRng(1), n=1000)
    ids = table.column("id").to_pylist()
    assert len(set(ids)) == 1000


def test_arrow_schema_matches_canonical_types() -> None:
    table = generate_table(_customers(), SeededRng(1), n=10)
    schema = table.schema
    assert schema.field("id").type == pa.int64()
    assert schema.field("balance").type == pa.decimal128(12, 2)
    assert schema.field("name").type == pa.string()


def test_not_null_columns_have_no_nulls() -> None:
    table = generate_table(_customers(), SeededRng(1), n=1000)
    assert table.column("id").null_count == 0
    assert table.column("name").null_count == 0


def test_nullable_column_honours_null_rate() -> None:
    table = generate_table(_customers(), SeededRng(1), n=2000)
    nulls = table.column("note").null_count
    assert 800 < nulls < 1200  # ~50% within a generous band


def test_generation_is_deterministic() -> None:
    a = generate_table(_customers(), SeededRng(1), n=300)
    b = generate_table(_customers(), SeededRng(1), n=300)
    assert a.equals(b)


def test_generation_varies_by_seed() -> None:
    a = generate_table(_customers(), SeededRng(1), n=300)
    b = generate_table(_customers(), SeededRng(2), n=300)
    assert not a.equals(b)


def test_decimal_values_preserve_scale_no_float_drift() -> None:
    table = generate_table(_customers(), SeededRng(1), n=200)
    for value in table.column("balance").to_pylist():
        assert isinstance(value, Decimal)
        assert -value.as_tuple().exponent == 2


def test_unique_column_with_insufficient_domain_raises() -> None:
    spec = TableSpec(
        name="t",
        primary_key=["k"],
        columns=[ColumnSpec("k", CanonicalType(TypeKind.INT32), IntRange(0, 2))],
    )
    with pytest.raises(UniquenessError):
        generate_table(spec, SeededRng(1), n=100)
