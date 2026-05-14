"""Small synthetic event fixtures.

Synthetic fixtures make examples and tests runnable without paid data. They are
not intended to be statistically realistic; they are tiny, readable scenarios
that exercise order-book event semantics.
"""

from decimal import Decimal

from ordersim.types import MBOEvent


class SyntheticSource:
    """In-repo market-by-order fixtures."""

    @staticmethod
    def small_mbo() -> tuple[MBOEvent, ...]:
        """Return a tiny deterministic MBO event stream.

        The stream creates one ask and one bid, trades against the ask, cancels
        part of the bid, then modifies the remaining bid. This gives connector
        and matching tests all core event kinds without private market data.
        """

        return (
            MBOEvent(
                ts_ns=1_000_000_000,
                action="add",
                side="ask",
                price=Decimal("101.0"),
                size=10,
                order_id=1,
            ),
            MBOEvent(
                ts_ns=1_000_000_100,
                action="add",
                side="bid",
                price=Decimal("100.0"),
                size=12,
                order_id=2,
            ),
            MBOEvent(
                ts_ns=1_000_000_200,
                action="trade",
                side="ask",
                price=Decimal("101.0"),
                size=2,
                order_id=1,
            ),
            MBOEvent(
                ts_ns=1_000_000_300,
                action="cancel",
                side="bid",
                price=Decimal("100.0"),
                size=3,
                order_id=2,
            ),
            MBOEvent(
                ts_ns=1_000_000_400,
                action="modify",
                side="bid",
                price=Decimal("99.9"),
                size=9,
                order_id=2,
            ),
        )
