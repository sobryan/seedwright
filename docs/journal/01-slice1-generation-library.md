# Journal — Slice 1: Generation Library (complete)

**Date:** 2026-06-30 · **Status:** ✅ complete · **Tests:** 92 passing (incl. 1 `@slow` 1M-row) · ruff + mypy-strict clean · ~866 LoC src

The deterministic substrate (spec FR-M) is built and proven end-to-end offline. This is the
highest-risk, most novel part of the platform — done first, on purpose.

## What was built (TDD, RED→GREEN→REFACTOR each step)

| Module | Responsibility | Key spec ties |
|---|---|---|
| `rng.py` | Stable seed derivation (BLAKE2b, cross-process) + order-independent per-column streams | §3, NFR-REPRO |
| `types.py` | Arrow-anchored canonical type system + Postgres SQL→canonical parsing | FR-M.4 |
| `generators.py` | Seeded value generators: `IntRange`, `Categorical`, `Serial`, `DecimalRange`, `FakerField` | FR-C.2, FR-M.2 |
| `schema.py` | Structured spec: `ColumnSpec`/`ForeignKeySpec`/`TableSpec`/`SchemaSpec`, table classes | OPEN-5, FR-O.1 |
| `generate.py` | Single-table generation: PK/unique enforcement, null-rate, canonical typing | FR-E.3, FR-C.4 |
| `dataset.py` | Cross-table: FK topo order + cycle detection, cardinality expansion, reference pools | FR-A.3, FR-E.3, FR-O.1 |
| `parquet.py` | Row-group-batched Parquet writer, one file/table | FR-M.3, FR-E.4, NFR-SCALE |
| `loadplan.py` | Load-Plan emitter (topo order, namespace, row counts, per-column type hints) | FR-M |
| `determinism.py` | Double-run determinism gate | FR-L.4, §3 |

## Properties proven by tests (the ones that matter)

- **Reproducibility**: same `(schema, seed)` ⇒ byte-identical Arrow output; a golden seed value
  is pinned so the derivation algorithm can't drift silently.
- **Order-independence**: per-column RNG streams derive from the seed *value*, not another
  stream's consumed state → columns can be reordered/parallelized without changing output.
- **Chunk-invariance**: random generators draw from a persistent stream; splitting a run into
  chunks yields the identical concatenation (prerequisite for streamed 10M-row generation).
- **Referential integrity**: every generated FK value resolves to a real parent key; per-parent
  cardinality bounds respected; reference-table FKs sample only from the provided pool.
- **Money safety**: `DECIMAL` → Arrow `decimal128(p,s)`, `Decimal` end-to-end, scale preserved
  exactly — never a binary float.
- **Determinism gate**: a build that sneaks in unseeded randomness (`secrets`) is rejected.
- **Scale**: 1M rows generated + Parquet-written in ~0.5s (vectorized path).

## Decisions made along the way

- Seed derivation uses BLAKE2b over a length-prefixed encoding (not Python `hash()`, which is
  per-process salted) — required for cross-process reproducibility.
- `Serial` is offset-driven (not stream-driven) so chunked PK generation stays contiguous.
- MVP substrate = pyarrow + numpy + Faker; DuckDB/Polars deferred until the out-of-core path
  demands it (FR-M.5 keeps the substrate swappable behind the API).

## Known limitations (tracked, deferred with intent)

- Uniqueness for non-`Serial` unique columns is *checked* (raises on collision), not *guaranteed*
  by without-replacement sampling. Fine for surrogate-key MVP; revisit for natural unique keys.
- Self-referential / circular FKs are detected and rejected; the nullable-first-pass break
  strategy (FR-A.3) is future work.
- Multi-parent cardinality: a table's row count is driven by its first FK to a generated parent;
  additional generated-parent FKs sample from pools. Documented in `dataset.py`.
- Generation materializes full arrays in memory per table (fine ≤1M per OPEN-8); truly streamed
  *generation* (vs streamed *write*, which is done) is a later enhancement toward the 10M ceiling.

## Next: Slice 2 — Postgres loader + safety (FR-G, FR-L, FR-M.4 canonical→Postgres)

Test-DB strategy (Docker unavailable): unit-test the canonical→Postgres DDL/bulk-load SQL
generation + namespace scoping + idempotent teardown offline (deterministic, no live DB), with
live-Postgres tests marked `@pytest.mark.integration` that auto-skip when no server is reachable.
A local Postgres can be wired in to exercise them for real.
