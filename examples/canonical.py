"""Canonical ordersim example.

Run with:

    python examples/canonical.py
"""

from decimal import Decimal

from ordersim import InstrumentSpec, Replay, ReplayResult
from ordersim.fixtures.synthetic import SyntheticSource


def strategy(gateway) -> None:
    """Rest at the bid, then cross the spread if no passive fill arrives."""

    gateway.advance_to(1_000_000_100)
    bid, _ask = gateway.book_top()
    if bid is None:
        return

    result = gateway.place_limit(side="buy", price=bid, size=1)
    gateway.advance_to(gateway.now_ns() + 1_000_000_000)

    if gateway.position() == 0:
        if result.order_id is not None:
            gateway.cancel(result.order_id)
        gateway.place_market(side="buy", size=1)


def run() -> ReplayResult:
    """Run the example and return the replay result."""

    spec = InstrumentSpec(
        symbol="GC",
        tick_size=Decimal("0.10"),
        point_value=Decimal("100"),
        commission_per_contract=Decimal("2.50"),
    )
    replay = Replay(data=SyntheticSource.small_mbo(), instrument=spec)
    return replay.run(strategy)


if __name__ == "__main__":
    result = run()
    print(result.fills)
    print(result.order_events)
