# Journal — Slices 4–7: the on-prem topology (complete, proven live)

**Date:** 2026-07-01/02 · **Status:** ✅ all four components built, live end-to-end verified

ADR-0004 fixed the on-prem shape: **one central Spring Boot server** (H2 file metadata that
persists sudden restarts) + **a Python MCP data-engine** (stdio) + **a Java JDBC Spring MCP
server** (Streamable HTTP) + **Next.js UI** (static export).

## What was built

| Slice | Component | Tests | Notes |
|---|---|---|---|
| 4 | `data-engine/` (Python 3.12, FastMCP/stdio) | 21 | `author_generator` / `generate_dataset` / `validate_dataset` / `export_dataset` (new CSV/JSONL/SQL file sink) / `load_postgres` / `teardown_postgres`. Includes the **HeuristicProvider** — a deterministic no-LLM authoring provider (serial for int PKs, fk sentinel, decimal_range at authoritative scale, enum→categorical, name-hinted Faker) that passes the full loop + determinism gate in one iteration. Makes the product work offline with zero API keys. |
| 5 | `server/` (Java 21, Spring Boot 3.5) | 4 | REST (202+Job), H2 file store, virtual-thread JobManager (bounded, orphan reconciliation), MCP client (SDK 2.0) spawning the data-engine. Includes a **live Java↔Python stdio MCP test**. |
| 6 | `jdbc-mcp/` (Java 21, Spring Boot) | 26 | MCP tools `introspect_schema` (emits exactly the shape `author_generator` consumes), `load_dataset` (JSONL+plan → DDL + batched inserts, one txn, pre-commit row-count verify), `teardown_dataset` (marker-table-guarded), `verify_materialization`. Mirrors the Python loader's safety invariants. Credentials are node-local named connections (spec §7). |
| 7 | `ui/` (Next.js static export) | build ✓ | Blueprint create (prefilled demo) → generate → poll job → dataset status → export. No runtime Node in production. |

## Live end-to-end proof (real processes, no fakes)

1. `mvn spring-boot:run` booted the central server; it **spawned the real Python data-engine
   over stdio MCP**.
2. `POST /api/blueprints` (customers/orders demo) → `POST /blueprints/{id}/datasets` → job
   **succeeded in 1.3 s**: heuristic authoring → deterministic generation → validation (6
   data-tests) → dataset `ready`, 100 customers + 249 orders (cardinality-derived).
3. `POST /datasets/{id}/export` → real CSV/JSONL/SQL files on disk beside the canonical
   Parquet + Load Plan.
4. **`kill -9` the JVM → restart → blueprint (with cached `ga_…` artifacts) and the ready
   dataset were still there.** The headline persistence requirement, proven literally.

## Issue found & fixed during verification

`PersistenceAcrossRestartTest` used `SpringApplicationBuilder.properties(...)`, which sets
*default* properties that `application.yml` overrides — so the test silently ran against
`./data` instead of its temp dir (leaking a `survives` blueprint into the dev DB). Fixed by
passing command-line args (highest precedence) to `.run(...)`. Lesson recorded: builder
`.properties()` ≠ overrides.

## Slice 8 — the DB-sink path (added after slices 4–7, proven live)

The central server now commands the jdbc-mcp node over **live Streamable HTTP MCP**
(`HttpClientStreamableHttpTransport`): `GET /api/connections` (names only — credentials stay on
the node), `POST /api/connections/{name}/introspect` (feeds Blueprint creation), and gated
`POST /api/datasets/{id}/materialize|teardown` (FR-G.4: `confirm:true` required, 400 without).
Materialize job = export JSONL via the data-engine → `load_dataset` on the node → verify →
per-sink record on the Dataset. UI grew a connection picker + load/teardown controls.

**Live three-process proof:** central server + data-engine (stdio MCP) + jdbc-mcp (HTTP MCP)
with a `demo` H2 target ("their DB"): unconfirmed request refused (400) → confirmed
materialize succeeded (**349 rows, verified**) → introspection of the target showed
`customers`/`orders` + the `_seedwright` marker inside the `ds_…` schema → teardown → target
clean. One real bug found and fixed by the live run: the server handed **relative** work-dir
paths across process boundaries (fine for the stdio child sharing its cwd, broken for the
separate jdbc-mcp process) — now absolutized at the boundary.

## Slice 9 — agent integration: seedwright as an MCP server (GitHub Copilot CLI first)

The central server now exposes the **product surface as MCP tools at `/mcp`** (Streamable
HTTP): `list_connections`, `introspect_connection`, `create_blueprint`, `list_blueprints`,
`generate_dataset` (waits for the job), `get_job`, `list_datasets`, `get_dataset`,
`export_dataset`, and confirm-gated `materialize_dataset`/`teardown_dataset` (FR-G.4 holds for
agents: refused without `confirm=true`; tool descriptions instruct the agent to ask its human).
Blueprint creation extracted to `BlueprintService`, shared by REST and MCP. Tested with a REAL
MCP client over HTTP (`ProductMcpEndpointTest`, server suite 9/9).

**Live proof with the actual integration target:** installed GitHub Copilot CLI (1.0.68),
registered seedwright in `~/.copilot/mcp-config.json` (`type: http`, `url:
http://localhost:8080/mcp`), and drove it headless: Copilot created the `copilot-shop`
blueprint (FK topology + rules), generated + validated a dataset (50 customers, 114 orders,
6/6 data-tests), materialized into the `demo` connection with explicit confirmation (164 rows,
verified), and introspected the target to confirm `customers`/`orders`/`_seedwright` inside the
`ds_…` schema — the complete product lifecycle from a third-party agent in ~19s.
Integration guide: `docs/integrations/copilot-cli.md` (same endpoint works for Claude Code,
VS Code, Cursor — it's standard MCP).

## Slice 10 — Copilot CLI as the authoring LLM + one-command quickstart

**`CopilotCliProvider`** (data-engine): the first REAL provider behind the authoring `Provider`
protocol — shells out to `copilot -p <prompt>` headless. The prompt carries the authoritative
schema (SQL types + canonical kinds), declared rules, FK topology, volumes, and the frozen
genspec contract + generator catalog; on refine it feeds Copilot its own failures back. JSON is
extracted best-effort (fenced → brace-scan → `{}`), and an unparseable reply becomes PARSE_ERROR
refine feedback rather than a crash — the evaluator-optimizer working as designed (§3A). The
shop's existing Copilot subscription is the model: **no new API keys**. Provider selection
(`heuristic` default | `copilot-cli`) threads through the whole stack: data-engine tool → V3
migration + BlueprintEntity → REST + product-MCP `create_blueprint` → UI select. data-engine
30/30 (fake-runner tests incl. garbage-then-good refinement), server 9/9.

**Live proof:** `./quickstart.sh` (new: builds data-engine + UI + both jars, starts the stack,
serves the UI static export from the server at `/`) → blueprint with `provider: copilot-cli` →
generation job: the data-engine spawned the real `copilot`, which authored a genspec that passed
validation, the judge, and the determinism gate → dataset ready (100 customers / 249 orders,
validation passed). Notably the artifact hash matched the heuristic's (`ga_16aee0eeb7…`) —
Copilot converged on the identical canonical genspec, independently confirming that execution is
provider-independent (the §3 keystone).

## Slice 11 — temporal generators + DB2 dialect + drop-in driver jars

**11A (the biggest real-schema gap, closed):** `DateRange` + `TimestampRange` in genlib —
seeded, chunk-invariant, tz-aware (naive vs UTC per the column, FR-M.4) — wired through the
authoring catalog with static param validation (ISO parse, `RANGE_INVALID`, and `TZ_MISMATCH`
mirroring money's `SCALE_MISMATCH`), the heuristic provider (fixed deterministic default
windows — no wall-clock; rule bounds win), and the Copilot prompt catalog. `NO_MVP_GENERATOR`
no longer fires for DATE/TIMESTAMP. genlib 99, authoring 78, data-engine 31. UI demo schema now
carries `signed_up date` + `created_at timestamptz`.

**11B (dialects):** `Dialect` resolver (Postgres | H2 | **DB2** | ANSI fallback) with the
divergences as data: DB2's footguns handled — BOOLEAN→`SMALLINT` 0/1, no tz timestamp
(values normalized to UTC wall time by the binder), `VARCHAR` 32672 cap → `CLOB`,
`BLOB`/`CHAR(36)`. **Teardown rewritten to be portable by construction** (DB2 LUW has no
`DROP SCHEMA … CASCADE`): tables enumerated via JDBC metadata, dropped individually — each
schema-qualified into the validated `ds_` namespace — then `DROP SCHEMA RESTRICT`; existence
checks via metadata (no information_schema assumption). **Unspecified dialects:** a
`DriverDirectoryLoader` scans `./drivers` for vendor jars, registers each `java.sql.Driver`
behind a DriverManager shim — DB2 = drop `jcc.jar` in + a named connection; anything else the
same, landing on the conservative ANSI mappings. Proven with a fake vendor driver jar compiled
at test time (a class genuinely absent from the classpath — the parent-first classloading trap
made the "copy the H2 jar" version of that test a false test, caught and replaced). jdbc-mcp
35/35; README documents the dialect matrix + DB2 recipe.

## Deferred (cloud phase / fast-follows)

Central-server↔jdbc-mcp wiring for direct DB sinks end-to-end; UI static export baked into the
server jar (currently separate); relay-node hardening (mTLS, signed command tokens, egress
lockdown); real LLM provider adapters; DB2 driver + dialect entry; date/timestamp generators in
the genlib catalog (most real schemas need them — nearest-term gap); packaging (uberjar +
worker bundle + Docker).
