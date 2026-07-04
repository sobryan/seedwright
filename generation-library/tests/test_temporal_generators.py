"""Temporal generators (spec FR-C.2 — most real schemas carry dates/timestamps).

Same determinism contracts as every other generator: seeded, order-independent,
chunk-invariant. Timestamps honour the column's tz semantics (naive vs UTC-aware) so they land
in the right Arrow type (FR-M.4).
"""

from datetime import UTC, date, datetime

import pyarrow as pa

from seedwright_genlib.generate import generate_table
from seedwright_genlib.generators import DateRange, Serial, TimestampRange
from seedwright_genlib.rng import SeededRng
from seedwright_genlib.schema import ColumnSpec, TableSpec
from seedwright_genlib.types import CanonicalType, TypeKind

LO_D, HI_D = date(2020, 1, 1), date(2025, 12, 31)
LO_TS, HI_TS = datetime(2020, 1, 1, 0, 0, 0), datetime(2025, 12, 31, 23, 59, 59)


def test_date_range_within_bounds() -> None:
    values = DateRange(LO_D, HI_D).generate(SeededRng(1), 300)
    assert len(values) == 300
    assert all(isinstance(v, date) and LO_D <= v <= HI_D for v in values)


def test_date_range_deterministic_and_seed_sensitive() -> None:
    gen = DateRange(LO_D, HI_D)
    assert list(gen.generate(SeededRng(1), 50)) == list(gen.generate(SeededRng(1), 50))
    assert list(gen.generate(SeededRng(1), 50)) != list(gen.generate(SeededRng(2), 50))


def test_date_range_chunk_invariant() -> None:
    whole = list(DateRange(LO_D, HI_D).generate(SeededRng(5), 100))
    rng = SeededRng(5)
    chunked = list(DateRange(LO_D, HI_D).generate(rng, 60)) + list(
        DateRange(LO_D, HI_D).generate(rng, 40))
    assert whole == chunked


def test_timestamp_range_naive() -> None:
    values = TimestampRange(LO_TS, HI_TS).generate(SeededRng(1), 200)
    assert all(isinstance(v, datetime) and v.tzinfo is None for v in values)
    assert all(LO_TS <= v <= HI_TS for v in values)


def test_timestamp_range_aware_utc() -> None:
    gen = TimestampRange(LO_TS, HI_TS, tz=True)
    values = gen.generate(SeededRng(1), 100)
    assert all(v.tzinfo is UTC for v in values)
    assert all(LO_TS.replace(tzinfo=UTC) <= v <= HI_TS.replace(tzinfo=UTC) for v in values)


def test_timestamp_range_deterministic() -> None:
    gen = TimestampRange(LO_TS, HI_TS)
    assert list(gen.generate(SeededRng(9), 40)) == list(gen.generate(SeededRng(9), 40))


def test_temporal_columns_land_in_correct_arrow_types() -> None:
    spec = TableSpec(
        name="events",
        primary_key=["id"],
        columns=[
            ColumnSpec("id", CanonicalType(TypeKind.INT64), Serial()),
            ColumnSpec("day", CanonicalType(TypeKind.DATE), DateRange(LO_D, HI_D)),
            ColumnSpec("at_naive", CanonicalType(TypeKind.TIMESTAMP, tz=False),
                       TimestampRange(LO_TS, HI_TS)),
            ColumnSpec("at_utc", CanonicalType(TypeKind.TIMESTAMP, tz=True),
                       TimestampRange(LO_TS, HI_TS, tz=True)),
        ],
    )
    table = generate_table(spec, SeededRng(3), n=50)
    assert table.schema.field("day").type == pa.date32()
    assert table.schema.field("at_naive").type == pa.timestamp("us")
    assert table.schema.field("at_utc").type == pa.timestamp("us", tz="UTC")
    assert table.column("day").null_count == 0
