# seedwright

A model-agnostic **synthetic data generation platform**. Define a **Blueprint** (a DB connection + imported schema + example data + generation rules + validation suite + model config), then generate many reproducible, validated **Datasets** of synthetic data from it and materialize them to one or more database/file sinks.

The keystone is a **two-phase** design: an **authoring phase** (a model-in-the-loop evaluator-optimizer writes generator artifacts *once*) and a **deterministic execution phase** (a worker runs those artifacts with a seed — no model involved — so the same inputs always produce byte-identical data).

> **Status: early, actively built.** The requirements spec (`synthetic-data-creator-requirements.md`) is the source of truth; `CLAUDE.md` is the working guide; `docs/decisions/` holds ADRs and `docs/journal/` logs each milestone.

## What's built

| Sub-project | What it is | State |
|---|---|---|
| [`generation-library/`](generation-library) | The deterministic substrate (Python): seeded RNG, canonical Arrow types, generators, FK-topological cross-table generation, streamed Parquet writer, Load-Plan emitter, determinism gate. | ✅ 92 tests |
| [`postgres-loader/`](postgres-loader) | Turns canonical Parquet + Load-Plan JSON into a **scoped, idempotent, reversible** Postgres load + teardown. Injection-safe, marker-guarded, one transaction. | ✅ 122 tests (+ live-DB integration) |
| [`authoring/`](authoring) | The model-agnostic **evaluator-optimizer**: a model emits a declarative genspec → validate → compile into the generation library → sample → judge → refine → determinism gate → versioned Generator Artifacts. Offline via a mock provider. | ✅ 74 tests |

The two-phase keystone is proven end-to-end: **authoring** writes artifacts → the **generation library** executes them deterministically → the **loader** materializes them to Postgres.

## Architecture at a glance

```
Blueprint ─▶ authoring loop (model)  ─writes─▶  Generator Artifacts (declarative, versioned)
                                                        │  executed deterministically (no model, seeded)
                                                        ▼
                                          Canonical Dataset (Arrow → Parquet) + Load Plan
                                                        │
                        ┌───────────────────────────────┼───────────────────────────────┐
                        ▼                                ▼                                ▼
                validate once                    Postgres loader                  file export
             (against canonical)          (scoped schema, teardown)          (Parquet/SQL/CSV)
```

## Principles

- **Determinism is enforced, not hoped for** — no wall-clock, no unseeded randomness in any execution path; a double-run gate rejects anything that isn't reproducible.
- **Safety is structural** — synthetic data lands only in an isolated, identifiable namespace; a bare `DROP TABLE`/`DELETE FROM` is never emitted; untrusted imported identifiers are always safely composed.
- **Model-agnostic** — the model only *chooses* generators; execution is model-free by construction, so swapping providers never changes how data is produced.

## Development

Each Python sub-project uses [`uv`](https://docs.astral.sh/uv/). See each sub-project's README and `CLAUDE.md` for commands. In short: `cd <sub-project> && uv sync && uv run pytest`.

## License

See [`LICENSE`](LICENSE).
