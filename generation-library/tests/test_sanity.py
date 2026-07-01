import seedwright_genlib


def test_package_exposes_version() -> None:
    assert seedwright_genlib.__version__ == "0.0.1"
