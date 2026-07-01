"""The judge/critic (spec FR-F.1a): generate a small sample through genlib and evaluate it against
data-tests derived from the schema + declared rules. This is what decides pass/refine in the loop.
"""

import copy

from seedwright_authoring.compile import compile_to_genlib
from seedwright_authoring.datatests import derive_data_tests, judge_sample
from seedwright_authoring.genspec import parse_genspec
from seedwright_authoring.imported import ImportedSchema
from seedwright_authoring.rules import RuleSet

from .golden import GOLDEN_GENSPEC, GOLDEN_IMPORTED, GOLDEN_RULES


def _imported() -> ImportedSchema:
    return ImportedSchema.from_sql_columns(
        GOLDEN_IMPORTED, primary_keys={"customers": ["id"], "orders": ["id"]}
    )


def _rules() -> RuleSet:
    return RuleSet.from_dicts(GOLDEN_RULES)


def test_derive_covers_rule_and_schema_tests() -> None:
    tests = derive_data_tests(parse_genspec(GOLDEN_GENSPEC), _imported(), _rules())
    kinds = {(t.kind, t.table, t.column) for t in tests}
    assert ("value_range", "orders", "total") in kinds
    assert ("enum", "customers", "tier") in kinds
    assert ("fk_resolves", "orders", "customer_id") in kinds


def test_judge_passes_on_valid_golden_sample() -> None:
    gs = parse_genspec(GOLDEN_GENSPEC)
    schema = compile_to_genlib(gs, _imported())
    tests = derive_data_tests(gs, _imported(), _rules())
    result = judge_sample(schema, tests, seed=gs.seed, sample_rows=200)
    assert result.passed, [f.to_dict() for f in result.failures]


def test_judge_flags_value_range_violation() -> None:
    bad = copy.deepcopy(GOLDEN_GENSPEC)
    bad["tables"][1]["columns"][2]["generator"]["params"] = {
        "low": "1.00", "high": "5000.00", "scale": 2,  # rule caps orders.total at 1000
    }
    gs = parse_genspec(bad)
    schema = compile_to_genlib(gs, _imported())
    tests = derive_data_tests(gs, _imported(), _rules())
    result = judge_sample(schema, tests, seed=gs.seed, sample_rows=200)
    assert not result.passed
    offenders = [f for f in result.failures if f.category == "constraint" and f.column == "total"]
    assert offenders and offenders[0].feedback


def test_judge_converts_generation_error_to_failure() -> None:
    bad = copy.deepcopy(GOLDEN_GENSPEC)
    # tier: unique over only 3 categorical values. Validation passes (authored row_count 3), but
    # the sample overrides to 200 rows -> genlib raises UniquenessError, which the judge catches.
    bad["tables"][0]["row_count"] = 3
    bad["tables"][0]["columns"][2]["unique"] = True
    gs = parse_genspec(bad)
    schema = compile_to_genlib(gs, _imported())
    tests = derive_data_tests(gs, _imported(), _rules())
    result = judge_sample(schema, tests, seed=gs.seed, sample_rows=200)
    assert not result.passed
    assert any(f.category == "generation" for f in result.failures)
