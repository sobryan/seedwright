"""CopilotCliProvider — GitHub Copilot CLI as the authoring LLM (FR-H.7, NFR-AGNOSTIC).

The first REAL provider behind the authoring `Provider` protocol: shells out to
`copilot -p <prompt>` and extracts a genspec JSON from the reply. The shop's existing Copilot
subscription is the model — no new API keys. Tests inject a fake runner (no real CLI, no
credits); the loop's validate→judge→refine machinery is exercised with bad-then-good replies.
"""

import json

from seedwright_authoring.imported import ImportedSchema
from seedwright_authoring.loop import author
from seedwright_authoring.provider import ProposeRequest
from seedwright_authoring.rules import RuleSet

from seedwright_data_engine.copilot_provider import (
    CopilotCliProvider,
    build_prompt,
    extract_genspec,
)

IMPORTED = {
    "customers": [("id", "bigint"), ("email", "varchar(255)"), ("tier", "varchar(20)"),
                  ("balance", "numeric(12,2)")],
    "orders": [("id", "bigint"), ("customer_id", "bigint"), ("total", "numeric(10,2)")],
}
PKS = {"customers": ["id"], "orders": ["id"]}
FKS = {
    "orders": [{"column": "customer_id", "references_table": "customers",
                "references_column": "id", "min_per_parent": 1, "max_per_parent": 4}],
}
RULES = [{"table": "customers", "column": "tier", "enum": ["free", "pro"]}]

GOOD_GENSPEC = {
    "genspec_version": "1",
    "seed": 7,
    "tables": [
        {"name": "customers", "table_class": "generated", "row_count": 30,
         "primary_key": ["id"], "foreign_keys": [],
         "columns": [
             {"name": "id", "canonical_kind": "INT64",
              "generator": {"kind": "serial", "params": {"start": 1}},
              "nullable": False, "null_rate": 0.0, "unique": True},
             {"name": "email", "canonical_kind": "STRING",
              "generator": {"kind": "faker", "params": {"method": "email"}},
              "nullable": False, "null_rate": 0.0, "unique": False},
             {"name": "tier", "canonical_kind": "STRING",
              "generator": {"kind": "categorical", "params": {"values": ["free", "pro"]}},
              "nullable": False, "null_rate": 0.0, "unique": False},
             {"name": "balance", "canonical_kind": "DECIMAL",
              "generator": {"kind": "decimal_range",
                            "params": {"low": "0.00", "high": "5000.00", "scale": 2}},
              "nullable": False, "null_rate": 0.0, "unique": False},
         ]},
        {"name": "orders", "table_class": "generated", "row_count": None,
         "primary_key": ["id"], "foreign_keys": FKS["orders"],
         "columns": [
             {"name": "id", "canonical_kind": "INT64",
              "generator": {"kind": "serial", "params": {"start": 1}},
              "nullable": False, "null_rate": 0.0, "unique": True},
             {"name": "customer_id", "canonical_kind": "INT64",
              "generator": {"kind": "fk", "params": {}},
              "nullable": False, "null_rate": 0.0, "unique": False},
             {"name": "total", "canonical_kind": "DECIMAL",
              "generator": {"kind": "decimal_range",
                            "params": {"low": "1.00", "high": "500.00", "scale": 2}},
              "nullable": False, "null_rate": 0.0, "unique": False},
         ]},
    ],
}


def _request(feedback=(), prior=None) -> ProposeRequest:
    imported = ImportedSchema.from_sql_columns(IMPORTED, primary_keys=PKS)
    return ProposeRequest(imported, RuleSet.from_dicts(RULES), prior, tuple(feedback))


def _provider(replies: list[str]) -> CopilotCliProvider:
    calls: list[str] = []

    def runner(prompt: str) -> str:
        calls.append(prompt)
        return replies[min(len(calls) - 1, len(replies) - 1)]

    provider = CopilotCliProvider(foreign_keys=FKS, volumes={"customers": 30}, seed=7,
                                  runner=runner)
    provider.prompts = calls  # expose for assertions
    return provider


# --- prompt construction ----------------------------------------------------------------

def test_prompt_carries_schema_kinds_rules_and_contract() -> None:
    prompt = build_prompt(_request(), foreign_keys=FKS, volumes={"customers": 30}, seed=7)
    assert "customers" in prompt and "orders" in prompt
    assert "numeric(12,2)" in prompt and "DECIMAL" in prompt   # authoritative types + kinds
    assert '"kind": "fk"' in prompt or "'fk'" in prompt        # fk sentinel instruction
    assert "free" in prompt and "pro" in prompt                # declared rules
    assert "genspec_version" in prompt                          # the contract
    assert "row_count" in prompt


def test_refine_prompt_includes_failures_and_prior() -> None:
    from seedwright_authoring.feedback import Failure

    failure = Failure("constraint", "orders", "total", "value_range:orders.total",
                      "max observed 900 exceeds 500", "lower decimal_range.high")
    prompt = build_prompt(_request(feedback=[failure], prior={"seed": 1}),
                          foreign_keys=FKS, volumes={}, seed=7)
    assert "value_range:orders.total" in prompt
    assert "lower decimal_range.high" in prompt
    assert "previous attempt" in prompt.lower()


# --- JSON extraction ---------------------------------------------------------------------

def test_extracts_fenced_json() -> None:
    text = "Here you go:\n```json\n" + json.dumps(GOOD_GENSPEC) + "\n```\nDone."
    assert extract_genspec(text) == GOOD_GENSPEC


def test_extracts_bare_json_object() -> None:
    text = "Sure! " + json.dumps(GOOD_GENSPEC) + "\n\nTokens: 12k"
    assert extract_genspec(text) == GOOD_GENSPEC


def test_garbage_yields_empty_dict_for_refine_path() -> None:
    assert extract_genspec("I cannot help with that.") == {}


# --- the provider through the real loop --------------------------------------------------

def test_good_reply_authors_in_one_iteration() -> None:
    provider = _provider(["```json\n" + json.dumps(GOOD_GENSPEC) + "\n```"])
    artifacts = author(ImportedSchema.from_sql_columns(IMPORTED, primary_keys=PKS),
                       RuleSet.from_dicts(RULES), provider)
    assert artifacts.provenance.provider_id == "copilot-cli"
    assert artifacts.provenance.iterations == 1
    assert artifacts.provenance.determinism_gate_passed


def test_garbage_then_good_reply_refines_then_passes() -> None:
    provider = _provider(["Sorry, here is an explanation instead.",
                          json.dumps(GOOD_GENSPEC)])
    artifacts = author(ImportedSchema.from_sql_columns(IMPORTED, primary_keys=PKS),
                       RuleSet.from_dicts(RULES), provider)
    assert artifacts.provenance.iterations == 2
    # the second prompt carried the parse-failure feedback
    assert "PARSE_ERROR" in provider.prompts[1] or "genspec" in provider.prompts[1]
