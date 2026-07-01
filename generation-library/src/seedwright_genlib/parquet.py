"""Canonical Parquet writer (spec FR-M.3, FR-E.4).

Writes the Canonical Dataset to disk — one Parquet file per table — batched into row
groups so peak memory stays bounded at the ~10M-row ceiling (NFR-SCALE). This on-disk
Parquet is the reproducibility checkpoint and the single source validation and every sink
loader read from.
"""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

DEFAULT_ROW_GROUP_SIZE = 64_000


def write_table(table: pa.Table, path: str | Path, *, row_group_size: int | None = None) -> Path:
    """Write one Arrow table to a single Parquet file, batched into row groups.

    Streaming the write in row-group-sized batches (rather than one buffer) is what keeps
    memory bounded for very large tables.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rg = row_group_size or DEFAULT_ROW_GROUP_SIZE

    with pq.ParquetWriter(path, table.schema) as writer:  # type: ignore[no-untyped-call]
        for batch in table.to_batches(max_chunksize=rg):
            writer.write_batch(batch)
    return path


def write_dataset(
    tables: dict[str, pa.Table], out_dir: str | Path, *, row_group_size: int | None = None
) -> dict[str, Path]:
    """Write every table to ``<out_dir>/<name>.parquet``; return name -> path."""
    out_dir = Path(out_dir)
    return {
        name: write_table(table, out_dir / f"{name}.parquet", row_group_size=row_group_size)
        for name, table in tables.items()
    }
