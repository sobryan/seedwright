"""Cross-table generation (spec FR-A.3, FR-E.3, FR-O.1).

Generates a whole schema's tables in FK-topological order so a parent's primary keys exist
before its children reference them. Foreign keys are resolved two ways:

- **into a generated parent** — the *driving* FK: each parent key is expanded by a sampled
  per-parent cardinality (min..max), which derives the child table's row count. This models
  "each customer has 0-20 orders".
- **into a reference table or a second generated parent** — sampled from that table's key
  pool at the child's row count (reference pools are supplied by the caller; FR-O.1).

Every emitted FK value therefore resolves to a real parent key. Cycles are detected and
raised (self-referential/circular FK break strategies are future work, FR-A.3).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np
import pyarrow as pa

from .generate import generate_table
from .rng import SeededRng
from .schema import ForeignKeySpec, SchemaSpec, TableClass, TableSpec


class CycleError(ValueError):
    """The FK dependency graph among generated tables contains a cycle (spec FR-A.3)."""


def topological_order(schema: SchemaSpec) -> list[str]:
    """Order generated tables so every table follows the generated parents it references.

    Reference/excluded tables are omitted. FKs into non-generated tables impose no order.
    Raises ``CycleError`` if generated tables are mutually dependent.
    """
    generated = [t.name for t in schema.tables if t.table_class is TableClass.GENERATED]
    generated_set = set(generated)

    deps: dict[str, set[str]] = {name: set() for name in generated}
    for table in schema.tables:
        if table.table_class is not TableClass.GENERATED:
            continue
        for fk in table.foreign_keys:
            if fk.references_table in generated_set and fk.references_table != table.name:
                deps[table.name].add(fk.references_table)

    order: list[str] = []
    resolved: set[str] = set()
    remaining = list(generated)
    while remaining:
        ready = [name for name in remaining if deps[name] <= resolved]
        if not ready:
            raise CycleError(f"FK cycle among generated tables: {remaining}")
        for name in ready:
            order.append(name)
            resolved.add(name)
            remaining.remove(name)
    return order


def generate_dataset(
    schema: SchemaSpec,
    root: SeededRng,
    *,
    row_counts: dict[str, int] | None = None,
    reference_pools: dict[str, Sequence[Any]] | None = None,
) -> dict[str, pa.Table]:
    """Generate every generated table in ``schema`` as a dict of ``name -> Arrow table``."""
    row_counts = row_counts or {}
    reference_pools = reference_pools or {}
    generated_set = {t.name for t in schema.tables if t.table_class is TableClass.GENERATED}

    key_pools: dict[str, Sequence[Any]] = dict(reference_pools)
    results: dict[str, pa.Table] = {}

    for name in topological_order(schema):
        table = schema.table(name)
        driving = _driving_fk(table, generated_set)
        fk_columns: dict[str, Sequence[Any]] = {}

        if driving is not None:
            parent_keys = key_pools[driving.references_table]
            fk_values = _expand_by_cardinality(table, driving, parent_keys, root)
            n = len(fk_values)
            fk_columns[driving.column] = fk_values
        else:
            resolved = row_counts.get(name, table.row_count)
            if resolved is None:
                raise ValueError(f"table {name!r} has no driving FK and no row_count")
            n = resolved

        for fk in table.foreign_keys:
            if fk is driving:
                continue
            pool = key_pools.get(fk.references_table)
            if pool is None:
                raise ValueError(
                    f"{name}.{fk.column} references {fk.references_table!r} but no key pool is "
                    "available (supply reference_pools for reference tables)"
                )
            fk_columns[fk.column] = _sample_pool(table, fk, pool, n, root)

        result = generate_table(table, root, n=n, fk_columns=fk_columns)
        results[name] = result
        if table.primary_key:
            key_pools[name] = result.column(table.primary_key[0]).to_pylist()

    return results


def _driving_fk(table: TableSpec, generated_set: set[str]) -> ForeignKeySpec | None:
    for fk in table.foreign_keys:
        if fk.references_table in generated_set and fk.references_table != table.name:
            return fk
    return None


def _expand_by_cardinality(
    table: TableSpec, fk: ForeignKeySpec, parent_keys: Sequence[Any], root: SeededRng
) -> list[Any]:
    rng = root.derive(table.name, "__cardinality__", fk.column).numpy()
    counts = rng.integers(fk.min_per_parent, fk.max_per_parent + 1, size=len(parent_keys))
    expanded = np.repeat(np.asarray(parent_keys), counts)
    return list(expanded.tolist())


def _sample_pool(
    table: TableSpec, fk: ForeignKeySpec, pool: Sequence[Any], n: int, root: SeededRng
) -> list[Any]:
    rng = root.derive(table.name, "__fk_sample__", fk.column).numpy()
    idx = rng.integers(0, len(pool), size=n)
    return [pool[i] for i in idx]
