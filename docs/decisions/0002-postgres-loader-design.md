# ADR 0002 — Postgres loader (Slice 2) design

**Date:** 2026-07-01
**Status:** Accepted
**Method:** Design produced by a 6-facet parallel design fan-out + an adversarial architecture critic (workflow `wf_7292097b`, 7 agents). This ADR records the *reconciled* design — the critic caught cross-facet contradictions and over-engineering, which are resolved here.

## Architecture

The loader (`postgres-loader/`, package `seedwright_pgloader`) consumes a **Canonical Dataset** (Parquet, one file/table) + a **Load Plan** (JSON from genlib's `loadplan.to_dict()`). It does **not** import the generation library — the seam is Parquet + JSON, matching the future MCP contract.

Two layers:
- **Pure SQL-generation** — offline, deterministic, unit-tested. Renders SQL via `psycopg.sql` Composables (`.as_string(None)`), which is injection-safe and needs no DB server. (`psycopg[binary]` is a base dep; libpq is bundled, so offline unit tests need no system Postgres.)
- **psycopg executor** — integration, `@pytest.mark.integration`, auto-skipped unless `SEEDWRIGHT_TEST_PG_DSN` points at a reachable server.

## Reconciled decisions (the load-bearing ones)

1. **Isolation = dedicated schema per Dataset, mandatory `ds_` prefix.** One `validate_namespace()` in one module (`safesql`), used by *every* builder. Rule: `^ds_[a-z0-9_]+$`, ≤63 UTF-8 bytes, reserved denylist (`public`, `pg_catalog`, `information_schema`, `pg_toast`, `pg_*`). The prefix is what makes collision with a real application schema structurally impossible — so `DROP SCHEMA ds_… CASCADE` can never hit `public`.
2. **All identifiers via `psycopg.sql.Identifier`; integers via `sql.Literal`.** Never f-string/`%` into SQL. Untrusted table/column names (imported schema) are thereby neutralized (verified: `a"; DROP TABLE…` → `"a""; DROP TABLE…"`).
3. **DDL = columns + `NOT NULL` only.** No PK/UNIQUE/FK constraint DDL in MVP — genlib already generates referentially-valid data by construction (FR-E.3), so DB constraints are *fidelity*, not correctness. Also, `build_load_plan` does not yet emit PK/UNIQUE/FK (uniqueness is folded into `nullable`), so constraint DDL would be untestable end-to-end. Deferred to a later slice once the Load Plan carries them.
4. **Type mapping from `canonical_kind` + structured fields only; `source_sql` ignored for DDL.** Injection-proof and simpler. `DECIMAL`→`numeric(p,s)` (bare→`numeric(38,9)`), never float; `TIMESTAMP` tz→`timestamptz` else `timestamp`; `TIME`→`time` regardless of tz (Arrow `time64` carries no zone — `timetz` would be nondeterministic; documented); `JSON`→`jsonb`; `STRING`→`varchar(n)`/`text` (never `char`, which space-pads); `UUID`→`uuid`; `BYTES`→`bytea`. Unknown kind raises.
5. **Bulk load = COPY, text format.** Manual per-type encoder (deterministic, offline-testable): `\N` null sentinel; `Decimal` via `str` (no float path); `timestamptz` with explicit `+00:00`; `bytea` `\x…` hex; float `Infinity`/`-Infinity`/`NaN` tokens; empty-string ≠ `\N`; embedded TAB/newline/backslash escaped; NUL byte raises. No batched-INSERT fallback (single role, COPY always available).
6. **Modes:** `create` (strict — fail loud if the schema exists) and `replace` (idempotent default = `DROP SCHEMA IF EXISTS … CASCADE` + `CREATE SCHEMA` + `CREATE TABLE`s + COPY, one transaction). No `append`, no `TRUNCATE`.
7. **Teardown = `DROP SCHEMA IF EXISTS <ns> CASCADE`** (idempotent — absent namespace is a no-op success, FR-L.6). Provably scoped: a single schema-qualified drop, never a table-level `DROP`/`DELETE`.
8. **Ownership marker guard (the runtime safety net).** At create: `COMMENT ON SCHEMA <ns> IS 'seedwright:<ns>'`. Before *any* drop (replace/teardown): read `obj_description` and refuse (`ForeignSchemaError`) if the schema isn't seedwright-marked. Since least-privilege role provisioning is deferred, this + the `ds_` prefix are the guards for FR-L.3.
9. **Executor hygiene:** one transaction; `SET LOCAL search_path = ''` (unqualified reference → error; doubles as a leak test) and `TimeZone = 'UTC'`; stream `ParquetFile.iter_batches()` → encode → `cursor.copy`; **plan/Parquet type-agreement guard** (re-derive expected Arrow type from `canonical_kind`, assert the Parquet field matches before COPY — catches a plan that mislabels a column); row-count verification before commit (FR-F.1c), treating the Parquet as source of truth (plan `row_count` advisory).

## MVP cuts (deferred with intent)

Constraint DDL (PK/UNIQUE/FK), `source_sql` parsing, batched-INSERT fallback, `TRUNCATE`, `append` mode, `timetz`, partitioned multi-file Parquet, checksum/spot-check verification, least-privilege role provisioning. Each is fidelity/robustness, not MVP correctness.

## TDD build order (each module: pure, offline, RED→GREEN→REFACTOR, full suite each)

1. `safesql` — `validate_namespace`, `safe_identifier`, `qualified_table`. Injection keystone.
2. `pgtypes` — `column_type(kind, precision, scale, length, tz)`. All 14 kinds; unknown raises.
3. `plan` — `parse_plan(dict)` → loader-local frozen dataclasses (no genlib import).
4. `ddl` — `create_schema_sql`, `schema_marker_sql`, `create_table_sql` (NOT NULL only), `drop_schema_sql` (always `IF EXISTS … CASCADE`).
5. `copy` — `encode_value`, `encode_batch`, `copy_sql`. In-memory Arrow batch tests.
6. `results` — `LoadResult`/`TeardownResult`/`VerificationResult` dataclasses + `to_dict()`.
7. `executor` (integration, last) — `load_dataset`/`teardown_dataset`/`verify_materialization`, marker-guarded, `@pytest.mark.integration`.

## Critical tests carried from the critique

Offline-render test (no libpq server); teardown SQL always contains `IF EXISTS`; one `validate_namespace` rejects the same bad set from every entry point; adversarial identifier neutralization; plan/Parquet type-agreement guard; COPY encoding edges (empty vs `\N`, NUL raises, decimal trailing-zero scale, `timestamptz +00:00`, empty `bytea` `\x` vs NULL, float specials, TAB/newline escaping); reload idempotency as multiset-equal (not byte-identical heap order); marker-guard raises `ForeignSchemaError` on an unmarked schema.
