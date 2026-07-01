"""Data-tests + the judge (spec FR-F.1a).

Derives data-tests from the schema (referential, uniqueness) and declared rules (value-range,
enum, null-rate), generates a small sample through genlib, and evaluates it. A genlib error at
sample time (uniqueness/cycle/type) is turned into a ``generation`` Failure so the loop can refine
rather than crash. Every failure carries actionable feedback for the authoring model.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import pyarrow as pa
from seedwright_genlib.dataset import generate_dataset
from seedwright_genlib.rng import SeededRng
from seedwright_genlib.schema import SchemaSpec, TableClass

from .feedback import Failure
from .genspec import GenSpec
from .imported import ImportedSchema
from .rules import RuleSet

SAMPLE_ROWS = 200


@dataclass(frozen=True)
class DataTest:
    kind: str
    table: str
    column: str | None
    params: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "table": self.table, "column": self.column,
                "params": dict(self.params)}


@dataclass(frozen=True)
class JudgeResult:
    passed: bool
    failures: tuple[Failure, ...]


def derive_data_tests(
    genspec: GenSpec, imported: ImportedSchema, rules: RuleSet
) -> list[DataTest]:
    tests: list[DataTest] = []
    for rule in rules.rules:
        if rule.min_value is not None or rule.max_value is not None:
            tests.append(DataTest("value_range", rule.table, rule.column,
                                  {"min": rule.min_value, "max": rule.max_value}))
        if rule.enum is not None:
            tests.append(DataTest("enum", rule.table, rule.column, {"values": list(rule.enum)}))
        if rule.max_null_rate is not None:
            tests.append(DataTest("null_rate", rule.table, rule.column,
                                  {"max": rule.max_null_rate}))

    for table in genspec.tables:
        if table.table_class != "generated":
            continue
        for fk in table.foreign_keys:
            tests.append(DataTest("fk_resolves", table.name, fk.column,
                                  {"ref_table": fk.references_table,
                                   "ref_column": fk.references_column}))
            tests.append(DataTest("fk_cardinality", table.name, fk.column,
                                  {"max_per_parent": fk.max_per_parent}))
        for col in table.columns:
            if col.unique or col.name in table.primary_key:
                tests.append(DataTest("unique", table.name, col.name, {}))
    return tests


def generate_sample(
    schema: SchemaSpec, seed: int, sample_rows: int = SAMPLE_ROWS,
    reference_pools: dict[str, Any] | None = None,
) -> dict[str, pa.Table]:
    """Generate a small sample: override non-driving generated tables to ``sample_rows`` rows."""
    generated = {t.name for t in schema.tables if t.table_class is TableClass.GENERATED}
    driving = {
        t.name for t in schema.tables
        if any(fk.references_table in generated and fk.references_table != t.name
               for fk in t.foreign_keys)
    }
    row_counts = {
        t.name: sample_rows for t in schema.tables
        if t.table_class is TableClass.GENERATED and t.name not in driving
    }
    return generate_dataset(schema, SeededRng(seed), row_counts=row_counts,
                            reference_pools=reference_pools)


def judge_sample(
    schema: SchemaSpec, tests: list[DataTest], *, seed: int,
    sample_rows: int = SAMPLE_ROWS, reference_pools: dict[str, Any] | None = None,
) -> JudgeResult:
    try:
        tables = generate_sample(schema, seed, sample_rows, reference_pools)
    except (ValueError, KeyError, pa.ArrowInvalid) as exc:
        return JudgeResult(False, (Failure(
            "generation", "?", None, "generation_error",
            f"sample generation failed: {exc}",
            "fix the generator/params so a sample can be produced",
        ),))
    try:
        failures = run_data_tests(tests, tables)
    except (ValueError, KeyError, ArithmeticError, pa.ArrowInvalid) as exc:
        # a rule mistargeted at a missing/non-numeric column must not crash the loop
        return JudgeResult(False, (Failure(
            "constraint", "?", None, "datatest_error",
            f"a data-test could not run: {exc}",
            "align rules with the schema's columns and types",
        ),))
    return JudgeResult(passed=not failures, failures=tuple(failures))


def run_data_tests(tests: list[DataTest], tables: dict[str, pa.Table]) -> list[Failure]:
    out: list[Failure] = []
    for test in tests:
        failure = _run(test, tables)
        if failure is not None:
            out.append(failure)
    return out


def _run(test: DataTest, tables: dict[str, pa.Table]) -> Failure | None:
    runner = _RUNNERS.get(test.kind)
    if runner is None or test.table not in tables:
        return None
    return runner(test, tables)


def _values(test: DataTest, tables: dict[str, pa.Table]) -> list[Any]:
    assert test.column is not None
    return list(tables[test.table].column(test.column).to_pylist())


def _value_range(test: DataTest, tables: dict[str, pa.Table]) -> Failure | None:
    lo = Decimal(test.params["min"]) if test.params.get("min") is not None else None
    hi = Decimal(test.params["max"]) if test.params.get("max") is not None else None
    bad = [
        v for v in _values(test, tables)
        if v is not None and ((lo is not None and Decimal(str(v)) < lo)
                              or (hi is not None and Decimal(str(v)) > hi))
    ]
    if not bad:
        return None
    return Failure("constraint", test.table, test.column,
                   f"value_range:{test.table}.{test.column}",
                   f"{len(bad)} values outside [{lo}, {hi}], e.g. {bad[0]}",
                   f"constrain {test.column} to [{lo}, {hi}]")


def _enum(test: DataTest, tables: dict[str, pa.Table]) -> Failure | None:
    allowed = set(test.params["values"])
    seen = {v for v in _values(test, tables) if v is not None}
    extra = seen - allowed
    if not extra:
        return None
    return Failure("constraint", test.table, test.column,
                   f"enum:{test.table}.{test.column}",
                   f"values outside the allowed set: {sorted(extra)}",
                   f"restrict {test.column} to {sorted(allowed)}")


def _null_rate(test: DataTest, tables: dict[str, pa.Table]) -> Failure | None:
    values = _values(test, tables)
    if not values:
        return None
    rate = sum(1 for v in values if v is None) / len(values)
    max_rate = float(test.params["max"])
    slack = 0.0 if max_rate == 0.0 else 0.05  # a hard NOT-NULL (max=0) gets no slack
    if rate <= max_rate + slack:
        return None
    return Failure("null_rate", test.table, test.column,
                   f"null_rate:{test.table}.{test.column}",
                   f"observed null rate {rate:.2f} exceeds declared max {max_rate:.2f}",
                   f"lower null_rate for {test.column}")


def _unique(test: DataTest, tables: dict[str, pa.Table]) -> Failure | None:
    values = [v for v in _values(test, tables) if v is not None]
    if len(set(values)) == len(values):
        return None
    return Failure("uniqueness", test.table, test.column,
                   f"unique:{test.table}.{test.column}",
                   "duplicate values in a unique column",
                   f"use a serial/unique generator for {test.column}")


def _fk_resolves(test: DataTest, tables: dict[str, pa.Table]) -> Failure | None:
    ref_table = test.params["ref_table"]
    if ref_table not in tables:
        return None
    parent_keys = set(tables[ref_table].column(test.params["ref_column"]).to_pylist())
    unresolved = [v for v in _values(test, tables) if v is not None and v not in parent_keys]
    if not unresolved:
        return None
    return Failure("referential", test.table, test.column,
                   f"fk_resolves:{test.table}.{test.column}",
                   f"{len(unresolved)} FK values do not resolve to a parent key",
                   f"ensure {test.column} references existing {ref_table} keys")


def _fk_cardinality(test: DataTest, tables: dict[str, pa.Table]) -> Failure | None:
    max_pp = int(test.params["max_per_parent"])
    counts = Counter(v for v in _values(test, tables) if v is not None)
    over = {k: c for k, c in counts.items() if c > max_pp}
    if not over:
        return None
    return Failure("referential", test.table, test.column,
                   f"fk_cardinality:{test.table}.{test.column}",
                   f"{len(over)} parents exceed max_per_parent {max_pp}",
                   f"reduce max_per_parent for {test.column}")


_RUNNERS = {
    "value_range": _value_range,
    "enum": _enum,
    "null_rate": _null_rate,
    "unique": _unique,
    "fk_resolves": _fk_resolves,
    "fk_cardinality": _fk_cardinality,
}
