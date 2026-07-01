"""The single shared Failure record (ADR-0003).

Both static validation issues and judge data-test failures convert to Failure — it is the
loop's uniform refine signal, consumed unchanged by the provider's refine path.
"""

from seedwright_authoring.feedback import Failure


def test_failure_to_dict_round_trips_fields() -> None:
    f = Failure(
        category="constraint",
        table="orders",
        column="total",
        test_id="value_range:orders.total",
        detail="max observed 5000.00 exceeds declared max 1000.00",
        feedback="lower decimal_range.high for orders.total to <= 1000.00",
    )
    assert f.to_dict() == {
        "category": "constraint",
        "table": "orders",
        "column": "total",
        "test_id": "value_range:orders.total",
        "detail": "max observed 5000.00 exceeds declared max 1000.00",
        "feedback": "lower decimal_range.high for orders.total to <= 1000.00",
    }


def test_failure_column_is_optional() -> None:
    f = Failure("referential", "orders", None, "fk_resolves:orders", "unresolved fk", "fix fk")
    assert f.column is None
    assert f.to_dict()["column"] is None
