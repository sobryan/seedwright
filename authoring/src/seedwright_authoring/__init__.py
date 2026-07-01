"""seedwright authoring loop — the model-agnostic evaluator-optimizer (spec §3A, FR-E.1).

Authors Generator Artifacts: the model emits a declarative Generator Spec (JSON) that is
validated and compiled into the generation library's SchemaSpec, then a sample is generated,
judged against derived data-tests, and refined until it passes (or fails explicitly). Offline
by construction via a deterministic mock provider; execution stays model-free.
"""

__version__ = "0.0.1"
