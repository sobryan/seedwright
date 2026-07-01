"""Provider capability floor (spec FR-H.7).

The one capability the authoring loop hard-requires: structured JSON output. Checked once at
loop entry so an incapable provider fails fast and explicitly, rather than the loop silently
degrading. Richer capability negotiation (tool-use, constrained decoding, per-provider envelope
normalization) is deferred until real adapters land.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Capabilities:
    structured_json_output: bool


class CapabilityFloorError(RuntimeError):
    """The provider does not meet the authoring loop's minimum capability floor."""


def enforce_capability_floor(capabilities: Capabilities) -> None:
    if not capabilities.structured_json_output:
        raise CapabilityFloorError(
            "authoring requires a provider that can emit structured JSON output"
        )
