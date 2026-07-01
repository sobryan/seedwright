"""Determinism foundation (spec §3, NFR-REPRO, FR-L.4).

Everything reproducible in seedwright rests on these properties. If any of these
break, generated Datasets are no longer byte-reproducible.
"""

from seedwright_genlib.rng import SeededRng, derive_seed


def test_derive_seed_is_deterministic() -> None:
    assert derive_seed(42, "orders", "id") == derive_seed(42, "orders", "id")


def test_derive_seed_depends_on_root_seed() -> None:
    assert derive_seed(1, "orders", "id") != derive_seed(2, "orders", "id")


def test_derive_seed_depends_on_labels() -> None:
    assert derive_seed(42, "orders", "id") != derive_seed(42, "orders", "total")
    assert derive_seed(42, "orders", "id") != derive_seed(42, "customers", "id")
    # label boundaries matter — ("a","b") must not collide with ("ab",)
    assert derive_seed(42, "a", "b") != derive_seed(42, "ab")


def test_derive_seed_is_stable_across_processes() -> None:
    # A golden lock: this value must never change silently. It is what makes an
    # old Dataset regenerate identically on a future library version. If a change
    # to the derivation algorithm is intentional, update this deliberately.
    assert derive_seed(42, "orders", "id") == 15_217_398_670_046_459_282


def test_derive_seed_in_uint64_range() -> None:
    s = derive_seed(42, "orders", "id")
    assert 0 <= s < 2**64


def test_seeded_rng_numpy_stream_is_reproducible() -> None:
    a = SeededRng(123).numpy().integers(0, 1_000_000, size=50)
    b = SeededRng(123).numpy().integers(0, 1_000_000, size=50)
    assert list(a) == list(b)


def test_seeded_rng_different_seeds_differ() -> None:
    a = SeededRng(123).numpy().integers(0, 1_000_000, size=50)
    b = SeededRng(124).numpy().integers(0, 1_000_000, size=50)
    assert list(a) != list(b)


def test_derived_streams_are_order_independent() -> None:
    # Deriving child 'a' before or after child 'b' must not change either stream,
    # and drawing from the parent must not perturb children — this is what lets
    # column generation be reordered/parallelized without changing output.
    root1 = SeededRng(7)
    a1 = root1.derive("a").numpy().integers(0, 10**9, size=20)
    b1 = root1.derive("b").numpy().integers(0, 10**9, size=20)

    root2 = SeededRng(7)
    root2.numpy().integers(0, 10**9, size=100)  # perturb parent state
    b2 = root2.derive("b").numpy().integers(0, 10**9, size=20)
    a2 = root2.derive("a").numpy().integers(0, 10**9, size=20)

    assert list(a1) == list(a2)
    assert list(b1) == list(b2)


def test_seeded_faker_is_reproducible() -> None:
    a = [SeededRng(99).faker().name() for _ in range(1)][0]
    b = [SeededRng(99).faker().name() for _ in range(1)][0]
    assert a == b


def test_seeded_faker_differs_by_seed() -> None:
    names_a = _faker_names(SeededRng(1), 25)
    names_b = _faker_names(SeededRng(2), 25)
    assert names_a != names_b


def _faker_names(rng: SeededRng, n: int) -> list[str]:
    f = rng.faker()
    return [f.name() for _ in range(n)]
