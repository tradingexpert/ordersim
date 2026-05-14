"""Reference Python matching engine.

This module is intentionally plain Python. It is the behavior reference that a
future compiled execution engine must match before it can be trusted.
"""

from dataclasses import dataclass
from typing import Literal

from ordersim.types import BookSide, Fill, MBOEvent, OrderId, OrderResult, Price, Side

QueueOwner = Literal["public", "own"]


@dataclass(slots=True)
class PublicOrder:
    """One visible market-data order resting on the simulated book."""

    order_id: OrderId
    side: BookSide
    price: Price
    size: int


@dataclass(slots=True)
class OwnOrder:
    """One strategy order resting on the simulated book."""

    order_id: OrderId
    side: BookSide
    price: Price
    size: int


@dataclass(frozen=True, slots=True)
class PriceLevel:
    """Aggregated visible size at one price level."""

    price: Price
    size: int


@dataclass(frozen=True, slots=True)
class _QueueEntry:
    owner: QueueOwner
    order_id: OrderId


class MatchingEngine:
    """Queue-aware MBO matching engine.

    Public market-data events and strategy orders share the same per-level FIFO.
    A strategy limit order joins the back of the queue at its price. Public
    cancels, modifies, and trades then update that queue, making each own
    order's current queue-ahead quantity inspectable from the event history.
    """

    def __init__(self) -> None:
        self.bids: dict[Price, int] = {}
        self.asks: dict[Price, int] = {}
        self.public_orders: dict[OrderId, PublicOrder] = {}
        self.own_orders: dict[OrderId, OwnOrder] = {}
        self._queues: dict[tuple[BookSide, Price], list[_QueueEntry]] = {}
        self._passive_fills: list[Fill] = []
        self._next_order_id = 1_000_000_000
        self._now_ns = 0
        self._position = 0

    def apply_event(self, event: MBOEvent) -> list[Fill]:
        """Apply one normalized MBO event and return passive own fills."""

        self._now_ns = event.ts_ns
        before = len(self._passive_fills)

        if event.action == "add":
            self._add_public(event)
        elif event.action == "cancel":
            self._cancel_public(event)
        elif event.action == "modify":
            self._modify_public(event)
        elif event.action == "trade":
            self._consume_level(event.side, event.price, event.size, event.ts_ns)
        else:
            raise ValueError(f"unknown MBO action: {event.action!r}")

        return self._passive_fills[before:]

    def place_limit(
        self,
        side: Side,
        price: Price,
        size: int,
        tif: Literal["GTC", "IOC"] = "GTC",
    ) -> OrderResult:
        """Place a strategy limit order.

        Aggressive quantity matches immediately. Remaining quantity rests only
        for GTC orders.
        """

        self._validate_order(size=size, price=price)
        order_id = self._allocate_order_id()
        active_fills, remaining = self._match_active_order(
            order_id=order_id,
            side=side,
            size=size,
            limit_price=price,
        )

        resting_order_id: OrderId | None = None
        if remaining > 0 and tif == "GTC":
            resting_side = _book_side_for_order_side(side)
            self._add_own(order_id, resting_side, price, remaining)
            resting_order_id = order_id

        return OrderResult(order_id=resting_order_id, fills=tuple(active_fills))

    def place_market(self, side: Side, size: int) -> list[Fill]:
        """Place a strategy market order and return immediate fills."""

        self._validate_order(size=size)
        order_id = self._allocate_order_id()
        fills, _remaining = self._match_active_order(
            order_id=order_id,
            side=side,
            size=size,
            limit_price=None,
        )
        return fills

    def cancel(self, order_id: OrderId) -> bool:
        """Cancel one own resting order."""

        order = self.own_orders.pop(order_id, None)
        if order is None:
            return False

        self._remove_from_book(order.side, order.price, order.size)
        self._remove_from_queue(order.side, order.price, "own", order_id)
        return True

    def book_top(self) -> tuple[Price | None, Price | None]:
        """Return ``(best_bid, best_ask)``."""

        bid = max(self.bids) if self.bids else None
        ask = min(self.asks) if self.asks else None
        return bid, ask

    def book_depth(
        self,
        levels: int,
    ) -> tuple[tuple[PriceLevel, ...], tuple[PriceLevel, ...]]:
        """Return top bid and ask levels as ``((price, size), ...)`` tuples."""

        bids = tuple(
            PriceLevel(price, self.bids[price])
            for price in sorted(self.bids, reverse=True)[:levels]
        )
        asks = tuple(
            PriceLevel(price, self.asks[price])
            for price in sorted(self.asks)[:levels]
        )
        return bids, asks

    def position(self) -> int:
        """Return signed position from own active and passive fills."""

        return self._position

    def now_ns(self) -> int:
        """Return the timestamp of the last applied event."""

        return self._now_ns

    def advance_time(self, ts_ns: int) -> None:
        """Advance engine time without applying a market-data event."""

        if ts_ns < self._now_ns:
            raise ValueError("cannot move engine time backwards")
        self._now_ns = ts_ns

    def own_orders_snapshot(
        self,
    ) -> tuple[tuple[OrderId, BookSide, Price, int, int], ...]:
        """Return own resting orders with current queue-ahead quantity.

        Rows are ``(order_id, side, price, remaining_size, queue_ahead_size)``.
        """

        return tuple(
            (
                order.order_id,
                order.side,
                order.price,
                order.size,
                self._queue_ahead(order.side, order.price, order.order_id),
            )
            for order in sorted(
                self.own_orders.values(),
                key=lambda item: item.order_id,
            )
        )

    def pop_passive_fills(self) -> list[Fill]:
        """Return and clear passive fills caused by market-data trades."""

        fills = list(self._passive_fills)
        self._passive_fills.clear()
        return fills

    def _add_public(self, event: MBOEvent) -> None:
        order = PublicOrder(
            order_id=event.order_id,
            side=event.side,
            price=event.price,
            size=event.size,
        )
        self.public_orders[event.order_id] = order
        self._queue(event.side, event.price).append(
            _QueueEntry("public", event.order_id)
        )
        self._add_to_book(event.side, event.price, event.size)

    def _cancel_public(self, event: MBOEvent) -> None:
        order = self.public_orders.get(event.order_id)
        if order is None:
            self._remove_from_book(event.side, event.price, event.size)
            return

        cancelled = min(order.size, event.size)
        order.size -= cancelled
        self._remove_from_book(order.side, order.price, cancelled)
        if order.size == 0:
            del self.public_orders[event.order_id]
            self._remove_from_queue(order.side, order.price, "public", event.order_id)

    def _modify_public(self, event: MBOEvent) -> None:
        order = self.public_orders.get(event.order_id)
        if order is None:
            self._add_public(event)
            return

        same_level = order.side == event.side and order.price == event.price
        if same_level:
            delta = event.size - order.size
            if delta > 0:
                self._add_to_book(order.side, order.price, delta)
            elif delta < 0:
                self._remove_from_book(order.side, order.price, -delta)
            order.size = event.size
            if order.size == 0:
                del self.public_orders[event.order_id]
                self._remove_from_queue(
                    order.side,
                    order.price,
                    "public",
                    event.order_id,
                )
            return

        self._remove_from_book(order.side, order.price, order.size)
        self._remove_from_queue(order.side, order.price, "public", event.order_id)
        order.side = event.side
        order.price = event.price
        order.size = event.size
        self._queue(event.side, event.price).append(
            _QueueEntry("public", event.order_id)
        )
        self._add_to_book(event.side, event.price, event.size)

    def _add_own(
        self,
        order_id: OrderId,
        side: BookSide,
        price: Price,
        size: int,
    ) -> None:
        order = OwnOrder(order_id=order_id, side=side, price=price, size=size)
        self.own_orders[order_id] = order
        self._queue(side, price).append(_QueueEntry("own", order_id))
        self._add_to_book(side, price, size)

    def _match_active_order(
        self,
        *,
        order_id: OrderId,
        side: Side,
        size: int,
        limit_price: Price | None,
    ) -> tuple[list[Fill], int]:
        fills: list[Fill] = []
        remaining = size
        book_side = _opposite_book_side(side)
        prices = self._matchable_prices(book_side, limit_price)

        for price in prices:
            if remaining == 0:
                break
            level_size = self._book_for_side(book_side)[price]
            trade_size = min(remaining, level_size)
            self._consume_level(book_side, price, trade_size, self._now_ns)
            fills.append(
                Fill(
                    order_id=order_id,
                    side=side,
                    price=price,
                    size=trade_size,
                    ts_ns=self._now_ns,
                )
            )
            self._position += trade_size if side == "buy" else -trade_size
            remaining -= trade_size

        return fills, remaining

    def _consume_level(
        self,
        side: BookSide,
        price: Price,
        size: int,
        ts_ns: int,
    ) -> None:
        remaining = size
        queue = self._queue(side, price)

        while remaining > 0 and queue:
            entry = queue[0]
            if entry.owner == "public":
                consumed = self._consume_public_entry(
                    entry.order_id,
                    side,
                    price,
                    remaining,
                )
            else:
                consumed = self._consume_own_entry(
                    entry.order_id,
                    side,
                    price,
                    remaining,
                    ts_ns,
                )

            remaining -= consumed
            if consumed == 0:
                queue.pop(0)

        if not queue:
            self._queues.pop((side, price), None)

    def _consume_public_entry(
        self,
        order_id: OrderId,
        side: BookSide,
        price: Price,
        available_size: int,
    ) -> int:
        order = self.public_orders.get(order_id)
        if order is None:
            return 0

        consumed = min(order.size, available_size)
        order.size -= consumed
        self._remove_from_book(side, price, consumed)
        if order.size == 0:
            del self.public_orders[order_id]
            self._queue(side, price).pop(0)
        return consumed

    def _consume_own_entry(
        self,
        order_id: OrderId,
        side: BookSide,
        price: Price,
        available_size: int,
        ts_ns: int,
    ) -> int:
        order = self.own_orders.get(order_id)
        if order is None:
            return 0

        consumed = min(order.size, available_size)
        order.size -= consumed
        self._remove_from_book(side, price, consumed)
        fill = Fill(
            order_id=order_id,
            side=_order_side_for_book_side(side),
            price=price,
            size=consumed,
            ts_ns=ts_ns,
        )
        self._passive_fills.append(fill)
        self._position += consumed if side == "bid" else -consumed

        if order.size == 0:
            del self.own_orders[order_id]
            self._queue(side, price).pop(0)
        return consumed

    def _queue_ahead(self, side: BookSide, price: Price, order_id: OrderId) -> int:
        total = 0
        for entry in self._queue(side, price):
            if entry.owner == "own" and entry.order_id == order_id:
                return total
            if entry.owner == "public":
                order = self.public_orders.get(entry.order_id)
            else:
                order = self.own_orders.get(entry.order_id)
            if order is not None:
                total += order.size
        raise KeyError(order_id)

    def _matchable_prices(
        self,
        side: BookSide,
        limit_price: Price | None,
    ) -> list[Price]:
        prices = sorted(self._book_for_side(side), reverse=side == "bid")
        if limit_price is None:
            return prices
        if side == "ask":
            return [price for price in prices if price <= limit_price]
        return [price for price in prices if price >= limit_price]

    def _queue(self, side: BookSide, price: Price) -> list[_QueueEntry]:
        return self._queues.setdefault((side, price), [])

    def _book_for_side(self, side: BookSide) -> dict[Price, int]:
        return self.bids if side == "bid" else self.asks

    def _add_to_book(self, side: BookSide, price: Price, size: int) -> None:
        book = self._book_for_side(side)
        book[price] = book.get(price, 0) + size
        if book[price] <= 0:
            del book[price]

    def _remove_from_book(self, side: BookSide, price: Price, size: int) -> None:
        book = self._book_for_side(side)
        if price not in book:
            return
        book[price] -= size
        if book[price] <= 0:
            del book[price]

    def _remove_from_queue(
        self,
        side: BookSide,
        price: Price,
        owner: QueueOwner,
        order_id: OrderId,
    ) -> None:
        queue = self._queue(side, price)
        queue[:] = [
            entry
            for entry in queue
            if not (entry.owner == owner and entry.order_id == order_id)
        ]
        if not queue:
            self._queues.pop((side, price), None)

    def _allocate_order_id(self) -> OrderId:
        order_id = self._next_order_id
        self._next_order_id += 1
        return order_id

    @staticmethod
    def _validate_order(size: int, price: Price | None = None) -> None:
        if size <= 0:
            raise ValueError("size must be positive")
        if price is not None and price <= 0:
            raise ValueError("price must be positive")


def _book_side_for_order_side(side: Side) -> BookSide:
    return "bid" if side == "buy" else "ask"


def _opposite_book_side(side: Side) -> BookSide:
    return "ask" if side == "buy" else "bid"


def _order_side_for_book_side(side: BookSide) -> Side:
    return "buy" if side == "bid" else "sell"
