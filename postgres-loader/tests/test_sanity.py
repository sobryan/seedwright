import seedwright_pgloader


def test_package_exposes_version() -> None:
    assert seedwright_pgloader.__version__ == "0.0.1"
