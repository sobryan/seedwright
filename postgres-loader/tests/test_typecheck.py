"""Plan / Parquet type-agreement guard (spec FR-M.3/M.4).

Before COPY, re-derive the Arrow type each canonical_kind must have and assert the actual
Parquet field matches. This catches a Load Plan that mislabels a column (DECIMAL over a float
column, STRING over binary, INT32 over int64) instead of silently mis-encoding. Pure/offline —
does not import the generation library.
"""

import pyarrow as pa
import pytest

from seedwright_pgloader.plan import PlanColumn, PlanTable
from seedwright_pgloader.typecheck import TypeAgreementError, assert_parquet_matches_plan


def _plan_table() -> PlanTable:
    return PlanTable(
        name="t",
        row_count=1,
        columns=(
            PlanColumn("id", "INT64"),
            PlanColumn("amount", "DECIMAL", precision=10, scale=2),
            PlanColumn("name", "STRING"),
            PlanColumn("created", "TIMESTAMP", tz=True),
        ),
    )


def _matching_schema() -> pa.Schema:
    return pa.schema(
        [
            ("id", pa.int64()),
            ("amount", pa.decimal128(10, 2)),
            ("name", pa.string()),
            ("created", pa.timestamp("us", tz="UTC")),
        ]
    )


def test_matching_schema_passes() -> None:
    assert_parquet_matches_plan(_matching_schema(), _plan_table())  # must not raise


def test_decimal_over_float_raises() -> None:
    schema = pa.schema([("id", pa.int64()), ("amount", pa.float64()),
                        ("name", pa.string()), ("created", pa.timestamp("us", tz="UTC"))])
    with pytest.raises(TypeAgreementError):
        assert_parquet_matches_plan(schema, _plan_table())


def test_string_over_binary_raises() -> None:
    schema = pa.schema([("id", pa.int64()), ("amount", pa.decimal128(10, 2)),
                        ("name", pa.binary()), ("created", pa.timestamp("us", tz="UTC"))])
    with pytest.raises(TypeAgreementError):
        assert_parquet_matches_plan(schema, _plan_table())


def test_int_width_mismatch_raises() -> None:
    schema = pa.schema([("id", pa.int32()), ("amount", pa.decimal128(10, 2)),
                        ("name", pa.string()), ("created", pa.timestamp("us", tz="UTC"))])
    with pytest.raises(TypeAgreementError):
        assert_parquet_matches_plan(schema, _plan_table())


def test_timestamp_tz_mismatch_raises() -> None:
    schema = pa.schema([("id", pa.int64()), ("amount", pa.decimal128(10, 2)),
                        ("name", pa.string()), ("created", pa.timestamp("us"))])  # naive
    with pytest.raises(TypeAgreementError):
        assert_parquet_matches_plan(schema, _plan_table())


def test_decimal_precision_mismatch_raises() -> None:
    schema = pa.schema([("id", pa.int64()), ("amount", pa.decimal128(12, 2)),
                        ("name", pa.string()), ("created", pa.timestamp("us", tz="UTC"))])
    with pytest.raises(TypeAgreementError):
        assert_parquet_matches_plan(schema, _plan_table())


def test_missing_column_raises() -> None:
    schema = pa.schema([("id", pa.int64())])  # missing amount/name/created
    with pytest.raises(TypeAgreementError):
        assert_parquet_matches_plan(schema, _plan_table())


def _decimal_only(precision: int | None, scale: int | None) -> PlanTable:
    return PlanTable(
        name="t", row_count=1,
        columns=(PlanColumn("amount", "DECIMAL", precision=precision, scale=scale),),
    )


def test_decimal_precision_without_scale_rejects_scaled_parquet() -> None:
    # Found by review: precision-without-scale => numeric(p,0), which would silently round a
    # decimal128(5,2) Parquet column. The guard must reject it, not pass it.
    schema = pa.schema([("amount", pa.decimal128(5, 2))])
    with pytest.raises(TypeAgreementError):
        assert_parquet_matches_plan(schema, _decimal_only(precision=5, scale=None))


def test_decimal_precision_without_scale_accepts_scale0_parquet() -> None:
    schema = pa.schema([("amount", pa.decimal128(5, 0))])
    assert_parquet_matches_plan(schema, _decimal_only(precision=5, scale=None))  # must not raise
