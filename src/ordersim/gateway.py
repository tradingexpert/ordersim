"""Small public execution gateway used by strategies.

The gateway is the boundary between user strategy code and the replay engine.
It deliberately exposes order intent directly: place, cancel, inspect book,
inspect position, and advance replay time.
"""

from typing import Any, Protocol

from ordersim.types import Fill, OrderId, OrderResult, Price, Side, TimeInForce


class OrderGateway(Protocol):
    """Execution interface consumed by strategies.

    Concrete gateways may be backed by an MBO replay, a synthetic fixture, or a
    test double. Strategy code should depend on this protocol rather than on a
    matching engine or data source.
    """

    def advance_to(self, ts_ns: int) -> list[Fill]:
        """Advance replay time and return passive fills since the last call."""

    def place_limit(
        self,
        side: Side,
        price: Price,
        size: int,
        tif: TimeInForce = "GTC",
    ) -> OrderResult:
        """Place a limit order.

        Returns an :class:`OrderResult` containing the resting order id, if any,
        and any immediate fills produced by the order.
        """

    def place_market(self, side: Side, size: int) -> list[Fill]:
        """Place a market order and return its fills."""

    def cancel(self, order_id: OrderId) -> bool:
        """Cancel a resting order, returning whether the cancel was accepted."""

    def book_top(self) -> tuple[Price | None, Price | None]:
        """Return ``(best_bid, best_ask)`` for the gateway's instrument."""

    def book_depth(self, levels: int) -> Any:
        """Return a depth snapshot.

        The exact snapshot type is intentionally left to the replay engine
        until the public schema lands.
        """

    def position(self) -> int:
        """Return current signed position for the gateway's instrument."""

    def now_ns(self) -> int:
        """Return current replay time in integer nanoseconds."""
