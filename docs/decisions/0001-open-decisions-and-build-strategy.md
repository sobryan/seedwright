# ADR 0001 — Open decisions resolved + build strategy

**Date:** 2026-06-30
**Status:** Accepted (autonomous, per user directive to "make all reasonable decisions")
**Context:** `synthetic-data-creator-requirements.md` v0.5 left several `[OPEN]` forks. This ADR resolves each with reasoning and fixes the build strategy so implementation can proceed without further gating questions. Supersedes nothing; future ADRs may revise.

---

## Build strategy

**We build the keystone vertical slice first, bottom-up, starting from the most testable unit.**

The spec's §3 keystone (two-phase generation) and §FR-L safety invariants are the highest-risk, most novel part of the system. Everything else (REST CRUD, React UI, connection management) is conventional. So we prove the risky core end-to-end before layering conventional plumbing around it.

Bottom-up build order within the slice:

1. **Generation Library** (Python, sub-project A) — pure, offline-testable, no DB/model. **← we start here.**
2. **Postgres loader + canonical→dialect mapping + scoped teardown** (sub-project C) — needs a DB.
3. **Authoring loop with a mock provider** (sub-project B) — proves the evaluator-optimizer loop and deterministic test mode without live model spend.
4. **Validation against the canonical Parquet** (part of A/C).
5. **Thin CLI** stitching the slice into a `provision → validate → teardown` flow (early FR-N.1).

The Spring orchestrator + REST API (D), React UI (E), and full observability (F) come after the core is proven.

**Discipline:** incremental TDD (RED→GREEN→REFACTOR). The full test suite is the regression corpus and is run in its entirety on every new feature. No feature is "done" until the whole suite is green.

---

## Open decisions

### OPEN-3 — v1 database matrix → **Postgres only for the slice/MVP; additive dialects after**
Prove the canonical→dialect seam once against Postgres. The canonical type system and the loader interface are designed so adding MySQL / SQL Server / DB2 is purely additive (a new loader + a new canonical→SQL mapping table), with **no change to the Generation Library or canonical format** (NFR-EXT). DB2's footguns (no historical native boolean, decimal/timestamp semantics) are captured as canonical-type metadata now so a DB2 loader later has what it needs.

### OPEN-4 — v1 output sink → **file export + a gated direct-Postgres load**
File export of the Canonical Dataset (Parquet) plus rendered SQL/CSV/JSON is the always-available sink. The keystone slice *also* includes a **direct Postgres load**, because proving scoped, idempotent, reversible load+teardown on real infra is the entire point of the slice. Direct-DB writes stay **gated behind explicit confirmation** and least-privilege, namespace-scoped roles (FR-G.4, FR-L.1–3).

### OPEN-5 — rule authoring modality → **structured representation is the source of truth; NL is a later convenience front-end**
The Generation Library consumes only the **structured** rule form. Natural-language→structured compilation is an authoring-time concern that needs a model and belongs to the orchestrator/authoring loop (built later, and only as a convenience over the canonical structured form). This keeps the deterministic core model-free.

### OPEN-6 — auth / tenancy for v1 → **API-key single-tenant, tenant-ready data model**
Adopt the spec default. Not relevant to the Generation Library; recorded here for the API sub-project. `owner`/`tenant` fields exist in the domain model from day one.

### OPEN-8 — scale ceiling → **architect for ~10M rows/table via streaming; validate at ~1M**
The Generation Library streams from the start: generate a chunk → write Parquet → free memory. Correctness tests run at small sizes for speed; a `@pytest.mark.slow` performance test exercises the ~1M-row path and is excluded from the default fast loop but included in full regression runs.

### OPEN-14 — differential privacy → **out of scope (Phase 4, optional)**
Deferred entirely. Privacy in MVP is provider-choice (NFR-PRIV) + always-on output-leakage validation (FR-F.2), not formal DP.

### OPEN-15 — reference/fixed tables + partial generation → **in scope for MVP, modeled from day one**
Almost no real schema lacks lookup tables, so this is MVP. Each table is classed **generated**, **reference**, or **excluded**. The Generation Library:
- generates only `generated` tables;
- for FKs into `reference` tables, samples from a **provided key pool** (in-memory) now;
- defers *live sampling of existing keys from a running reference table* to the loader milestone (it needs a DB connection).

This makes MVP honest without over-building the loader before we have one.

---

## Supporting build-level decisions

- **Python 3.12** (via `uv`), **pytest** for tests, **ruff** for lint, **mypy** for types. `uv` manages the venv + lockfile for reproducibility.
- **Canonical substrate = pyarrow (Arrow/Parquet) + numpy (distributions) + Faker (value primitives)** for MVP. The substrate is hidden behind the library's authoring API (FR-M.5); DuckDB/Polars can replace the internals later without changing generated glue or canonical output. No DuckDB yet — added only when the out-of-core path demands it.
- **Determinism model:** one root seed → deterministically-derived per-table/per-column sub-seeds (hash of `root_seed + table + column`), so column generation is order-independent and cannot leak cross-column RNG state. No wall-clock, no unseeded randomness anywhere in the execution path. Faker/numpy are always seeded from a derived sub-seed.
- **Determinism gate** (FR-L.4): generate twice with the same seed, assert identical canonical output (Arrow table equality + Parquet round-trip), before a generator is accepted.
- **Canonical type system** is anchored on Arrow logical types, carrying source SQL type + precision/scale/length/nullability as metadata. Footguns handled explicitly: `DECIMAL` → Arrow `decimal128(p,s)` (**never float**); `TIMESTAMP` carries tz semantics; `BOOLEAN`, string length/encoding, and no-clean-primitive types (JSON/UUID/array) each get a documented convention.
