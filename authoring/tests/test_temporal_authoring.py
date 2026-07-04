"""date_range / timestamp_range in the authoring surface (catalog + validation + compile).

Kills NO_MVP_GENERATOR for DATE/TIMESTAMP — the gap every real schema hits first. Params are
ISO strings (JSON-able); timestamp tz is asserted against the column's authoritative tz
(TZ_MISMATCH mirrors SCALE_MISMATCH for money).
"""

from seedwright_genlib.dataset import generate_dataset
from seedwright_genlib.generators import DateRange, TimestampRange
from seedwright_genlib.rng import SeededRng
from seedwright_genlib.types import TypeKind

from seedwright_authoring.catalog import GENERATOR_CATALOG, build_generator
from seedwright_authoring.compile import compile_to_genlib
from seedwright_authoring.genspec import parse_genspec
from seedwright_authoring.imported import ImportedSchema
from seedwright_authoring.validate import validate_genspec

IMPORTED = ImportedSchema.from_sql_columns(
    {"events": [("id", "bigint"), ("day", "date"),
                ("at", "timestamp with time zone"), ("logged", "timestamp")]},
    primary_keys={"events": ["id"]},
)


def _genspec(day_params=None, at_params=None, logged_params=None) -> dict:
    return {
        "genspec_version": "1", "seed": 3,
        "tables": [{
            "name": "events", "table_class": "generated", "row_count": 20,
            "primary_key": ["id"], "foreign_keys": [],
            "columns": [
                {"name": "id", "canonical_kind": "INT64",
                 "generator": {"kind": "serial", "params": {}},
                 "nullable": False, "null_rate": 0.0, "unique": True},
                {"name": "day", "canonical_kind": "DATE",
                 "generator": {"kind": "date_range", "params": day_params or
                               {"low": "2020-01-01", "high": "2025-12-31"}},
                 "nullable": False, "null_rate": 0.0, "unique": False},
                {"name": "at", "canonical_kind": "TIMESTAMP",
                 "generator": {"kind": "timestamp_range", "params": at_params or
                               {"low": "2020-01-01T00:00:00", "high": "2025-12-31T23:59:59",
                                "tz": True}},
                 "nullable": False, "null_rate": 0.0, "unique": False},
                {"name": "logged", "canonical_kind": "TIMESTAMP",
                 "generator": {"kind": "timestamp_range", "params": logged_params or
                               {"low": "2020-01-01T00:00:00", "high": "2025-12-31T23:59:59",
                                "tz": False}},
                 "nullable": False, "null_rate": 0.0, "unique": False},
            ],
        }],
    }


def _codes(genspec: dict) -> set[str]:
    issues = validate_genspec(parse_genspec(genspec), IMPORTED)
    return {f.test_id.split(":")[0] for f in issues}


def test_catalog_builds_temporal_generators() -> None:
    assert isinstance(
        build_generator("date_range", {"low": "2020-01-01", "high": "2021-01-01"}), DateRange)
    assert isinstance(
        build_generator("timestamp_range",
                        {"low": "2020-01-01T00:00:00", "high": "2021-01-01T00:00:00",
                         "tz": True}), TimestampRange)
    assert GENERATOR_CATALOG["date_range"].compatible_kinds == frozenset({TypeKind.DATE})
    assert GENERATOR_CATALOG["timestamp_range"].compatible_kinds == frozenset({TypeKind.TIMESTAMP})


def test_valid_temporal_genspec_passes_and_generates() -> None:
    genspec = _genspec()
    assert validate_genspec(parse_genspec(genspec), IMPORTED) == []
    compiled = compile_to_genlib(parse_genspec(genspec), IMPORTED)
    tables = generate_dataset(compiled, SeededRng(3))
    at_values = tables["events"].column("at").to_pylist()
    assert all(v.tzinfo is not None for v in at_values)      # tz column is aware
    logged = tables["events"].column("logged").to_pylist()
    assert all(v.tzinfo is None for v in logged)             # naive column stays naive


def test_bad_iso_and_reversed_range_are_validation_issues() -> None:
    assert "GENERATOR_PARAMS" in _codes(_genspec(day_params={"low": "not-a-date",
                                                             "high": "2025-01-01"}))
    assert "RANGE_INVALID" in _codes(_genspec(day_params={"low": "2025-01-01",
                                                          "high": "2020-01-01"}))
    assert "GENERATOR_PARAMS" in _codes(_genspec(at_params={"low": "2020-01-01T00:00:00"}))


def test_timestamp_tz_must_match_column() -> None:
    # 'at' is timestamptz but the generator claims tz=False -> TZ_MISMATCH (and vice versa)
    codes = _codes(_genspec(at_params={"low": "2020-01-01T00:00:00",
                                       "high": "2025-12-31T23:59:59", "tz": False}))
    assert "TZ_MISMATCH" in codes
    codes = _codes(_genspec(logged_params={"low": "2020-01-01T00:00:00",
                                           "high": "2025-12-31T23:59:59", "tz": True}))
    assert "TZ_MISMATCH" in codes
