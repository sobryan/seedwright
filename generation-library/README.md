# seedwright Generation Library

The deterministic substrate (spec FR-M) that thin-glue generators target. Owns seeded RNG, canonical typing, FK ordering, streamed Parquet output, the Load-Plan emitter, and the determinism gate. No model runs here; execution is model-free and reproducible.

## Development

Uses [`uv`](https://docs.astral.sh/uv/). Python 3.12.

```bash
cd generation-library
uv sync                 # create venv + install runtime and dev deps
uv run pytest           # run the full regression suite (fast tests)
uv run pytest -m slow   # run the large-scale/perf tests
uv run pytest -m "not slow"   # fast loop only
uv run ruff check .     # lint
uv run mypy             # type-check src
```

The **entire suite is the regression corpus** — run `uv run pytest` on every change; nothing is "done" until it is green.
