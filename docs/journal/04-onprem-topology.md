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

## Deferred (cloud phase / fast-follows)

Central-server↔jdbc-mcp wiring for direct DB sinks end-to-end; UI static export baked into the
server jar (currently separate); relay-node hardening (mTLS, signed command tokens, egress
lockdown); real LLM provider adapters; DB2 driver + dialect entry; date/timestamp generators in
the genlib catalog (most real schemas need them — nearest-term gap); packaging (uberjar +
worker bundle + Docker).
