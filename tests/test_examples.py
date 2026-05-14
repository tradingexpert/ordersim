from decimal import Decimal

from examples.canonical import run


def test_canonical_example_runs_and_records_order_intent() -> None:
    result = run()

    assert result.final_position == 1
    assert [(fill.price, fill.size) for fill in result.fills] == [
        (Decimal("101.0"), 1),
    ]
    assert result.execution_summary.net_realized_pnl == Decimal("-2.50")
    assert result.equity_curve[-1].equity == Decimal("-57.50")
    assert [event.kind for event in result.order_events] == [
        "place_limit",
        "cancel",
        "place_market",
        "fill",
    ]
