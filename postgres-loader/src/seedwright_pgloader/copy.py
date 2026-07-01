"""COPY text-format encoding (spec FR-G.2, FR-M.4).

Serializes canonical values into Postgres COPY *text* format — chosen over binary so the
output bytes are deterministic and testable offline without a server. One encoder per
canonical kind, each pinned by tests:

- NULL is the ``\\N`` sentinel; an empty string is an empty field (they must not collide).
- Backslash / TAB / newline / CR are escaped; a NUL byte is rejected (Postgres text data
  cannot contain it).
- ``DECIMAL`` is emitted via ``str(Decimal)`` — never through float.
- ``timestamptz`` carries an explicit offset; ``bytea`` is ``\\x`` hex; floats use the
  ``Infinity``/``-Infinity``/``NaN`` tokens Postgres understands.
"""

from __future__ import annotations

import math
from typing import Any

import pyarrow as pa
from psycopg import sql

from .safesql import identifier, qualified

_NULL = r"\N"
_INT_KINDS = frozenset({"INT16", "INT32", "INT64"})
_FLOAT_KINDS = frozenset({"FLOAT32", "FLOAT64"})
_TEXT_KINDS = frozenset({"STRING", "UUID", "JSON"})


def escape_text(value: str) -> str:
    """Escape a field for COPY text format; reject NUL (Postgres text can't contain it)."""
    if "\x00" in value:
        raise ValueError("value contains NUL byte, which Postgres text data cannot represent")
    return (
        value.replace("\\", "\\\\")
        .replace("\t", "\\t")
        .replace("\n", "\\n")
        .replace("\r", "\\r")
    )


def encode_field(value: Any, kind: str) -> str:
    """Encode one canonical value into a COPY text field (``\\N`` for NULL)."""
    if value is None:
        return _NULL
    return escape_text(_encode_value(value, kind))


def _encode_value(value: Any, kind: str) -> str:
    if kind == "BOOLEAN":
        return "t" if value else "f"
    if kind in _INT_KINDS:
        return str(int(value))
    if kind in _FLOAT_KINDS:
        return _encode_float(float(value))
    if kind == "DECIMAL":
        return str(value)  # Decimal -> exact decimal string, no float path
    if kind == "DATE":
        return str(value.isoformat())
    if kind == "TIME":
        return str(value.isoformat())
    if kind == "TIMESTAMP":
        return str(value.isoformat(sep=" "))  # aware -> '...+00:00', naive -> no offset
    if kind == "BYTES":
        return "\\x" + str(value.hex())  # escape_text will double the backslash
    if kind in _TEXT_KINDS:
        return str(value)
    raise ValueError(f"cannot COPY-encode unknown canonical kind: {kind!r}")


def _encode_float(f: float) -> str:
    if math.isnan(f):
        return "NaN"
    if math.isinf(f):
        return "Infinity" if f > 0 else "-Infinity"
    return str(f)


def encode_batch(batch: pa.RecordBatch, kinds: list[str]) -> bytes:
    """Encode an Arrow record batch into COPY text bytes (one ``\\n``-terminated row each)."""
    if len(kinds) != batch.num_columns:
        raise ValueError(
            f"kinds count ({len(kinds)}) != column count ({batch.num_columns})"
        )
    columns = [batch.column(i).to_pylist() for i in range(batch.num_columns)]
    lines: list[str] = []
    for row in zip(*columns, strict=True) if columns else []:
        lines.append("\t".join(encode_field(v, k) for v, k in zip(row, kinds, strict=True)))
    if not lines:
        return b""
    return ("\n".join(lines) + "\n").encode("utf-8")


def copy_sql(namespace: str, table: str, column_names: list[str]) -> sql.Composed:
    """``COPY "<ns>"."<table>" (<cols>) FROM STDIN WITH (FORMAT text)`` — safe identifiers."""
    cols = sql.SQL(", ").join(identifier(c) for c in column_names)
    return sql.SQL("COPY {} ({}) FROM STDIN WITH (FORMAT text)").format(
        qualified(namespace, table), cols
    )
