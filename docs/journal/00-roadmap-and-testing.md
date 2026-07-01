# Roadmap, milestones & testing strategy

This is the living plan for building seedwright. It records *what* we build, in *what order*, and *how we prove it*. Cross-references use the requirements tags (`FR-*`, `NFR-*`) from `synthetic-data-creator-requirements.md`.

## Guiding discipline

- **Incremental TDD.** Every feature: write a failing test (RED) → minimal code to pass (GREEN) → refactor. No implementation without a failing test first.
- **The suite is the regression corpus.** The entire pytest suite runs on every new feature. A feature is not done until the whole suite is green. Slow/large-scale tests are marked and included in full regression runs.
- **Determinism is a first-class test target**, not an afterthought — it's the property the whole architecture depends on.

## Milestones

### Slice 1 — Generation Library (Python) `[in progress]`
The deterministic substrate (FR-M). Pure Python, offline, no DB or model.

| Step | Feature | Proves |
|---|---|---|
| M1.1 | Project scaffold + sanity test | Toolchain/pytest works |
| M1.2 | `SeededRng` — deterministic sub-seed derivation | NFR-REPRO foundation |
| M1.3 | Canonical type system (Arrow-anchored) + source-SQL→canonical | FR-M.4 |
| M1.4 | Column generators (int-range, categorical-weighted, faker-backed), all seeded | FR-C.2, FR-M.2 |
| M1.5 | Table generator with PK uniqueness | FR-E.3 (partial) |
| M1.6 | FK topological ordering + FK cardinality sampling (incl. reference-table key pools) | FR-A.3, FR-E.3, FR-O.1 |
| M1.7 | Arrow assembly + streamed Parquet writer (chunked) | FR-M.3, FR-E.4, NFR-SCALE |
| M1.8 | Load-Plan emitter | FR-M / Load Plan |
| M1.9 | Determinism gate (double-run) | FR-L.4, §3 |
| M1.10 | `@slow` perf test at ~1M rows/table | FR-E.5, OPEN-8 |

### Slice 2 — Postgres loader + safety (sub-project C)
Canonical + Load Plan → scoped Postgres load + teardown. Needs a DB (resolve test-DB strategy: local Postgres or `pytest-postgresql`; Docker unavailable).
Covers FR-G.2/3, FR-L.1–3/6, FR-M.4 (canonical→Postgres), FR-F.1c.

### Slice 3 — Authoring loop with mock provider (sub-project B)
Evaluator-optimizer loop authors thin glue; sample-and-judge; deterministic test mode (NFR-TEST). Provider abstraction with a mock + one real adapter. Covers FR-E.1, FR-H.7, §3A.

### Slice 4 — Validation suite against canonical
Structural / constraint / referential / business / leakage checks against the Parquet (FR-F.1b/F.2), ValidationReport.

### Slice 5 — Thin CLI
`provision → validate → teardown` with JSON output + non-zero exit codes (early FR-N.1).

### Later slices
Spring orchestrator + REST API (D), React UI (E), full observability + OTel (F), then Phase-2 features (more dialects, refinement loop, TTL/GC, audit log).

## Testing strategy

- **Unit** — every generator, type mapping, ordering, emitter. Deterministic by construction.
- **Property/invariant** — determinism gate (same seed ⇒ identical output; different seed ⇒ different output), PK uniqueness, FK resolvability, null-rate within tolerance, canonical type fidelity (decimal precision preserved, no float money).
- **Golden/regression** — pin representative canonical outputs; these are the saved regressions replayed on every change.
- **Scale** — `@pytest.mark.slow` at ~1M rows, memory-bounded (streamed).
- **Integration** (Slice 2+) — real Postgres load/teardown, idempotency, scoping.

Run commands live in each sub-project's README and are mirrored into `CLAUDE.md` as they solidify.
