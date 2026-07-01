"""Imported schema = the authoritative type source (ADR-0003).

The model asserts each column's canonical_kind, but precision/scale/length/source_sql come from
here (parsed via genlib's from_sql), never from the model — so authored money can't get the
wrong scale.
"""

import pytest
from seedwright_genlib.types import TypeKind

from seedwright_authoring.imported import ImportedSchema

from .golden import GOLDEN_IMPORTED


def _schema() -> ImportedSchema:
    return ImportedSchema.from_sql_columns(
        GOLDEN_IMPORTED, primary_keys={"customers": ["id"], "orders": ["id"]}
    )


def test_decimal_type_carries_precision_scale_and_source_sql() -> None:
    t = _schema().column_type("customers", "balance")
    assert t.kind is TypeKind.DECIMAL
    assert (t.precision, t.scale) == (12, 2)
    assert t.source_sql == "numeric(12,2)"


def test_bigint_and_varchar_mapping() -> None:
    schema = _schema()
    assert schema.column_type("customers", "id").kind is TypeKind.INT64
    email = schema.column_type("customers", "email")
    assert email.kind is TypeKind.STRING
    assert email.length == 255


def test_primary_key_recorded() -> None:
    assert _schema().table("customers").primary_key == ("id",)


def test_unknown_sql_type_raises() -> None:
    with pytest.raises(ValueError):
        ImportedSchema.from_sql_columns({"t": [("g", "polygon")]})


def test_unknown_column_lookup_raises() -> None:
    with pytest.raises(KeyError):
        _schema().column_type("customers", "nope")
