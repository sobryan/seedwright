"""seedwright Generation Library — the deterministic substrate (spec FR-M).

Thin-glue generators target this library. It owns everything determinism-critical:
seeded RNG, canonical typing, FK ordering, streamed Parquet output, the Load-Plan
emitter, and the determinism gate. No model runs here; execution is model-free and
reproducible by construction.
"""

__version__ = "0.0.1"
