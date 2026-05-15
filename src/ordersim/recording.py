"""Recording wrapper for order-intent audit logs.

Every side-effecting gateway call appends a flat, typed event row to a
caller-supplied sink. The wrapper keeps strategy code pointed at the ordinary
gateway surface while making the execution path inspectable after the run.
"""

from collections.abc import MutableSequence
from typing import Any

from ordersim.gateway import OrderGateway
from ordersim.types import (
    Fill,
    OrderEvent,
    OrderId,
    OrderResult,
    Price,
    RestingOrder,
    Side,
    TimeInForce,
)


class RecordingGateway:
    """Wrap an :class:`OrderGateway` and record order intent.

    The wrapper is transparent to strategy code: methods return the inner
    gateway's values unchanged. The `sink` receives `OrderEvent` rows for each
    place, cancel, active fill, and passive fill.
    """

    def __init__(
        self,
        inner: OrderGateway,
        sink: MutableSequence[OrderEvent],
        *,
        strategy: str = "default",
    ) -> None:
        self._inner = inner
        self._sink = sink
        self._strategy = strategy

    def _record(self, event: OrderEvent) -> None:
        self._sink.append(event)

    def _record_fills(self, fills: list[Fill], source: str) -> None:
        for fill in fills:
            self._record(
                OrderEvent(
                    strategy=self._strategy,
                    kind="fill",
                    ts_ns=fill.ts_ns,
                    order_id=fill.order_id,
                    side=fill.side,
                    fill_price=fill.price,
                    fill_size=fill.size,
                    source=source,
                )
            )

    def _record_passive_fills(self, fills: list[Fill]) -> None:
        for fill in fills:
            self._record(
                OrderEvent(
                    strategy=self._strategy,
                    kind="fill_passive",
                    ts_ns=fill.ts_ns,
                    order_id=fill.order_id,
                    side=fill.side,
                    fill_price=fill.price,
                    fill_size=fill.size,
                )
            )

    def _observed_fills(self) -> tuple[Fill, ...]:
        return tuple(getattr(self._inner, "fills", ()))

    def _new_passive_fills(
        self,
        before: tuple[Fill, ...],
        active_fills: tuple[Fill, ...] = (),
    ) -> list[Fill]:
        new_fills = list(self._observed_fills()[len(before) :])
        for fill in active_fills:
            if fill in new_fills:
                new_fills.remove(fill)
        return new_fills

    def advance_to(self, ts_ns: int) -> list[Fill]:
        """Advance replay time and record passive fills."""

        fills = self._inner.advance_to(ts_ns)
        self._record_passive_fills(fills)
        return fills

    def place_limit(
        self,
        side: Side,
        price: Price,
        size: int,
        tif: TimeInForce = "GTC",
    ) -> OrderResult:
        """Place a limit order and record the attempt plus immediate fills."""

        before = self._observed_fills()
        result = self._inner.place_limit(side=side, price=price, size=size, tif=tif)
        self._record_passive_fills(self._new_passive_fills(before, result.fills))
        self._record(
            OrderEvent(
                strategy=self._strategy,
                kind="place_limit",
                ts_ns=self.now_ns(),
                order_id=result.order_id,
                side=side,
                price=price,
                size=size,
                tif=tif,
                n_fills=len(result.fills),
            )
        )
        self._record_fills(result.fills, "place_limit")
        return result

    def place_market(self, side: Side, size: int) -> list[Fill]:
        """Place a market order and record the attempt plus fills."""

        before = self._observed_fills()
        fills = self._inner.place_market(side=side, size=size)
        self._record_passive_fills(self._new_passive_fills(before, tuple(fills)))
        self._record(
            OrderEvent(
                strategy=self._strategy,
                kind="place_market",
                ts_ns=self.now_ns(),
                side=side,
                size=size,
                n_fills=len(fills),
            )
        )
        self._record_fills(fills, "place_market")
        return fills

    def cancel(self, order_id: OrderId) -> bool:
        """Cancel an order and record whether the cancel was accepted."""

        before = self._observed_fills()
        accepted = self._inner.cancel(order_id)
        self._record_passive_fills(self._new_passive_fills(before))
        self._record(
            OrderEvent(
                strategy=self._strategy,
                kind="cancel",
                ts_ns=self.now_ns(),
                order_id=order_id,
                accepted=accepted,
            )
        )
        return accepted

    def book_top(self) -> tuple[Price | None, Price | None]:
        return self._inner.book_top()

    def book_depth(self, levels: int) -> Any:
        return self._inner.book_depth(levels)

    def position(self) -> int:
        return self._inner.position()

    def own_orders(self) -> tuple[RestingOrder, ...]:
        return self._inner.own_orders()

    def now_ns(self) -> int:
        return self._inner.now_ns()

    def __getattr__(self, name: str) -> Any:
        """Forward non-public helper attributes from the wrapped gateway."""

        return getattr(self._inner, name)
