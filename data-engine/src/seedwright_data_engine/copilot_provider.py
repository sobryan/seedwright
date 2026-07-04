"""GitHub Copilot CLI as the authoring LLM (FR-H.7, NFR-AGNOSTIC).

The first real provider behind the authoring loop's ``Provider`` protocol. It shells out to the
``copilot`` CLI in headless mode (``copilot -p <prompt>``) — the shop's existing Copilot
subscription is the authoring model; no new API keys, nothing leaves the machines they already
trust with code. The reply's genspec JSON is extracted best-effort; anything unparseable becomes
an empty genspec, which the loop turns into PARSE_ERROR refine feedback — Copilot gets its own
mistakes back and fixes them (the evaluator-optimizer working as designed, §3A).

Authoring is the non-deterministic phase by design; execution stays deterministic regardless of
what model wrote the genspec (the §3 keystone).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from collections.abc import Callable
from typing import Any

from seedwright_authoring.capability import Capabilities
from seedwright_authoring.provider import ProposeRequest, ProposeResponse

DEFAULT_TIMEOUT_SECONDS = 180

_FENCED_JSON = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)

_CONTRACT = """\
Respond with ONLY a fenced ```json code block containing a genspec object — no prose.

The genspec contract:
{
  "genspec_version": "1",
  "seed": <int>,
  "tables": [{
    "name": "<table>",
    "table_class": "generated",
    "row_count": <int, or null ONLY for a table whose foreign key references another generated
                  table (its row count is derived from per-parent cardinality)>,
    "primary_key": ["<col>"],
    "foreign_keys": [<copy the declared foreign keys for this table verbatim>],
    "columns": [{
      "name": "<col>",
      "canonical_kind": "<MUST equal the column's canonical kind listed below>",
      "generator": {"kind": "<kind>", "params": {...}},
      "nullable": false, "null_rate": 0.0, "unique": <true for primary-key columns>
    }]
  }]
}

Generator catalog (the ONLY kinds allowed, with type compatibility):
- serial {"start": int} — integer columns; REQUIRED for integer primary keys
- int_range {"low": int, "high": int} — integer columns
- decimal_range {"low": "<str>", "high": "<str>", "scale": int} — DECIMAL columns;
  scale MUST equal the column's scale; low/high are strings, low <= high
- categorical {"values": [...], "weights": [optional floats]} — strings/ints/booleans;
  use the rule's enum values verbatim when a rule declares one
- faker {"method": "<faker method like email, name, word>"} — STRING/UUID/JSON columns
- date_range {"low": "YYYY-MM-DD", "high": "YYYY-MM-DD"} — DATE columns
- timestamp_range {"low": "YYYY-MM-DDTHH:MM:SS", "high": "...", "tz": bool} — TIMESTAMP
  columns; bounds are naive ISO datetimes; tz MUST equal the column's tz (true only for
  'timestamp with time zone' columns)
- {"kind": "fk", "params": {}} — REQUIRED for every declared foreign-key column, and for
  no other column

Honor every declared rule (enum -> categorical with those exact values; min/max -> generator
bounds within them). Use the requested per-table row counts. Every table and every column listed
below must appear.
"""


def build_prompt(
    request: ProposeRequest,
    *,
    foreign_keys: dict[str, list[dict[str, Any]]] | None,
    volumes: dict[str, int] | None,
    seed: int,
) -> str:
    foreign_keys = foreign_keys or {}
    volumes = volumes or {}
    lines: list[str] = [
        "You are the authoring model for seedwright, a synthetic-data generator.",
        "Design a generator spec (genspec) for the database schema below.",
        "",
        f"Use seed {seed}.",
        "",
        "SCHEMA (authoritative column types and canonical kinds):",
    ]
    for table in request.imported.tables:
        pk = ", ".join(table.primary_key) or "-"
        lines.append(f"- table {table.name} (primary key: {pk}, "
                     f"row_count: {volumes.get(table.name, 100)})")
        for col in table.columns:
            lines.append(f"    {col.name}: {col.type.source_sql or col.type.kind.name} "
                         f"-> canonical_kind {col.type.kind.name}")
        for fk in foreign_keys.get(table.name, []):
            lines.append(f"    FOREIGN KEY {fk['column']} -> "
                         f"{fk['references_table']}.{fk['references_column']} "
                         f"(min_per_parent {fk.get('min_per_parent', 0)}, "
                         f"max_per_parent {fk.get('max_per_parent', 1)}) "
                         f"-> declare in foreign_keys and give the column "
                         '{"kind": "fk", "params": {}}')

    if request.rules.rules:
        lines += ["", "DECLARED RULES (must hold in the generated data):"]
        for rule in request.rules.rules:
            parts = []
            if rule.enum:
                parts.append(f"enum {list(rule.enum)}")
            if rule.min_value is not None:
                parts.append(f"min {rule.min_value}")
            if rule.max_value is not None:
                parts.append(f"max {rule.max_value}")
            lines.append(f"- {rule.table}.{rule.column}: {', '.join(parts)}")

    if request.prior_genspec is not None or request.feedback:
        lines += ["", "YOUR PREVIOUS ATTEMPT FAILED. Fix it."]
        if request.feedback:
            lines.append("Failures to address:")
            for failure in request.feedback:
                lines.append(f"- [{failure.test_id}] {failure.detail} -> {failure.feedback}")
        if request.prior_genspec is not None:
            lines.append("Previous attempt (revise this):")
            lines.append(json.dumps(request.prior_genspec))

    lines += ["", _CONTRACT]
    return "\n".join(lines)


def extract_genspec(text: str) -> dict[str, Any]:
    """Best-effort genspec extraction; ``{}`` on failure so the loop refines, never crashes."""
    fenced = _FENCED_JSON.search(text)
    if fenced:
        try:
            parsed = json.loads(fenced.group(1))
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
    start = text.find("{")
    end = text.rfind("}")
    if 0 <= start < end:
        try:
            parsed = json.loads(text[start : end + 1])
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
    return {}


def _run_copilot(prompt: str, *, timeout: int = DEFAULT_TIMEOUT_SECONDS) -> str:
    """Invoke the Copilot CLI headless. Requires an authenticated `copilot` (or GH_TOKEN)."""
    env = dict(os.environ)
    env.setdefault("NO_COLOR", "1")
    result = subprocess.run(
        ["copilot", "-p", prompt],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
        check=False,
    )
    if result.returncode != 0 and not result.stdout.strip():
        raise RuntimeError(
            f"copilot CLI failed (exit {result.returncode}): {result.stderr.strip()[:500]}"
        )
    return result.stdout


class CopilotCliProvider:
    """Authoring provider backed by the GitHub Copilot CLI (headless)."""

    provider_id = "copilot-cli"

    def __init__(
        self,
        *,
        foreign_keys: dict[str, list[dict[str, Any]]] | None = None,
        volumes: dict[str, int] | None = None,
        seed: int = 42,
        runner: Callable[[str], str] | None = None,
        timeout: int = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._foreign_keys = foreign_keys
        self._volumes = volumes
        self._seed = seed
        self._runner = runner or (lambda prompt: _run_copilot(prompt, timeout=timeout))

    def capabilities(self) -> Capabilities:
        return Capabilities(structured_json_output=True)

    def propose(self, request: ProposeRequest) -> ProposeResponse:
        prompt = build_prompt(request, foreign_keys=self._foreign_keys,
                              volumes=self._volumes, seed=self._seed)
        reply = self._runner(prompt)
        return ProposeResponse(genspec=extract_genspec(reply))
