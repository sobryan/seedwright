# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

**seedwright** is a model-agnostic synthetic data generation platform: a web app + REST API where a user defines a **Blueprint** (DB connection + imported schema + example data + generation rules + validation suite + model config), then generates many reproducible, validated **Datasets** of synthetic data from it and materializes them to one or more database/file sinks.

**Status: greenfield.** The only artifact today is `synthetic-data-creator-requirements.md` (Draft v0.5) — the authoritative spec. No code, build, or test infrastructure exists yet. When that spec and this file disagree, the spec wins; update this file to match.

> Requirements use `FR-*` (functional) / `NFR-*` (non-functional) tags and `[OPEN-N]` for unresolved forks. Cite those tags in commits and PRs so work traces back to a requirement.

## The keystone: two-phase generation (read this first)

Everything hangs off one decision (spec §3). Get this wrong and the rest doesn't make sense:

1. **Authoring phase — non-deterministic, runs *once* per Blueprint version.** A provider-agnostic **evaluator-optimizer loop** (plan → implement → write data-tests → execute → judge a *sample* → refine) writes **Generator Artifacts**: versioned *thin-glue code* that targets the Generation Library. The LLM lives **only** here.
2. **Execution phase — deterministic, re-runnable forever.** A worker runs the Generator Artifacts with a **seed** to produce data. **No model is in this loop.** Same `(blueprint_version, generator_artifacts_version, generation_library_version, seed)` ⇒ byte-identical output, always.

Consequences that constrain almost every design choice:
- **Generated code is thin glue, never freeform.** The model declares *generator choice / distribution / cardinality / business rules* against a first-class **Generation Library** that owns all determinism-critical plumbing. Keep the generated surface small enough to sandbox, statically scan, and human-approve (FR-L.5).
- **Determinism is gated, not hoped for.** A generator is accepted only after a **double-run determinism gate** (run twice, same seed, assert identical). Generators must be pure functions of `(schema, rules, seed)` — no wall-clock, no unseeded randomness. Time and per-entity variety are injected as seeded inputs.
- **Model-agnosticism lives at authoring, not execution.** Execution is model-free by construction; swapping providers only changes *who writes* the generator. `NFR-AGNOSTIC` primarily binds the authoring adapter.

## The canonical-data + load-plan seam

Generation does **not** emit dialect SQL. It emits two neutral artifacts (spec §3, FR-M):
- **Canonical Dataset** — typed, dialect-neutral data: Arrow in memory → **Parquet** on disk (one file/table, partitioned when large). This is *the* reproducibility checkpoint and the single source read by validation **and** every sink loader.
- **Load Plan** — table order (FK topological), namespace, per-table row counts, per-column type hints (canonical type + original SQL type/precision/scale/length/nullability).

Each sink's **MCP loader** turns `canonical + load plan` into that dialect's bulk-load (`COPY`/Postgres, `LOAD DATA`/MySQL, load utility or batched inserts/DB2) plus a matching scoped teardown. This is what makes "generate **once**, fan out to N sinks simultaneously" clean — the namespace-scoping safety logic lives centrally in loaders, never scattered across generated code.

**Validate once against the canonical Parquet, before any load** (FR-F.1b). Per-sink checks afterward only verify materialization (row counts, checksums).

## Non-negotiable safety invariants (FR-L / NFR-EXEC)

The system writes and executes code that mutates real databases, and imported schema/example data is **untrusted input** (an injection vector). These are mandatory, not "nice to have":
- **Sandboxed execution** — generated code runs isolated: no arbitrary network/fs, resource caps, reaches only sanctioned DB connections.
- **Provable teardown scoping** — synthetic data **always** lands in an isolated, identifiable namespace (dedicated schema / table prefix / mandatory `dataset_id` discriminator). Generated deletes operate **only** within that namespace. A bare `DROP TABLE` or `DELETE FROM <table>` is **never** emitted.
- **Least-privilege DB roles** — load/teardown connections cannot do broad DDL or `DROP`.
- **Static analysis + human approval** before a generator/teardown first runs against any real target.
- **Idempotent + reversible** load and teardown (re-running load never duplicates; teardown fully reverses load).
- **Direct-DB sinks are gated behind explicit user confirmation** — writing to a database is side-effecting and must never be implicit. File export is the MVP default sink.

If you are about to generate code that touches a DB without a scoped namespace, stop — you are violating the core safety contract.

## Domain vocabulary (used everywhere — don't invent synonyms)

| Term | Meaning |
|---|---|
| **Blueprint** | The versioned generation spec (the user's "pool"). 1 Blueprint → N Datasets. |
| **Dataset** | One materialized body of synthetic data from a Blueprint. Pins blueprint/generator/library versions + seed. |
| **Generator Artifacts** | The thin-glue code the authoring loop writes against the Generation Library + its data-tests. |
| **Generation Library** | The versioned deterministic substrate the glue targets (seeded RNG, FK ordering, streaming, canonical typing, Arrow/Parquet writer, namespace scoping, Load-Plan emitter, determinism gate). A platform dependency, not per-Blueprint. |
| **Canonical Dataset** | Dialect-neutral Arrow→Parquet output; the reproducibility checkpoint. |
| **Load Plan** | The materialization recipe emitted alongside the Canonical Dataset. |
| **Sink** | A materialization target — a file export or a target DB (each DB sink has an MCP loader + teardown). |

## Multi-runtime topology (recommended stack — §7, planning agent may adjust)

Three runtimes with deliberate seams between them:
- **Backend / API / orchestration** — Spring Boot (Java 21), Spring Web/Data; async jobs via queue or virtual threads. Hosts the provider-agnostic authoring loop (Spring AI ships `EvaluatorOptimizerWorkflow`; LangGraph or hand-rolled are alternatives). The UI is just a client of this REST API — **no privileged side channel** (FR-I.4).
- **Generation runtime** — **Python**: the Generation Library over a hidden DuckDB/Polars/pandas substrate + Faker/Mimesis + numpy, producing Parquet + Load Plan. Runs in the worker sandbox. *Generation is Python; this is separate from DB access.*
- **DB access & loading** — **MCP loaders** with normalized contracts (`load_dataset`, `teardown_dataset`, `introspect_schema`) so the orchestrator never special-cases a backend. A **JDBC-backed MCP** covers relational breadth (DB2/Oracle/SQL Server/MySQL/Postgres); add a **Python MCP** only for capability gaps. **Credentials live in the MCP server**, never in the orchestrator or model. Don't spin up one MCP per database.
- **Metadata store** Postgres (JSONB for rules/metadata/reports); **canonical storage** object storage (GCS/S3) for Parquet; **frontend** React + TS SPA (Monaco for rule editing, a graph lib for the FK visualization); **secrets** GCP Secret Manager / Vault.

## Key rules to hold while building

- **Provider abstraction is a hard requirement** (NFR-AGNOSTIC). No provider-specific assumptions leak into engine/API/UI. The authoring adapter must normalize structured/JSON-schema output, tool/function calling, and code-gen across Claude/OpenAI/Gemini/local, with a capability floor that **surfaces authoring failure explicitly** rather than degrading silently (FR-H.7).
- **Privacy = provider choice** (NFR-PRIV). The tool does **not** redact by default; example data (incl. real/production values) *is* sent to the user-selected authoring model. The tool's job is visibility (FR-H.6), transparency, secure transit/rest (NFR-SEC), and **always-on output leakage validation** (FR-F.2) — not certification or restriction. There is **one paradigm**: import examples → generate fresh leakage-checked values (no separate masking engine).
- **Canonical type system is Arrow-anchored** (FR-M.4). Source SQL→canonical at import; canonical→target SQL in each loader. Handle the footguns explicitly: decimal precision/scale (money — **never floats**), timestamp tz semantics (DB2/MySQL/Postgres differ), boolean representation (DB2 historically none, MySQL `TINYINT(1)`, Postgres native), string length/encoding, and no-clean-Arrow-primitive types (JSON/UUID/arrays/spatial each need a documented convention).
- **Determinism + test mode** (NFR-TEST): a fixed-seed + **mock provider** mode must let generation/validation be unit/integration-tested without live model calls. Design for this from day one.
- **No silent partial Datasets** (FR-E.4, NFR-REL): failure ⇒ marked `failed`/`quarantined`, never `ready`. Jobs are resumable, cancelable, streamed in chunks to bound memory.

## Phasing (spec §8) — what counts as MVP

- **Phase 1 (MVP):** Postgres only, end-to-end — introspection, example import + PII classification, structured rules (+NL compile), the authoring loop with determinism gate, ~1M rows/table, full validation suite, sandboxed execution + namespace-scoped teardown, file export, single provider behind the abstraction, REST CRUD on Blueprints+Datasets with async jobs, OTel observability, deterministic test mode.
- **Phase 2+:** more dialects (MySQL/SQL Server/DB2), reference/fixed tables (FR-O.1 — *candidate to pull into MVP, OPEN-15*), model switching + cost tracking, refinement loop, CLI/SDK + Dataset TTL + namespace GC, audit log, then direct-DB sinks, SDV fidelity backend, schema-drift detection, Blueprint-as-code, scheduling.

## Open decisions still to resolve before/during planning

Defaults are in the spec (§11); these still need a call: **OPEN-3** (v1 DB matrix), **OPEN-4** (v1 sink = file export vs direct insert), **OPEN-5** (rule authoring modality), **OPEN-6** (auth/tenancy for v1), **OPEN-8** (scale ceiling), **OPEN-14** (differential privacy), **OPEN-15** (reference/fixed tables: MVP or Phase 2). Resolve these before locking the Phase 1 plan.

## Build status & commands

This is a polyglot monorepo built bottom-up (see `docs/decisions/0001-*` and `docs/journal/`). Current state:

- **`generation-library/`** (sub-project A, Python) — **built, Slice 1 complete** (92 tests green). The deterministic substrate: seeded RNG, canonical types, generators, single-table + cross-table FK generation, Parquet writer, Load-Plan emitter, determinism gate.
- **`postgres-loader/`** (sub-project C, Python) — **built, Slice 2 complete** (101 tests + 5 skippable integration; see `docs/decisions/0002-*`). Consumes canonical Parquet + Load-Plan JSON (no genlib dep). Pure offline layer: `safesql` (namespace/identifier injection guard), `pgtypes`, `plan`, `ddl` (NOT-NULL-only), `copy` (COPY text encoder), `typecheck` (plan/Parquet type-agreement), `results`. Integration `executor` (psycopg): scoped load/teardown, marker-guarded drop, one txn with `search_path=''`+UTC.
- **`authoring/`** (sub-project B, Python) — **built, Slice 3 complete** (62 tests; see `docs/decisions/0003-*`). The model-agnostic evaluator-optimizer. Path-depends on genlib. Model emits a declarative genspec (JSON) → `validate` → `compile` into genlib `SchemaSpec` → sample → `judge` (data-tests from declared rules) → refine → determinism gate → `GeneratorArtifacts` (PENDING_APPROVAL). Offline via a scripted mock provider; real LLM adapters slot in behind the `provider` protocol.
- **`data-engine/`** (Python 3.12) — **built, Slice 4** (21 tests). The Python MCP server (stdio, FastMCP): tools `author_generator` (heuristic no-LLM provider by default), `generate_dataset`, `validate_dataset`, `export_dataset` (canonical→CSV/JSONL/SQL), `load_postgres`/`teardown_postgres`. Tool logic in plain tested functions; MCP layer is a shim.
- **`server/`** (Java 21, Spring Boot 3.5, Maven) — **built, Slice 5** (4 tests incl. a LIVE Java↔Python stdio MCP test and an H2 restart-persistence test). The central application (ADR-0004): REST + async jobs + **H2 file-mode metadata** (`./data/seedwright`) + MCP client that spawns the data-engine.
- **`jdbc-mcp/`** (Java 21, Spring Boot, Maven) — **built, Slice 6** (26 tests vs real H2). MCP server over Streamable HTTP (`/mcp`, port 8081): `introspect_schema`, `load_dataset` (JSONL+plan → DDL + batched inserts, one txn, row-count verify), `teardown_dataset` (marker-guarded), `verify_materialization`. Credentials are node-local named connections (spec §7). Same artifact becomes the remote relay node later.
- **`ui/`** (Next.js, static export) — **built, Slice 7**. Blueprint create/generate/watch/export; `npm run build` → `out/` served by the central server in production.
- Not yet built: real LLM provider adapters, validation-suite service beyond data-tests, central-server↔jdbc-mcp wiring for DB sinks, relay-node security hardening (cloud phase).

Commands (`cd <dir>` first). Python sub-projects use `uv`; **postgres-loader** and **data-engine** are pinned to Python 3.12:

```bash
uv sync && uv run pytest    # every Python sub-project; run the FULL suite on every change
uv run ruff check . && uv run mypy   # lint + strict types (must be clean)
mvn test                    # server/ and jdbc-mcp/ (Java 21 + Maven)
npm run build               # ui/ (static export to out/)
SEEDWRIGHT_TEST_PG_DSN=postgresql://user:pass@localhost/db uv run pytest -m integration  # pgloader live tests
```

**Regression discipline (per user directive):** every feature is TDD'd (RED→GREEN→REFACTOR) and the **entire** suite is run before a feature is considered done. The suite *is* the regression corpus. Keep it green; keep it fast.

## Conventions

- The canonical Parquet + Load Plan is the contract between modules. Never let one runtime reach around the seam — e.g., the orchestrator must not write DB rows directly; that's the loader's job.
- `docs/decisions/` holds ADRs (open-decision resolutions + load-bearing choices); `docs/journal/` logs each slice's milestones, proven properties, and deferred limitations. Update the journal at each milestone; add an ADR when making a load-bearing decision.
- Determinism is the invariant everything rests on: no wall-clock, no unseeded randomness in any execution path. Anything reproducibility-critical must be provable by a test (ideally pinned with a golden value).
