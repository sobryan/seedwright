"""The evaluator-optimizer authoring loop (spec §3A, FR-E.1, FR-H.7) — end-to-end, offline.

Proves happy-path, refine-then-pass (both from a judge failure and a static validation failure),
explicit failure on exhaustion, the capability floor, reproducibility, and the cross-facet contract
(judge failures feed the provider's refine unchanged). All with a scripted mock — no LLM, no cost.
"""

import copy

import pytest

from seedwright_authoring.artifacts import ApprovalStatus
from seedwright_authoring.capability import CapabilityFloorError
from seedwright_authoring.imported import ImportedSchema
from seedwright_authoring.loop import AuthoringFailed, author
from seedwright_authoring.provider import ScriptedMockProvider
from seedwright_authoring.rules import RuleSet

from .golden import GOLDEN_GENSPEC, GOLDEN_IMPORTED, GOLDEN_RULES


def _imported() -> ImportedSchema:
    return ImportedSchema.from_sql_columns(
        GOLDEN_IMPORTED, primary_keys={"customers": ["id"], "orders": ["id"]}
    )


def _rules() -> RuleSet:
    return RuleSet.from_dicts(GOLDEN_RULES)


def _bad_range() -> dict:
    bad = copy.deepcopy(GOLDEN_GENSPEC)
    bad["tables"][1]["columns"][2]["generator"]["params"] = {
        "low": "1.00", "high": "5000.00", "scale": 2,  # violates orders.total <= 1000 rule
    }
    return bad


def _invalid_kind() -> dict:
    bad = copy.deepcopy(GOLDEN_GENSPEC)
    bad["tables"][0]["columns"][3]["canonical_kind"] = "INT64"  # balance is DECIMAL: mismatch
    return bad


def test_happy_path_one_iteration() -> None:
    provider = ScriptedMockProvider([GOLDEN_GENSPEC])
    artifacts = author(_imported(), _rules(), provider)
    assert artifacts.provenance.iterations == 1
    assert artifacts.provenance.determinism_gate_passed is True
    assert artifacts.provenance.approval_status is ApprovalStatus.PENDING_APPROVAL
    assert artifacts.version.startswith("ga_")


def test_refines_after_a_judge_failure_then_passes() -> None:
    provider = ScriptedMockProvider([_bad_range(), GOLDEN_GENSPEC])
    artifacts = author(_imported(), _rules(), provider)
    assert artifacts.provenance.iterations == 2
    # cross-facet contract: the refine request carried the judge's failures + the prior genspec
    assert provider.last_request is not None
    assert provider.last_request.prior_genspec == _bad_range()
    assert any(f.column == "total" for f in provider.last_request.feedback)


def test_refines_after_a_static_validation_failure() -> None:
    provider = ScriptedMockProvider([_invalid_kind(), GOLDEN_GENSPEC])
    artifacts = author(_imported(), _rules(), provider)
    assert artifacts.provenance.iterations == 2
    assert any(f.test_id.startswith("KIND_MISMATCH") for f in provider.last_request.feedback)


def test_exhaustion_raises_with_transcript_and_no_artifact() -> None:
    provider = ScriptedMockProvider([_bad_range()])  # always bad
    with pytest.raises(AuthoringFailed) as exc:
        author(_imported(), _rules(), provider, max_iters=3)
    assert exc.value.failures
    assert len(exc.value.transcript) == 3


def test_capability_floor_fails_before_any_propose() -> None:
    provider = ScriptedMockProvider([GOLDEN_GENSPEC], structured=False)
    with pytest.raises(CapabilityFloorError):
        author(_imported(), _rules(), provider)
    assert provider.last_request is None  # never called propose


def test_max_iters_below_one_is_rejected() -> None:
    provider = ScriptedMockProvider([GOLDEN_GENSPEC])
    with pytest.raises(ValueError):
        author(_imported(), _rules(), provider, max_iters=0)
    assert provider.last_request is None


def test_author_is_reproducible() -> None:
    a = author(_imported(), _rules(), ScriptedMockProvider([GOLDEN_GENSPEC]))
    b = author(_imported(), _rules(), ScriptedMockProvider([GOLDEN_GENSPEC]))
    assert a.to_dict() == b.to_dict()
