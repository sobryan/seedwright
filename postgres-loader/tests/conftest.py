"""Integration-test plumbing.

`@pytest.mark.integration` tests need a live Postgres via ``SEEDWRIGHT_TEST_PG_DSN``. Without
it (the default here — Docker/Postgres unavailable) they auto-skip, so the suite stays green
offline while still verifying the real load path wherever a DB is reachable.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any

import pytest


@pytest.fixture
def pg_conn() -> Iterator[Any]:
    dsn = os.environ.get("SEEDWRIGHT_TEST_PG_DSN")
    if not dsn:
        pytest.skip("SEEDWRIGHT_TEST_PG_DSN not set — skipping live-Postgres integration test")

    import psycopg

    try:
        conn = psycopg.connect(dsn, autocommit=True)
    except Exception as exc:  # noqa: BLE001 - any connect failure => skip, don't fail
        pytest.skip(f"cannot reach Postgres at SEEDWRIGHT_TEST_PG_DSN: {exc}")

    try:
        yield conn
    finally:
        conn.close()
