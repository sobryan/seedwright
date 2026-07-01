"""DDL builders (spec FR-G, FR-L, FR-M.4).

Every statement is schema-qualified into a validated namespace and composed through the safe
identifier layer — never string interpolation. MVP DDL is columns + NOT NULL only: genlib
generates referentially-valid data by construction (FR-E.3), so PK/UNIQUE/FK are fidelity,
deferred to a later slice once the Load Plan carries them.

The ownership marker (``COMMENT ON SCHEMA … IS 'seedwright:…'``) is the runtime guard that
lets the executor refuse to drop any schema seedwright did not create.
"""

from __future__ import annotations

from psycopg import sql

from .pgtypes import column_type
from .plan import PlanColumn, PlanTable
from .safesql import identifier, qualified, validate_namespace

SCHEMA_MARKER_PREFIX = "seedwright:"


def create_schema_sql(namespace: str) -> sql.Composed:
    """``CREATE SCHEMA "<ns>"`` — plain (no IF NOT EXISTS) so 'create' mode fails loud."""
    validate_namespace(namespace)
    return sql.SQL("CREATE SCHEMA {}").format(identifier(namespace))


def drop_schema_sql(namespace: str) -> sql.Composed:
    """``DROP SCHEMA IF EXISTS "<ns>" CASCADE`` — idempotent (FR-L.6) and provably scoped.

    A single schema-qualified drop; structurally never a ``DROP TABLE``/``DELETE FROM``.
    """
    validate_namespace(namespace)
    return sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(identifier(namespace))


def schema_marker_value(namespace: str) -> str:
    return f"{SCHEMA_MARKER_PREFIX}{namespace}"


def schema_marker_sql(namespace: str) -> sql.Composed:
    """``COMMENT ON SCHEMA "<ns>" IS 'seedwright:<ns>'`` — stamps ownership at create time."""
    validate_namespace(namespace)
    return sql.SQL("COMMENT ON SCHEMA {} IS {}").format(
        identifier(namespace), sql.Literal(schema_marker_value(namespace))
    )


def is_seedwright_schema(comment: str | None) -> bool:
    """True iff a schema's comment marks it as seedwright-owned (drop guard predicate)."""
    return comment is not None and comment.startswith(SCHEMA_MARKER_PREFIX)


def create_table_sql(namespace: str, table: PlanTable) -> sql.Composed:
    """``CREATE TABLE "<ns>"."<table>" (<col> <type> [NOT NULL], …)`` — no constraints."""
    validate_namespace(namespace)
    column_defs = [_column_def(col) for col in table.columns]
    return sql.SQL("CREATE TABLE {} ({})").format(
        qualified(namespace, table.name), sql.SQL(", ").join(column_defs)
    )


def _column_def(col: PlanColumn) -> sql.Composed:
    not_null = sql.SQL(" NOT NULL") if not col.nullable else sql.SQL("")
    return sql.SQL("{} {}{}").format(
        identifier(col.name),
        column_type(
            col.canonical_kind,
            precision=col.precision,
            scale=col.scale,
            length=col.length,
            tz=col.tz,
        ),
        not_null,
    )
