"""Canonical type system (spec FR-M.4).

A dialect-neutral type layer anchored on Arrow logical types. Source SQL types map to
canonical types at import/generation (retaining the original SQL text as metadata);
canonical types map back to a target dialect inside each sink loader, guided by the Load
Plan. This module owns the source-SQL -> canonical direction and the canonical -> Arrow
direction; canonical -> target-SQL lives in the loaders.

The footguns the spec calls out are handled here on purpose:
- DECIMAL always becomes an Arrow ``decimal128`` — never a float (money must not lose cents).
- TIMESTAMP carries timezone semantics (naive vs UTC-aware) because DB dialects differ.
- No-clean-Arrow-primitive types (UUID, JSON) use a documented string convention and keep
  their original SQL type so a loader can restore the native type where one exists.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum, auto

import pyarrow as pa


class TypeKind(Enum):
    BOOLEAN = auto()
    INT16 = auto()
    INT32 = auto()
    INT64 = auto()
    FLOAT32 = auto()
    FLOAT64 = auto()
    DECIMAL = auto()
    STRING = auto()
    DATE = auto()
    TIME = auto()
    TIMESTAMP = auto()
    UUID = auto()
    JSON = auto()
    BYTES = auto()


@dataclass(frozen=True)
class CanonicalType:
    """A dialect-neutral column type.

    ``precision``/``scale`` apply to DECIMAL, ``length`` to STRING (VARCHAR/CHAR),
    ``tz`` to TIME/TIMESTAMP. ``source_sql`` retains the original SQL type verbatim so
    loaders can reproduce faithful dialect DDL.
    """

    kind: TypeKind
    precision: int | None = None
    scale: int | None = None
    length: int | None = None
    tz: bool = False
    source_sql: str | None = None

    def __post_init__(self) -> None:
        if self.kind is TypeKind.DECIMAL and (self.precision is None or self.scale is None):
            raise ValueError("DECIMAL requires both precision and scale")

    def to_arrow(self) -> pa.DataType:
        kind = self.kind
        if kind is TypeKind.DECIMAL:
            assert self.precision is not None and self.scale is not None
            return pa.decimal128(self.precision, self.scale)
        if kind is TypeKind.TIMESTAMP:
            return pa.timestamp("us", tz="UTC" if self.tz else None)
        if kind is TypeKind.TIME:
            return pa.time64("us")
        return _SIMPLE_ARROW[kind]


_SIMPLE_ARROW: dict[TypeKind, pa.DataType] = {
    TypeKind.BOOLEAN: pa.bool_(),
    TypeKind.INT16: pa.int16(),
    TypeKind.INT32: pa.int32(),
    TypeKind.INT64: pa.int64(),
    TypeKind.FLOAT32: pa.float32(),
    TypeKind.FLOAT64: pa.float64(),
    TypeKind.DATE: pa.date32(),
    TypeKind.STRING: pa.string(),
    TypeKind.UUID: pa.string(),
    TypeKind.JSON: pa.string(),
    TypeKind.BYTES: pa.binary(),
}

# Base source-SQL name -> canonical kind (Postgres dialect, MVP). Aliases included.
_SQL_BASE: dict[str, TypeKind] = {
    "smallint": TypeKind.INT16,
    "int2": TypeKind.INT16,
    "integer": TypeKind.INT32,
    "int": TypeKind.INT32,
    "int4": TypeKind.INT32,
    "bigint": TypeKind.INT64,
    "int8": TypeKind.INT64,
    "boolean": TypeKind.BOOLEAN,
    "bool": TypeKind.BOOLEAN,
    "real": TypeKind.FLOAT32,
    "float4": TypeKind.FLOAT32,
    "double precision": TypeKind.FLOAT64,
    "float8": TypeKind.FLOAT64,
    "text": TypeKind.STRING,
    "varchar": TypeKind.STRING,
    "character varying": TypeKind.STRING,
    "char": TypeKind.STRING,
    "character": TypeKind.STRING,
    "bpchar": TypeKind.STRING,
    "uuid": TypeKind.UUID,
    "json": TypeKind.JSON,
    "jsonb": TypeKind.JSON,
    "date": TypeKind.DATE,
    "bytea": TypeKind.BYTES,
}

_PARAM_RE = re.compile(r"^\s*(?P<base>[a-z0-9_ ]+?)\s*(?:\(\s*(?P<args>[^)]*)\s*\))?\s*$")


def from_sql(sql_type: str) -> CanonicalType:
    """Parse a source SQL type (Postgres, MVP) into a canonical type.

    Retains ``sql_type`` verbatim as ``source_sql``. Raises ``ValueError`` for unknown
    types rather than guessing — silent mis-mapping would produce wrong data.
    """
    normalized = sql_type.strip().lower()

    # timestamp/time carry timezone semantics that the base map can't express
    if normalized.startswith(("timestamp", "time")) and "timestamptz" != normalized:
        return _from_temporal(normalized, sql_type)
    if normalized == "timestamptz":
        return CanonicalType(TypeKind.TIMESTAMP, tz=True, source_sql=sql_type)
    if normalized == "timetz":
        return CanonicalType(TypeKind.TIME, tz=True, source_sql=sql_type)

    match = _PARAM_RE.match(normalized)
    if match is None:
        raise ValueError(f"cannot parse SQL type: {sql_type!r}")
    base = match.group("base").strip()
    args = _parse_args(match.group("args"))

    if base in ("numeric", "decimal"):
        return _numeric_from_args(args, sql_type)

    kind = _SQL_BASE.get(base)
    if kind is None:
        raise ValueError(f"unsupported SQL type: {sql_type!r}")

    if kind is TypeKind.STRING:
        length = args[0] if args else None
        return CanonicalType(kind, length=length, source_sql=sql_type)
    return CanonicalType(kind, source_sql=sql_type)


def _from_temporal(normalized: str, original: str) -> CanonicalType:
    aware = "with time zone" in normalized
    kind = TypeKind.TIMESTAMP if normalized.startswith("timestamp") else TypeKind.TIME
    return CanonicalType(kind, tz=aware, source_sql=original)


def _parse_args(raw: str | None) -> list[int]:
    if not raw:
        return []
    return [int(part.strip()) for part in raw.split(",") if part.strip()]


# numeric/decimal need precision+scale from their args; handle before the base map
def _numeric_from_args(args: list[int], original: str) -> CanonicalType:
    if len(args) >= 2:
        return CanonicalType(
            TypeKind.DECIMAL, precision=args[0], scale=args[1], source_sql=original
        )
    if len(args) == 1:
        return CanonicalType(TypeKind.DECIMAL, precision=args[0], scale=0, source_sql=original)
    # bare numeric/decimal: Postgres allows unconstrained. Default to a wide money-safe
    # precision; the loader restores exact DDL from source_sql.
    return CanonicalType(TypeKind.DECIMAL, precision=38, scale=9, source_sql=original)
