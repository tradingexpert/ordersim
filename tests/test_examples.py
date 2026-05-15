from decimal import Decimal

from examples.canonical import run
from examples.latency_demo import render_svg
from examples.latency_demo import run as run_latency_demo


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


def test_latency_demo_shows_latency_changing_the_execution_path() -> None:
    fast, slow = run_latency_demo()

    assert fast.queue_ahead_at_arrival == 2
    assert fast.fill_kind == "fill_passive"
    assert fast.result.fills[0].price == Decimal("100.0")
    assert fast.result.equity_curve[-1].equity == Decimal("42.50")

    assert slow.queue_ahead_at_arrival == 0
    assert slow.fill_kind == "fill"
    assert slow.result.fills[0].price == Decimal("101.0")
    assert slow.result.equity_curve[-1].equity == Decimal("-57.50")

    svg = render_svg((fast, slow))
    assert "Same replay. Same strategy. Different latency." in svg
    assert "fill_passive: 100.0" in svg
    assert "fill: 101.0" in svg
