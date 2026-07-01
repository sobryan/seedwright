"""namespace_for collision safety (spec FR-L.3 — cross-dataset isolation).

Found by the Slice-2 adversarial safety review: the old namespace_for truncated to 63 bytes,
so two long dataset ids sharing a ~60-char prefix collapsed to the SAME ds_ namespace. In
replace mode that means loading dataset B drops dataset A's schema. The namespace must be a
deterministic function of the *full* id that never collides for distinct ids.
"""

from seedwright_pgloader.safesql import (
    MAX_IDENTIFIER_BYTES,
    namespace_for,
    validate_namespace,
)


def test_result_is_a_valid_namespace() -> None:
    ns = namespace_for("Order Batch #42")
    assert validate_namespace(ns) == ns
    assert len(ns.encode("utf-8")) <= MAX_IDENTIFIER_BYTES


def test_is_deterministic() -> None:
    assert namespace_for("abc") == namespace_for("abc")


def test_distinct_short_ids_differ() -> None:
    assert namespace_for("abc") != namespace_for("abd")


def test_long_similar_ids_do_not_collide() -> None:
    a = "batch_" + "x" * 80 + "_A"
    b = "batch_" + "x" * 80 + "_B"
    # Same 60+ char prefix -> old truncation collapsed these to one namespace.
    assert namespace_for(a) != namespace_for(b)
    assert len(namespace_for(a).encode("utf-8")) <= MAX_IDENTIFIER_BYTES
