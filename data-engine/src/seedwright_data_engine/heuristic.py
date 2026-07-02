"""HeuristicProvider — a deterministic, rule-driven authoring provider (no LLM).

Implements the authoring loop's ``Provider`` protocol with pure heuristics: integer PKs get
``serial``, declared FK columns get the ``fk`` sentinel, decimals get ``decimal_range`` at the
column's authoritative scale with rule-declared bounds, enum rules become ``categorical``, and
strings pick a Faker method by column-name hint. Deterministic and offline — it makes the
on-prem product work end-to-end with zero LLM keys; a real LLM adapter replaces it behind the
same protocol without touching anything else (FR-H.7 / NFR-AGNOSTIC).

Columns whose canonical kind has no MVP generator (float/date/time/timestamp/bytes) raise a
clear error at propose time — explicit failure beats burning refine iterations on the
unfixable (the same fail-fast stance as the loop's preconditions).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from seedwright_authoring.capability import Capabilities
from seedwright_authoring.imported import ImportedColumn, ImportedTable
from seedwright_authoring.provider import ProposeRequest, ProposeResponse
from seedwright_authoring.rules import ColumnRule
from seedwright_genlib.types import TypeKind

DEFAULT_ROW_COUNT = 100

_INT_KINDS = {TypeKind.INT16: 32_767, TypeKind.INT32: 1_000_000, TypeKind.INT64: 1_000_000}

_FAKER_HINTS: list[tuple[str, str]] = [
    ("email", "email"),
    ("first_name", "first_name"),
    ("last_name", "last_name"),
    ("full_name", "name"),
    ("name", "name"),
    ("phone", "phone_number"),
    ("address", "address"),
    ("city", "city"),
    ("country", "country"),
    ("company", "company"),
    ("url", "url"),
    ("username", "user_name"),
    ("description", "sentence"),
    ("note", "sentence"),
    ("comment", "sentence"),
]


class UnsupportedColumnError(ValueError):
    """A column's canonical kind has no MVP generator — surfaced explicitly (FR-H.7)."""


class HeuristicProvider:
    """Deterministic genspec proposer. FK topology and volumes are task inputs, not guesses."""

    provider_id = "heuristic"

    def __init__(
        self,
        *,
        foreign_keys: dict[str, list[dict[str, Any]]] | None = None,
        volumes: dict[str, int] | None = None,
        seed: int = 42,
    ) -> None:
        self._foreign_keys = foreign_keys or {}
        self._volumes = volumes or {}
        self._seed = seed

    def capabilities(self) -> Capabilities:
        return Capabilities(structured_json_output=True)

    def propose(self, request: ProposeRequest) -> ProposeResponse:
        table_names = {t.name for t in request.imported.tables}
        tables = [
            self._table(table, request, table_names) for table in request.imported.tables
        ]
        return ProposeResponse(
            genspec={"genspec_version": "1", "seed": self._seed, "tables": tables}
        )

    def _table(
        self, table: ImportedTable, request: ProposeRequest, all_tables: set[str]
    ) -> dict[str, Any]:
        fks = [fk for fk in self._foreign_keys.get(table.name, [])]
        fk_columns = {fk["column"] for fk in fks}
        driving = any(fk["references_table"] in all_tables for fk in fks)
        columns = [
            self._column(table, col, request, fk_columns) for col in table.columns
        ]
        return {
            "name": table.name,
            "table_class": "generated",
            "row_count": None if driving else self._volumes.get(table.name, DEFAULT_ROW_COUNT),
            "primary_key": list(table.primary_key),
            "foreign_keys": fks,
            "columns": columns,
        }

    def _column(
        self,
        table: ImportedTable,
        col: ImportedColumn,
        request: ProposeRequest,
        fk_columns: set[str],
    ) -> dict[str, Any]:
        rule = request.rules.find(table.name, col.name)
        generator = self._generator(table, col, rule, fk_columns)
        return {
            "name": col.name,
            "canonical_kind": col.type.kind.name,
            "generator": generator,
            "nullable": False,
            "null_rate": 0.0,
            "unique": col.name in table.primary_key,
        }

    def _generator(
        self,
        table: ImportedTable,
        col: ImportedColumn,
        rule: ColumnRule | None,
        fk_columns: set[str],
    ) -> dict[str, Any]:
        kind = col.type.kind
        if col.name in fk_columns:
            return {"kind": "fk", "params": {}}
        if kind in _INT_KINDS:
            if col.name in table.primary_key:
                return {"kind": "serial", "params": {"start": 1}}
            low = int(Decimal(rule.min_value)) if rule and rule.min_value else 0
            high = int(Decimal(rule.max_value)) if rule and rule.max_value else _INT_KINDS[kind]
            return {"kind": "int_range", "params": {"low": low, "high": high}}
        if kind is TypeKind.DECIMAL:
            scale = col.type.scale if col.type.scale is not None else 2
            dec_low = rule.min_value if rule and rule.min_value else "0.00"
            dec_high = rule.max_value if rule and rule.max_value else "10000.00"
            return {
                "kind": "decimal_range",
                "params": {"low": dec_low, "high": dec_high, "scale": scale},
            }
        if kind is TypeKind.BOOLEAN:
            return {"kind": "categorical", "params": {"values": [True, False]}}
        if kind is TypeKind.STRING:
            if rule and rule.enum:
                return {"kind": "categorical", "params": {"values": list(rule.enum)}}
            return {"kind": "faker", "params": {"method": self._faker_method(col.name)}}
        if kind is TypeKind.UUID:
            return {"kind": "faker", "params": {"method": "uuid4"}}
        if kind is TypeKind.JSON:
            return {"kind": "faker", "params": {"method": "json"}}
        raise UnsupportedColumnError(
            f"{table.name}.{col.name}: canonical kind {kind.name} has no MVP generator yet"
        )

    @staticmethod
    def _faker_method(column_name: str) -> str:
        lowered = column_name.lower()
        for hint, method in _FAKER_HINTS:
            if hint in lowered:
                return method
        return "word"
