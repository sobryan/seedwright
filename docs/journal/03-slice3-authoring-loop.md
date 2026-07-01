# Journal — Slice 3: Authoring loop (complete)

**Date:** 2026-07-01 · **Status:** ✅ complete · **Tests:** 62 passing · ruff + mypy-strict clean

The model-agnostic **evaluator-optimizer** that authors Generator Artifacts (spec §3A, FR-E.1, FR-H.7). Proves the *other* half of the §3 keystone (the authoring phase), fully offline with a mock provider — completing the two-phase story: authoring (model-in-loop) produces artifacts; execution (genlib, model-free) runs them deterministically.

## The idea, realized

The model emits a **declarative genspec (JSON)** — per-column generator choice + params, FK cardinality, per-table volume. It is validated, **compiled into genlib's `SchemaSpec`** (real generators), sample-generated, judged against data-tests, and refined until it passes — then the determinism gate runs and the artifact is finalized. The model never writes code; determinism is genlib's by construction. The genspec + data-tests are the versioned Generator Artifacts.

## How it was built

1. **Design fan-out (workflow `wf_0769092f`, 5 agents).** Four facet designs + adversarial critic. The critic caught that the facets had shipped **three incompatible genspec dialects** and two loop designs; it froze one contract (ADR-0003) and gave a 14-step build order. It also debunked one facet's determinism-gate rationale as factually wrong for this genlib.
2. **Bottom-up TDD** in that order: `feedback` → `genspec` → `imported` → `catalog` → `validate` → `compile` → **integration checkpoint** → `rules` → `datatests` (judge) → `provider` (scripted mock) + `capability` → `artifacts` → `loop` → e2e.
3. **Adversarial correctness review (workflow `wf_d8bad4b6`).**

## Load-bearing decisions (from the critic, all honored)

- **Type authority = imported schema, not the model.** The model asserts `canonical_kind`; the compiler pulls the authoritative `CanonicalType` (precision/scale/source_sql) from `ImportedSchema`. A `numeric(19,4)` column can't be authored as `numeric(10,2)` — `KIND_MISMATCH` catches the lie. (Money-safety, FR-M.4.)
- **FK bidirectional invariant** (`FK_GENERATOR_CONFLICT`): exactly the `foreign_keys[]` columns use `{kind:fk}`; the shared placeholder generator can never run.
- **Determinism gate is a cheap mandatory barrier**, not oversold — with the MVP catalog it can't reject a catalog generator (documented). The rejection path is exercised only by a fabricated bad generator.
- **Static catches** for cycles + known-count unique-infeasibility (no wasted refine iterations). **Fail-fast** on missing reference pools + capability floor (un-actionable by the model).
- **Judge derives tests from declared rules**, never the generator's own params (no tautology).
- **Scripted MockProvider** (`[bad, good]` / `[always-bad]`) proves happy/refine/exhaust with zero LLM cost.

## Properties proven by tests

- **Integration checkpoint**: compiled genspec → genlib `generate_dataset` under `assert_deterministic` → deterministic + referentially valid (every FK resolves, cardinality bounded).
- **The loop**: happy-path (1 iter), refine-after-judge-failure (value-range), refine-after-static-validation (KIND_MISMATCH), explicit `AuthoringFailed` on exhaustion (never returns a bad generator), capability floor fails before any propose, `max_iters<1` guard, and **reproducibility** (same inputs → byte-identical artifact).
- **Cross-facet contract**: judge/validation failures feed the provider's refine request unchanged.
- **14 static validation codes** (KIND_MISMATCH, GENERATOR_INCOMPATIBLE, FK_GENERATOR_CONFLICT both directions, COLUMN_UNKNOWN/MISSING, ROWCOUNT_*, UNIQUE_INFEASIBLE, PK_NULLABLE, FK_UNRESOLVED/TYPE_MISMATCH, NO_MVP_GENERATOR, CYCLE).

## Known limits (documented, deferred)

Real LLM adapters (Anthropic/OpenAI/Gemini/local) behind the same provider protocol; rule-based repairing mock; k-anonymity/distance leakage (verbatim-only unit-tested, never reached e2e by the mock); unique-at-scale (small sample can pass then fail at full scale — steer strict-unique to Serial). The determinism gate is a tautology for the current catalog.

## Next: real provider adapter, a thin CLI stitching authoring → genlib → pgloader end-to-end, or the Spring orchestrator/REST layer.
