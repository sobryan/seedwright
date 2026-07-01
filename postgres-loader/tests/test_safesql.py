"""Identifier + namespace safety (spec FR-L — untrusted imported schema is an injection
vector; scoped namespaces are the teardown-safety boundary).

This is the injection keystone: every DDL/COPY/teardown builder routes identifiers and the
namespace through here. Tests assert the rendered SQL text (`.as_string(None)`, offline).
"""

import pytest

from seedwright_pgloader.safesql import (
    UnsafeIdentifierError,
    UnsafeNamespaceError,
    identifier,
    namespace_for,
    qualified,
    validate_namespace,
)

# --- namespace validation -------------------------------------------------------------

@pytest.mark.parametrize("ns", ["ds_1", "ds_abc123", "ds_a_b_c", "ds_0"])
def test_valid_namespaces_accepted(ns: str) -> None:
    assert validate_namespace(ns) == ns


@pytest.mark.parametrize(
    "ns",
    [
        "customers",              # no ds_ prefix -> could collide with a real schema
        "public",                 # reserved
        "pg_catalog",             # reserved
        "information_schema",     # reserved
        "sw_1",                   # wrong prefix
        "ds_ABC",                 # uppercase not allowed
        "ds_",                    # empty suffix
        "ds_a-b",                 # hyphen not allowed
        'ds_a"; DROP SCHEMA public CASCADE;--',  # injection payload
        "ds_a b",                 # space
        "",                       # empty
    ],
)
def test_invalid_namespaces_rejected(ns: str) -> None:
    with pytest.raises(UnsafeNamespaceError):
        validate_namespace(ns)


def test_namespace_over_63_bytes_rejected() -> None:
    assert validate_namespace("ds_" + "a" * 60)  # 63 bytes exactly: ok
    with pytest.raises(UnsafeNamespaceError):
        validate_namespace("ds_" + "a" * 61)  # 64 bytes: rejected (silent truncation risk)


def test_namespace_with_nul_rejected() -> None:
    with pytest.raises(UnsafeNamespaceError):
        validate_namespace("ds_a\x00b")


# --- identifier neutralization --------------------------------------------------------

def test_identifier_quotes_plainly() -> None:
    assert identifier("orders").as_string(None) == '"orders"'


def test_identifier_neutralizes_embedded_quotes() -> None:
    assert identifier('a"b').as_string(None) == '"a""b"'


def test_identifier_neutralizes_injection_payload() -> None:
    payload = 'x"; DROP TABLE users; --'
    assert identifier(payload).as_string(None) == '"x""; DROP TABLE users; --"'


def test_identifier_rejects_empty() -> None:
    with pytest.raises(UnsafeIdentifierError):
        identifier("")


def test_identifier_rejects_nul() -> None:
    with pytest.raises(UnsafeIdentifierError):
        identifier("a\x00b")


def test_identifier_rejects_over_63_bytes() -> None:
    with pytest.raises(UnsafeIdentifierError):
        identifier("c" * 64)


# --- qualified table ------------------------------------------------------------------

def test_qualified_renders_schema_and_table() -> None:
    assert qualified("ds_1", "orders").as_string(None) == '"ds_1"."orders"'


def test_qualified_validates_namespace() -> None:
    with pytest.raises(UnsafeNamespaceError):
        qualified("customers", "orders")  # non-namespace schema must be refused


def test_qualified_neutralizes_table_injection() -> None:
    rendered = qualified("ds_1", 'o"; DROP TABLE x;--').as_string(None)
    assert rendered == '"ds_1"."o""; DROP TABLE x;--"'


# --- namespace_for --------------------------------------------------------------------

def test_namespace_for_builds_valid_namespace() -> None:
    ns = namespace_for("Order-Batch 42")
    assert ns.startswith("ds_")
    assert validate_namespace(ns) == ns


def test_namespace_for_is_deterministic() -> None:
    assert namespace_for("abc") == namespace_for("abc")
