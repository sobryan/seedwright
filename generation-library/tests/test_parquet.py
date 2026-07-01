"""Canonical Parquet output (spec FR-M.3, FR-E.4).

One Parquet file per table is the durable canonical checkpoint — the single artifact that
validation and every sink loader read from. Writing is batched into row groups to bound
memory at the ~10M-row ceiling (NFR-SCALE).
"""

from decimal import Decimal

import pyarrow as pa
import pyarrow.parquet as pq

from seedwright_genlib.generate import generate_table
from seedwright_genlib.generators import DecimalRange, FakerField, Serial
from seedwright_genlib.parquet import write_dataset, write_table
from seedwright_genlib.rng import SeededRng
from seedwright_genlib.schema import ColumnSpec, TableSpec
from seedwright_genlib.types import CanonicalType, TypeKind


def _table() -> pa.Table:
    spec = TableSpec(
        name="customers",
        primary_key=["id"],
        columns=[
            ColumnSpec("id", CanonicalType(TypeKind.INT64), Serial()),
            ColumnSpec("name", CanonicalType(TypeKind.STRING), FakerField("name")),
            ColumnSpec(
                "balance",
                CanonicalType(TypeKind.DECIMAL, precision=12, scale=2),
                DecimalRange(Decimal("0.00"), Decimal("999.99"), scale=2),
            ),
        ],
    )
    return generate_table(spec, SeededRng(1), n=1000)


def test_write_table_roundtrips(tmp_path) -> None:
    table = _table()
    path = write_table(table, tmp_path / "customers.parquet")
    assert pq.read_table(path).equals(table)


def test_write_table_preserves_canonical_types(tmp_path) -> None:
    path = write_table(_table(), tmp_path / "customers.parquet")
    schema = pq.read_table(path).schema
    assert schema.field("id").type == pa.int64()
    assert schema.field("balance").type == pa.decimal128(12, 2)


def test_row_group_size_bounds_batches(tmp_path) -> None:
    path = write_table(_table(), tmp_path / "customers.parquet", row_group_size=100)
    assert pq.ParquetFile(path).metadata.num_row_groups == 10


def test_write_dataset_writes_one_file_per_table(tmp_path) -> None:
    tables = {"customers": _table(), "orders": _table()}
    paths = write_dataset(tables, tmp_path)
    assert set(paths) == {"customers", "orders"}
    assert (tmp_path / "customers.parquet").exists()
    assert (tmp_path / "orders.parquet").exists()
    assert pq.read_table(paths["orders"]).num_rows == 1000
