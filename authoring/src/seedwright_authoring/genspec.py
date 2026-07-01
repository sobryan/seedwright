"""The declarative Generator Spec — the model's output (ADR-0003 frozen schema).

Immutable dataclasses + ``parse_genspec`` (validate required shape, default optionals) +
``to_dict`` (canonical, stable round-trip). ``canonical_kind`` here is the model's *assertion*;
the authoritative type is pulled from the imported schema at compile time.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


class GenSpecParseError(ValueError):
    """The genspec JSON is missing required structure or has the wrong shape."""


@dataclass(frozen=True)
class GenGenerator:
    kind: str
    params: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "params": dict(self.params)}


@dataclass(frozen=True)
class GenColumn:
    name: str
    canonical_kind: str
    generator: GenGenerator
    nullable: bool = False
    null_rate: float = 0.0
    unique: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "canonical_kind": self.canonical_kind,
            "generator": self.generator.to_dict(),
            "nullable": self.nullable,
            "null_rate": self.null_rate,
            "unique": self.unique,
        }


@dataclass(frozen=True)
class GenForeignKey:
    column: str
    references_table: str
    references_column: str
    min_per_parent: int = 0
    max_per_parent: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "column": self.column,
            "references_table": self.references_table,
            "references_column": self.references_column,
            "min_per_parent": self.min_per_parent,
            "max_per_parent": self.max_per_parent,
        }


@dataclass(frozen=True)
class GenTable:
    name: str
    table_class: str
    columns: tuple[GenColumn, ...]
    primary_key: tuple[str, ...] = ()
    foreign_keys: tuple[GenForeignKey, ...] = ()
    row_count: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "table_class": self.table_class,
            "row_count": self.row_count,
            "primary_key": list(self.primary_key),
            "foreign_keys": [fk.to_dict() for fk in self.foreign_keys],
            "columns": [c.to_dict() for c in self.columns],
        }


@dataclass(frozen=True)
class GenSpec:
    genspec_version: str
    seed: int
    tables: tuple[GenTable, ...]

    def table(self, name: str) -> GenTable:
        for tbl in self.tables:
            if tbl.name == name:
                return tbl
        raise KeyError(f"no table {name!r} in genspec")

    def to_dict(self) -> dict[str, Any]:
        return {
            "genspec_version": self.genspec_version,
            "seed": self.seed,
            "tables": [t.to_dict() for t in self.tables],
        }


def parse_genspec(data: Mapping[str, Any]) -> GenSpec:
    version = data.get("genspec_version")
    if not isinstance(version, str):
        raise GenSpecParseError("genspec missing string 'genspec_version'")
    seed = data.get("seed")
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise GenSpecParseError("genspec missing integer 'seed'")
    tables = data.get("tables")
    if not isinstance(tables, list):
        raise GenSpecParseError("genspec 'tables' must be a list")
    return GenSpec(genspec_version=version, seed=seed, tables=tuple(_table(t) for t in tables))


def _require(mapping: Any, key: str, where: str) -> Any:
    if not isinstance(mapping, Mapping) or key not in mapping:
        raise GenSpecParseError(f"{where} missing required {key!r}")
    return mapping[key]


def _table(raw: Any) -> GenTable:
    name = _require(raw, "name", "table")
    table_class = _require(raw, "table_class", f"table {name!r}")
    columns = _require(raw, "columns", f"table {name!r}")
    if not isinstance(columns, list):
        raise GenSpecParseError(f"table {name!r} 'columns' must be a list")
    fks = raw.get("foreign_keys", [])
    return GenTable(
        name=name,
        table_class=str(table_class).lower(),  # normalize so validate/derive/compile agree
        columns=tuple(_column(c, name) for c in columns),
        primary_key=tuple(raw.get("primary_key", [])),
        foreign_keys=tuple(_fk(f, name) for f in fks),
        row_count=raw.get("row_count"),
    )


def _column(raw: Any, table: str) -> GenColumn:
    name = _require(raw, "name", f"column in {table!r}")
    kind = _require(raw, "canonical_kind", f"column {table}.{name}")
    generator = _require(raw, "generator", f"column {table}.{name}")
    gkind = _require(generator, "kind", f"generator for {table}.{name}")
    return GenColumn(
        name=name,
        canonical_kind=kind,
        generator=GenGenerator(kind=gkind, params=dict(generator.get("params", {}))),
        nullable=bool(raw.get("nullable", False)),
        null_rate=_coerce_float(raw.get("null_rate", 0.0), f"{table}.{name} null_rate"),
        unique=bool(raw.get("unique", False)),
    )


def _fk(raw: Any, table: str) -> GenForeignKey:
    return GenForeignKey(
        column=_require(raw, "column", f"foreign_key in {table!r}"),
        references_table=_require(raw, "references_table", f"foreign_key in {table!r}"),
        references_column=_require(raw, "references_column", f"foreign_key in {table!r}"),
        min_per_parent=_coerce_int(raw.get("min_per_parent", 0), f"foreign_key in {table!r} min"),
        max_per_parent=_coerce_int(raw.get("max_per_parent", 1), f"foreign_key in {table!r} max"),
    )


def _coerce_float(value: Any, where: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise GenSpecParseError(f"{where} must be a number, got {value!r}") from exc


def _coerce_int(value: Any, where: str) -> int:
    if isinstance(value, bool):
        raise GenSpecParseError(f"{where} must be an integer, got {value!r}")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise GenSpecParseError(f"{where} must be an integer, got {value!r}") from exc
