"""DDL builders (spec FR-G, FR-L, FR-M.4).

All DDL is schema-qualified into the validated namespace and composed through the safe
identifier layer. MVP emits columns + NOT NULL only (no PK/UNIQUE/FK — data is referentially
valid by construction from genlib). Teardown is always idempotent + scoped. The schema
ownership marker is what lets the executor refuse to drop a schema seedwright didn't create.
"""

import pytest

from seedwright_pgloader.ddl import (
    create_schema_sql,
    create_table_sql,
    drop_schema_sql,
    is_seedwright_schema,
    schema_marker_sql,
    schema_marker_value,
)
from seedwright_pgloader.plan import PlanColumn, PlanTable
from seedwright_pgloader.safesql import UnsafeNamespaceError


def _customers() -> PlanTable:
    return PlanTable(
        name="customers",
        row_count=10,
        columns=(
            PlanColumn("id", "INT64", nullable=False),
            PlanColumn("email", "STRING", length=255, nullable=True),
            PlanColumn("balance", "DECIMAL", precision=12, scale=2, nullable=False),
        ),
    )


# --- schema lifecycle -----------------------------------------------------------------

def test_create_schema_sql() -> None:
    assert create_schema_sql("ds_1").as_string(None) == 'CREATE SCHEMA "ds_1"'


def test_create_schema_validates_namespace() -> None:
    with pytest.raises(UnsafeNamespaceError):
        create_schema_sql("public")


def test_drop_schema_sql_is_idempotent_and_scoped() -> None:
    rendered = drop_schema_sql("ds_1").as_string(None)
    assert rendered == 'DROP SCHEMA IF EXISTS "ds_1" CASCADE'
    # provably scoped: never a table-level destructive statement
    assert "TABLE" not in rendered
    assert "DELETE" not in rendered
    assert "IF EXISTS" in rendered


def test_drop_schema_validates_namespace() -> None:
    with pytest.raises(UnsafeNamespaceError):
        drop_schema_sql("customers")


# --- ownership marker -----------------------------------------------------------------

def test_schema_marker_sql() -> None:
    assert schema_marker_sql("ds_1").as_string(None) == (
        'COMMENT ON SCHEMA "ds_1" IS \'seedwright:ds_1\''
    )


def test_marker_value_and_recognition() -> None:
    assert schema_marker_value("ds_1") == "seedwright:ds_1"
    assert is_seedwright_schema("seedwright:ds_1") is True
    assert is_seedwright_schema("seedwright:anything") is True
    assert is_seedwright_schema(None) is False
    assert is_seedwright_schema("a real app schema comment") is False


# --- create table ---------------------------------------------------------------------

def test_create_table_renders_columns_types_and_not_null() -> None:
    rendered = create_table_sql("ds_1", _customers()).as_string(None)
    assert rendered == (
        'CREATE TABLE "ds_1"."customers" '
        '("id" bigint NOT NULL, "email" varchar(255), "balance" numeric(12,2) NOT NULL)'
    )


def test_create_table_emits_no_constraints() -> None:
    rendered = create_table_sql("ds_1", _customers()).as_string(None)
    for forbidden in ("PRIMARY KEY", "FOREIGN KEY", "UNIQUE", "REFERENCES"):
        assert forbidden not in rendered


def test_create_table_neutralizes_column_name_injection() -> None:
    table = PlanTable(
        name="t",
        row_count=1,
        columns=(PlanColumn('x"; DROP TABLE y;--', "INT32", nullable=True),),
    )
    rendered = create_table_sql("ds_1", table).as_string(None)
    assert '"x""; DROP TABLE y;--" integer' in rendered


def test_create_table_validates_namespace() -> None:
    with pytest.raises(UnsafeNamespaceError):
        create_table_sql("public", _customers())
