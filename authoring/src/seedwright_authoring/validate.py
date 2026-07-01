"""Static genspec validation (ADR-0003, hardened by the Slice-3 adversarial review).

Returns a list of ``Failure(category='validation')`` — the loop feeds these back to the model as
refine feedback. Beyond kind/type checks, this validates *generator params and invariants* so that
compile + genlib never raise a raw exception on plausible-but-wrong model output (which would crash
the loop instead of refining). An empty list means the genspec is safe to compile.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from seedwright_genlib.types import TypeKind

from .catalog import GENERATOR_CATALOG
from .feedback import Failure
from .genspec import GenColumn, GenForeignKey, GenSpec, GenTable
from .imported import ImportedSchema

_NON_FK_KINDS = frozenset(k for k in GENERATOR_CATALOG if k != "fk")
_COVERABLE_KINDS = frozenset().union(
    *(GENERATOR_CATALOG[k].compatible_kinds for k in _NON_FK_KINDS)
)
_FINITE_DOMAIN = frozenset({"int_range", "categorical"})
_KNOWN_CLASSES = frozenset({"generated", "reference", "excluded"})


def validate_genspec(genspec: GenSpec, imported: ImportedSchema) -> list[Failure]:
    issues: list[Failure] = []
    generated = {t.name for t in genspec.tables if t.table_class == "generated"}
    for table in genspec.tables:
        issues += _validate_table(table, genspec, imported, generated)
    issues += _detect_cycles(genspec, generated)
    return issues


def _issue(code: str, table: str, column: str | None, detail: str, feedback: str) -> Failure:
    loc = f"{table}.{column}" if column else table
    return Failure("validation", table, column, f"{code}:{loc}", detail, feedback)


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _validate_table(
    table: GenTable, genspec: GenSpec, imported: ImportedSchema, generated: set[str]
) -> list[Failure]:
    issues: list[Failure] = []
    if table.table_class not in _KNOWN_CLASSES:
        issues.append(_issue("TABLE_CLASS_UNKNOWN", table.name, None,
                             f"unknown table_class {table.table_class!r}",
                             "use one of generated|reference|excluded"))
    try:
        imported_table = imported.table(table.name)
    except KeyError:
        return issues + [_issue("TABLE_UNKNOWN", table.name, None,
                                "table not in imported schema", f"remove table {table.name!r}")]

    imported_names = {c.name for c in imported_table.columns}
    authored_names = {c.name for c in table.columns}
    fk_columns = {fk.column for fk in table.foreign_keys}

    for col in table.columns:
        issues += _validate_column(table, col, imported, imported_names, fk_columns)

    for missing in sorted(imported_names - authored_names):
        issues.append(_issue("COLUMN_MISSING", table.name, missing,
                             "imported column not authored",
                             f"add a generator for column {missing!r}"))

    issues += _validate_rowcount(table, generated)
    issues += _validate_foreign_keys(table, genspec, imported, generated)
    return issues


def _validate_column(
    table: GenTable, col: GenColumn, imported: ImportedSchema,
    imported_names: set[str], fk_columns: set[str],
) -> list[Failure]:
    issues: list[Failure] = []
    is_fk = col.generator.kind == "fk"

    if col.name in fk_columns and not is_fk:
        issues.append(_issue("FK_GENERATOR_CONFLICT", table.name, col.name,
                             "FK column must use the fk generator sentinel",
                             f"set {col.name!r} generator to {{'kind': 'fk'}}"))
    if is_fk and col.name not in fk_columns:
        issues.append(_issue("FK_GENERATOR_CONFLICT", table.name, col.name,
                             "fk sentinel on a column not declared as a foreign key",
                             f"declare a foreign_key for {col.name!r} or pick a real generator"))

    if not 0.0 <= col.null_rate <= 1.0:
        issues.append(_issue("NULL_RATE_INVALID", table.name, col.name,
                             f"null_rate {col.null_rate} outside [0, 1]",
                             "set null_rate within [0, 1]"))

    if col.name not in imported_names:
        issues.append(_issue("COLUMN_UNKNOWN", table.name, col.name,
                             "column not in imported schema",
                             f"remove column {col.name!r} or fix its name"))
        return issues

    actual_kind = imported.column_type(table.name, col.name).kind
    if col.canonical_kind != actual_kind.name:
        issues.append(_issue("KIND_MISMATCH", table.name, col.name,
                             f"asserted {col.canonical_kind}, schema says {actual_kind.name}",
                             f"set canonical_kind to {actual_kind.name}"))

    if col.name in table.primary_key and col.nullable:
        issues.append(_issue("PK_NULLABLE", table.name, col.name,
                             "primary-key column marked nullable",
                             f"set {col.name!r} nullable=false"))

    if not is_fk:
        issues += _validate_generator_choice(table, col, actual_kind)
        issues += _validate_params(table, col, imported)
        issues += _validate_unique_feasibility(table, col)
    return issues


def _validate_generator_choice(
    table: GenTable, col: GenColumn, actual_kind: TypeKind
) -> list[Failure]:
    entry = GENERATOR_CATALOG.get(col.generator.kind)
    if entry is None:
        return [_issue("GENERATOR_UNKNOWN", table.name, col.name,
                       f"unknown generator kind {col.generator.kind!r}",
                       "pick a generator from the catalog")]
    if actual_kind not in _COVERABLE_KINDS:
        return [_issue("NO_MVP_GENERATOR", table.name, col.name,
                       f"no MVP generator supports canonical kind {actual_kind.name}",
                       "this column type is not yet supported by the authoring loop")]
    if actual_kind not in entry.compatible_kinds:
        return [_issue("GENERATOR_INCOMPATIBLE", table.name, col.name,
                       f"generator {col.generator.kind!r} incompatible with {actual_kind.name}",
                       "choose a generator compatible with this column's type")]
    return []


def _validate_params(table: GenTable, col: GenColumn, imported: ImportedSchema) -> list[Failure]:
    """Validate required generator params + invariants so genlib constructors never raise raw."""
    kind = col.generator.kind
    p = col.generator.params

    def params_bad(detail: str) -> list[Failure]:
        return [_issue("GENERATOR_PARAMS", table.name, col.name, detail,
                       "fix the generator params")]

    if kind == "serial":
        if "start" in p and not _is_int(p["start"]):
            return params_bad("serial 'start' must be an integer")
        return []

    if kind == "int_range":
        if not (_is_int(p.get("low")) and _is_int(p.get("high"))):
            return params_bad("int_range needs integer 'low' and 'high'")
        if p["low"] > p["high"]:
            return [_issue("RANGE_INVALID", table.name, col.name,
                           f"int_range low {p['low']} > high {p['high']}", "make low <= high")]
        return []

    if kind == "decimal_range":
        if not all(k in p for k in ("low", "high", "scale")):
            return params_bad("decimal_range needs 'low', 'high', and 'scale'")
        try:
            low, high = Decimal(str(p["low"])), Decimal(str(p["high"]))
        except (InvalidOperation, TypeError):
            return params_bad("decimal_range 'low'/'high' must be decimal strings")
        if not _is_int(p["scale"]) or p["scale"] < 0:
            return params_bad("decimal_range 'scale' must be a non-negative integer")
        if low > high:
            return [_issue("RANGE_INVALID", table.name, col.name,
                           f"decimal_range low {low} > high {high}", "make low <= high")]
        column_scale = imported.column_type(table.name, col.name).scale
        if column_scale is not None and p["scale"] != column_scale:
            return [_issue("SCALE_MISMATCH", table.name, col.name,
                           f"generator scale {p['scale']} != column scale {column_scale}",
                           f"set decimal_range scale to {column_scale}")]
        return []

    if kind == "categorical":
        values = p.get("values")
        if not isinstance(values, list) or not values:
            return params_bad("categorical needs a non-empty 'values' list")
        weights = p.get("weights")
        if weights is not None and len(weights) != len(values):
            return params_bad("categorical 'weights' length must match 'values'")
        return []

    if kind == "faker":
        if not isinstance(p.get("method"), str):
            return params_bad("faker needs a string 'method'")
        return []

    return []


def _validate_unique_feasibility(table: GenTable, col: GenColumn) -> list[Failure]:
    requires_unique = col.unique or col.name in table.primary_key
    if not (requires_unique and _is_int(table.row_count)):
        return []
    domain = _finite_domain(col)
    if domain is not None and table.row_count is not None and domain < table.row_count:
        return [_issue("UNIQUE_INFEASIBLE", table.name, col.name,
                       f"domain {domain} < row_count {table.row_count} for a unique column",
                       "widen the range/enum or use a serial generator")]
    return []


def _finite_domain(col: GenColumn) -> int | None:
    if col.generator.kind not in _FINITE_DOMAIN:
        return None
    p = col.generator.params
    if col.generator.kind == "int_range":
        if not (_is_int(p.get("low")) and _is_int(p.get("high"))):
            return None
        return int(p["high"]) - int(p["low"]) + 1
    values = p.get("values")
    return len(values) if isinstance(values, list) else None


def _validate_rowcount(table: GenTable, generated: set[str]) -> list[Failure]:
    if table.table_class != "generated":
        return []
    driving = any(
        fk.references_table in generated and fk.references_table != table.name
        for fk in table.foreign_keys
    )
    if driving:
        if table.row_count is not None:
            return [_issue("ROWCOUNT_IGNORED", table.name, None,
                           "row_count set on a driving-FK child (count is derived)",
                           "set row_count to null")]
        return []
    if table.row_count is None:
        return [_issue("ROWCOUNT_MISSING", table.name, None,
                       "generated table without a driving FK needs a row_count",
                       "set an integer row_count")]
    if not _is_int(table.row_count) or table.row_count <= 0:
        return [_issue("ROWCOUNT_INVALID", table.name, None,
                       f"row_count {table.row_count!r} must be a positive integer",
                       "set a positive integer row_count")]
    return []


def _validate_foreign_keys(
    table: GenTable, genspec: GenSpec, imported: ImportedSchema, generated: set[str]
) -> list[Failure]:
    issues: list[Failure] = []
    for fk in table.foreign_keys:
        if fk.max_per_parent < fk.min_per_parent:
            issues.append(_issue("FK_CARDINALITY_INVALID", table.name, fk.column,
                                 f"max_per_parent {fk.max_per_parent} < min {fk.min_per_parent}",
                                 "make max_per_parent >= min_per_parent"))
        try:
            parent = imported.table(fk.references_table)
            parent_col = parent.column(fk.references_column)
        except KeyError:
            issues.append(_issue("FK_UNRESOLVED", table.name, fk.column,
                                 f"FK references {fk.references_table}.{fk.references_column} "
                                 "which is not in the imported schema",
                                 "fix the referenced table/column"))
            continue
        try:
            child_col = imported.table(table.name).column(fk.column)
        except KeyError:
            continue
        if child_col.type.kind is not parent_col.type.kind:
            issues.append(_issue("FK_TYPE_MISMATCH", table.name, fk.column,
                                 f"FK column kind {child_col.type.kind.name} != referenced "
                                 f"{parent_col.type.kind.name}",
                                 "make the FK column type match the referenced key"))
        # genlib resolves FKs from the parent's primary key only, so a generated parent must
        # declare a single-column PK that the FK references (else genlib would crash at generation).
        if fk.references_table in generated:
            issues += _validate_generated_parent_pk(table, fk, genspec)
    return issues


def _validate_generated_parent_pk(
    table: GenTable, fk: GenForeignKey, genspec: GenSpec
) -> list[Failure]:
    try:
        parent = genspec.table(fk.references_table)
    except KeyError:
        return []
    if not parent.primary_key:
        return [_issue("FK_PARENT_NO_PK", table.name, fk.column,
                       f"generated parent {fk.references_table!r} has no primary_key",
                       f"declare a primary_key on {fk.references_table!r}")]
    if fk.references_column != parent.primary_key[0]:
        return [_issue("FK_REF_NOT_PK", table.name, fk.column,
                       f"FK must reference the parent primary key {parent.primary_key[0]!r}",
                       f"reference {fk.references_table}.{parent.primary_key[0]}")]
    return []


def _detect_cycles(genspec: GenSpec, generated: set[str]) -> list[Failure]:
    deps: dict[str, set[str]] = {name: set() for name in generated}
    for table in genspec.tables:
        if table.name not in generated:
            continue
        for fk in table.foreign_keys:
            if fk.references_table in generated and fk.references_table != table.name:
                deps[table.name].add(fk.references_table)

    resolved: set[str] = set()
    remaining = set(generated)
    while remaining:
        ready = {n for n in remaining if deps[n] <= resolved}
        if not ready:
            return [_issue("CYCLE", sorted(remaining)[0], None,
                           f"FK cycle among generated tables: {sorted(remaining)}",
                           "break the circular foreign-key dependency")]
        resolved |= ready
        remaining -= ready
    return []
