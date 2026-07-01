"""Canonical type system (spec FR-M.4).

A dialect-neutral type layer anchored on Arrow logical types, carrying the original
source SQL type as metadata so loaders can reproduce faithful dialect DDL. The tests
below pin the known footguns the spec calls out explicitly.
"""

import pyarrow as pa
import pytest

from seedwright_genlib.types import CanonicalType, TypeKind, from_sql

# --- footgun: money is decimal, never float -------------------------------------------

def test_decimal_maps_to_arrow_decimal_never_float() -> None:
    t = CanonicalType(TypeKind.DECIMAL, precision=12, scale=2)
    arrow = t.to_arrow()
    assert arrow == pa.decimal128(12, 2)
    assert not pa.types.is_floating(arrow)


def test_decimal_requires_precision_and_scale() -> None:
    with pytest.raises(ValueError):
        CanonicalType(TypeKind.DECIMAL)  # missing precision/scale


# --- footgun: timestamp timezone semantics --------------------------------------------

def test_naive_timestamp_has_no_timezone() -> None:
    assert CanonicalType(TypeKind.TIMESTAMP, tz=False).to_arrow() == pa.timestamp("us")


def test_aware_timestamp_carries_utc() -> None:
    arrow = CanonicalType(TypeKind.TIMESTAMP, tz=True).to_arrow()
    assert pa.types.is_timestamp(arrow)
    assert arrow.tz == "UTC"


# --- core kinds -----------------------------------------------------------------------

@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        (TypeKind.BOOLEAN, pa.bool_()),
        (TypeKind.INT16, pa.int16()),
        (TypeKind.INT32, pa.int32()),
        (TypeKind.INT64, pa.int64()),
        (TypeKind.FLOAT32, pa.float32()),
        (TypeKind.FLOAT64, pa.float64()),
        (TypeKind.DATE, pa.date32()),
        (TypeKind.STRING, pa.string()),
        (TypeKind.UUID, pa.string()),
        (TypeKind.JSON, pa.string()),
        (TypeKind.BYTES, pa.binary()),
    ],
)
def test_kind_maps_to_expected_arrow_type(kind: TypeKind, expected: pa.DataType) -> None:
    assert CanonicalType(kind).to_arrow() == expected


# --- source SQL -> canonical (Postgres, MVP) ------------------------------------------

@pytest.mark.parametrize(
    ("sql", "kind"),
    [
        ("integer", TypeKind.INT32),
        ("int4", TypeKind.INT32),
        ("bigint", TypeKind.INT64),
        ("smallint", TypeKind.INT16),
        ("boolean", TypeKind.BOOLEAN),
        ("double precision", TypeKind.FLOAT64),
        ("real", TypeKind.FLOAT32),
        ("text", TypeKind.STRING),
        ("uuid", TypeKind.UUID),
        ("jsonb", TypeKind.JSON),
        ("date", TypeKind.DATE),
        ("bytea", TypeKind.BYTES),
    ],
)
def test_from_sql_maps_base_types(sql: str, kind: TypeKind) -> None:
    assert from_sql(sql).kind is kind


def test_from_sql_parses_varchar_length() -> None:
    t = from_sql("character varying(255)")
    assert t.kind is TypeKind.STRING
    assert t.length == 255


def test_from_sql_parses_numeric_precision_scale() -> None:
    t = from_sql("numeric(10,2)")
    assert t.kind is TypeKind.DECIMAL
    assert (t.precision, t.scale) == (10, 2)


def test_from_sql_detects_timestamp_timezone() -> None:
    assert from_sql("timestamp without time zone").tz is False
    assert from_sql("timestamp with time zone").tz is True
    assert from_sql("timestamptz").tz is True


def test_from_sql_retains_source_sql_verbatim() -> None:
    # loaders need the original to reproduce faithful DDL (FR-M.4)
    assert from_sql("NUMERIC(10, 2)").source_sql == "NUMERIC(10, 2)"


def test_from_sql_is_case_insensitive() -> None:
    assert from_sql("INTEGER").kind is TypeKind.INT32


def test_from_sql_rejects_unknown_type() -> None:
    with pytest.raises(ValueError):
        from_sql("polygon")
