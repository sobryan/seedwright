"""Declared intent (RuleSet) — the judge derives constraint tests from these, never from the
generator's own params (ADR-0003), so a data-test can't check a generator against itself.
"""

from seedwright_authoring.rules import RuleSet

from .golden import GOLDEN_RULES


def test_from_dicts_reads_enum_and_range() -> None:
    rs = RuleSet.from_dicts(GOLDEN_RULES)
    tier = rs.rule("customers", "tier")
    assert tier.enum == ("free", "pro", "enterprise")
    total = rs.rule("orders", "total")
    assert (total.min_value, total.max_value) == ("1.00", "1000.00")


def test_missing_rule_lookup_returns_none() -> None:
    assert RuleSet.from_dicts(GOLDEN_RULES).find("customers", "nope") is None
