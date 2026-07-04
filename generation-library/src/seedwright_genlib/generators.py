"""Value generators (spec FR-C.2, FR-M.2).

A generator turns a seeded RNG stream + a requested count into column values. The glue
picks one generator per column. Two determinism contracts every generator must honour:

- **Random** generators draw from ``rng``'s persistent stream, so splitting a run into
  chunks never changes the concatenated result (``offset`` is ignored — position in the
  stream already encodes it).
- **Sequential** generators (``Serial``) are pure functions of ``offset`` and ignore the
  random stream, so a chunked run continues the sequence correctly.

New column types are added here without touching the engine (NFR-EXT).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, Protocol, cast, runtime_checkable

import numpy as np

from .rng import SeededRng


@runtime_checkable
class Generator(Protocol):
    """Produces ``n`` column values from a seeded RNG, starting at global row ``offset``."""

    def generate(self, rng: SeededRng, n: int, offset: int = 0) -> Sequence[Any]: ...


class IntRange:
    """Uniform integers in the inclusive range ``[low, high]``."""

    def __init__(self, low: int, high: int) -> None:
        if high < low:
            raise ValueError(f"IntRange high ({high}) < low ({low})")
        self._low = low
        self._high = high

    def generate(self, rng: SeededRng, n: int, offset: int = 0) -> Sequence[int]:
        # high is inclusive; numpy's integers() upper bound is exclusive
        return cast("list[int]", rng.numpy().integers(self._low, self._high + 1, size=n).tolist())


class Categorical:
    """Weighted choice over a fixed set of values (uniform if no weights)."""

    def __init__(self, values: Sequence[Any], weights: Sequence[float] | None = None) -> None:
        if not values:
            raise ValueError("Categorical requires at least one value")
        if weights is not None:
            if len(weights) != len(values):
                raise ValueError("weights length must match values length")
            total = float(sum(weights))
            self._probs: np.ndarray | None = np.asarray(weights, dtype=float) / total
        else:
            self._probs = None
        self._values = list(values)

    def generate(self, rng: SeededRng, n: int, offset: int = 0) -> Sequence[Any]:
        idx = rng.numpy().choice(len(self._values), size=n, p=self._probs)
        return [self._values[i] for i in idx]


class Serial:
    """Sequential integers starting at ``start``; ``offset`` continues across chunks."""

    def __init__(self, start: int = 1) -> None:
        self._start = start

    def generate(self, rng: SeededRng, n: int, offset: int = 0) -> Sequence[int]:
        base = self._start + offset
        return list(range(base, base + n))


class DecimalRange:
    """Uniform ``Decimal`` values in ``[low, high]`` quantized to ``scale`` places.

    Uses ``Decimal`` end to end so money never touches binary float (spec FR-M.4).
    """

    def __init__(self, low: Decimal, high: Decimal, scale: int) -> None:
        if high < low:
            raise ValueError(f"DecimalRange high ({high}) < low ({low})")
        if scale < 0:
            raise ValueError("scale must be non-negative")
        self._low = low
        self._high = high
        self._scale = scale
        self._quantum = Decimal(1).scaleb(-scale)  # e.g. scale=2 -> Decimal('0.01')

    def generate(self, rng: SeededRng, n: int, offset: int = 0) -> Sequence[Decimal]:
        span = self._high - self._low
        # draw fractions in [0,1) from the seeded stream, then map onto the decimal range
        fractions = rng.numpy().random(size=n)
        out: list[Decimal] = []
        for f in fractions:
            value = self._low + span * Decimal(float(f))
            out.append(value.quantize(self._quantum))
        return out


class DateRange:
    """Uniform dates in the inclusive range ``[low, high]`` (seeded, chunk-invariant)."""

    def __init__(self, low: date, high: date) -> None:
        if high < low:
            raise ValueError(f"DateRange high ({high}) < low ({low})")
        self._low = low
        self._span_days = (high - low).days

    def generate(self, rng: SeededRng, n: int, offset: int = 0) -> Sequence[date]:
        offsets = rng.numpy().integers(0, self._span_days + 1, size=n)
        return [self._low + timedelta(days=int(d)) for d in offsets]


class TimestampRange:
    """Uniform timestamps in ``[low, high]`` at second resolution.

    ``tz=False`` emits naive datetimes (canonical ``TIMESTAMP`` without time zone);
    ``tz=True`` emits UTC-aware datetimes (``timestamptz`` semantics, FR-M.4). ``low``/``high``
    are given naive and interpreted as UTC wall time in the aware case.
    """

    def __init__(self, low: datetime, high: datetime, *, tz: bool = False) -> None:
        if high < low:
            raise ValueError(f"TimestampRange high ({high}) < low ({low})")
        if low.tzinfo is not None or high.tzinfo is not None:
            raise ValueError("give low/high as naive datetimes; tz=True makes outputs UTC-aware")
        self._low = low
        self._span_seconds = int((high - low).total_seconds())
        self._tz = tz

    def generate(self, rng: SeededRng, n: int, offset: int = 0) -> Sequence[datetime]:
        seconds = rng.numpy().integers(0, self._span_seconds + 1, size=n)
        values = [self._low + timedelta(seconds=int(s)) for s in seconds]
        if self._tz:
            return [v.replace(tzinfo=UTC) for v in values]
        return values


class FakerField:
    """Values from a named Faker provider (e.g. ``name``, ``email``), deterministically seeded."""

    def __init__(self, method: str, locale: str | None = None, **kwargs: Any) -> None:
        self._method = method
        self._locale = locale
        self._kwargs = kwargs

    def generate(self, rng: SeededRng, n: int, offset: int = 0) -> Sequence[Any]:
        faker = rng.faker(self._locale)
        provider = getattr(faker, self._method)
        return [provider(**self._kwargs) for _ in range(n)]
