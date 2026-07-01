"""Value generators (spec FR-C.2, FR-M.2).

Each generator is a pure, seeded function of its RNG stream (and, for sequential
generators, a row offset). Random generators draw from a persistent stream so that
splitting a run into chunks never changes the concatenated output — the property the
streamed Parquet writer and the determinism gate depend on.
"""

from collections import Counter
from decimal import Decimal

from seedwright_genlib.generators import Categorical, DecimalRange, FakerField, IntRange, Serial
from seedwright_genlib.rng import SeededRng

# --- IntRange -------------------------------------------------------------------------

def test_int_range_within_bounds_and_length() -> None:
    values = IntRange(10, 20).generate(SeededRng(1), 200)
    assert len(values) == 200
    assert all(10 <= v <= 20 for v in values)


def test_int_range_is_deterministic() -> None:
    assert list(IntRange(0, 10**6).generate(SeededRng(1), 100)) == list(
        IntRange(0, 10**6).generate(SeededRng(1), 100)
    )


def test_int_range_varies_by_seed() -> None:
    assert list(IntRange(0, 10**6).generate(SeededRng(1), 100)) != list(
        IntRange(0, 10**6).generate(SeededRng(2), 100)
    )


def test_random_generator_stream_is_continuous_across_chunks() -> None:
    # One rng drawn as 100, then split as 60 + 40, must concatenate to the same values.
    whole = list(IntRange(0, 10**9).generate(SeededRng(5), 100))
    rng = SeededRng(5)
    chunked = list(IntRange(0, 10**9).generate(rng, 60)) + list(
        IntRange(0, 10**9).generate(rng, 40)
    )
    assert whole == chunked


# --- Categorical ----------------------------------------------------------------------

def test_categorical_only_emits_given_values() -> None:
    values = Categorical(["red", "green", "blue"]).generate(SeededRng(1), 300)
    assert set(values) <= {"red", "green", "blue"}


def test_categorical_weights_bias_the_distribution() -> None:
    values = Categorical(["a", "b"], weights=[0.99, 0.01]).generate(SeededRng(1), 1000)
    assert Counter(values)["a"] > 900


def test_categorical_is_deterministic() -> None:
    gen = Categorical(["x", "y", "z"])
    assert list(gen.generate(SeededRng(3), 50)) == list(gen.generate(SeededRng(3), 50))


# --- Serial (offset-driven, for unique PKs) -------------------------------------------

def test_serial_is_sequential_from_start() -> None:
    assert list(Serial(start=1).generate(SeededRng(1), 5)) == [1, 2, 3, 4, 5]


def test_serial_offset_continues_the_sequence() -> None:
    assert list(Serial(start=1).generate(SeededRng(1), 3, offset=100)) == [101, 102, 103]


def test_serial_values_are_unique() -> None:
    values = list(Serial().generate(SeededRng(1), 1000))
    assert len(set(values)) == 1000


# --- DecimalRange (footgun: money must be Decimal, not float) --------------------------

def test_decimal_range_emits_decimals_not_floats() -> None:
    values = DecimalRange(Decimal("0.00"), Decimal("100.00"), scale=2).generate(SeededRng(1), 50)
    assert all(isinstance(v, Decimal) for v in values)
    assert all(Decimal("0.00") <= v <= Decimal("100.00") for v in values)
    # scale is respected exactly — no binary-float drift
    assert all(-v.as_tuple().exponent == 2 for v in values)


def test_decimal_range_is_deterministic() -> None:
    gen = DecimalRange(Decimal("0"), Decimal("1000"), scale=4)
    assert list(gen.generate(SeededRng(7), 40)) == list(gen.generate(SeededRng(7), 40))


# --- FakerField -----------------------------------------------------------------------

def test_faker_field_is_deterministic() -> None:
    gen = FakerField("name")
    assert list(gen.generate(SeededRng(9), 20)) == list(gen.generate(SeededRng(9), 20))


def test_faker_field_varies_by_seed() -> None:
    gen = FakerField("name")
    assert list(gen.generate(SeededRng(9), 20)) != list(gen.generate(SeededRng(10), 20))


def test_faker_field_invokes_named_provider() -> None:
    emails = FakerField("email").generate(SeededRng(1), 10)
    assert all("@" in e for e in emails)
