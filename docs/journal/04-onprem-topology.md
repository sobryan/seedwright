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

## Slice 12 — preview, row browsing, introspect→Blueprint (the UI becomes a product)

**Preview / dry-run (FR-E.6):** `preview_dataset` in the data-engine reuses the authoring
loop's sample path (what you preview is what the judge judged) — a small in-memory sample,
no files, JSON-safe rows (decimals exact strings, temporals ISO). Surfaced as
`POST /api/blueprints/{id}/preview`, the product-MCP tool `preview_blueprint`, and a UI
button rendering per-table sample grids.

**Row browsing (FR-G.1):** `read_rows` pages the canonical Parquet (clamped offset/limit,
path-safe table names) → `GET /api/datasets/{id}/rows`, MCP `read_dataset_rows`, and a UI
browser with prev/next (click a table's row-count chip on any dataset).

**Introspect→Blueprint in the UI:** pick a connection, one click introspects their database
through jdbc-mcp and prefills the Blueprint form's schema + foreign keys — "point seedwright
at your DB" is now a UI flow, not just an agent flow.

Live-verified end-to-end with the temporal demo schema: instant preview (dates + tz-aware
timestamps), then paging through 249 generated orders. data-engine 36, server 11.

## Slice 13 — artifact approval workflow (FR-L.5): the last unenforced safety gate

The spec's non-negotiables include **human approval before generated code first runs
against a real target**. Everything else in FR-L was enforced (ds_ scoping, marker-guarded
drops, confirm-gated writes, injection-safe identifiers) — approval was tracked but not
*enforced*. This slice closes it.

**The gate:** materialization now fails fast at submission unless the EXACT artifacts
version that produced the dataset is human-approved (`JobManager.requireApprovedArtifacts`
→ `ApprovalRequiredException` → 409). Two independent conditions: approval flag = `approved`,
AND the dataset's `artifactsVersion` matches the blueprint's current one (regenerating with
new artifacts after approval doesn't inherit the old approval).

**Approval resets on (re)authoring:** whenever the loop writes fresh artifacts, the blueprint
drops back to `pending_approval` (approving stale-then-changed artifacts is impossible by
construction). Approval is a *named* act — `approvedBy` is required and recorded with a
timestamp (V4 migration adds the three columns).

Because our artifacts are **declarative genspecs, not freeform code**, the "static analysis"
half of FR-L.5 is already satisfied upstream (schema validation + determinism gate); approval
presents that vouched-for artifact to a human rather than re-scanning arbitrary code.

**Surfaced on all three faces:** REST (`GET /blueprints/{id}/artifacts` to review,
`POST /blueprints/{id}/approve`), the product-MCP surface (`get_artifacts` +
`approve_artifacts`, whose description tells the agent approval is a human act — pass the
user's name, only after they've reviewed), and the UI (pending/approved badge, a
"review & approve" button that shows the artifacts and captures the approver, and a
materialize button disabled until approved). server 12 — two new tests prove the confirmed
-but-unapproved path is refused via both REST and a real MCP client, and that approve→load
succeeds.

## Slice 14 — non-Docker packaging: the shippable bundle

The on-prem pivot's payoff: `./package.sh` produces a single relocatable
`seedwright-<version>.tar.gz` a shop can drop on one host and run — **no build tools, no
separate database**. Target prereqs collapse to **Java 21 + uv** (uv provides Python 3.12 and
the data-engine's deps on first start; Maven/Node/npm are build-host-only).

**How it relocates:** every moving part was already config-driven, so packaging is assembly +
a bundle-relative `conf/application.yml` loaded via `--spring.config.additional-location`. The
launcher (`bin/seedwright`) cd's to the bundle root so all `./` paths resolve there — H2 in
`./data`, UI static export in `./ui`, drop-in JDBC drivers in `./drivers`, and the data-engine
spawned as `uv run --project ./data-engine`. The Python projects ship as **source siblings**
(data-engine + generation-library + authoring + postgres-loader) preserving the exact
`../<name>` layout their pyprojects path-depend on, so uv resolves them identically to in-tree
— a pre-built venv would hardcode absolute paths + platform and wouldn't relocate.

**Proven from a relocated copy:** extracted the tarball into a fresh dir (a stand-in target
host) and `./bin/seedwright start` → central server UP, jdbc-mcp UP, UI served (HTTP 200), then
a REST create→generate ran green end-to-end (dataset ready, 20 rows, validation passed) — which
means the server spawned uv and uv resolved the sibling projects with zero in-tree references.
`stop`/`status` verified. Two real packaging bugs found and fixed by the live run: version
parsing grabbed the Spring parent's `3.5.3` instead of the project's `0.0.1` (now reads the
`<version>` following the project artifactId), and the status probe false-negatived jdbc-mcp
(an MCP endpoint 400s a non-MCP ping — any HTTP code, not just 2xx, means UP).

**Deferred:** a fully air-gapped bundle (vendored wheels so first start needs no network) —
today the first `uv sync` fetches Python deps.

## Slice 15 — the refinement loop (FR-D): profile → suggest → apply → regenerate

In a system where rules *drive* generation, a full-dataset validation failure is rare (data
satisfies the rules by construction), so the valuable refinement loop is **inspection-driven**:
profile the data you just generated and propose rules that TIGHTEN the Blueprint.

**The profiler** (`run_suggest_rules`, data-engine): reads a Dataset's canonical Parquet and
proposes ColumnRule patches — low-cardinality STRING columns → `enum`, numeric spread →
`value_range` (money-safe string bounds), observed nulls → `max_null_rate` (rounded up so it
never sits below what was seen). Skips identifier columns (`id`, `*_id`) and any column that
already carries a rule, so suggestions are disjoint from existing intent and never conflict.
Each suggestion's `rule` is directly appendable to the Blueprint. 5 unit tests on a hand-built
fixture pin the exact proposals.

**The apply mechanic** (`PUT /api/blueprints/{id}/rules`): replacing rules invalidates the
cached Generator Artifacts AND their approval (nulls both) — the next generate re-authors
against the new intent (FR-L.5 approval must be re-earned). Already-generated Datasets are
untouched.

**Surfaced everywhere:** REST (`GET /datasets/{id}/suggestions`, `PUT /blueprints/{id}/rules`),
product MCP (`suggest_rules`, `update_blueprint_rules` — the tool copy tells the agent adopting
suggestions invalidates approval), and the UI (a "refine" button on any ready dataset → a
checklist of suggestions with their reasons → "apply & regenerate"). data-engine 41, server 13.

**Proven live through real MCP:** generated 30 customers with an unruled `score` column; the
Python profiler read the Parquet, saw the 58184..940021 spread, and proposed exactly that
`value_range`; `PUT /rules` adopted it and cleared `artifactsVersion` (re-author forced). A
ruled column and the `id` column were correctly left un-suggested.

## Slice 16 — a second real provider (Anthropic): proving NFR-AGNOSTIC

The Copilot CLI provider showed one real backend worked; a second, structurally different one
proves the abstraction is real rather than incidental. `AnthropicProvider` (data-engine) sits
behind the same authoring `Provider` protocol and — crucially — **reuses `build_prompt` and
`extract_genspec` verbatim** from the Copilot provider. Only the *transport* differs: an HTTP
POST to the Anthropic Messages API (stdlib `urllib`, no SDK dependency) instead of shelling out
to a CLI. That the prompt and extraction are shared is the point: provider-agnosticism lives at
authoring, and everything downstream (compile → generate → validate → load) is untouched.

**Testable offline by construction:** the network call sits behind an injectable `runner` (the
same seam the Copilot provider uses). `build_request` (URL + headers + body) and `parse_reply`
(assistant text out of the Messages envelope, `""` on any malformed/blocked shape) are pure and
unit-tested; a blocked reply becomes an empty genspec → PARSE_ERROR the loop refines on, never a
crash (FR-H.7). 6 new tests, all offline — no key, no network. The real HTTP path is deliberately
not exercised in CI: calling it would send schema/rules to an external service and cost money, so
it stays behind the key + explicit provider selection (NFR-PRIV: privacy is the provider choice).

**Threaded through the stack:** `PROVIDERS` now `(heuristic, copilot-cli, anthropic)`; `run_author`
gains an `anthropic` branch (+ an `_anthropic_runner` test seam); the data-engine tool doc, the
product-MCP `create_blueprint` description, and the UI provider select all list it. One real
integration fix the design forced: the server spawns the data-engine over stdio MCP, and the SDK
passed only a filtered child env — so `ANTHROPIC_API_KEY` wouldn't reach the engine. The spawn now
inherits the operator's full environment (`.env(System.getenv())`), the on-prem-correct behavior
for a tool configured by env vars. data-engine 47, server 13.

## Deferred (cloud phase / fast-follows)

Central-server↔jdbc-mcp wiring for direct DB sinks end-to-end; UI static export baked into the
server jar (currently separate); relay-node hardening (mTLS, signed command tokens, egress
lockdown); real LLM provider adapters; DB2 driver + dialect entry; date/timestamp generators in
the genlib catalog (most real schemas need them — nearest-term gap); packaging (uberjar +
worker bundle + Docker).
