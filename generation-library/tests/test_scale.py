"""Scale target (spec FR-E.5, OPEN-8): validate MVP at ~1M rows/table.

Marked ``slow`` — excluded from the fast loop but part of full regression runs. Uses only
vectorized generators (no per-row Faker) so the check exercises the pipeline's scale, not
Faker's throughput. The Parquet write is row-group-batched to keep write memory bounded.
"""

import pyarrow.parquet as pq
import pytest

from seedwright_genlib.dataset import generate_dataset
from seedwright_genlib.generators import Categorical, IntRange, Serial
from seedwright_genlib.rng import SeededRng
from seedwright_genlib.schema import ColumnSpec, SchemaSpec, TableSpec
from seedwright_genlib.types import CanonicalType, TypeKind

ONE_MILLION = 1_000_000


@pytest.mark.slow
def test_generates_and_writes_one_million_rows(tmp_path) -> None:
    schema = SchemaSpec(
        tables=[
            TableSpec(
                name="events",
                primary_key=["id"],
                row_count=ONE_MILLION,
                columns=[
                    ColumnSpec("id", CanonicalType(TypeKind.INT64), Serial()),
                    ColumnSpec("amount", CanonicalType(TypeKind.INT32), IntRange(0, 10**6)),
                    ColumnSpec(
                        "status",
                        CanonicalType(TypeKind.STRING),
                        Categorical(["ok", "fail"], weights=[0.9, 0.1]),
                    ),
                ],
            )
        ]
    )
    tables = generate_dataset(schema, SeededRng(1))
    assert tables["events"].num_rows == ONE_MILLION
    # primary key remains unique at scale
    assert tables["events"].column("id").to_pylist()[-1] == ONE_MILLION

    path = write_table_million(tables, tmp_path)
    meta = pq.ParquetFile(path).metadata
    assert meta.num_rows == ONE_MILLION
    assert meta.num_row_groups == 10  # 1M / 100k row-group size


def write_table_million(tables, tmp_path):
    from seedwright_genlib.parquet import write_table

    return write_table(tables["events"], tmp_path / "events.parquet", row_group_size=100_000)
