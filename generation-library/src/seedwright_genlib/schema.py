"""Structured schema + generation spec (spec OPEN-5: the structured form is the source
of truth; natural language is a later convenience front-end that compiles to this).

This is the declarative surface the thin glue authors against (FR-M.1/2). The Generation
Library reads these specs; it never interprets free-form code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto

from .generators import Generator
from .types import CanonicalType


class TableClass(Enum):
    """How a table participates in generation (spec FR-O.1)."""

    GENERATED = auto()   # the library generates its rows
    REFERENCE = auto()   # not generated; FKs into it sample existing keys
    EXCLUDED = auto()    # ignored entirely


@dataclass
class ColumnSpec:
    name: str
    type: CanonicalType
    generator: Generator
    nullable: bool = False
    null_rate: float = 0.0
    unique: bool = False

    def __post_init__(self) -> None:
        if not 0.0 <= self.null_rate <= 1.0:
            raise ValueError(f"null_rate must be in [0,1], got {self.null_rate}")


@dataclass
class ForeignKeySpec:
    """A single-column foreign key with a per-parent child cardinality (FR-C.2)."""

    column: str
    references_table: str
    references_column: str
    min_per_parent: int = 0
    max_per_parent: int = 1

    def __post_init__(self) -> None:
        if self.max_per_parent < self.min_per_parent:
            raise ValueError("max_per_parent < min_per_parent")


@dataclass
class TableSpec:
    name: str
    columns: list[ColumnSpec]
    primary_key: list[str] = field(default_factory=list)
    foreign_keys: list[ForeignKeySpec] = field(default_factory=list)
    row_count: int | None = None
    table_class: TableClass = TableClass.GENERATED

    def column(self, name: str) -> ColumnSpec:
        for col in self.columns:
            if col.name == name:
                return col
        raise KeyError(f"no column {name!r} in table {self.name!r}")

    @property
    def unique_columns(self) -> set[str]:
        """Columns that must hold distinct values: the primary key plus any UNIQUE column."""
        return set(self.primary_key) | {c.name for c in self.columns if c.unique}


@dataclass
class SchemaSpec:
    tables: list[TableSpec]

    def table(self, name: str) -> TableSpec:
        for tbl in self.tables:
            if tbl.name == name:
                return tbl
        raise KeyError(f"no table {name!r} in schema")
