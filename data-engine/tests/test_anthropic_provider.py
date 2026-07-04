"""Anthropic API as a second real authoring provider (NFR-AGNOSTIC).

Proves provider-independence: the same loop, prompt, and extraction that back the Copilot CLI
provider work behind a different transport (the Anthropic Messages API). The HTTP call is behind
an injectable runner, so every test here is offline — no network, no API key.
"""

import json

from seedwright_data_engine.anthropic_provider import (
    AnthropicProvider,
    build_request,
    parse_reply,
)
from seedwright_data_engine.engine import run_author

SCHEMA = {
    "customers": {
        "columns": [
            {"name": "id", "sql_type": "bigint"},
            {"name": "tier", "sql_type": "varchar(20)"},
        ],
        "primary_key": ["id"],
    },
}
RULES = [{"table": "customers", "column": "tier", "enum": ["free", "pro"]}]

GOOD_GENSPEC = {
    "genspec_version": "1",
    "seed": 7,
    "tables": [{
        "name": "customers",
        "table_class": "generated",
        "row_count": 10,
        "primary_key": ["id"],
        "foreign_keys": [],
        "columns": [
            {"name": "id", "canonical_kind": "INT64",
             "generator": {"kind": "serial", "params": {"start": 1}},
             "nullable": False, "null_rate": 0.0, "unique": True},
            {"name": "tier", "canonical_kind": "STRING",
             "generator": {"kind": "categorical", "params": {"values": ["free", "pro"]}},
             "nullable": False, "null_rate": 0.0, "unique": False},
        ],
    }],
}


def test_provider_identity_and_capabilities() -> None:
    provider = AnthropicProvider(seed=7, runner=lambda _p: "")
    assert provider.provider_id == "anthropic"
    assert provider.capabilities().structured_json_output is True


def test_build_request_targets_the_messages_api() -> None:
    req = build_request("hello prompt", model="claude-sonnet-5", api_key="sk-test", max_tokens=2048)
    assert req["url"] == "https://api.anthropic.com/v1/messages"
    assert req["headers"]["x-api-key"] == "sk-test"
    assert req["headers"]["anthropic-version"]  # version pin present
    body = json.loads(req["body"])
    assert body["model"] == "claude-sonnet-5"
    assert body["max_tokens"] == 2048
    assert body["messages"][0]["role"] == "user"
    assert "hello prompt" in body["messages"][0]["content"]


def test_parse_reply_extracts_text_content() -> None:
    api_json = json.dumps({"content": [{"type": "text", "text": "```json\n{\"ok\": 1}\n```"}]})
    assert "```json" in parse_reply(api_json)


def test_parse_reply_survives_unexpected_shape() -> None:
    # a malformed/blocked reply must not crash — the loop refines on an empty genspec
    assert parse_reply("{}") == ""
    assert parse_reply("not json at all") == ""


def test_propose_returns_parsed_genspec() -> None:
    reply = json.dumps({"content": [{"type": "text",
                                     "text": "```json\n" + json.dumps(GOOD_GENSPEC) + "\n```"}]})
    provider = AnthropicProvider(seed=7, runner=lambda _prompt: reply)
    from seedwright_authoring.provider import ProposeRequest
    from seedwright_authoring.rules import RuleSet

    from seedwright_data_engine.engine import _imported_schema

    imported = _imported_schema(SCHEMA)
    request = ProposeRequest(imported=imported, rules=RuleSet.from_dicts(RULES),
                             prior_genspec=None, feedback=())
    response = provider.propose(request)
    assert response.genspec["tables"][0]["name"] == "customers"


def test_run_author_end_to_end_with_injected_runner() -> None:
    reply = json.dumps({"content": [{"type": "text",
                                     "text": "```json\n" + json.dumps(GOOD_GENSPEC) + "\n```"}]})
    artifacts = run_author(schema=SCHEMA, rules=RULES, volumes={"customers": 10}, seed=7,
                           provider="anthropic", _anthropic_runner=lambda _p: reply)
    assert artifacts["version"].startswith("ga_")
    assert artifacts["provenance"]["provider_id"] == "anthropic"
    assert artifacts["provenance"]["approval_status"] == "pending_approval"
