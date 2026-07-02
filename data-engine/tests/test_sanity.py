import seedwright_data_engine


def test_package_exposes_version() -> None:
    assert seedwright_data_engine.__version__ == "0.0.1"


def test_all_wrapped_libraries_importable() -> None:
    import seedwright_authoring
    import seedwright_genlib
    import seedwright_pgloader

    assert seedwright_genlib.__version__
    assert seedwright_authoring.__version__
    assert seedwright_pgloader.__version__
