"""Load Plan emitter (spec FR-M).

Emitted alongside the Canonical Dataset. Carries everything a sink loader needs to turn
dialect-neutral Parquet into faithful dialect DDL + bulk-load: FK-topological table order,
the isolated target namespace, per-table row counts, and per-column type hints that retain
both the canonical kind and the original source SQL type/precision/scale/length/nullability.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pyarrow as pa

from .dataset import topological_order
from .schema import SchemaSpec


@dataclass(frozen=True)
class ColumnHint:
    name: str
    canonical_kind: str
    source_sql: str | None
    precision: int | None
    scale: int | None
    length: int | None
    tz: bool
    nullable: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "canonical_kind": self.canonical_kind,
            "source_sql": self.source_sql,
            "precision": self.precision,
            "scale": self.scale,
            "length": self.length,
            "tz": self.tz,
            "nullable": self.nullable,
        }


@dataclass(frozen=True)
class TableLoad:
    name: str
    row_count: int
    columns: list[ColumnHint]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "row_count": self.row_count,
            "columns": [c.to_dict() for c in self.columns],
        }


@dataclass(frozen=True)
class LoadPlan:
    namespace: str
    tables: list[TableLoad]

    def to_dict(self) -> dict[str, Any]:
        return {"namespace": self.namespace, "tables": [t.to_dict() for t in self.tables]}


def build_load_plan(
    schema: SchemaSpec, results: dict[str, pa.Table], *, namespace: str
) -> LoadPlan:
    """Build a Load Plan for the generated ``results`` of ``schema`` into ``namespace``."""
    tables: list[TableLoad] = []
    for name in topological_order(schema):
        if name not in results:
            continue
        spec = schema.table(name)
        unique = spec.unique_columns
        hints = [
            ColumnHint(
                name=col.name,
                canonical_kind=col.type.kind.name,
                source_sql=col.type.source_sql,
                precision=col.type.precision,
                scale=col.type.scale,
                length=col.type.length,
                tz=col.type.tz,
                nullable=col.nullable and col.name not in unique,
            )
            for col in spec.columns
        ]
        tables.append(TableLoad(name=name, row_count=results[name].num_rows, columns=hints))
    return LoadPlan(namespace=namespace, tables=tables)
