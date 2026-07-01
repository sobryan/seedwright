"""The single shared refine-feedback record (ADR-0003).

Static validation issues and judge data-test failures both convert to ``Failure``. This one
type crosses the judge -> loop -> provider seam unchanged, so the evaluator-optimizer loop has a
uniform signal to feed back to the authoring model.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Failure categories: validation (static genspec), structural / constraint / referential /
# null_rate / leakage / uniqueness (judge data-tests), generation (genlib raised at sample).
Category = str


@dataclass(frozen=True)
class Failure:
    category: Category
    table: str
    column: str | None
    test_id: str
    detail: str
    feedback: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "table": self.table,
            "column": self.column,
            "test_id": self.test_id,
            "detail": self.detail,
            "feedback": self.feedback,
        }
