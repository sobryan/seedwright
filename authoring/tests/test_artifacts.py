"""Generator Artifacts (ADR-0003) — the versioned, serializable output of the loop.

Provenance defaults to PENDING_APPROVAL (FR-L.5: human approval before first real execution). The
version is a deterministic content hash (no wall-clock), so identical inputs yield identical
artifacts — the cache/reproducibility identity for FR-E.1.
"""

import copy

from seedwright_authoring.artifacts import ApprovalStatus, GeneratorArtifacts, Provenance

from .golden import GOLDEN_GENSPEC


def _artifacts() -> GeneratorArtifacts:
    return GeneratorArtifacts(
        genspec=GOLDEN_GENSPEC,
        data_tests=({"kind": "value_range", "table": "orders", "column": "total", "params": {}},),
        provenance=Provenance(
            provider_id="scripted-mock", iterations=2,
            determinism_gate_passed=True, genlib_version="0.0.1",
        ),
    )


def test_approval_status_defaults_to_pending() -> None:
    assert _artifacts().provenance.approval_status is ApprovalStatus.PENDING_APPROVAL


def test_version_is_deterministic_and_prefixed() -> None:
    assert _artifacts().version == _artifacts().version
    assert _artifacts().version.startswith("ga_")


def test_version_changes_with_genspec() -> None:
    base = _artifacts()
    changed_spec = copy.deepcopy(GOLDEN_GENSPEC)
    changed_spec["seed"] = 999
    changed = GeneratorArtifacts(changed_spec, base.data_tests, base.provenance)
    assert base.version != changed.version


def test_to_dict_from_dict_round_trip() -> None:
    original = _artifacts()
    restored = GeneratorArtifacts.from_dict(original.to_dict())
    assert restored.to_dict() == original.to_dict()
    assert restored.provenance.approval_status is ApprovalStatus.PENDING_APPROVAL


def test_to_dict_is_stable_no_wall_clock() -> None:
    assert _artifacts().to_dict() == _artifacts().to_dict()
