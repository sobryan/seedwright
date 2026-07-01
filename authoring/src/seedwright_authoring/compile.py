"""Compile a validated genspec into a genlib ``SchemaSpec`` (ADR-0003).

Validation runs first; any issue raises ``GenSpecValidationError`` carrying the issues (which the
loop turns into refine feedback). Column *types* come from the imported schema (authoritative),
never the model's assertion; generators come from the catalog. The result is an ordinary genlib
SchemaSpec that executes deterministically and model-free.
"""

from __future__ import annotations

from seedwright_genlib.schema import (
    ColumnSpec,
    ForeignKeySpec,
    SchemaSpec,
    TableClass,
    TableSpec,
)

from .catalog import build_generator
from .feedback import Failure
from .genspec import GenSpec, GenTable
from .imported import ImportedSchema
from .validate import validate_genspec


class GenSpecValidationError(ValueError):
    """The genspec failed static validation; carries the issues for the refine loop."""

    def __init__(self, issues: list[Failure]) -> None:
        self.issues = issues
        summary = ", ".join(f.test_id for f in issues[:5])
        super().__init__(f"{len(issues)} genspec validation issue(s): {summary}")


def compile_to_genlib(genspec: GenSpec, imported: ImportedSchema) -> SchemaSpec:
    issues = validate_genspec(genspec, imported)
    if issues:
        raise GenSpecValidationError(issues)
    return SchemaSpec(tables=[_table(t, imported) for t in genspec.tables])


def _table(table: GenTable, imported: ImportedSchema) -> TableSpec:
    columns = [
        ColumnSpec(
            name=col.name,
            type=imported.column_type(table.name, col.name),  # authoritative, not the model's
            generator=build_generator(col.generator.kind, col.generator.params),
            nullable=col.nullable,
            null_rate=col.null_rate,
            unique=col.unique,
        )
        for col in table.columns
    ]
    foreign_keys = [
        ForeignKeySpec(
            column=fk.column,
            references_table=fk.references_table,
            references_column=fk.references_column,
            min_per_parent=fk.min_per_parent,
            max_per_parent=fk.max_per_parent,
        )
        for fk in table.foreign_keys
    ]
    return TableSpec(
        name=table.name,
        columns=columns,
        primary_key=list(table.primary_key),
        foreign_keys=foreign_keys,
        row_count=table.row_count,
        table_class=TableClass[table.table_class.upper()],
    )
