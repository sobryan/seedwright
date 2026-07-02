"""File-export sink (spec FR-G.4): canonical Parquet -> CSV / JSONL / SQL-INSERT files.

The always-available sink — usable with no database at all. Written by hand (not a library
writer) so the fidelity rules are explicit and pinned by tests:

- decimals render via ``str(Decimal)`` — exact scale, never through binary float;
- NULL is distinguishable from empty string where the format allows (JSONL ``null``; CSV uses
  an unquoted empty field for NULL vs ``""`` for an empty string; SQL ``NULL``);
- SQL string literals double embedded single quotes; identifiers are double-quoted;
- output is deterministic (same input -> identical bytes);
- table names are validated as path segments (same guard as the loader).
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
from seedwright_pgloader.safesql import validate_relname

FORMATS = ("csv", "jsonl", "sql")
SQL_BATCH_ROWS = 500


def export_dataset(
    canonical_dir: str | Path,
    load_plan: dict[str, Any],
    out_dir: str | Path,
    *,
    formats: list[str],
) -> dict[str, Any]:
    """Export every table in the Load Plan to the requested formats; returns written files."""
    unknown = [f for f in formats if f not in FORMATS]
    if unknown:
        raise ValueError(f"unknown export format(s) {unknown}; supported: {list(FORMATS)}")
    canonical_dir = Path(canonical_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    files: dict[str, list[str]] = {f: [] for f in formats}
    total_rows = 0
    for table in load_plan["tables"]:
        name = validate_relname(table["name"])
        columns = [c["name"] for c in table["columns"]]
        arrow = pq.read_table(  # type: ignore[no-untyped-call]
            canonical_dir / f"{name}.parquet", columns=columns
        )
        rows = arrow.to_pylist()
        total_rows += len(rows)
        for fmt in formats:
            path = out_dir / f"{name}.{fmt}"
            _WRITERS[fmt](path, name, columns, rows)
            files[fmt].append(str(path))
    return {"out_dir": str(out_dir), "files": files, "total_rows": total_rows}


# --- CSV --------------------------------------------------------------------------------

def _csv_field(value: Any) -> str:
    if value is None:
        return ""  # NULL = bare empty; empty string renders as ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float, Decimal)):
        return str(value)
    text = value.hex() if isinstance(value, bytes) else str(value)
    return '"' + text.replace('"', '""') + '"'


def _write_csv(path: Path, name: str, columns: list[str], rows: list[dict[str, Any]]) -> None:
    lines = [",".join(f'"{c}"' for c in columns)]
    lines += [",".join(_csv_field(row[c]) for c in columns) for row in rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# --- JSONL ------------------------------------------------------------------------------

def _json_default(value: Any) -> str:
    if isinstance(value, Decimal):
        return str(value)  # exact scale as a string, never float
    if isinstance(value, bytes):
        return value.hex()
    if hasattr(value, "isoformat"):
        return str(value.isoformat())
    return str(value)


def _write_jsonl(path: Path, name: str, columns: list[str], rows: list[dict[str, Any]]) -> None:
    lines = [
        json.dumps({c: row[c] for c in columns}, default=_json_default, ensure_ascii=False)
        for row in rows
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# --- SQL --------------------------------------------------------------------------------

def _sql_literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float, Decimal)):
        return str(value)
    if isinstance(value, bytes):
        return "X'" + value.hex() + "'"
    text = str(value.isoformat()) if hasattr(value, "isoformat") else str(value)
    if "\x00" in text:
        raise ValueError("value contains NUL byte, not representable in a SQL literal")
    return "'" + text.replace("'", "''") + "'"


def _write_sql(path: Path, name: str, columns: list[str], rows: list[dict[str, Any]]) -> None:
    ident = '"' + name.replace('"', '""') + '"'
    col_list = ", ".join('"' + c.replace('"', '""') + '"' for c in columns)
    statements: list[str] = []
    for start in range(0, len(rows), SQL_BATCH_ROWS):
        batch = rows[start : start + SQL_BATCH_ROWS]
        values = ",\n".join(
            "  (" + ", ".join(_sql_literal(row[c]) for c in columns) + ")" for row in batch
        )
        statements.append(f"INSERT INTO {ident} ({col_list}) VALUES\n{values};")
    path.write_text("\n".join(statements) + "\n", encoding="utf-8")


_WRITERS = {"csv": _write_csv, "jsonl": _write_jsonl, "sql": _write_sql}
