"""Generator catalog (ADR-0003) — the single source of truth mapping genspec generator kinds
to genlib ``Generator`` objects, plus each kind's type compatibility.

Validation, compilation, and (later) the model-facing prompt all read this one table, so adding
a generator touches exactly one place (NFR-EXT) and can never drift out of sync.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from seedwright_genlib.generators import (
    Categorical,
    DateRange,
    DecimalRange,
    FakerField,
    Generator,
    IntRange,
    Serial,
    TimestampRange,
)
from seedwright_genlib.types import TypeKind

# A single shared placeholder for FK-filled columns. genlib's dataset layer fills any column
# named in a table's foreign_keys and never calls its generator (generate.py), so this object is
# never invoked — the validator's FK bidirectional invariant is what keeps that guarantee true.
_FK_PLACEHOLDER: Generator = Serial()

_INT_KINDS = frozenset({TypeKind.INT16, TypeKind.INT32, TypeKind.INT64})


class UnknownGeneratorKindError(ValueError):
    """The genspec used a generator kind not in the catalog."""


@dataclass(frozen=True)
class CatalogEntry:
    kind: str
    compatible_kinds: frozenset[TypeKind]
    build: Callable[[dict[str, Any]], Generator]


def _serial(p: dict[str, Any]) -> Generator:
    return Serial(start=int(p.get("start", 1)))


def _int_range(p: dict[str, Any]) -> Generator:
    return IntRange(int(p["low"]), int(p["high"]))


def _decimal_range(p: dict[str, Any]) -> Generator:
    # low/high arrive as strings so money never touches binary float (FR-M.4).
    return DecimalRange(Decimal(str(p["low"])), Decimal(str(p["high"])), int(p["scale"]))


def _categorical(p: dict[str, Any]) -> Generator:
    return Categorical(p["values"], p.get("weights"))


def _faker(p: dict[str, Any]) -> Generator:
    return FakerField(p["method"], p.get("locale"), **p.get("kwargs", {}))


def _date_range(p: dict[str, Any]) -> Generator:
    return DateRange(date.fromisoformat(str(p["low"])), date.fromisoformat(str(p["high"])))


def _timestamp_range(p: dict[str, Any]) -> Generator:
    return TimestampRange(
        datetime.fromisoformat(str(p["low"])),
        datetime.fromisoformat(str(p["high"])),
        tz=bool(p.get("tz", False)),
    )


def _fk(p: dict[str, Any]) -> Generator:
    return _FK_PLACEHOLDER


_ALL_KINDS = frozenset(TypeKind)

GENERATOR_CATALOG: dict[str, CatalogEntry] = {
    "serial": CatalogEntry("serial", _INT_KINDS, _serial),
    "int_range": CatalogEntry("int_range", _INT_KINDS, _int_range),
    "decimal_range": CatalogEntry("decimal_range", frozenset({TypeKind.DECIMAL}), _decimal_range),
    "categorical": CatalogEntry(
        "categorical", _INT_KINDS | {TypeKind.STRING, TypeKind.BOOLEAN}, _categorical
    ),
    "faker": CatalogEntry(
        "faker", frozenset({TypeKind.STRING, TypeKind.UUID, TypeKind.JSON}), _faker
    ),
    "date_range": CatalogEntry("date_range", frozenset({TypeKind.DATE}), _date_range),
    "timestamp_range": CatalogEntry(
        "timestamp_range", frozenset({TypeKind.TIMESTAMP}), _timestamp_range
    ),
    # fk is type-agnostic here; FK-specific checks (resolves, matches parent) live in validate.
    "fk": CatalogEntry("fk", _ALL_KINDS, _fk),
}


def build_generator(kind: str, params: dict[str, Any]) -> Generator:
    entry = GENERATOR_CATALOG.get(kind)
    if entry is None:
        raise UnknownGeneratorKindError(f"unknown generator kind: {kind!r}")
    return entry.build(params)
