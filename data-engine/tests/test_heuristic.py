"""HeuristicProvider — a deterministic, rule-driven Provider (no LLM).

Proposes a sensible genspec from the imported schema + declared rules: serial for integer PKs,
fk sentinel for FK columns, decimal_range from rule bounds (or defaults) at the column's real
scale, categorical from enum rules, name-hinted faker methods for strings. It makes the on-prem
product demoable offline; a real LLM provider slots in behind the same protocol later.
"""

from seedwright_authoring.compile import compile_to_genlib
from seedwright_authoring.genspec import parse_genspec
from seedwright_authoring.imported import ImportedSchema
from seedwright_authoring.loop import author
from seedwright_authoring.provider import ProposeRequest
from seedwright_authoring.rules import RuleSet
from seedwright_authoring.validate import validate_genspec

from seedwright_data_engine.heuristic import HeuristicProvider

IMPORTED = {
    "customers": [("id", "bigint"), ("email", "varchar(255)"), ("tier", "varchar(20)"),
                  ("balance", "numeric(12,2)")],
    "orders": [("id", "bigint"), ("customer_id", "bigint"), ("total", "numeric(10,2)")],
}
PKS = {"customers": ["id"], "orders": ["id"]}
FKS = {
    "orders": [{"column": "customer_id", "references_table": "customers",
                "references_column": "id", "min_per_parent": 0, "max_per_parent": 5}],
}
RULES = [
    {"table": "customers", "column": "tier", "enum": ["free", "pro"]},
    {"table": "orders", "column": "total", "min_value": "1.00", "max_value": "500.00"},
]


def _provider() -> HeuristicProvider:
    return HeuristicProvider(foreign_keys=FKS, volumes={"customers": 50}, seed=7)


def _request() -> ProposeRequest:
    imported = ImportedSchema.from_sql_columns(IMPORTED, primary_keys=PKS)
    return ProposeRequest(imported, RuleSet.from_dicts(RULES), prior_genspec=None, feedback=())


def test_proposal_is_a_valid_genspec() -> None:
    genspec = parse_genspec(_provider().propose(_request()).genspec)
    imported = ImportedSchema.from_sql_columns(IMPORTED, primary_keys=PKS)
    assert validate_genspec(genspec, imported) == []


def test_generator_choices() -> None:
    spec = parse_genspec(_provider().propose(_request()).genspec)
    customers = spec.table("customers")
    by_name = {c.name: c for c in customers.columns}
    assert by_name["id"].generator.kind == "serial"
    assert by_name["email"].generator.kind == "faker"
    assert by_name["email"].generator.params["method"] == "email"
    assert by_name["tier"].generator.kind == "categorical"
    assert by_name["tier"].generator.params["values"] == ["free", "pro"]
    balance = by_name["balance"].generator
    assert balance.kind == "decimal_range"
    assert balance.params["scale"] == 2  # from the imported numeric(12,2)

    orders = spec.table("orders")
    fk_col = next(c for c in orders.columns if c.name == "customer_id")
    assert fk_col.generator.kind == "fk"
    assert orders.row_count is None  # driving-FK child
    total = next(c for c in orders.columns if c.name == "total").generator
    assert (total.params["low"], total.params["high"]) == ("1.00", "500.00")  # from the rule


def test_volumes_and_seed_applied() -> None:
    spec = parse_genspec(_provider().propose(_request()).genspec)
    assert spec.table("customers").row_count == 50
    assert spec.seed == 7


def test_proposal_is_deterministic() -> None:
    assert _provider().propose(_request()).genspec == _provider().propose(_request()).genspec


def test_full_authoring_loop_accepts_the_heuristic() -> None:
    imported = ImportedSchema.from_sql_columns(IMPORTED, primary_keys=PKS)
    artifacts = author(imported, RuleSet.from_dicts(RULES), _provider())
    assert artifacts.provenance.iterations == 1
    assert artifacts.provenance.determinism_gate_passed


def test_compiles_and_declares_capabilities() -> None:
    provider = _provider()
    assert provider.capabilities().structured_json_output is True
    imported = ImportedSchema.from_sql_columns(IMPORTED, primary_keys=PKS)
    compile_to_genlib(parse_genspec(provider.propose(_request()).genspec), imported)
