"""Generator Spec parsing + round-trip (ADR-0003 frozen schema)."""

import copy

import pytest

from seedwright_authoring.genspec import GenSpecParseError, parse_genspec

from .golden import GOLDEN_GENSPEC


def test_parse_then_to_dict_is_stable_round_trip() -> None:
    spec = parse_genspec(GOLDEN_GENSPEC)
    assert spec.to_dict() == GOLDEN_GENSPEC


def test_parse_reads_structure() -> None:
    spec = parse_genspec(GOLDEN_GENSPEC)
    assert spec.seed == 42
    customers = spec.table("customers")
    assert customers.row_count == 200
    balance = next(c for c in customers.columns if c.name == "balance")
    assert balance.generator.kind == "decimal_range"
    assert balance.generator.params == {"low": "0.00", "high": "1000.00", "scale": 2}
    assert balance.null_rate == 0.1


def test_driving_fk_child_has_null_row_count_and_fk_sentinel() -> None:
    spec = parse_genspec(GOLDEN_GENSPEC)
    orders = spec.table("orders")
    assert orders.row_count is None
    assert orders.foreign_keys[0].max_per_parent == 10
    fk_col = next(c for c in orders.columns if c.name == "customer_id")
    assert fk_col.generator.kind == "fk"


def test_missing_tables_raises() -> None:
    with pytest.raises(GenSpecParseError):
        parse_genspec({"genspec_version": "1", "seed": 1})


def test_missing_canonical_kind_raises() -> None:
    bad = copy.deepcopy(GOLDEN_GENSPEC)
    del bad["tables"][0]["columns"][0]["canonical_kind"]
    with pytest.raises(GenSpecParseError):
        parse_genspec(bad)


def test_missing_generator_kind_raises() -> None:
    bad = copy.deepcopy(GOLDEN_GENSPEC)
    del bad["tables"][0]["columns"][0]["generator"]["kind"]
    with pytest.raises(GenSpecParseError):
        parse_genspec(bad)


def test_unknown_table_lookup_raises() -> None:
    with pytest.raises(KeyError):
        parse_genspec(GOLDEN_GENSPEC).table("nope")
