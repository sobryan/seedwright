"""Load Plan parsing (spec FR-M).

Turns the Load Plan JSON (genlib ``loadplan.to_dict()``) into loader-local frozen
dataclasses. Deliberately does NOT import the generation library — the seam is the JSON, so
the loader could be reimplemented in any language / packaged as an MCP server. Required shape
is validated; optional fields default; unknown keys are ignored for forward compatibility.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


class InvalidLoadPlanError(ValueError):
    """The Load Plan JSON is missing required structure or has wrong types."""


@dataclass(frozen=True)
class PlanColumn:
    name: str
    canonical_kind: str
    precision: int | None = None
    scale: int | None = None
    length: int | None = None
    tz: bool = False
    nullable: bool = True  # permissive: emit NOT NULL only when the plan says nullable=False
    source_sql: str | None = None  # retained for traceability; not used for DDL


@dataclass(frozen=True)
class PlanTable:
    name: str
    row_count: int
    columns: tuple[PlanColumn, ...]


@dataclass(frozen=True)
class LoadPlan:
    namespace: str
    tables: tuple[PlanTable, ...]

    def table(self, name: str) -> PlanTable:
        for tbl in self.tables:
            if tbl.name == name:
                return tbl
        raise KeyError(f"no table {name!r} in load plan")


def parse_plan(data: Mapping[str, Any]) -> LoadPlan:
    """Parse and validate a Load Plan mapping into a :class:`LoadPlan`."""
    namespace = data.get("namespace")
    if not isinstance(namespace, str) or not namespace:
        raise InvalidLoadPlanError("load plan missing a non-empty 'namespace'")

    tables_raw = data.get("tables")
    if not isinstance(tables_raw, list):
        raise InvalidLoadPlanError("load plan 'tables' must be a list")

    return LoadPlan(namespace=namespace, tables=tuple(_parse_table(t) for t in tables_raw))


def _parse_table(raw: Any) -> PlanTable:
    if not isinstance(raw, Mapping):
        raise InvalidLoadPlanError(f"table entry must be an object, got {type(raw).__name__}")
    name = raw.get("name")
    if not isinstance(name, str) or not name:
        raise InvalidLoadPlanError("table entry missing a non-empty 'name'")
    row_count = raw.get("row_count")
    if not isinstance(row_count, int) or isinstance(row_count, bool):
        raise InvalidLoadPlanError(f"table {name!r} missing an integer 'row_count'")
    columns_raw = raw.get("columns")
    if not isinstance(columns_raw, list):
        raise InvalidLoadPlanError(f"table {name!r} 'columns' must be a list")
    return PlanTable(
        name=name, row_count=row_count, columns=tuple(_parse_column(c, name) for c in columns_raw)
    )


def _parse_column(raw: Any, table_name: str) -> PlanColumn:
    if not isinstance(raw, Mapping):
        raise InvalidLoadPlanError(f"column in {table_name!r} must be an object")
    name = raw.get("name")
    if not isinstance(name, str) or not name:
        raise InvalidLoadPlanError(f"column in {table_name!r} missing a non-empty 'name'")
    kind = raw.get("canonical_kind")
    if not isinstance(kind, str) or not kind:
        raise InvalidLoadPlanError(f"column {table_name}.{name} missing 'canonical_kind'")
    return PlanColumn(
        name=name,
        canonical_kind=kind,
        precision=_opt_int(raw.get("precision")),
        scale=_opt_int(raw.get("scale")),
        length=_opt_int(raw.get("length")),
        tz=bool(raw.get("tz", False)),
        nullable=bool(raw.get("nullable", True)),
        source_sql=raw.get("source_sql"),
    )


def _opt_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise InvalidLoadPlanError(f"expected an integer or null, got {value!r}")
    return value
