# ADR 0003 — Authoring loop (Slice 3) design

**Date:** 2026-07-01
**Status:** Accepted
**Method:** 4-facet design fan-out + adversarial critic (workflow `wf_0769092f`, 5 agents). The critic found the facets had shipped three incompatible genspec dialects, two loop designs, and three failure-record shapes. This ADR freezes the single shared contract and records the reconciled design.

## The big idea

The authoring model does **not** write code. It emits a **declarative Generator Spec (JSON)**: per-column generator choice + params, FK cardinality, per-table volume, table classes. That JSON is validated and **compiled into genlib's `SchemaSpec`** (real `Generator` objects). Determinism is genlib's by construction — the model only *chooses*. The genspec + its data-tests are the versioned **Generator Artifacts**.

Two-phase: **authoring** (model-in-loop, once) produces artifacts; **execution** (model-free, deterministic) runs them. This slice is authoring; genlib (execution) is already built.

## Frozen genspec schema (STEP 0 — every module imports this)

```json
{
  "genspec_version": "1",
  "seed": 42,
  "tables": [{
    "name": "customers",
    "table_class": "generated",              // generated | reference | excluded (mapped to genlib TableClass)
    "row_count": 1000,                        // null iff the table has a driving FK into a generated parent
    "primary_key": ["id"],
    "foreign_keys": [{"column": "...", "references_table": "...", "references_column": "...",
                      "min_per_parent": 0, "max_per_parent": 20}],
    "columns": [{
      "name": "id", "canonical_kind": "INT64",           // an ASSERTION; authoritative type comes from ImportedSchema
      "generator": {"kind": "serial", "params": {"start": 1}},
      "unique": true, "nullable": false, "null_rate": 0.0
    }, {
      "name": "customer_id", "canonical_kind": "INT64",
      "generator": {"kind": "fk"}                          // sentinel; dataset.py fills it, generator never runs
    }]
  }]
}
```

**Load-bearing rules the critic mandated:**
1. **Type authority = `ImportedSchema`, not the model.** The model asserts `canonical_kind`; the compiler pulls the authoritative `CanonicalType` (precision/scale/length/source_sql) from `ImportedSchema`. A `numeric(19,4)` column authored as `numeric(10,2)` is impossible — the model can't supply precision/scale. Mismatched kind → `KIND_MISMATCH` validation error. (Rejects the facet that passed a raw SQL `type` through `from_sql` — that would silently corrupt money, FR-M.4.)
2. **FK bidirectional invariant.** Exactly the columns named in `foreign_keys[].column` use `{"kind":"fk"}`, and no others (`FK_GENERATOR_CONFLICT`). The shared placeholder generator is safe *only* because `dataset.py` fills every FK column (generate.py:70); an unlisted `fk` column would let the placeholder actually run.
3. **`row_count`** mirrors genlib exactly: omit (null) on a driving-FK child (count is derived); require on a non-driving generated table; ignore on reference/excluded.
4. **Determinism gate is a cheap mandatory barrier, not a tautology-breaker.** With the MVP catalog every generator is deterministic and `generate_dataset` never consumes the root stream, so the gate can't reject a catalog-built generator. Keep it (defense + FR-L.4), but do **not** assert "reusing one SeededRng would differ" — verified false. The rejection path is exercised only via a fabricated bad generator fixture.

## Single shared `Failure` (judge → loop → provider)

`Failure{category, table, column, test_id, detail, feedback}` where `category ∈ {validation, structural, constraint, referential, null_rate, leakage, uniqueness, generation}`. Static validation issues and judge data-test failures both convert to `Failure` — that is the loop's uniform refine signal.

## Reconciled decisions

- **Declared intent (`RuleSet`) is separate from the genspec.** The judge derives range/enum/null_rate tests from user-declared rules, never from the generator's own params (else it checks a generator against itself). Structural + referential tests come from the schema and always run.
- **Scripted `MockProvider`** returns a fixed sequence of genspec dicts (`[bad, good]`, `[always-bad]`). Deterministic; proves happy-path, refine-then-pass, and exhaustion with no coupling to the failure vocabulary. (Rule-based repairing mock deferred.)
- **Capability floor** = a single `structured_json_output` check at loop entry → `CapabilityFloorError` (FR-H.7). Multi-provider envelope normalizer deferred (no real adapters yet).
- **Fail-fast at loop entry:** missing `reference_pools` for a reference FK is a precondition failure (the model can't fix pools — they're task input), not a refine signal. Schema cycles and known-count unique-infeasibility are caught **statically** in `validate`, not after N wasted iterations.
- **`GeneratorArtifacts`** = genspec + derived data-tests + `Provenance{provider_id, model, iterations, determinism_gate_passed, genlib_version, approval_status}`, `approval_status` defaults `PENDING_APPROVAL` (FR-L.5). Simple deterministic version + `to_dict`/`from_dict`. No tamper re-verification (deferred).
- **Loop on exhaustion RAISES `AuthoringFailed`** carrying the transcript — never returns a failing generator (FR-H.7).

## Known limits (documented, deferred)

Determinism gate can't reject a catalog generator (tautology for MVP). Unique-at-scale: a `UNIQUE` column with a small domain on a driving-FK child can pass the small sample gate then raise `UniquenessError` at full scale — steer strict-unique columns to `Serial`. Leakage is unit-tested but the mock loop never emits a leaking sample end-to-end (mock picks fresh `faker` for identifying columns). Real LLM adapters, k-anonymity/distance leakage, autonomous repairing mock: all deferred.

## TDD build order

`feedback` (Failure) → `genspec` (parse/to_dict) → `imported` (ImportedSchema + column_type) → `catalog` (build_generator) → `validate` → `compile` → **integration checkpoint** (compiled → `generate_dataset` under `assert_deterministic`) → `rules` + `datatests` (judge) → `provider` (scripted mock) + `capability` → `artifacts` → `loop` → **end-to-end golden + cross-facet contract test**.
