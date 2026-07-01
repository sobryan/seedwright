"""Plan / Parquet type-agreement guard (spec FR-M.3/M.4).

The Parquet is the canonical source of truth; the Load Plan is metadata about it. Before COPY
we re-derive the Arrow type each canonical kind must have and confirm the actual Parquet field
matches — so a plan that mislabels a column fails loudly instead of mis-encoding. Does not
import the generation library; the expected-type map mirrors the canonical type system.
"""

from __future__ import annotations

import pyarrow as pa

from .plan import PlanColumn, PlanTable


class TypeAgreementError(ValueError):
    """A Parquet field's type does not match the canonical kind the Load Plan claims."""


def assert_parquet_matches_plan(schema: pa.Schema, table: PlanTable) -> None:
    """Raise if any plan column is missing from ``schema`` or has a disagreeing Arrow type."""
    for col in table.columns:
        if col.name not in schema.names:
            raise TypeAgreementError(
                f"{table.name}.{col.name}: plan column missing from Parquet schema"
            )
        field_type = schema.field(col.name).type
        if not _matches(field_type, col):
            raise TypeAgreementError(
                f"{table.name}.{col.name}: canonical_kind {col.canonical_kind} "
                f"disagrees with Parquet type {field_type}"
            )


_EXACT: dict[str, pa.DataType] = {
    "BOOLEAN": pa.bool_(),
    "INT16": pa.int16(),
    "INT32": pa.int32(),
    "INT64": pa.int64(),
    "FLOAT32": pa.float32(),
    "FLOAT64": pa.float64(),
    "DATE": pa.date32(),
}


def _matches(field_type: pa.DataType, col: PlanColumn) -> bool:
    kind = col.canonical_kind
    if kind in _EXACT:
        return bool(field_type == _EXACT[kind])
    if kind == "DECIMAL":
        if not pa.types.is_decimal(field_type):
            return False
        if col.precision is not None and field_type.precision != col.precision:
            return False
        # A plan scale of None with a precision means numeric(p) == numeric(p,0): the DDL would
        # round to 0 places, so the Parquet field's scale must actually be 0 (else silent cents
        # loss). Only when precision is also absent is any decimal scale acceptable.
        if col.scale is not None:
            return bool(field_type.scale == col.scale)
        if col.precision is not None:
            return bool(field_type.scale == 0)
        return True
    if kind in ("STRING", "UUID", "JSON"):
        return bool(pa.types.is_string(field_type) or pa.types.is_large_string(field_type))
    if kind == "BYTES":
        return bool(pa.types.is_binary(field_type) or pa.types.is_large_binary(field_type))
    if kind == "TIME":
        return bool(pa.types.is_time(field_type))
    if kind == "TIMESTAMP":
        if not pa.types.is_timestamp(field_type):
            return False
        has_tz = field_type.tz is not None
        return has_tz == col.tz
    raise TypeAgreementError(f"unknown canonical kind in plan: {kind!r}")
