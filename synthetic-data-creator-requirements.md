# Synthetic Data Creator — Requirements Specification

**Status:** Draft v0.5 (for review)
**Changes in v0.5 (decisions resolved):** **OPEN-11** → build the Generation Library (SDV as optional fidelity backend; closes OPEN-7). **OPEN-9** → **provider-agnostic authoring loop** (Claude / OpenAI / Gemini / local); dynamic-workflow *patterns* borrowed, the Anthropic-only feature is **not** a dependency; adds authoring-capability parity + floor (FR-H.7). **OPEN-2** → **privacy = provider choice** (NFR-PRIV rewritten — data *is* sent to the user-selected local/cloud model; no redaction-default). **OPEN-12/13** → **one generation-from-examples paradigm** (no separate masking engine); example import generalized to any source incl. production, with referentially-consistent extraction (FR-B.1). New **product stance** (§2) makes the tool user-directed with no imposed data-governance policy.
**Changes in v0.4 (feature gap-audit):** Added the missing **automation surface** — CLI/SDK for CI/CD, Dataset TTL / ephemeral environments, namespace garbage collection, scheduling, notifications (FR-N). Added **real-schema correctness**: reference/fixed tables + partial generation, schema drift detection, coverage-driven generation (FR-O). Added **reuse/portability/governance**: Blueprint-as-code, templates/reusable generators, audit log, Dataset diff & fidelity report (FR-P). Added preview/dry-run (FR-E.6) and platform-hardening NFRs (NFR-OPS, NFR-DX). Three scope-expanding *modes* added as decisions, not features: masking (OPEN-12), subsetting (OPEN-13), differential privacy (OPEN-14).
**Changes in v0.3:** Generator Artifacts are now **thin glue authored against a first-class deterministic Generation Library** (not freeform code) — §3, FR-M. Locked the **canonical-data + load-plan seam**: the generator produces a typed, dialect-neutral **Canonical Dataset** (Arrow in memory → **Parquet** on disk) plus a small **Load Plan**; sink MCP loaders turn that into dialect bulk-load + scoped teardown (FR-G, FR-M). Added the **canonical type system** (Arrow-anchored) and its source→canonical / canonical→dialect mapping. Full validation now runs **once against the canonical Parquet**, then per-sink verifies materialization (FR-F.1). §7 split into generation runtime (Python) vs DB-access (MCP). OPEN-10 resolved; OPEN-11 (build-vs-adopt the Generation Library) added.
**Changes in v0.2:** Keystone generation architecture (§3) reframed from "Generation Plan data structure + interpreter engine" to **generated deterministic code authored by an evaluator-optimizer loop** (this is the layer that maps onto Claude *dynamic workflows* / the Agent SDK). Added two-phase (author-once / execute-deterministically) model, chain-of-functions with create + teardown, multi-sink simultaneous materialization (FR-G), generated-code execution safety (FR-L / NFR-EXEC), and the MCP execution boundary (§7). OPEN-1 resolved; OPEN-9 and OPEN-10 added.
**Purpose:** Source requirements for a model-agnostic synthetic data generation platform. This document is the input to a **planning agent**, which will produce implementation details for an **SDLC/coding agent**. It states *what* must be true and the key constraints; it deliberately defers most *how* to the planning stage, except where an architectural choice is load-bearing (those are called out explicitly).

**How to read this:** Requirements are tagged `FR-*` (functional) and `NFR-*` (non-functional). `[ASSUMPTION]` marks a default I have chosen so the doc is coherent — confirm or override. `[OPEN]` marks a fork that materially changes the architecture; all `[OPEN]` items are collected in §11.

---

## 1. Terminology & Naming

You've been calling the configuration container a "pool." I recommend renaming it for clarity, because the rules/schema/examples are really a *generation specification*, and "pool" collides with connection-pool and value-pool concepts.

**Recommended (used throughout this doc):**

| Concept | Name | Definition |
|---|---|---|
| The config container (your "pool") | **Blueprint** | The complete, versioned generation spec for one logical schema: connections + imported schema + example data + generation rules + refinement rules + validation suite + model config. The schema is *one component* of a Blueprint, not the whole thing. |
| The generated output (your "set") | **Dataset** | A concrete, materialized body of synthetic data produced from one Blueprint. Belongs to exactly one Blueprint. |
| The model-authored output (see §3) | **Generator Artifacts** | The versioned **thin-glue code** the authoring loop writes *against the Generation Library*: schema-specific generator declarations (which generator per column, distributions, FK cardinality, cross-field/cross-table rules, per-table volume) plus data-tests. Executed (not interpreted) to produce a Canonical Dataset + Load Plan. |
| The deterministic substrate (new, §3 / FR-M) | **Generation Library** | The reusable, **versioned** library the glue targets. Owns everything not re-derived per Blueprint: seeded RNG, FK topological ordering, chunked streaming, canonical typing, the Arrow/Parquet writer, namespace scoping, the Load-Plan emitter, and the determinism gate. Composes value primitives (Faker/Mimesis) + numpy; optional statistical-fidelity backend (e.g., SDV). |
| The neutral generated artifact (new, FR-M) | **Canonical Dataset** | The typed, **dialect-neutral** data the generator produces: Arrow in memory → **Parquet** on disk (one file/table, partitioned for large tables). This is the reproducibility checkpoint and the single thing validation and all sink-loads read from. |
| The materialization recipe (new, FR-M) | **Load Plan** | A small structured artifact emitted alongside the Canonical Dataset: table order (FK topo), namespace, per-table row counts, and per-column **type hints** (canonical type + source SQL type/precision/scale/length/nullability) that loaders use to produce faithful dialect DDL + bulk-load. |

**Relationship:** one Blueprint → many Datasets (1:N). This resolves your "there is one pool but each pool can generate many sets" — each Dataset is owned by one Blueprint; a Blueprint can spawn unlimited Datasets, each independently versioned, seeded, and validated.

**Alternate names for the Blueprint** (trivially swappable via find-replace — pick on vibe): `Crucible` (transformation + testing connotation; on-brand for a tool that both forges and validates), `Profile`, `Mold`, `Recipe`, `Foundry`. Alternate for Dataset: `Batch`, `Cast`.

> **Naming note:** I'll use **Blueprint** / **Dataset** below for self-explanatory reading by downstream agents. Say the word and I'll switch the whole doc to Crucible/Batch or anything else.

---

## 2. System Overview

A web application plus REST API that lets a user define a **Blueprint** (connect to a database, import its schema and example data, declare generation and refinement rules, and define a validation suite), then generate many **Datasets** of synthetic data from it using any configured model provider. Every Dataset is validated against the Blueprint's validation suite after generation. Generation is model-agnostic, reproducible, and observable.

**Core flow:**
```
Connect DB → Import schema → Import examples → Author rules → Configure model
   → [authoring loop writes & refines deterministic Generator Artifacts against a sample]
   → Worker executes Generator Artifacts (seeded) → materialize Dataset to one or more sinks
   → full-dataset Validate → review report → (refine → re-author) → (teardown when done)
```

The authoring loop (§3A) and the refine→re-author loop are first-class, not afterthoughts (§ FR-D, FR-E).

**Product stance `[resolved v0.5 — OPEN-2/12/13]`.** The tool is **user-directed** and does not impose data-governance policy. The user decides what to import (any source, **including production**), what to generate, and where to materialize it (**including production** — gated only by side-effect confirmations, not policy). There is **one generation paradigm**: import examples → generate synthetic data from them. "De-identified but realistic" data is achieved *by generating fresh values from examples* (leakage-checked), not by a separate masking engine. **Privacy is the user's provider choice**: example data is exposed to the user-selected authoring model (local or cloud), and the user selects a provider whose data-isolation/protection meets their needs (a local model for no egress, or a cloud provider under a BAA for regulated data). The tool's job is capability + safety mechanics + transparency — not certification, and not restriction.

---

## 3. Keystone — Generation Architecture `[RESOLVED v0.2]`

**Decision: the deterministic kernel is generated *code*, authored by an evaluator-optimizer loop, then executed deterministically. Non-determinism is confined to a one-time authoring phase; everything the user re-runs is plain deterministic code.**

This supersedes the v0.1 "Generation Plan data structure + interpreter engine" framing. The generated artifact is *executable generator functions*, not a config an engine interprets — which buys full expressive power, true determinism (seeded code), and clean reproducibility (the code is the versioned artifact). It maps onto Anthropic's **evaluator-optimizer** pattern. The authoring loop is **provider-agnostic** (Claude / OpenAI / Gemini / local — OPEN-9 resolved v0.5): we *borrow* dynamic-workflow patterns (journaled-deterministic orchestration, sample-and-verify, schema-validated output) but the runtime is **ours**, so any provider can drive it — we do **not** depend on the Anthropic-only dynamic-workflows feature.

**Two phases:**

**A. Authoring phase — non-deterministic, runs *once* per Blueprint version (or per refinement).** An agentic loop does *plan → implement → generate data-tests → execute → judge a sample → refine*, looping until a representative sample passes. The "implement" step writes the deterministic generator; the "judge/critic" step evaluates sampled output. Outputs are versioned **Generator Artifacts**: create-chain functions, teardown functions, and data-tests.

**B. Execution phase — deterministic, re-runnable forever.** A worker executes the Generator Artifacts with a **seed** to materialize the full Dataset, and later executes the teardown chain to delete it. *The model is not in this loop.* Same Blueprint version + same seed ⇒ identical data, every time.

**Dataset creation is a chain of functions (a DAG).** Ordered by FK topology: the create-chain inserts parents before children; the teardown-chain runs in reverse. Each link is one generated deterministic function.

**Determinism is enforced, not hoped for.** A generated function is accepted only after a **double-run determinism gate**: execute twice with the same seed, assert identical output. Generators must be pure functions of (schema, rules, seed) — no wall-clock, no unseeded randomness; time and per-entity variety are injected as seeded inputs. (This mirrors the dynamic-workflow runtime's own rule that nondeterministic calls throw.)

**Why this is model-agnostic — and why agnosticism now lives mostly at authoring.** The model's job is bounded (author and refine code against tests), so any competent model can do it, and the *executed* artifact is model-independent — often it calls no model at all at run time. Swapping models changes who *writes* the generator, never how it *runs*. Consequence: NFR-AGNOSTIC primarily constrains the **authoring** model; execution is model-free by construction. The authoring loop must run over the provider abstraction across Claude, OpenAI, Gemini, and local models (FR-H.7) — which requires normalizing structured output, tool-use, and code generation across them, since these differ by provider.

**Thin glue, not freeform code `[decided v0.3]`.** The authoring loop does **not** write generators from scratch each time. It writes *thin glue against a first-class, versioned Generation Library* (FR-M). The library owns determinism-critical plumbing (seeded RNG, FK ordering, streaming, canonical typing, namespace scoping, the determinism gate); the glue carries only the intelligence — generator choices, distributions, and business rules. This keeps the generated surface small enough to sandbox, statically scan, and approve (FR-L), and makes determinism a *property of the library by construction* rather than something the model has to remember to do. Generator Artifacts pin the Generation Library version for reproducibility.

**The canonical-data + load-plan seam `[decided v0.3]`.** Generation does **not** emit dialect-specific SQL. It emits two neutral artifacts: a **Canonical Dataset** (typed, dialect-neutral — Arrow → Parquet on disk) and a small **Load Plan** (table order, namespace, row counts, per-column type hints). Each sink's MCP loader then turns *canonical + load plan* into that dialect's bulk-load (e.g., `LOAD DATA` for MySQL, the load utility / batched inserts for DB2, `COPY` for Postgres), namespace-scoped and idempotent, with a matching teardown. This seam is what makes "generate canonical once, fan out to N sinks" (e.g., MySQL **and** DB2 at once) clean: generation is decoupled from dialects, the fan-out isn't duplicated, and the namespace-scoping safety logic lives centrally in loaders, not scattered across generated code.

---

## 4. Domain Model

- **Blueprint** — id, name, description, version, status (draft/active/archived), owner/tenant, timestamps. Aggregates the components below.
- **Connection** — DB connection profile (driver/dialect, host, port, db, schema, auth ref → secrets vault). Used for schema import, example import, and optionally as an output sink. Credentials are never stored in plaintext (NFR-SEC).
- **Schema** — tables, columns (type, nullability, length/precision, default), primary keys, unique constraints, check constraints, foreign keys, and the derived FK dependency graph. Source: live introspection or DDL/JSON import.
- **ExampleData** — imported sample rows, distilled into per-column value corpora and/or statistics (cardinality, null rate, min/max, distribution shape). PII-classified on import.
- **GenerationRules** — per-column, per-table, and cross-table rules: constraints, distributions, formats/regex, enums, value sources, FK cardinality, conditional/correlation rules, locale, and per-table volume targets.
- **RefinementRules** — corrective rules layered on top of GenerationRules, plus iteration history (§ FR-D).
- **ValidationSuite** — the ordered set of checks run after generation (§ FR-F).
- **ModelConfig** — provider, model name, optional task→model mapping (e.g., cheap model for plan structure, stronger model for free-text corpora), params, and budget/limits.
- **GeneratorArtifacts** — versioned **thin-glue code** authored by the loop (§3A) against the Generation Library: schema-specific generator declarations + data-tests. Pins the Generation Library version. Cached/reused across Datasets until the Blueprint changes. Provenance: authoring model, prompt/version, determinism-gate result, approval status.
- **GenerationLibrary** — the versioned deterministic substrate the glue targets (FR-M): seeded RNG, FK ordering, streaming, canonical typing, Arrow/Parquet writer, namespace scoping, Load-Plan emitter, determinism gate. A platform dependency, not per-Blueprint.
- **CanonicalDataset** — the typed, dialect-neutral generated data (Arrow → Parquet on disk; one file/table, partitioned for large tables). The reproducibility checkpoint; the single source read by validation and by every sink loader. Stored in object storage.
- **LoadPlan** — emitted with the CanonicalDataset: ordered table list (FK topo), namespace, per-table row counts, and per-column type hints (canonical type + source SQL type/precision/scale/length/nullability).
- **Dataset** — id, blueprint_id, **blueprint_version** + **generator_artifacts_version** + **generation_library_version** (pinned for reproducibility), name, status (pending/generating/validating/ready/failed/quarantined), **seed**, ref to its **CanonicalDataset + LoadPlan**, per-table row counts, **per-sink materialization records** (which sinks it landed in + status of each), generation metadata (authoring model, tokens in/out, cost, duration, rows/sec), validation_report ref. One canonical generation, fanned out to ≥1 sinks (FR-G).
- **Sink** — a materialization target for a Dataset: a **file export** (the CanonicalDataset itself, or rendered SQL/CSV/JSON) or a **target database**. A Dataset may target several sinks at once (e.g., MySQL + DB2). Each DB sink has an MCP **loader** that consumes CanonicalDataset + LoadPlan, plus a matching teardown, both scoped to an isolated, identifiable namespace (NFR-EXEC).
- **Job** — async unit of work (generate or validate); status, progress %, logs, errors, cancelable.
- **ValidationReport** — per-Dataset results: per-check pass/fail, severity, sample failures, aggregate score.

---

## 5. Functional Requirements

### FR-A — Connections & Schema Import
- **FR-A.1** Connect to a relational database via JDBC; test the connection before saving.
- **FR-A.2** Import schema by **live introspection** (tables, columns, types, PK, unique, check, FK) and/or by uploading **DDL or a JSON schema definition**.
- **FR-A.3** Auto-derive the FK dependency graph and detect cycles (self-referential and circular FKs); surface cycles to the user since they require a break strategy (nullable-first-pass insert, then update).
- **FR-A.4** Allow manual override/augmentation of any introspected detail (the live DB may under-declare constraints).
- **FR-A.5** Database support matrix for v1 — `[OPEN-3]`. `[ASSUMPTION]` Postgres, MySQL, SQL Server, and **DB2** (JDBC) for v1; NoSQL/document stores deferred.

### FR-B — Example Data Import
- **FR-B.1** Import examples — a **representative, referentially-consistent sample** (schema + sample rows + formats) — from **any supported source** (relational DBs, files/CSV/JSON, and extensible connectors), **including production at the user's direction** (OPEN-13 resolved). The captured representation can both seed generation and be exported as a portable artifact.
- **FR-B.2** On import, classify columns for PII (and surface what will be exposed to the authoring model) and distill each column into a value corpus and/or summary statistics. Example data — including real values — is exposed to the **user-selected** authoring provider per NFR-PRIV; stored example data is secured at rest and in transit (NFR-SEC).
- **FR-B.3** Define how examples influence generation: (a) few-shot signal to the authoring model, (b) statistical seed for distributions, (c) sampleable value pools for the generator. All three are supported; the user (or rules) decide per column.

### FR-C — Generation Rules
- **FR-C.1** Author rules at **column**, **table**, and **cross-table** scope.
- **FR-C.2** Supported rule types: type/format/regex, value range and enum, nullability and null-rate, uniqueness, distribution (e.g., uniform/normal/categorical-weighted/from-examples), FK cardinality (e.g., each customer has 0–20 orders), conditional logic, cross-field correlation (e.g., `order.created_at >= customer.signed_up_at`), locale/region, and per-table volume.
- **FR-C.3** Rule authoring modality — `[OPEN-5]`. `[ASSUMPTION]` Dual mode: a natural-language box that the model **compiles into the canonical structured rule representation**, which the user can also edit directly. The structured form is the source of truth; NL is a convenience front end.
- **FR-C.4** Rules are validated for self-consistency before a generator is authored (e.g., a UNIQUE column whose value range is smaller than its row count is rejected with an explanation).

### FR-D — Refinement Loop
- **FR-D.1** After a Dataset is validated, the user can review failures and add **refinement rules** layered over generation rules.
- **FR-D.2** The model can **propose** refinement rules automatically from the validation report (user approves before they apply — proposed rules are never auto-committed).
- **FR-D.3** Refinement is iterative and tracked: each iteration records what changed, the resulting generator version, and the resulting Dataset's score, so the user can see whether quality is improving or regressing.

### FR-E — Authoring Loop & Execution
- **FR-E.1** **Author** Generator Artifacts (thin glue against the Generation Library, FR-M) from the Blueprint via the evaluator-optimizer loop (§3A); version and cache them; re-author only when the Blueprint changes or on explicit refinement.
- **FR-E.2** **Execute** Generator Artifacts deterministically given a **seed** to produce a **CanonicalDataset + LoadPlan** — *not* direct DB writes. Same Blueprint version + generator version + library version + seed ⇒ identical CanonicalDataset (NFR-REPRO). A generator is accepted only after the double-run determinism gate (§3, FR-L.4).
- **FR-E.3** The Generation Library resolves create order by FK topology and enforces PK/unique/check/FK constraints and declared cardinalities while generating the canonical data. (Per-sink load order follows the LoadPlan; teardown runs in reverse.)
- **FR-E.4** Generate in streamed chunks to bound memory (generate batch → write Parquet → free); report progress; support cancel and resume; no silent partial Datasets (failure ⇒ marked `failed`, never `ready`).
- **FR-E.5** Scale target — `[OPEN-8]`. `[ASSUMPTION]` Architect for up to ~10M rows/table via streaming; MVP acceptance validated at ~1M rows/table.
- **FR-E.6 Preview / dry-run.** Produce a cheap, small sample from a generator (reuse the authoring-loop sample path) and show it before committing to a full run — fast feedback while authoring/refining rules, no full materialization.

### FR-F — Validation
- **FR-F.1** Validation runs at **three points**: (a) *sample validation* inside the authoring loop — the critic judges a representative sample to decide whether a Generator Artifact is good enough (fast; keeps authoring cheap); (b) *full-dataset validation* — the **ValidationSuite** runs **once against the CanonicalDataset (Parquet)**, before any load, since it's the single neutral source; (c) *per-sink materialization verification* — after each load, confirm it landed correctly (row counts, checksums/spot-checks; the DB enforces its own constraints). Full validation also runs on explicit re-run.
- **FR-F.2** Check categories: **structural** (types, nullability, lengths, PK/unique), **constraint** (check constraints, ranges, enums, regex), **referential integrity** (every FK resolves; cardinality within bounds), **business rules** (cross-field/cross-table logic), **statistical fidelity** (distribution similarity, cardinality, null-rate vs source — only when example data is present), **privacy/leakage** (no real example values reproduced verbatim; optional distance/k-anonymity checks), **uniqueness/coverage**.
- **FR-F.3** The **ValidationReport** gives per-check pass/fail with severity, sample failing records, and an aggregate score.
- **FR-F.4** Configurable gating: on failure above a severity threshold, the Dataset is **quarantined** (retained for inspection, not exportable) and optionally triggers an auto-refinement proposal (FR-D.2).
- **FR-F.5** Statistical-fidelity backend `[resolved v0.5 — see OPEN-11]`. Simple numpy-based stats for MVP; advanced fidelity (correlation-preserving tests) via the optional **SDV backend** of the Generation Library (FR-M.2) later.

### FR-G — Datasets, Multi-Sink Materialization & Teardown
- **FR-G.1** **CRUD on Datasets**: list, read metadata, rename/tag, delete; read rows **paginated**; edit/delete individual rows (manual touch-ups) with edits re-validated.
- **FR-G.2** **Materialize to one or more Sinks simultaneously from the CanonicalDataset.** Generate **canonical once**; each sink's MCP **loader** consumes *CanonicalDataset + LoadPlan* and produces that dialect's bulk-load (`LOAD DATA`/MySQL, load utility or batched inserts/DB2, `COPY`/Postgres) with identical keys/values — so a single Dataset can populate, e.g., MySQL **and** DB2 at once because a test must execute across both. Each Dataset records what landed in which sink.
- **FR-G.3** **Teardown.** Each DB sink's loader has a matching teardown that deletes **only this Dataset's** data, scoped by an isolated namespace (NFR-EXEC, FR-L.3). Cross-database ACID is **not** assumed; the contract is *deterministic canonical generation + idempotent scoped load + idempotent scoped teardown* per sink.
- **FR-G.4** File-sink export formats: SQL `INSERT`s, CSV, JSON, Parquet, with download. Direct-database sinks are gated behind explicit user confirmation (writing to a database is side-effecting and must never be implicit) — `[OPEN-4]`.

### FR-H — Model Management (Agnostic) `[NFR-AGNOSTIC binds here]`
- **FR-H.1** Configure multiple **model providers** behind one abstraction (e.g., Anthropic, Google Vertex/Gemini, OpenAI, Azure OpenAI, and a **local/self-hosted** option such as Ollama/vLLM).
- **FR-H.2** **Switch the active model at runtime** at Blueprint scope, and optionally map different tasks to different models (plan structuring vs free-text corpus generation).
- **FR-H.3** Per-provider config: endpoint, model name, params, auth ref (vaulted), token/cost budget, rate-limit and retry/fallback behavior.
- **FR-H.4** Track and expose per-Dataset model cost and token usage (feeds §FR-K).
- **FR-H.5** A "test prompt" action verifies a provider is reachable and credentialed before it's used in generation.
- **FR-H.6 Data-handling visibility.** Each provider config records and surfaces its data-handling posture — **local / no-egress**, **cloud under BAA / data-isolation agreement**, or **standard cloud** — so the user's privacy choice (NFR-PRIV) is explicit at selection time.
- **FR-H.7 Authoring-capability parity & floor.** Because the authoring loop is provider-agnostic, the adapter must normalize **structured/JSON-schema output, tool/function calling, and code generation** across providers. The loop enforces a capability floor and, when a model (especially a weak local one) cannot produce a generator that passes the sample gate after N iterations, **surfaces the failure explicitly** rather than degrading silently.

### FR-I — REST API
- **FR-I.1** Full CRUD on **Blueprints** and their components, and full CRUD on **Datasets** (your two explicit API requirements).
- **FR-I.2** **Asynchronous semantics** for long-running work: generation and validation return `202 Accepted` + a Job reference; clients poll `/jobs/{id}` or subscribe via webhook.
- **FR-I.3** **Idempotency keys** on generation triggers; **pagination** on row and list reads; consistent error envelope.
- **FR-I.4** API authentication via API keys/tokens (NFR-SEC). The UI is a client of this same API — no privileged side channel.

(Concrete surface in §9.)

### FR-J — UI
- **FR-J.1** The UI must support every capability above: manage connections; import/edit schema (incl. a **visual FK graph**); import/inspect examples; author rules (NL + structured editor, e.g., Monaco); define the validation suite; configure/switch models; trigger generation; watch job progress; browse/edit/export Datasets; review validation reports; drive the refinement loop; and configure observability.
- **FR-J.2** Surface cost, token usage, generation time, and validation score prominently per Dataset.

### FR-K — Observability `[your Elastic APM / OTel requirement]`
- **FR-K.1** Instrument the service for **distributed tracing, metrics, and logs**, exportable to an external observability backend.
- **FR-K.2** Support **two modes**, user-configurable: (a) attach the **Elastic APM agent** (auto-instrumentation; configurable APM server URL + token), or (b) native **OpenTelemetry** export via OTLP to any collector/backend.
- **FR-K.3** Emit **generation-specific** signals, not just generic HTTP metrics: spans for schema import, plan build (model call), engine generation, and validation; metrics for tokens in/out, model cost, rows generated, rows/sec, generation duration, validation pass rate, and job-queue depth.
- **FR-K.4** Configurable endpoints (OTLP endpoint or Elastic APM server) and service name/environment tags.

### FR-L — Generated-Code Execution & Safety `[new in v0.2 — load-bearing]`
The system writes and then *executes* code that creates and deletes data in real databases, and imported schema/example data is **untrusted input** (an injection vector). The following are mandatory, not optional:
- **FR-L.1 Sandboxed execution.** Generated code runs in an isolated sandbox with no arbitrary network/filesystem access and resource caps; it may reach only sanctioned DB connections. (If built on dynamic workflows / the Agent SDK, inherit that runtime's isolation.)
- **FR-L.2 Least-privilege DB roles.** Load/teardown connections use roles scoped to the dataset namespace; no broad DDL or `DROP` rights.
- **FR-L.3 Provable teardown scoping.** Synthetic data always lands in an isolated, identifiable namespace — a dedicated schema, a table-name prefix, or a mandatory `dataset_id` discriminator. Generated deletes operate **only** within that namespace; a bare `DROP TABLE` / `DELETE FROM <table>` is never emitted. This is what makes "create and delete the dataset" exact and safe.
- **FR-L.4 Determinism gate.** Double-run check (execute twice, same seed, assert identical output) before a generator is accepted (§3).
- **FR-L.5 Static analysis + human approval.** Generated generators and teardowns are statically scanned for dangerous operations and require human approval before first execution against any real target.
- **FR-L.6 Idempotency & reversibility.** Load and teardown are idempotent; re-running load does not duplicate; teardown fully reverses load.

### FR-M — Generation Library & Canonical Format `[new in v0.3 — load-bearing]`
- **FR-M.1 The Generation Library is a first-class deliverable** with a stable, well-documented **authoring API** that the thin glue targets (a good interface for the model to use is the whole reason thin glue is possible). It owns: seeded RNG, FK topological ordering, chunked streaming, canonical typing, the Arrow/Parquet writer, namespace scoping, the Load-Plan emitter, and the determinism gate.
- **FR-M.2 Authoring contract.** The glue declares, per table/column: generator choice, distribution, nullability/null-rate, uniqueness, FK cardinality, cross-field and cross-table rules, per-table volume, locale — declaratively, with imperative hooks only where a rule needs code. The library catalog composes value primitives (Faker/Mimesis) + numpy distributions; an optional statistical-fidelity backend (e.g., SDV) is pluggable for the "learn from example data" mode (OPEN-7).
- **FR-M.3 Canonical format.** Output is **Arrow in memory → Parquet on disk** (durable canonical), one file per table, partitioned for large tables. The CanonicalDataset is the reproducibility checkpoint and the single source for validation (FR-F.1b) and all sink loads (FR-G.2).
- **FR-M.4 Canonical type system.** A dialect-neutral type system **anchored on Arrow logical types** sits between source and target. **Source SQL → canonical** mapping happens at import/generation (retaining the original SQL type + parameters as metadata); **canonical → target SQL** mapping happens in each sink loader, guided by the LoadPlan type hints. Must faithfully handle the known footguns: decimal precision/scale (money — never floats), timestamp timezone semantics (DB2/MySQL/Postgres differ), boolean representation (DB2 has no native boolean historically; MySQL `TINYINT(1)`; Postgres native), string length/encoding limits, and types with no clean Arrow primitive (JSON, UUID, arrays, spatial — each needs a documented convention).
- **FR-M.5 Data substrate is library-internal.** The engine behind the library (DuckDB / Polars / pandas) is hidden from the glue. `[ASSUMPTION]` DuckDB or Polars for the out-of-core, native-Parquet, low-memory fit at the ~10M-row ceiling; pandas acceptable for MVP. Changing the substrate must not change generated glue or canonical output.

### FR-N — Automation, Lifecycle & Scheduling `[new in v0.4 — primary consumer is CI, not the UI]`
- **FR-N.1 CLI + client SDK.** A scriptable client over the full REST API, built for CI/CD: provision a Dataset (generate + materialize to named sinks) and tear it down as discrete steps, with non-zero exit codes on failure and machine-readable (JSON) output. This is the intended *provision → run tests → teardown* entry point for a pipeline.
- **FR-N.2 Dataset TTL / ephemeral environments.** A Dataset (and its materializations) may carry a TTL; on expiry it is auto-torn-down from all sinks and optionally archived. Enables per-PR / per-branch data that cleans itself up.
- **FR-N.3 Namespace garbage collection.** A reconciler tracks every namespace created in every sink and reaps expired/orphaned ones; surfaces "leaked" namespaces (materializations with no owning Dataset). Closes the operational + safety loop on FR-L.3 — without it, synthetic data accumulates in live databases indefinitely.
- **FR-N.4 Scheduling & triggers.** Scheduled (re)generation (e.g., nightly refresh) and webhook/event triggers; idempotent, with the same gating and validation as manual runs.
- **FR-N.5 Notifications.** Configurable notifications (generation complete, validation failed, materialization/teardown, TTL expiry) via webhook/email/chat.

### FR-O — Real-Schema Correctness `[new in v0.4 — the whole-graph assumption is too narrow]`
- **FR-O.1 Reference/fixed tables + partial generation.** Each table is classed **generated**, **reference** (not generated — FKs into it sample from values already present in the sink), or **excluded**. The generator produces only generated tables; the loader resolves FKs into reference tables by sampling existing keys at load time. Required for lookup/reference tables and for generating child rows against existing parents. *(Likely MVP-necessary — see OPEN, almost no real schema lacks lookup tables.)*
- **FR-O.2 Schema drift detection.** Compare the Blueprint's imported schema against the live source/target schema; flag drift (added/removed/changed columns, types, constraints), mark affected Generator Artifacts **stale**, and assist re-authoring. Prevents silent generation of wrong data as schemas evolve.
- **FR-O.3 Coverage-driven generation.** Optionally generate to satisfy explicit coverage goals: every enum value, boundary/edge values (min/max, null, empty, overflow-length), each branch of a CHECK constraint, and pairwise combinations of selected columns — so test data exercises edge cases, not just the happy path.

### FR-P — Reuse, Portability & Governance `[new in v0.4]`
- **FR-P.1 Blueprint-as-code.** Export/import a Blueprint as a declarative file (YAML/JSON) that round-trips with the UI, for version control and GitOps (define Blueprints in-repo, diff them, review them).
- **FR-P.2 Templates & reusable generators.** Clone/fork a Blueprint; a shared library of named, reusable generators/rules; domain "starter packs."
- **FR-P.3 Audit log.** Append-only record of who did what (generate, materialize, teardown, schema import, model/connection/rule changes) against which target, with timestamps and — for materialize/teardown — namespace + row counts. Compliance-grade; pairs with NFR-PRIV.
- **FR-P.4 Dataset comparison & fidelity report.** Diff two Datasets, or a Dataset against the source distribution; produce a quantified fidelity/quality score with drill-down (beyond pass/fail).

---

## 6. Non-Functional Requirements

- **NFR-AGNOSTIC** — Provider abstraction is a hard requirement: adapters per provider, config-driven, runtime-swappable; no provider-specific assumptions leak into the engine, API, or UI. The **authoring loop** must run over this abstraction across **Claude, OpenAI, Gemini, and local models** (FR-H.7); execution is model-free regardless (§3).
- **NFR-SEC** — DB credentials and model API keys stored in a secrets vault (e.g., GCP Secret Manager / HashiCorp Vault), encrypted at rest and in transit; API authenticated; least-privilege DB roles recommended for import/sink connections.
- **NFR-EXEC** — Generated-code execution is **sandboxed, least-privilege, namespace-scoped, determinism-gated, statically analyzed, and human-approved** before first run against real targets (FR-L). Non-negotiable: the tool executes code that mutates databases.
- **NFR-PRIV** — Privacy = **provider choice** `[resolved v0.5 — OPEN-2]`. Example data (including real values, possibly from production) **is** sent to the **user-selected** authoring model — local or cloud. The tool does **not** impose redaction-by-default or a stats-only mode. Instead it (a) makes each provider's data-handling posture visible (FR-H.6), (b) is transparent about what data is sent where, (c) always runs **output leakage validation** (FR-F.2 — synthetic output must contain no real values, regardless of egress), and (d) secures data in transit and at rest (NFR-SEC). Regulatory compliance (e.g., HIPAA) is satisfied by the **user** via provider selection — a local model (no egress) or a cloud provider under a BAA — not certified by the tool. A no-egress posture is simply *one of the user's provider choices*, not a default.
- **NFR-REPRO** — Reproducibility: every Dataset pins its Blueprint version and seed; regeneration with the same inputs is deterministic (FR-E.2).
- **NFR-SCALE** — Streaming/batch generation with bounded memory and backpressure; configurable volume (FR-E.5).
- **NFR-REL** — Reliability: resumable/cancelable jobs; no silent partial Datasets; clear failure states.
- **NFR-EXT** — Extensibility: pluggable **generators**, **validators**, **providers**, and **sinks** so new column types, checks, models, and outputs are added without core changes.
- **NFR-TEST** — Testability: deterministic test mode (fixed seed + **mock provider**) so generation and validation are unit/integration-testable without live model calls; acceptance criteria per FR.
- **NFR-MT** — Multi-tenancy/auth scope `[OPEN-6]`. `[ASSUMPTION]` API-key-secured single-tenant service for v1, with the data model built tenant-ready (owner/tenant fields present from day one).
- **NFR-OPS** — Operability: job retry policy + run history with log retention; health/readiness endpoints for the service and each MCP loader; **load throttling/backpressure and batch sizing** when writing to live target DBs (don't overwhelm a target); per-org/Blueprint **quotas and spend caps** with alerts.
- **NFR-DX** — Developer experience: preview/dry-run (FR-E.6); inspectable canonical data; clear, machine-readable errors for CLI/CI consumption.

---

## 7. Recommended Technical Stack *(recommendation, not mandate — planning agent may adjust)*

Chosen to match a JVM/Spring background and a GCP-friendly deployment:

- **Backend / API / orchestration:** Spring Boot (Java 21), Spring Web, Spring Data; async jobs via a queue or virtual threads. Authoring loop is a **provider-agnostic evaluator-optimizer** over the provider abstraction (Spring AI ships `EvaluatorOptimizerWorkflow`; LangGraph or a hand-rolled loop are alternatives). Dynamic-workflow *patterns* are borrowed; the Anthropic-only feature is **not** a dependency (OPEN-9 resolved).
- **Generation runtime (where the generator runs):** **Python** — the Generation Library (FR-M) over a hidden **DuckDB / Polars / pandas** substrate, plus Faker/Mimesis + numpy, producing the Canonical Dataset (Parquet) + Load Plan. Runs in the worker sandbox (FR-L). *Generation is Python; this is separate from DB access.*
- **DB access & loading boundary:** **MCP** loaders — `load_dataset(canonical_ref, load_plan, namespace, mode)`, `teardown_dataset(namespace)`, `introspect_schema(...)`, with **normalized contracts across servers** so the orchestrator never special-cases a backend. A **JDBC-backed MCP** gives the broadest relational/enterprise reach (**DB2**, Oracle, SQL Server, MySQL, Postgres); a **Python MCP** is added only for capability gaps (a Python-only driver, NoSQL). Credentials live in the MCP server, never in the orchestrator or model. *Don't spin up one MCP per database; JDBC already covers relational breadth.*
- **Metadata store:** PostgreSQL (JSONB for rules / generator metadata / reports).
- **Canonical & large-Dataset storage:** object storage (GCS/S3) holding the Parquet CanonicalDatasets.
- **Provider abstraction:** interface + per-provider adapters (Anthropic, Vertex/Gemini, OpenAI, Azure, local) — binds the **authoring** model (execution is model-free, §3).
- **Frontend:** React + TypeScript SPA; Monaco for rule editing; a graph lib for the FK visualization.
- **Observability:** Micrometer + OTel exporter, with Elastic APM Java agent attach as the alternative mode.
- **Secrets:** GCP Secret Manager / Vault.
- **Deploy:** containerized (Docker), Cloud Run / GKE friendly.

---

## 8. Phased Roadmap *(sufficiency-first; tight MVP, then expand)*

- **Phase 1 — MVP:** one DB dialect end-to-end (Postgres), schema introspection, example import with PII classification, structured rules (+ NL compile), the **authoring loop** producing seeded deterministic generators with the determinism gate, generation at ~1M rows/table, full validation suite, **sandboxed execution + namespace-scoped teardown** (FR-L core), file export + download, single provider behind the abstraction, REST CRUD on Blueprints + Datasets with async jobs, OTel observability, deterministic test mode.
- **Phase 2:** additional dialects (MySQL, SQL Server, **DB2**), **reference/fixed tables + partial generation (FR-O.1)** if not pulled into MVP, model switching + task→model mapping + cost tracking, refinement loop with model-proposed rules, **CLI/SDK + Dataset TTL + namespace GC (FR-N.1–3)**, **audit log (FR-P.3)**, Elastic APM mode, visual FK graph, preview/dry-run.
- **Phase 3:** direct DB-insert sinks (gated), advanced statistical fidelity (SDV backend), **schema drift detection (FR-O.2)**, **coverage-driven generation (FR-O.3)**, **Blueprint-as-code + templates (FR-P.1–2)**, scheduling + notifications (FR-N.4–5), Dataset diff & fidelity report (FR-P.4), local/no-egress model path hardening, multi-tenant RBAC, webhooks.
- **Phase 4:** generalized sinks (warehouses / queues / NoSQL); optional differential-privacy capability (OPEN-14). *(Masking folded into the single generation-from-examples paradigm; subsetting reframed as referentially-consistent prod-example extraction, FR-B.1 — both resolved v0.5, no longer separate modes.)*

---

## 9. REST API Surface *(indicative; planning agent finalizes)*

| Method & Path | Purpose |
|---|---|
| `GET/POST /blueprints`, `GET/PATCH/DELETE /blueprints/{id}` | Blueprint CRUD |
| `POST/GET/PATCH /blueprints/{id}/schema` | Import/read/edit schema |
| `POST/GET/DELETE /blueprints/{id}/examples` | Example data |
| `GET/PUT /blueprints/{id}/rules` | Generation + refinement rules |
| `GET/PUT /blueprints/{id}/validation` | Validation suite |
| `GET/PUT /blueprints/{id}/model-config` | Model selection/config |
| `POST/GET /blueprints/{id}/generator` | Author/read/re-author Generator Artifacts (the authoring loop) |
| `POST /blueprints/{id}/datasets` | **Trigger generation** → `202` + Job |
| `GET /blueprints/{id}/datasets` | List Datasets for a Blueprint |
| `GET/PATCH/DELETE /datasets/{id}` | Dataset CRUD (metadata) |
| `GET /datasets/{id}/rows` (paginated), `PATCH/DELETE /datasets/{id}/rows/{rowId}` | Row-level read/edit/delete |
| `POST /datasets/{id}/validate` | Re-run full-dataset validation → Job |
| `GET /datasets/{id}/validation-report` | Validation results |
| `GET /datasets/{id}/canonical` | Download the CanonicalDataset (Parquet) + LoadPlan |
| `POST /datasets/{id}/materialize` | Materialize/fan-out to one or more sinks → Job |
| `POST /datasets/{id}/teardown` | Scoped teardown from one or more sinks → Job |
| `GET /jobs/{id}`, `POST /jobs/{id}/cancel` | Async status/cancel |
| `GET /providers`, `POST /providers/{id}/test` | List/test model providers |
| `GET/POST /connections`, `POST /connections/{id}/test` | DB connection profiles |

---

## 10. Gaps & Assumptions Summary

The requirements as originally stated did not address: generation architecture (§3 — the big one), referential integrity / generation ordering (FR-A.3, FR-E.3), scale/volume targets (FR-E.5), where generated data lands (FR-G.2 sinks), privacy/leakage and data egress to external models (NFR-PRIV — important given the data this will touch), reproducibility/seeds (NFR-REPRO), async job semantics for long generation (FR-I.2), the distinction between *generation* and *refinement* rules (FR-C vs FR-D — interpreted as: generation = how to make data, refinement = corrective feedback to improve it), how example data actually influences generation (FR-B.3), rule authoring format (FR-C.3), what validation concretely checks and whether failure gates the Dataset (FR-F), versioning of Blueprints for reproducible Datasets (NFR-REPRO), secrets handling (NFR-SEC), and auth/multi-tenancy (NFR-MT). **v0.2 adds:** generated-code execution safety / sandboxing / provable teardown scoping (FR-L, NFR-EXEC), multi-sink simultaneous materialization (FR-G.2), two-tier validation (FR-F.1), and the build-on-dynamic-workflows question (OPEN-9). **v0.3 adds:** the first-class **Generation Library** + thin-glue authoring contract (FR-M.1–2), the **canonical-data + load-plan seam** (FR-M.3, FR-G.2), the **Arrow-anchored canonical type system** and its dialect-mapping footguns (FR-M.4), validate-canonical-once (FR-F.1), the generation-runtime vs DB-access split (§7), and build-vs-adopt the Generation Library (OPEN-11). **v0.4 adds** (gap-audit): the **automation surface** for CI/CD — CLI/SDK, Dataset TTL/ephemeral environments, namespace garbage collection, scheduling, notifications (FR-N); **real-schema correctness** — reference/fixed tables + partial generation, schema drift detection, coverage-driven generation (FR-O); **reuse/portability/governance** — Blueprint-as-code, templates, audit log, Dataset diff/fidelity (FR-P); preview/dry-run (FR-E.6); operability + DX NFRs (NFR-OPS, NFR-DX); and the scope-mode decisions masking/subsetting/DP (OPEN-12–14) plus the reference-tables-MVP question (OPEN-15). **v0.5 resolves** OPEN-2/7/9/11/12/13: a **user-directed product stance** (§2), **privacy = provider choice** (NFR-PRIV rewritten — data *is* sent to the user-selected local/cloud model), a **provider-agnostic authoring loop** (Claude/OpenAI/Gemini/local; dynamic-workflow patterns borrowed, not depended on; FR-H.7), the **Generation Library is built** (SDV optional backend), and **one generation-from-examples paradigm** (no separate masking; subsetting reframed as prod-example extraction, FR-B.1). Still open: OPEN-3/4/5/6/8/14/15. All are covered above, with defaults flagged `[ASSUMPTION]`.

---

## 11. Open Decisions — to resolve before planning *(each has my recommended default)*

1. **`[OPEN-1] — RESOLVED v0.2`** Generation architecture = generated deterministic code via an evaluator-optimizer loop; two-phase (author once / execute deterministically); chain-of-functions with create + teardown; canonical-once + fan-out to sinks. Supersedes the hybrid-plan-interpreter.
2. **`[OPEN-2] — RESOLVED v0.5`** Privacy = **provider choice**, not tool-imposed redaction. Data (incl. real examples, possibly from prod) is sent to the user-selected local/cloud authoring model; the user picks a provider with the isolation they need (local = no egress; cloud under BAA for regulated data). Tool provides visibility (FR-H.6), transparency, output leakage checks, and secure transit — not certification or restriction. See NFR-PRIV + §2 product stance.
3. **`[OPEN-3]` DB support matrix for v1.** Postgres + MySQL + SQL Server + DB2 *(recommended; MVP Postgres-only per §8)* vs narrower/wider. Note DB2 is in scope given your environment.
4. **`[OPEN-4]` Output sink for v1.** File export + download for MVP, gated direct-DB-insert as fast-follow *(recommended)* vs direct insert in v1.
5. **`[OPEN-5]` Rule authoring modality.** Dual NL-compiles-to-structured *(recommended)* vs structured-only vs NL-only.
6. **`[OPEN-6]` Auth / tenancy for v1.** API-key single-tenant, tenant-ready data model *(recommended)* vs full multi-tenant RBAC up front.
7. **`[OPEN-7] — RESOLVED v0.5`** Statistical-fidelity backend = simple numpy stats for MVP; **SDV (or copulas) as an optional pluggable backend** of the Generation Library for the learn-from-example-data mode later. (Resolved with OPEN-11.)
8. **`[OPEN-8]` Scale ceiling for v1.** Architect ~10M rows/table, validate MVP at ~1M *(recommended)* vs different target.
9. **`[OPEN-9] — RESOLVED v0.5`** **Provider-agnostic authoring loop** (Claude / OpenAI / Gemini / local). Build a portable evaluator-optimizer over the provider abstraction; **borrow** dynamic-workflow patterns but do **not** depend on the Anthropic-only feature. Consequence: adapter must normalize structured output + tool-use + code-gen across providers, with a capability floor that surfaces authoring failure (FR-H.7).
10. **`[OPEN-10] — RESOLVED v0.3`** Generation/DB-access split + MCP boundary: generation runs in **Python** (Generation Library); DB access is via **MCP loaders** with normalized contracts, orchestrator is language-blind. **JDBC-MCP** for relational breadth (DB2/Oracle/…); **Python-MCP** only for capability gaps. No one-MCP-per-database. Confirmed.
11. **`[OPEN-11] — RESOLVED v0.5`** **Build** a thin orchestration + authoring-contract Generation Library (owns determinism/ordering/streaming/typing/Parquet/namespace); **compose** Faker/Mimesis + numpy; **SDV** as an optional pluggable fidelity backend. Not adopting SDV as the core engine.
12. **`[OPEN-12] — RESOLVED v0.5`** **No separate masking engine.** One paradigm: import examples → generate fresh synthetic values (leakage-checked). De-identification is emergent from generation, not in-place field masking. Tool is user-directed; no policy restriction on using output in prod (§2 stance).
13. **`[OPEN-13] — RESOLVED v0.5`** **Yes** to extracting a referentially-consistent representative bundle (schema + sample data + formats + examples) from any source **including production**, user-directed (FR-B.1). Reframed from "subsetting mode" to **prod-example extraction** that seeds generation and/or exports.
14. **`[OPEN-14]` Differential privacy (still open, lower priority).** Given privacy-via-provider-choice (OPEN-2), DP becomes an *optional* capability for the statistical-fidelity path when real data is learned from, not a default. Decide later whether to offer formal DP guarantees.
15. **`[OPEN-15]` Is reference/fixed-tables + partial generation (FR-O.1) MVP or Phase 2?** Recommended **MVP** — almost no real schema lacks lookup/reference tables, and pointing at a real DB needs it on day one.
