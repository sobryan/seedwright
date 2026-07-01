"""Generator catalog — the one source of truth mapping genspec kinds to genlib generators
(ADR-0003). Used by validation, compilation, and (later) the model-facing prompt.
"""

from decimal import Decimal

import pytest
from seedwright_genlib.generators import (
    Categorical,
    DecimalRange,
    FakerField,
    IntRange,
    Serial,
)
from seedwright_genlib.rng import SeededRng
from seedwright_genlib.types import TypeKind

from seedwright_authoring.catalog import (
    GENERATOR_CATALOG,
    UnknownGeneratorKindError,
    build_generator,
)


def test_each_kind_builds_a_real_genlib_generator() -> None:
    assert isinstance(build_generator("serial", {"start": 1}), Serial)
    assert isinstance(build_generator("int_range", {"low": 0, "high": 9}), IntRange)
    assert isinstance(
        build_generator("decimal_range", {"low": "0.00", "high": "1.00", "scale": 2}), DecimalRange
    )
    assert isinstance(build_generator("categorical", {"values": ["a", "b"]}), Categorical)
    assert isinstance(build_generator("faker", {"method": "email"}), FakerField)


def test_decimal_range_is_built_with_decimal_never_float() -> None:
    gen = build_generator("decimal_range", {"low": "0.10", "high": "0.10", "scale": 2})
    values = gen.generate(SeededRng(1), 5)
    assert all(isinstance(v, Decimal) and v == Decimal("0.10") for v in values)


def test_fk_builds_the_shared_placeholder() -> None:
    a = build_generator("fk", {})
    b = build_generator("fk", {})
    assert a is b  # module-level placeholder, never invoked by genlib


def test_unknown_kind_raises() -> None:
    with pytest.raises(UnknownGeneratorKindError):
        build_generator("markov_chain", {})


def test_catalog_declares_type_compatibility() -> None:
    assert GENERATOR_CATALOG["decimal_range"].compatible_kinds == frozenset({TypeKind.DECIMAL})
    assert TypeKind.STRING in GENERATOR_CATALOG["faker"].compatible_kinds
    assert TypeKind.INT64 in GENERATOR_CATALOG["serial"].compatible_kinds
