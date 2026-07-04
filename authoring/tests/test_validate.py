"""Static genspec validation (ADR-0003) — each issue is a Failure(category='validation') that
becomes refine feedback. Catching these statically stops the loop wasting iterations on things a
generator tweak can't fix (cycles, unique-infeasibility, hallucinated types).
"""

from seedwright_authoring.genspec import parse_genspec
from seedwright_authoring.imported import ImportedSchema
from seedwright_authoring.validate import validate_genspec

from .golden import GOLDEN_GENSPEC, GOLDEN_IMPORTED


def _codes(issues: list) -> set[str]:
    return {f.test_id.split(":")[0] for f in issues}


def _col(name, kind, gen_kind, params=None, *, nullable=False, unique=False, null_rate=0.0):
    return {"name": name, "canonical_kind": kind,
            "generator": {"kind": gen_kind, "params": params or {}},
            "nullable": nullable, "unique": unique, "null_rate": null_rate}


def _table(name, cols, *, table_class="generated", row_count=1, pk=None, fks=None):
    return {"name": name, "table_class": table_class, "row_count": row_count,
            "primary_key": pk or [], "foreign_keys": fks or [], "columns": cols}


def _spec(*tables, seed=1):
    return parse_genspec({"genspec_version": "1", "seed": seed, "tables": list(tables)})


def test_golden_genspec_is_valid() -> None:
    imported = ImportedSchema.from_sql_columns(
        GOLDEN_IMPORTED, primary_keys={"customers": ["id"], "orders": ["id"]}
    )
    assert validate_genspec(parse_genspec(GOLDEN_GENSPEC), imported) == []


def test_kind_mismatch() -> None:
    spec = _spec(_table("t", [_col("a", "STRING", "faker", {"method": "name"})]))
    imported = ImportedSchema.from_sql_columns({"t": [("a", "bigint")]})  # actually INT64
    assert "KIND_MISMATCH" in _codes(validate_genspec(spec, imported))


def test_generator_incompatible() -> None:
    spec = _spec(_table("t", [_col("a", "INT64", "faker", {"method": "name"})]))
    imported = ImportedSchema.from_sql_columns({"t": [("a", "bigint")]})
    assert "GENERATOR_INCOMPATIBLE" in _codes(validate_genspec(spec, imported))


def test_no_mvp_generator_for_unsupported_kind() -> None:
    # BYTES still has no MVP generator (DATE/TIMESTAMP gained theirs in slice 11)
    spec = _spec(_table("t", [_col("blob", "BYTES", "faker", {"method": "binary"})]))
    imported = ImportedSchema.from_sql_columns({"t": [("blob", "bytea")]})
    assert "NO_MVP_GENERATOR" in _codes(validate_genspec(spec, imported))


def test_fk_generator_conflict_real_generator_on_fk_column() -> None:
    parent = _table("p", [_col("id", "INT64", "serial")], pk=["id"], row_count=5)
    child = _table("c", [
        _col("id", "INT64", "serial"),
        _col("p_id", "INT64", "int_range", {"low": 1, "high": 5}),  # should be fk sentinel!
    ], pk=["id"], row_count=None,
        fks=[{"column": "p_id", "references_table": "p", "references_column": "id"}])
    imported = ImportedSchema.from_sql_columns(
        {"p": [("id", "bigint")], "c": [("id", "bigint"), ("p_id", "bigint")]},
        primary_keys={"p": ["id"], "c": ["id"]})
    assert "FK_GENERATOR_CONFLICT" in _codes(validate_genspec(_spec(parent, child), imported))


def test_fk_sentinel_on_non_fk_column() -> None:
    # a {kind:fk} column NOT declared in foreign_keys[] would let the placeholder actually run
    spec = _spec(_table("t", [_col("a", "INT64", "fk")]))
    imported = ImportedSchema.from_sql_columns({"t": [("a", "bigint")]})
    assert "FK_GENERATOR_CONFLICT" in _codes(validate_genspec(spec, imported))


def test_column_unknown_and_missing() -> None:
    spec = _spec(_table("t", [_col("ghost", "INT64", "serial")]))
    imported = ImportedSchema.from_sql_columns({"t": [("real", "bigint")]})
    codes = _codes(validate_genspec(spec, imported))
    assert "COLUMN_UNKNOWN" in codes   # 'ghost' not in schema
    assert "COLUMN_MISSING" in codes   # 'real' not authored


def test_rowcount_missing_on_non_driving_generated_table() -> None:
    spec = _spec(_table("t", [_col("a", "INT64", "serial")], row_count=None))
    imported = ImportedSchema.from_sql_columns({"t": [("a", "bigint")]})
    assert "ROWCOUNT_MISSING" in _codes(validate_genspec(spec, imported))


def test_rowcount_ignored_on_driving_fk_child() -> None:
    parent = _table("p", [_col("id", "INT64", "serial")], pk=["id"], row_count=5)
    child = _table("c", [_col("p_id", "INT64", "fk")], row_count=100,  # should be null
                   fks=[{"column": "p_id", "references_table": "p", "references_column": "id"}])
    imported = ImportedSchema.from_sql_columns(
        {"p": [("id", "bigint")], "c": [("p_id", "bigint")]}, primary_keys={"p": ["id"]})
    assert "ROWCOUNT_IGNORED" in _codes(validate_genspec(_spec(parent, child), imported))


def test_unique_infeasible_small_domain() -> None:
    spec = _spec(_table("t", [
        _col("k", "INT32", "int_range", {"low": 0, "high": 4}, unique=True),  # 5 values
    ], pk=["k"], row_count=100))
    imported = ImportedSchema.from_sql_columns({"t": [("k", "integer")]}, primary_keys={"t": ["k"]})
    assert "UNIQUE_INFEASIBLE" in _codes(validate_genspec(spec, imported))


def test_pk_nullable() -> None:
    spec = _spec(_table("t", [_col("id", "INT64", "serial", nullable=True)], pk=["id"]))
    imported = ImportedSchema.from_sql_columns(
        {"t": [("id", "bigint")]}, primary_keys={"t": ["id"]})
    assert "PK_NULLABLE" in _codes(validate_genspec(spec, imported))


def test_fk_unresolved() -> None:
    child = _table("c", [_col("p_id", "INT64", "fk")],
                   fks=[{"column": "p_id", "references_table": "ghost", "references_column": "id"}])
    imported = ImportedSchema.from_sql_columns({"c": [("p_id", "bigint")]})
    assert "FK_UNRESOLVED" in _codes(validate_genspec(_spec(child), imported))


def test_fk_type_mismatch() -> None:
    parent = _table("p", [_col("id", "STRING", "faker", {"method": "uuid4"})],
                    pk=["id"], row_count=5)
    child = _table("c", [_col("p_id", "INT64", "fk")],
                   fks=[{"column": "p_id", "references_table": "p", "references_column": "id"}])
    imported = ImportedSchema.from_sql_columns(
        {"p": [("id", "uuid")], "c": [("p_id", "bigint")]}, primary_keys={"p": ["id"]})
    assert "FK_TYPE_MISMATCH" in _codes(validate_genspec(_spec(parent, child), imported))


def test_cycle_detected_statically() -> None:
    a = _table("a", [_col("id", "INT64", "serial"), _col("b_id", "INT64", "fk")], pk=["id"],
               row_count=None, fks=[{"column": "b_id", "references_table": "b",
                                     "references_column": "id"}])
    b = _table("b", [_col("id", "INT64", "serial"), _col("a_id", "INT64", "fk")], pk=["id"],
               row_count=None, fks=[{"column": "a_id", "references_table": "a",
                                     "references_column": "id"}])
    imported = ImportedSchema.from_sql_columns(
        {"a": [("id", "bigint"), ("b_id", "bigint")], "b": [("id", "bigint"), ("a_id", "bigint")]},
        primary_keys={"a": ["id"], "b": ["id"]})
    assert "CYCLE" in _codes(validate_genspec(_spec(a, b), imported))
