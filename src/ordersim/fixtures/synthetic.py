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

    @staticmethod
    def execution_equivalence_mbo() -> tuple[MBOEvent, ...]:
        """Return a queue-aware fixture for execution-engine equivalence tests.

        The stream creates both sides of the book, modifies the ask, partially
        cancels queue ahead on the bid, then trades through the remaining bid
        queue. A strategy that rests a bid after timestamp 2 can be passively
        filled at timestamp 5 after public queue ahead is consumed.
        """

        return (
            MBOEvent(
                ts_ns=1,
                action="add",
                side="ask",
                price=Decimal("101.0"),
                size=3,
                order_id=10,
            ),
            MBOEvent(
                ts_ns=2,
                action="add",
                side="bid",
                price=Decimal("100.0"),
                size=5,
                order_id=20,
            ),
            MBOEvent(
                ts_ns=3,
                action="modify",
                side="ask",
                price=Decimal("101.0"),
                size=2,
                order_id=10,
            ),
            MBOEvent(
                ts_ns=4,
                action="cancel",
                side="bid",
                price=Decimal("100.0"),
                size=2,
                order_id=20,
            ),
            MBOEvent(
                ts_ns=5,
                action="trade",
                side="bid",
                price=Decimal("100.0"),
                size=4,
                order_id=20,
            ),
        )

    @staticmethod
    def latency_demo_mbo() -> tuple[MBOEvent, ...]:
        """Return a tiny replay where entry latency changes the fill path.

        A fast resting bid joins before the public trade at timestamp 110 and
        fills passively. A delayed order reaches the venue after that trade,
        so the same strategy later has to cancel and cross the spread.
        """

        return (
            MBOEvent(
                ts_ns=100,
                action="add",
                side="ask",
                price=Decimal("101.0"),
                size=10,
                order_id=10,
            ),
            MBOEvent(
                ts_ns=101,
                action="add",
                side="bid",
                price=Decimal("100.0"),
                size=2,
                order_id=20,
            ),
            MBOEvent(
                ts_ns=105,
                action="cancel",
                side="bid",
                price=Decimal("100.0"),
                size=1,
                order_id=20,
            ),
            MBOEvent(
                ts_ns=110,
                action="trade",
                side="bid",
                price=Decimal("100.0"),
                size=2,
                order_id=20,
            ),
            MBOEvent(
                ts_ns=120,
                action="add",
                side="bid",
                price=Decimal("99.9"),
                size=5,
                order_id=21,
            ),
        )
