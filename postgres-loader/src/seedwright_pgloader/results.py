"""Loader result records (spec FR-G, FR-F.1c).

Structured, JSON-serializable outcomes: what landed in which namespace, per-table row counts,
teardown outcome, and materialization verification (expected vs actual rows). These are the
machine-readable results a CI/CD caller consumes and the shape the MCP contract returns.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TableLoadResult:
    name: str
    rows_loaded: int

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "rows_loaded": self.rows_loaded}


@dataclass(frozen=True)
class LoadResult:
    namespace: str
    mode: str
    tables: tuple[TableLoadResult, ...]

    @property
    def total_rows(self) -> int:
        return sum(t.rows_loaded for t in self.tables)

    def to_dict(self) -> dict[str, Any]:
        return {
            "namespace": self.namespace,
            "mode": self.mode,
            "total_rows": self.total_rows,
            "tables": [t.to_dict() for t in self.tables],
        }


@dataclass(frozen=True)
class TeardownResult:
    namespace: str
    existed: bool

    def to_dict(self) -> dict[str, Any]:
        return {"namespace": self.namespace, "existed": self.existed}


@dataclass(frozen=True)
class TableVerification:
    name: str
    expected_rows: int
    actual_rows: int

    @property
    def ok(self) -> bool:
        return self.expected_rows == self.actual_rows

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "expected_rows": self.expected_rows,
            "actual_rows": self.actual_rows,
            "ok": self.ok,
        }


@dataclass(frozen=True)
class VerificationResult:
    namespace: str
    tables: tuple[TableVerification, ...]

    @property
    def ok(self) -> bool:
        return all(t.ok for t in self.tables)

    @property
    def mismatches(self) -> tuple[str, ...]:
        return tuple(
            f"{t.name}: expected {t.expected_rows}, got {t.actual_rows}"
            for t in self.tables
            if not t.ok
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "namespace": self.namespace,
            "ok": self.ok,
            "tables": [t.to_dict() for t in self.tables],
            "mismatches": list(self.mismatches),
        }
