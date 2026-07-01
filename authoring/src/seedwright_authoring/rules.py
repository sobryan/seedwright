"""Declared intent — user-authored generation rules (a minimal slice of FR-C for MVP).

The judge derives value-range / enum / null-rate data-tests from these, kept deliberately
separate from the genspec's generator params so a test never checks a generator against itself.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ColumnRule:
    table: str
    column: str
    min_value: str | None = None   # numeric bounds carried as strings (money-safe)
    max_value: str | None = None
    enum: tuple[Any, ...] | None = None
    max_null_rate: float | None = None


@dataclass(frozen=True)
class RuleSet:
    rules: tuple[ColumnRule, ...]

    def find(self, table: str, column: str) -> ColumnRule | None:
        for rule in self.rules:
            if rule.table == table and rule.column == column:
                return rule
        return None

    def rule(self, table: str, column: str) -> ColumnRule:
        found = self.find(table, column)
        if found is None:
            raise KeyError(f"no rule for {table}.{column}")
        return found

    @classmethod
    def from_dicts(cls, dicts: Sequence[Mapping[str, Any]]) -> RuleSet:
        rules = tuple(
            ColumnRule(
                table=d["table"],
                column=d["column"],
                min_value=_opt_str(d.get("min_value")),
                max_value=_opt_str(d.get("max_value")),
                enum=tuple(d["enum"]) if d.get("enum") is not None else None,
                max_null_rate=d.get("max_null_rate"),
            )
            for d in dicts
        )
        return cls(rules=rules)


def _opt_str(value: Any) -> str | None:
    return None if value is None else str(value)
