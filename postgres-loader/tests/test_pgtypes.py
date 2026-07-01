"""Canonical kind -> Postgres column type (spec FR-M.4).

Driven entirely off the closed ``canonical_kind`` enum + structured precision/scale/length/
tz — the untrusted ``source_sql`` is never parsed for DDL. Money is always ``numeric``,
never a float. ``TIME`` ignores tz for MVP (Arrow time64 carries no zone -> a ``timetz``
column would be nondeterministic).
"""

import pytest

from seedwright_pgloader.pgtypes import UnknownCanonicalKindError, column_type


def _render(kind: str, **kw: object) -> str:
    return column_type(kind, **kw).as_string(None)


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        ("BOOLEAN", "boolean"),
        ("INT16", "smallint"),
        ("INT32", "integer"),
        ("INT64", "bigint"),
        ("FLOAT32", "real"),
        ("FLOAT64", "double precision"),
        ("DATE", "date"),
        ("TIME", "time"),
        ("UUID", "uuid"),
        ("JSON", "jsonb"),
        ("BYTES", "bytea"),
    ],
)
def test_simple_kinds(kind: str, expected: str) -> None:
    assert _render(kind) == expected


def test_decimal_with_precision_and_scale() -> None:
    assert _render("DECIMAL", precision=10, scale=2) == "numeric(10,2)"


def test_decimal_bare_is_unconstrained_numeric() -> None:
    assert _render("DECIMAL") == "numeric"


def test_decimal_is_never_a_float() -> None:
    rendered = _render("DECIMAL", precision=38, scale=9)
    assert "numeric" in rendered
    assert "double" not in rendered and "real" not in rendered and "float" not in rendered


def test_string_with_length_is_varchar() -> None:
    assert _render("STRING", length=255) == "varchar(255)"


def test_string_without_length_is_text() -> None:
    assert _render("STRING") == "text"


def test_timestamp_naive_vs_aware() -> None:
    assert _render("TIMESTAMP", tz=False) == "timestamp"
    assert _render("TIMESTAMP", tz=True) == "timestamptz"


def test_time_ignores_tz_for_mvp() -> None:
    assert _render("TIME", tz=True) == "time"


def test_unknown_kind_raises() -> None:
    with pytest.raises(UnknownCanonicalKindError):
        column_type("POLYGON")
