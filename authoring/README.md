# seedwright authoring loop

The model-agnostic **evaluator-optimizer** that authors **Generator Artifacts** (spec §3A,
FR-E.1, FR-H.7). The authoring model emits a *declarative Generator Spec (JSON)* — per-column
generator choice + params, FK cardinality, per-table volume — which is validated and **compiled
into the generation library's `SchemaSpec`**. The model never writes freeform code; determinism
is preserved because genlib executes deterministically. The loop:

```
propose (genspec) → compile → generate sample → judge (data-tests)
   → pass? → determinism gate → finalize Generator Artifacts (pending_approval)
   → fail? → feedback → refine → loop (up to N; explicit failure on exhaustion)
```

Fully **offline** for MVP via a deterministic **MockProvider** (no LLM, no API keys, no cost).
Real Anthropic/OpenAI/Gemini/local adapters slot in behind the same provider abstraction later.

## Development

Uses [`uv`](https://docs.astral.sh/uv/). Path-depends on `../generation-library`.

```bash
cd authoring
uv sync            # installs genlib (editable) + dev tools
uv run pytest      # full regression suite — run on EVERY change
uv run ruff check .
uv run mypy
```
