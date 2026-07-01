"""Table generation (spec FR-E.3).

Turns a ``TableSpec`` into a typed Arrow table. Each column gets its own independent,
seed-derived RNG stream (so column order and parallelism don't affect output), values are
drawn from the column's generator, uniqueness is enforced for PK/UNIQUE columns, and the
null rate is applied to nullable columns. Foreign-key columns are populated separately by
the cross-table layer; here we generate a table's own values.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pyarrow as pa

from .rng import SeededRng
from .schema import ColumnSpec, TableSpec


class UniquenessError(ValueError):
    """A PK/UNIQUE column could not be filled with distinct values (spec FR-C.4).

    Surfaced rather than silently producing duplicates — e.g. a UNIQUE column whose value
    domain is smaller than the requested row count.
    """


def generate_table(
    table: TableSpec,
    root: SeededRng,
    n: int | None = None,
    *,
    fk_columns: dict[str, Sequence[Any]] | None = None,
    offset: int = 0,
) -> pa.Table:
    """Generate ``n`` rows of ``table`` as an Arrow table.

    ``fk_columns`` supplies pre-resolved values for foreign-key columns (from the
    cross-table layer); such columns are used verbatim instead of their generator.
    ``offset`` is the global row index of the first row (for chunked/streamed generation).
    """
    rows = n if n is not None else table.row_count
    if rows is None:
        raise ValueError(f"table {table.name!r} has no row_count and no explicit n")
    fk_columns = fk_columns or {}
    unique = table.unique_columns

    arrays: list[pa.Array] = []
    fields: list[pa.Field] = []
    for column in table.columns:
        values = _column_values(table, column, root, rows, offset, fk_columns, unique)
        arrow_type = column.type.to_arrow()
        nullable = _is_nullable(column, unique)
        arrays.append(pa.array(values, type=arrow_type))
        fields.append(pa.field(column.name, arrow_type, nullable=nullable))

    return pa.Table.from_arrays(arrays, schema=pa.schema(fields))


def _column_values(
    table: TableSpec,
    column: ColumnSpec,
    root: SeededRng,
    rows: int,
    offset: int,
    fk_columns: dict[str, Sequence[Any]],
    unique: set[str],
) -> Sequence[Any]:
    if column.name in fk_columns:
        return fk_columns[column.name]

    col_rng = root.derive(table.name, column.name)
    values = list(column.generator.generate(col_rng, rows, offset=offset))

    if column.name in unique and len(set(values)) != len(values):
        raise UniquenessError(
            f"{table.name}.{column.name} requires unique values but the generator produced "
            f"duplicates for {rows} rows — widen the value domain or use a Serial generator."
        )

    if _is_nullable(column, unique) and column.null_rate > 0.0:
        values = _apply_nulls(table, column, root, values)

    return values


def _apply_nulls(
    table: TableSpec, column: ColumnSpec, root: SeededRng, values: list[Any]
) -> list[Any]:
    null_rng = root.derive(table.name, column.name, "__nulls__").numpy()
    draws = null_rng.random(size=len(values))
    return [None if d < column.null_rate else v for d, v in zip(draws, values, strict=True)]


def _is_nullable(column: ColumnSpec, unique: set[str]) -> bool:
    # PK / UNIQUE columns are implicitly NOT NULL.
    return column.nullable and column.name not in unique
