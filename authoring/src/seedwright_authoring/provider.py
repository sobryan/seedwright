"""Provider abstraction + scripted mock (spec FR-H.7, NFR-TEST).

A ``Provider`` proposes a genspec (as a JSON dict) given the schema, rules, and — on refine —
the prior genspec plus the failures to fix. Real Anthropic/OpenAI/Gemini/local adapters slot in
behind this same protocol later (each normalizing its structured-output envelope to a dict). MVP
ships only the deterministic ``ScriptedMockProvider`` so the loop runs offline with no API cost.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from .capability import Capabilities
from .feedback import Failure
from .imported import ImportedSchema
from .rules import RuleSet


@dataclass(frozen=True)
class ProposeRequest:
    imported: ImportedSchema
    rules: RuleSet
    prior_genspec: dict[str, Any] | None
    feedback: tuple[Failure, ...]


@dataclass(frozen=True)
class ProposeResponse:
    genspec: dict[str, Any]


@runtime_checkable
class Provider(Protocol):
    provider_id: str

    def capabilities(self) -> Capabilities: ...

    def propose(self, request: ProposeRequest) -> ProposeResponse: ...


class ScriptedMockProvider:
    """Returns a fixed sequence of genspec dicts; sticks on the last once exhausted."""

    provider_id = "scripted-mock"

    def __init__(self, genspecs: Sequence[dict[str, Any]], *, structured: bool = True) -> None:
        if not genspecs:
            raise ValueError("ScriptedMockProvider needs at least one genspec")
        self._genspecs = list(genspecs)
        self._index = 0
        self._structured = structured
        self.last_request: ProposeRequest | None = None

    def capabilities(self) -> Capabilities:
        return Capabilities(structured_json_output=self._structured)

    def propose(self, request: ProposeRequest) -> ProposeResponse:
        self.last_request = request
        genspec = self._genspecs[min(self._index, len(self._genspecs) - 1)]
        self._index += 1
        return ProposeResponse(genspec=genspec)
