"""Determinism gate (spec §3, FR-L.4).

Execute a build twice and assert identical output. Generators are pure functions of
(schema, rules, seed); anything that reaches for the wall clock or unseeded randomness is
caught here and rejected before it can produce an irreproducible Dataset.
"""

from __future__ import annotations

from collections.abc import Callable

import pyarrow as pa


class DeterminismError(AssertionError):
    """A build produced different output across two same-seed runs (spec FR-L.4)."""


def assert_deterministic(build: Callable[[], dict[str, pa.Table]]) -> dict[str, pa.Table]:
    """Run ``build`` twice, assert the two results are identical, and return the verified one.

    Raises :class:`DeterminismError` if the table sets differ or any table's contents differ.
    """
    first = build()
    second = build()

    if first.keys() != second.keys():
        raise DeterminismError(
            f"table set differs across runs: {sorted(first)} vs {sorted(second)}"
        )

    for name, table in first.items():
        if not table.equals(second[name]):
            raise DeterminismError(
                f"table {name!r} is not reproducible: two same-seed runs produced different data"
            )
    return first
