# Journal — Slice 2: Postgres loader (complete)

**Date:** 2026-07-01 · **Status:** ✅ complete · **Tests:** 122 passing + 5 integration (skippable) · ruff + mypy-strict clean

Turns the Canonical Dataset (Parquet) + Load Plan (JSON) into a **scoped, idempotent, reversible** Postgres load + teardown (spec FR-G, FR-L, FR-M.4). Consumes only Parquet + JSON — no dependency on the generation library (the seam is the future MCP contract).

## How it was built

1. **Design fan-out (workflow `wf_7292097b`, 7 agents).** Six parallel facet designs (type mapping, COPY bulk-load, namespace scoping, teardown safety, injection safety, loader contract) + an adversarial architecture critic. The critic caught real cross-facet contradictions (namespace prefix `sw_` vs `ds_` vs none; COPY text vs binary; `replace` = TRUNCATE vs DROP+recreate) and over-engineering (a `source_sql` parser, PK/UNIQUE/FK DDL against a Load Plan that doesn't carry them yet). Reconciled into `docs/decisions/0002-postgres-loader-design.md`.
2. **Bottom-up TDD** in the critic's build order — `safesql` → `pgtypes` → `plan` → `ddl` → `copy` → `results` → `typecheck` → `executor`. RED→GREEN each, full suite green every step.
3. **Adversarial safety review (workflow `wf_84a872fa`, 7 agents).** Six attackers (unscoped-destruction, injection, marker-bypass, COPY-corruption, idempotency/atomicity, plan-trust) + triage. Since the executor can't run without Postgres here, this substituted for live execution.

## Modules

| Module | Responsibility | Layer |
|---|---|---|
| `safesql` | `validate_namespace` (`ds_` prefix, denylist, ≤63B), `identifier`/`qualified` (psycopg-safe), `validate_relname` (path-segment safety), `namespace_for` (collision-free) | pure |
| `pgtypes` | canonical_kind → Postgres type (decimal never float, tz, jsonb, varchar/text) | pure |
| `plan` | Load-Plan JSON → frozen dataclasses; validate + forward-compat | pure |
| `ddl` | `create_schema`/`drop_schema` (always `IF EXISTS CASCADE`)/`create_table` (NOT NULL only)/marker | pure |
| `copy` | COPY text encoder — null sentinel, escaping, decimals, timestamptz, bytea, float specials | pure |
| `typecheck` | plan/Parquet Arrow type-agreement guard | pure |
| `results` | Load/Teardown/Verification result records + `to_dict()` | pure |
| `executor` | psycopg orchestration: scoped load/teardown, marker-guarded drop, one txn (`search_path=''`+UTC), pre-commit row-count verify | integration |

## Safety properties proven (offline)

Injection payloads neutralized (`a"; DROP…` → `"a""; DROP…"`); teardown SQL always `IF EXISTS` + never table-level; marker guard refuses foreign schemas (pure decision unit-tested); decimal never float; COPY null-vs-empty, NUL-rejection, escaping, bytea/timestamptz/float-special encoding; plan/Parquet type-agreement.

## Adversarial review → fixes (all TDD'd)

| Sev | Finding | Fix |
|---|---|---|
| HIGH | `table.name` (untrusted) used verbatim as a filesystem path → `../../x` escapes canonical dir (SQL was safe; file read was not) | `validate_relname` + `resolve_table_parquet` with containment assert |
| MED | DECIMAL precision-without-scale → `numeric(p,0)` silently rounds cents past the type-agreement guard | type-agreement now requires field scale == 0 when scale absent-but-precision-present |
| MED | `load_dataset` committed without the promised pre-commit row-count check | `_verify_before_commit` inside the txn → mismatch rolls back (`MaterializationError`) |
| LOW | `namespace_for` truncated to 63B → long similar ids collide → one Dataset's `replace` drops another's schema | append a BLAKE2b digest of the full id (collision-free within 63B) |

Correctly **rejected** by triage: the intentional prefix-match ownership marker (design-consistent) and a duplicate.

## Known limitations (deferred with intent)

Constraint DDL (PK/UNIQUE/FK), `source_sql` parsing, batched-INSERT fallback, `TRUNCATE`, `append` mode, `timetz`, partitioned multi-file Parquet, checksum verification, least-privilege role provisioning. All fidelity/robustness, not MVP correctness. Integration tests need a live Postgres (`SEEDWRIGHT_TEST_PG_DSN`); Docker was unavailable here, so they auto-skip.

## Next: Slice 3 — authoring loop with a mock provider (sub-project B), or wire a live Postgres to run the integration suite for real.
