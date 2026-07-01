"""COPY text-format encoding (spec FR-G.2, FR-M.4).

The bulk-load path. Text format (not binary) so the bytes are deterministic and unit-testable
offline. Pins every footgun: null sentinel vs empty string, delimiter/newline/backslash
escaping, NUL rejection, decimals via str (no float drift), timestamptz explicit offset, bytea
hex, float Infinity/NaN tokens.
"""

from datetime import UTC, date, datetime, time
from decimal import Decimal

import pyarrow as pa
import pytest

from seedwright_pgloader.copy import copy_sql, encode_batch, encode_field, escape_text
from seedwright_pgloader.safesql import UnsafeNamespaceError

# --- escaping -------------------------------------------------------------------------

def test_escape_text_escapes_specials() -> None:
    assert escape_text("a\\b\tc\nd\re") == "a\\\\b\\tc\\nd\\re"


def test_escape_text_rejects_nul() -> None:
    with pytest.raises(ValueError):
        escape_text("a\x00b")


# --- null vs empty --------------------------------------------------------------------

def test_null_is_backslash_N() -> None:
    assert encode_field(None, "STRING") == r"\N"


def test_empty_string_is_not_null() -> None:
    assert encode_field("", "STRING") == ""


# --- scalars --------------------------------------------------------------------------

def test_boolean() -> None:
    assert encode_field(True, "BOOLEAN") == "t"
    assert encode_field(False, "BOOLEAN") == "f"


def test_integer() -> None:
    assert encode_field(42, "INT64") == "42"


def test_decimal_preserves_scale_no_float_drift() -> None:
    assert encode_field(Decimal("0.10"), "DECIMAL") == "0.10"
    assert encode_field(Decimal("100.00"), "DECIMAL") == "100.00"


def test_float_specials() -> None:
    assert encode_field(float("inf"), "FLOAT64") == "Infinity"
    assert encode_field(float("-inf"), "FLOAT64") == "-Infinity"
    assert encode_field(float("nan"), "FLOAT64") == "NaN"


def test_temporal() -> None:
    assert encode_field(date(2026, 7, 1), "DATE") == "2026-07-01"
    assert encode_field(time(13, 5, 9), "TIME") == "13:05:09"
    assert encode_field(datetime(2026, 7, 1, 13, 5, 9), "TIMESTAMP") == "2026-07-01 13:05:09"
    aware = datetime(2026, 7, 1, 13, 5, 9, tzinfo=UTC)
    assert encode_field(aware, "TIMESTAMP") == "2026-07-01 13:05:09+00:00"


def test_bytea_hex_with_copy_escaping() -> None:
    # logical bytea is \x4869; COPY escaping doubles the backslash
    assert encode_field(b"Hi", "BYTES") == r"\\x4869"


def test_string_escapes_embedded_specials() -> None:
    assert encode_field("a\tb\nc", "STRING") == "a\\tb\\nc"


def test_string_with_nul_raises() -> None:
    with pytest.raises(ValueError):
        encode_field("a\x00b", "STRING")


def test_uuid_and_json_treated_as_text() -> None:
    assert encode_field("550e8400-e29b-41d4-a716-446655440000", "UUID") == (
        "550e8400-e29b-41d4-a716-446655440000"
    )
    assert encode_field('{"k": 1}', "JSON") == '{"k": 1}'


# --- batch ----------------------------------------------------------------------------

def test_encode_batch_rows_and_nulls() -> None:
    batch = pa.record_batch(
        {"id": [1, 2], "name": ["ann", None]},
        schema=pa.schema([("id", pa.int64()), ("name", pa.string())]),
    )
    assert encode_batch(batch, ["INT64", "STRING"]) == b"1\tann\n2\t\\N\n"


def test_encode_batch_empty_is_empty_bytes() -> None:
    batch = pa.record_batch(
        {"id": []}, schema=pa.schema([("id", pa.int64())])
    )
    assert encode_batch(batch, ["INT64"]) == b""


def test_encode_batch_rejects_kind_count_mismatch() -> None:
    batch = pa.record_batch({"id": [1]}, schema=pa.schema([("id", pa.int64())]))
    with pytest.raises(ValueError):
        encode_batch(batch, ["INT64", "STRING"])


# --- COPY statement -------------------------------------------------------------------

def test_copy_sql() -> None:
    rendered = copy_sql("ds_1", "orders", ["id", "total"]).as_string(None)
    assert rendered == 'COPY "ds_1"."orders" ("id", "total") FROM STDIN WITH (FORMAT text)'


def test_copy_sql_validates_namespace() -> None:
    with pytest.raises(UnsafeNamespaceError):
        copy_sql("public", "t", ["a"])
