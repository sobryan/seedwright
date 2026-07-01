"""Canonical kind -> Postgres column type (spec FR-M.4).

Maps the closed canonical-kind enum (as its string name, from the Load Plan) plus structured
params to a Postgres type. The untrusted ``source_sql`` is deliberately *not* consulted — every
legit type is buildable from the enum + params, so we get injection-proofing for free.

Footguns handled: ``DECIMAL`` is always ``numeric`` (never a float — cents must not be lost);
``TIMESTAMP`` tz -> ``timestamptz`` vs ``timestamp``; ``TIME`` -> ``time`` regardless of tz
(Arrow time64 carries no zone); ``JSON`` -> ``jsonb``; ``STRING`` -> ``varchar(n)``/``text``
(never ``char``, which space-pads and would alter values).
"""

from __future__ import annotations

from psycopg import sql

_SIMPLE: dict[str, str] = {
    "BOOLEAN": "boolean",
    "INT16": "smallint",
    "INT32": "integer",
    "INT64": "bigint",
    "FLOAT32": "real",
    "FLOAT64": "double precision",
    "DATE": "date",
    "TIME": "time",  # tz ignored for MVP (see module docstring)
    "UUID": "uuid",
    "JSON": "jsonb",
    "BYTES": "bytea",
}

_PARAMETERIZED = frozenset({"DECIMAL", "STRING", "TIMESTAMP"})


class UnknownCanonicalKindError(ValueError):
    """The Load Plan carried a canonical kind this loader does not know — fail closed."""


def column_type(
    kind: str,
    *,
    precision: int | None = None,
    scale: int | None = None,
    length: int | None = None,
    tz: bool = False,
) -> sql.Composable:
    """Return the Postgres column type for a canonical kind + its structured params."""
    if kind in _SIMPLE:
        return sql.SQL(_SIMPLE[kind])
    if kind not in _PARAMETERIZED:
        raise UnknownCanonicalKindError(f"unknown canonical kind: {kind!r}")

    if kind == "TIMESTAMP":
        return sql.SQL("timestamptz" if tz else "timestamp")
    if kind == "STRING":
        if length is None:
            return sql.SQL("text")
        return sql.SQL("varchar({})").format(sql.Literal(int(length)))
    # DECIMAL
    if precision is None:
        return sql.SQL("numeric")
    if scale is None:
        return sql.SQL("numeric({})").format(sql.Literal(int(precision)))
    return sql.SQL("numeric({},{})").format(sql.Literal(int(precision)), sql.Literal(int(scale)))
