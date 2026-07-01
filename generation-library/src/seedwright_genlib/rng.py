"""Seeded, reproducible randomness — the root of determinism (spec §3, NFR-REPRO).

The whole architecture rests on one guarantee: same ``(schema, rules, seed)`` produces
identical output, forever. That requires two things this module provides:

1. **Stable seed derivation** (``derive_seed``) that is identical across processes and
   library runs — not Python's built-in ``hash()`` (which is salted per-process for
   strings). We use BLAKE2b over a length-prefixed encoding so labels can't collide at
   their boundaries (``("a", "b")`` must differ from ``("ab",)``).

2. **Order-independent streams** (``SeededRng.derive``). Each table/column gets its own
   RNG stream derived from the *seed value*, never from another stream's consumed state.
   So columns can be generated in any order, or in parallel, without changing output.
"""

from __future__ import annotations

import hashlib

import numpy as np
from faker import Faker

_UINT64 = 2**64


def derive_seed(root_seed: int, *labels: str) -> int:
    """Derive a stable ``uint64`` sub-seed from a root seed and a path of labels.

    Deterministic across processes and runs. Length-prefixing each component prevents
    boundary collisions between different label tuples.
    """
    h = hashlib.blake2b(digest_size=8)

    def _write(chunk: bytes) -> None:
        h.update(len(chunk).to_bytes(8, "big"))
        h.update(chunk)

    _write(str(int(root_seed)).encode("utf-8"))
    for label in labels:
        _write(label.encode("utf-8"))
    return int.from_bytes(h.digest(), "big")


class SeededRng:
    """A seed handle that materializes reproducible RNG streams.

    ``numpy()`` and ``faker()`` lazily materialize (and cache) one stream per handle, so a
    generator holds a single advancing stream for its column. ``derive(*labels)`` produces
    an independent child handle whose stream depends only on the derived seed value — never
    on how much this handle has been consumed.
    """

    __slots__ = ("_seed", "_np", "_fakers")

    def __init__(self, seed: int) -> None:
        self._seed = int(seed) % _UINT64
        self._np: np.random.Generator | None = None
        self._fakers: dict[str | None, Faker] = {}

    @property
    def seed(self) -> int:
        return self._seed

    def numpy(self) -> np.random.Generator:
        if self._np is None:
            self._np = np.random.Generator(np.random.PCG64(self._seed))
        return self._np

    def derive(self, *labels: str) -> SeededRng:
        return SeededRng(derive_seed(self._seed, *labels))

    def faker(self, locale: str | None = None) -> Faker:
        cached = self._fakers.get(locale)
        if cached is None:
            cached = Faker(locale)
            cached.seed_instance(self._seed)
            self._fakers[locale] = cached
        return cached
