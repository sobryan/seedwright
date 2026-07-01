"""Generator Artifacts (ADR-0003) — the versioned, serializable product of the authoring loop.

The accepted genspec + the derived data-tests + provenance. Executed (not interpreted) by genlib
later to produce Datasets. The version is a deterministic content hash of the genspec (no
wall-clock), so it doubles as a reproducibility/cache identity (FR-E.1). Approval starts PENDING —
FR-L.5 requires human approval before first execution against a real target.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import Any


class ApprovalStatus(Enum):
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"


@dataclass(frozen=True)
class Provenance:
    provider_id: str
    iterations: int
    determinism_gate_passed: bool
    genlib_version: str
    approval_status: ApprovalStatus = ApprovalStatus.PENDING_APPROVAL

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "iterations": self.iterations,
            "determinism_gate_passed": self.determinism_gate_passed,
            "genlib_version": self.genlib_version,
            "approval_status": self.approval_status.value,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Provenance:
        return cls(
            provider_id=data["provider_id"],
            iterations=data["iterations"],
            determinism_gate_passed=data["determinism_gate_passed"],
            genlib_version=data["genlib_version"],
            approval_status=ApprovalStatus(data["approval_status"]),
        )


@dataclass(frozen=True)
class GeneratorArtifacts:
    genspec: dict[str, Any]
    data_tests: tuple[dict[str, Any], ...]
    provenance: Provenance

    @property
    def version(self) -> str:
        payload = json.dumps(self.genspec, sort_keys=True, separators=(",", ":"))
        return "ga_" + hashlib.blake2b(payload.encode("utf-8"), digest_size=8).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "genspec": self.genspec,
            "data_tests": list(self.data_tests),
            "provenance": self.provenance.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GeneratorArtifacts:
        return cls(
            genspec=data["genspec"],
            data_tests=tuple(data["data_tests"]),
            provenance=Provenance.from_dict(data["provenance"]),
        )
