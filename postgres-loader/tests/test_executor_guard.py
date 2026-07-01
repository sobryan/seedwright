"""The drop-safety decision (spec FR-L.3) — pure, offline-testable.

Before replace/teardown drops a schema, the executor consults this. Extracted from the DB
path so the safety rule itself is unit-tested without a server: refuse to drop any existing
schema that isn't marked seedwright-owned. The mandatory ``ds_`` prefix + this marker guard
are the two lines of defense while least-privilege roles are deferred.
"""

from seedwright_pgloader.executor import drop_is_forbidden


def test_absent_schema_is_a_safe_noop() -> None:
    assert drop_is_forbidden(exists=False, comment=None) is False


def test_seedwright_marked_schema_may_be_dropped() -> None:
    assert drop_is_forbidden(exists=True, comment="seedwright:ds_1") is False


def test_existing_unmarked_schema_is_refused() -> None:
    assert drop_is_forbidden(exists=True, comment=None) is True


def test_existing_foreign_schema_is_refused() -> None:
    assert drop_is_forbidden(exists=True, comment="production application schema") is True
