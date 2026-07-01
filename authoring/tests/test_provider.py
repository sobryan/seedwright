"""Provider abstraction + scripted mock + capability floor (ADR-0003, FR-H.7, NFR-TEST).

The scripted mock returns a fixed sequence of genspecs (deterministic, no LLM) so the loop's
happy/refine/exhaust paths are testable offline. The capability floor is the one FR-H.7 check at
loop entry: a provider that can't emit structured JSON fails fast, before any propose call.
"""

import pytest

from seedwright_authoring.capability import (
    Capabilities,
    CapabilityFloorError,
    enforce_capability_floor,
)
from seedwright_authoring.imported import ImportedSchema
from seedwright_authoring.provider import ProposeRequest, ScriptedMockProvider
from seedwright_authoring.rules import RuleSet


def _req() -> ProposeRequest:
    return ProposeRequest(ImportedSchema(()), RuleSet(()), prior_genspec=None, feedback=())


def test_capability_floor_passes_with_structured_output() -> None:
    enforce_capability_floor(Capabilities(structured_json_output=True))  # no raise


def test_capability_floor_raises_without_structured_output() -> None:
    with pytest.raises(CapabilityFloorError):
        enforce_capability_floor(Capabilities(structured_json_output=False))


def test_scripted_mock_returns_genspecs_in_sequence_then_sticks() -> None:
    provider = ScriptedMockProvider([{"a": 1}, {"b": 2}])
    assert provider.propose(_req()).genspec == {"a": 1}
    assert provider.propose(_req()).genspec == {"b": 2}
    assert provider.propose(_req()).genspec == {"b": 2}  # exhausted -> repeats the last


def test_scripted_mock_records_last_request_for_refine_inspection() -> None:
    provider = ScriptedMockProvider([{"a": 1}])
    req = ProposeRequest(ImportedSchema(()), RuleSet(()), prior_genspec={"p": 1}, feedback=())
    provider.propose(req)
    assert provider.last_request is req


def test_scripted_mock_capabilities() -> None:
    assert ScriptedMockProvider([{}]).capabilities().structured_json_output is True
    incapable = ScriptedMockProvider([{}], structured=False)
    assert incapable.capabilities().structured_json_output is False
