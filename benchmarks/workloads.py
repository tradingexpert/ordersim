"""Deterministic public workloads shared by benchmark scripts."""

from decimal import Decimal

from ordersim import MBOEvent


def build_mixed_mbo_workload(cycles: int) -> tuple[MBOEvent, ...]:
    """Build mixed MBO cycles that end with an empty visible book."""

    if cycles <= 0:
        raise ValueError("cycles must be positive")

    events: list[MBOEvent] = []
    ts_ns = 1
    for cycle in range(cycles):
        bid_order_id = 2 * cycle + 1
        ask_order_id = 2 * cycle + 2
        events.extend(
            (
                MBOEvent(
                    ts_ns=ts_ns,
                    action="add",
                    side="bid",
                    price=Decimal("100.0"),
                    size=5,
                    order_id=bid_order_id,
                ),
                MBOEvent(
                    ts_ns=ts_ns + 1,
                    action="add",
                    side="ask",
                    price=Decimal("101.0"),
                    size=5,
                    order_id=ask_order_id,
                ),
                MBOEvent(
                    ts_ns=ts_ns + 2,
                    action="modify",
                    side="bid",
                    price=Decimal("100.0"),
                    size=4,
                    order_id=bid_order_id,
                ),
                MBOEvent(
                    ts_ns=ts_ns + 3,
                    action="trade",
                    side="bid",
                    price=Decimal("100.0"),
                    size=2,
                    order_id=bid_order_id,
                ),
                MBOEvent(
                    ts_ns=ts_ns + 4,
                    action="cancel",
                    side="ask",
                    price=Decimal("101.0"),
                    size=5,
                    order_id=ask_order_id,
                ),
                MBOEvent(
                    ts_ns=ts_ns + 5,
                    action="cancel",
                    side="bid",
                    price=Decimal("100.0"),
                    size=2,
                    order_id=bid_order_id,
                ),
            )
        )
        ts_ns += 6
    return tuple(events)
