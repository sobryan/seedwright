import seedwright_authoring


def test_package_exposes_version() -> None:
    assert seedwright_authoring.__version__ == "0.0.1"


def test_generation_library_is_importable() -> None:
    # the authoring loop compiles genspecs into genlib and runs samples through it
    import seedwright_genlib

    assert seedwright_genlib.__version__
