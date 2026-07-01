"""Table-name path safety (spec FR-L — table names are untrusted imported input).

Found by the Slice-2 adversarial safety review: table.name is used to build a filesystem path
for the Parquet read. Without validation, a plan table named '../../etc/secret' or '/etc/passwd'
escapes the canonical directory. The SQL layer stays safe (identifiers are quoted); this closes
the *file-read* escape.
"""

from pathlib import Path

import pytest

from seedwright_pgloader.executor import resolve_table_parquet
from seedwright_pgloader.safesql import UnsafeTableNameError, validate_relname


def test_validate_relname_accepts_plain_names() -> None:
    assert validate_relname("customers") == "customers"
    assert validate_relname("orders_2024") == "orders_2024"


@pytest.mark.parametrize(
    "bad", ["../x", "a/b", "/etc/passwd", "..", ".", "a\\b", "x\x00y", "", "sub/../../x"]
)
def test_validate_relname_rejects_traversal(bad: str) -> None:
    with pytest.raises(UnsafeTableNameError):
        validate_relname(bad)


def test_resolve_table_parquet_stays_in_dir(tmp_path: Path) -> None:
    assert resolve_table_parquet(tmp_path, "customers") == tmp_path / "customers.parquet"


@pytest.mark.parametrize("bad", ["../evil", "/etc/passwd", "a/b", ".."])
def test_resolve_table_parquet_rejects_escape(tmp_path: Path, bad: str) -> None:
    with pytest.raises(UnsafeTableNameError):
        resolve_table_parquet(tmp_path, bad)
