"""Hardening from the Slice-3 adversarial review: malformed model output must become refine
feedback (AuthoringFailed on exhaustion), never a raw crash. The scripted-mock tests couldn't
catch these because the mock only emits well-formed genspecs; here we feed deliberately broken ones.
"""

import copy
from collections.abc import Callable

import pytest

from seedwright_authoring.compile import compile_to_genlib
from seedwright_authoring.genspec import GenSpecParseError, parse_genspec
from seedwright_authoring.imported import ImportedSchema
from seedwright_authoring.loop import AuthoringFailed, author
from seedwright_authoring.provider import ScriptedMockProvider
from seedwright_authoring.rules import RuleSet
from seedwright_authoring.validate import validate_genspec

from .golden import GOLDEN_GENSPEC, GOLDEN_IMPORTED, GOLDEN_RULES


def _imported() -> ImportedSchema:
    return ImportedSchema.from_sql_columns(
        GOLDEN_IMPORTED, primary_keys={"customers": ["id"], "orders": ["id"]}
    )


def _rules() -> RuleSet:
    return RuleSet.from_dicts(GOLDEN_RULES)


def _mutate(fn: Callable[[dict], None]) -> dict:
    g = copy.deepcopy(GOLDEN_GENSPEC)
    fn(g)
    return g


def _decimal_low_gt_high(g: dict) -> None:
    g["tables"][0]["columns"][3]["generator"]["params"] = {
        "low": "1000.00", "high": "0.00", "scale": 2}


def _missing_scale(g: dict) -> None:
    g["tables"][0]["columns"][3]["generator"]["params"] = {"low": "0.00", "high": "10.00"}


def _empty_categorical(g: dict) -> None:
    g["tables"][0]["columns"][2]["generator"]["params"] = {"values": []}


def _null_rate_out_of_range(g: dict) -> None:
    g["tables"][0]["columns"][3]["null_rate"] = 1.5


def _unknown_table_class(g: dict) -> None:
    g["tables"][0]["table_class"] = "lookup"


def _negative_row_count(g: dict) -> None:
    g["tables"][0]["row_count"] = -5


def _driving_parent_without_pk(g: dict) -> None:
    g["tables"][0]["primary_key"] = []  # customers is the FK parent of orders


def _scale_mismatch(g: dict) -> None:
    g["tables"][0]["columns"][3]["generator"]["params"] = {
        "low": "0.0000", "high": "1.0000", "scale": 4}


MALFORMED = [
    _decimal_low_gt_high, _missing_scale, _empty_categorical, _null_rate_out_of_range,
    _unknown_table_class, _negative_row_count, _driving_parent_without_pk, _scale_mismatch,
]


@pytest.mark.parametrize("mutate", MALFORMED, ids=[f.__name__ for f in MALFORMED])
def test_malformed_genspec_refines_not_crashes(mutate: Callable[[dict], None]) -> None:
    provider = ScriptedMockProvider([_mutate(mutate)])  # always malformed -> must exhaust cleanly
    with pytest.raises(AuthoringFailed):
        author(_imported(), _rules(), provider, max_iters=2)


def _set_bad_null_rate(g: dict) -> None:
    g["tables"][0]["columns"][3]["null_rate"] = "abc"


def test_bad_scalar_type_is_a_parse_error() -> None:
    with pytest.raises(GenSpecParseError):
        parse_genspec(_mutate(_set_bad_null_rate))


def test_table_class_is_normalized_to_lowercase() -> None:
    spec = parse_genspec(_mutate(lambda g: g["tables"][0].__setitem__("table_class", "GENERATED")))
    assert spec.table("customers").table_class == "generated"


def _codes(mutate: Callable[[dict], None]) -> set[str]:
    issues = validate_genspec(parse_genspec(_mutate(mutate)), _imported())
    return {f.test_id.split(":")[0] for f in issues}


def test_validate_flags_specific_param_issues() -> None:
    assert "RANGE_INVALID" in _codes(_decimal_low_gt_high)
    assert "GENERATOR_PARAMS" in _codes(_missing_scale)
    assert "GENERATOR_PARAMS" in _codes(_empty_categorical)
    assert "NULL_RATE_INVALID" in _codes(_null_rate_out_of_range)
    assert "TABLE_CLASS_UNKNOWN" in _codes(_unknown_table_class)
    assert "ROWCOUNT_INVALID" in _codes(_negative_row_count)
    assert "FK_PARENT_NO_PK" in _codes(_driving_parent_without_pk)
    assert "SCALE_MISMATCH" in _codes(_scale_mismatch)


def test_null_rate_zero_rule_is_strict_no_slack() -> None:
    # a max_null_rate=0.0 rule must not be satisfied by ~5% nulls (no slack at a hard zero bound)
    from seedwright_authoring.datatests import derive_data_tests, judge_sample

    rules = RuleSet.from_dicts([{"table": "customers", "column": "balance", "max_null_rate": 0.0}])
    gs = parse_genspec(GOLDEN_GENSPEC)  # balance has null_rate 0.1
    schema = compile_to_genlib(gs, _imported())
    tests = derive_data_tests(gs, _imported(), rules)
    result = judge_sample(schema, tests, seed=gs.seed, sample_rows=200)
    assert not result.passed
    assert any(f.category == "null_rate" for f in result.failures)
