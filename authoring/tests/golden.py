"""Shared golden fixtures reused across parse / compile / judge / artifact tests (ADR-0003).

One canonical genspec (customers/orders) in the frozen schema, plus the imported SQL schema it
is authored against and a minimal declared-intent rule set. Keeping a single source avoids the
"three golden byte strings" problem the design critic warned about.
"""

from __future__ import annotations

# The canonical genspec — this is exactly what GenSpec.to_dict() must reproduce.
GOLDEN_GENSPEC = {
    "genspec_version": "1",
    "seed": 42,
    "tables": [
        {
            "name": "customers",
            "table_class": "generated",
            "row_count": 200,
            "primary_key": ["id"],
            "foreign_keys": [],
            "columns": [
                {"name": "id", "canonical_kind": "INT64",
                 "generator": {"kind": "serial", "params": {"start": 1}},
                 "nullable": False, "null_rate": 0.0, "unique": True},
                {"name": "email", "canonical_kind": "STRING",
                 "generator": {"kind": "faker", "params": {"method": "email"}},
                 "nullable": False, "null_rate": 0.0, "unique": True},
                {"name": "tier", "canonical_kind": "STRING",
                 "generator": {"kind": "categorical",
                               "params": {"values": ["free", "pro", "enterprise"],
                                          "weights": [0.7, 0.25, 0.05]}},
                 "nullable": False, "null_rate": 0.0, "unique": False},
                {"name": "balance", "canonical_kind": "DECIMAL",
                 "generator": {"kind": "decimal_range",
                               "params": {"low": "0.00", "high": "1000.00", "scale": 2}},
                 "nullable": True, "null_rate": 0.1, "unique": False},
            ],
        },
        {
            "name": "orders",
            "table_class": "generated",
            "row_count": None,  # driving FK into customers -> count is derived
            "primary_key": ["id"],
            "foreign_keys": [
                {"column": "customer_id", "references_table": "customers",
                 "references_column": "id", "min_per_parent": 0, "max_per_parent": 10},
            ],
            "columns": [
                {"name": "id", "canonical_kind": "INT64",
                 "generator": {"kind": "serial", "params": {"start": 1}},
                 "nullable": False, "null_rate": 0.0, "unique": True},
                {"name": "customer_id", "canonical_kind": "INT64",
                 "generator": {"kind": "fk", "params": {}},
                 "nullable": False, "null_rate": 0.0, "unique": False},
                {"name": "total", "canonical_kind": "DECIMAL",
                 "generator": {"kind": "decimal_range",
                               "params": {"low": "1.00", "high": "999.99", "scale": 2}},
                 "nullable": False, "null_rate": 0.0, "unique": False},
            ],
        },
    ],
}

# The imported schema (authoritative types) the genspec is authored against: table -> [(col, sql)].
GOLDEN_IMPORTED = {
    "customers": [
        ("id", "bigint"), ("email", "varchar(255)"), ("tier", "varchar(20)"),
        ("balance", "numeric(12,2)"),
    ],
    "orders": [
        ("id", "bigint"), ("customer_id", "bigint"), ("total", "numeric(10,2)"),
    ],
}

# Declared intent (user rules) the judge derives data-tests from — separate from generator params.
GOLDEN_RULES = [
    {"table": "customers", "column": "tier", "enum": ["free", "pro", "enterprise"]},
    {"table": "orders", "column": "total", "min_value": "1.00", "max_value": "1000.00"},
]
