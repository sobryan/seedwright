"""Imported schema — the authoritative type source (ADR-0003).

A minimal authoring-owned projection of the imported database schema: per column, the genlib
``CanonicalType`` (with precision/scale/length/source_sql) parsed from its SQL type. The compiler
reads types from here, not from the model's genspec, so the model cannot author a wrong decimal
scale (FR-M.4). Kept separate from genlib's ``SchemaSpec`` because that requires concrete
generators, which don't exist until authoring picks them.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from seedwright_genlib.types import CanonicalType, from_sql


@dataclass(frozen=True)
class ImportedColumn:
    name: str
    type: CanonicalType


@dataclass(frozen=True)
class ImportedTable:
    name: str
    columns: tuple[ImportedColumn, ...]
    primary_key: tuple[str, ...] = ()

    def column(self, name: str) -> ImportedColumn:
        for col in self.columns:
            if col.name == name:
                return col
        raise KeyError(f"no column {name!r} in imported table {self.name!r}")


@dataclass(frozen=True)
class ImportedSchema:
    tables: tuple[ImportedTable, ...]

    def table(self, name: str) -> ImportedTable:
        for tbl in self.tables:
            if tbl.name == name:
                return tbl
        raise KeyError(f"no table {name!r} in imported schema")

    def column_type(self, table: str, column: str) -> CanonicalType:
        return self.table(table).column(column).type

    @classmethod
    def from_sql_columns(
        cls,
        columns_by_table: Mapping[str, Sequence[tuple[str, str]]],
        primary_keys: Mapping[str, Sequence[str]] | None = None,
    ) -> ImportedSchema:
        """Build from ``{table: [(column, sql_type), ...]}`` (SQL types parsed via genlib)."""
        primary_keys = primary_keys or {}
        tables = tuple(
            ImportedTable(
                name=table,
                columns=tuple(ImportedColumn(col, from_sql(sql)) for col, sql in cols),
                primary_key=tuple(primary_keys.get(table, ())),
            )
            for table, cols in columns_by_table.items()
        )
        return cls(tables=tables)
