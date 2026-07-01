"""Compile genspec -> genlib SchemaSpec, and the integration checkpoint (ADR-0003).

The checkpoint is the payoff of the whole compile path: a compiled artifact runs through genlib's
real generate_dataset AND passes the determinism gate — proving the model's declarative choices
become a deterministic, referentially-valid generator by construction.
"""

import copy

import pytest
from seedwright_genlib.dataset import generate_dataset
from seedwright_genlib.determinism import assert_deterministic
from seedwright_genlib.rng import SeededRng
from seedwright_genlib.types import TypeKind

from seedwright_authoring.catalog import build_generator
from seedwright_authoring.compile import GenSpecValidationError, compile_to_genlib
from seedwright_authoring.genspec import parse_genspec
from seedwright_authoring.imported import ImportedSchema

from .golden import GOLDEN_GENSPEC, GOLDEN_IMPORTED


def _imported() -> ImportedSchema:
    return ImportedSchema.from_sql_columns(
        GOLDEN_IMPORTED, primary_keys={"customers": ["id"], "orders": ["id"]}
    )


def test_compile_uses_authoritative_types_from_imported_schema() -> None:
    schema = compile_to_genlib(parse_genspec(GOLDEN_GENSPEC), _imported())
    customers = schema.table("customers")
    balance = customers.column("balance")
    # type comes from imported numeric(12,2), NOT the model's assertion
    assert balance.type.kind is TypeKind.DECIMAL
    assert (balance.type.precision, balance.type.scale) == (12, 2)


def test_compile_maps_fk_child_and_placeholder() -> None:
    schema = compile_to_genlib(parse_genspec(GOLDEN_GENSPEC), _imported())
    orders = schema.table("orders")
    assert orders.row_count is None
    assert orders.column("customer_id").generator is build_generator("fk", {})


def test_compile_raises_with_issues_on_invalid_genspec() -> None:
    bad = copy.deepcopy(GOLDEN_GENSPEC)
    bad["tables"][0]["columns"][3]["canonical_kind"] = "INT64"  # lie: balance is DECIMAL
    with pytest.raises(GenSpecValidationError) as exc:
        compile_to_genlib(parse_genspec(bad), _imported())
    assert any(f.test_id.startswith("KIND_MISMATCH") for f in exc.value.issues)


def test_integration_checkpoint_deterministic_and_referentially_valid() -> None:
    genspec = parse_genspec(GOLDEN_GENSPEC)
    schema = compile_to_genlib(genspec, _imported())

    tables = assert_deterministic(lambda: generate_dataset(schema, SeededRng(genspec.seed)))

    assert tables["customers"].num_rows == 200
    n_orders = tables["orders"].num_rows
    assert 0 <= n_orders <= 200 * 10  # cardinality bound
    parent_ids = set(tables["customers"].column("id").to_pylist())
    assert set(tables["orders"].column("customer_id").to_pylist()) <= parent_ids
