"""Determinism gate (spec §3, FR-L.4).

A generator is accepted only after a double-run check: execute twice with the same seed
and assert byte-identical output. This is the mechanism that turns "should be reproducible"
into an enforced property. A build that sneaks in unseeded randomness is rejected here.
"""

import pyarrow as pa
import pytest

from seedwright_genlib.dataset import generate_dataset
from seedwright_genlib.determinism import DeterminismError, assert_deterministic
from seedwright_genlib.generators import IntRange, Serial
from seedwright_genlib.rng import SeededRng
from seedwright_genlib.schema import ColumnSpec, SchemaSpec, TableSpec
from seedwright_genlib.types import CanonicalType, TypeKind


def _build() -> dict[str, pa.Table]:
    schema = SchemaSpec(
        tables=[
            TableSpec(
                name="t",
                primary_key=["id"],
                row_count=100,
                columns=[
                    ColumnSpec("id", CanonicalType(TypeKind.INT64), Serial()),
                    ColumnSpec("v", CanonicalType(TypeKind.INT32), IntRange(0, 10**6)),
                ],
            )
        ]
    )
    return generate_dataset(schema, SeededRng(42))


def test_deterministic_build_passes_and_returns_tables() -> None:
    tables = assert_deterministic(_build)
    assert tables["t"].num_rows == 100


def test_verified_tables_equal_a_fresh_build() -> None:
    tables = assert_deterministic(_build)
    assert tables["t"].equals(_build()["t"])


def test_nondeterministic_build_is_rejected() -> None:
    state = {"n": 0}

    def bad() -> dict[str, pa.Table]:
        state["n"] += 1
        return {"t": pa.table({"x": [state["n"]]})}

    with pytest.raises(DeterminismError):
        assert_deterministic(bad)


def test_rejection_names_the_offending_table() -> None:
    def bad() -> dict[str, pa.Table]:
        import secrets

        return {"orders": pa.table({"x": [secrets.randbelow(10**9)]})}

    with pytest.raises(DeterminismError, match="orders"):
        assert_deterministic(bad)


def test_key_set_mismatch_is_rejected() -> None:
    state = {"n": 0}

    def bad() -> dict[str, pa.Table]:
        state["n"] += 1
        cols = {"a": pa.table({"x": [1]})}
        if state["n"] == 2:
            cols["b"] = pa.table({"x": [1]})
        return cols

    with pytest.raises(DeterminismError):
        assert_deterministic(bad)
