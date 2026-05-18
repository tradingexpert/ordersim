"""Optional pybind11 execution engine."""

from decimal import Decimal
from typing import Any

from ordersim.replay.compiled_events import CompiledEventSlice
from ordersim.sim.matching_engine import PriceLevel
from ordersim.types import (
    Fill,
    MBOEvent,
    OrderId,
    OrderResult,
    Price,
    RestingOrder,
    Side,
    TimeInForce,
)


class CppMatchingEngine:
    """Queue-aware compiled engine with the public execution-engine surface."""

    def __init__(self, *, tick_size: Decimal) -> None:
        if tick_size <= 0:
            raise ValueError("tick_size must be positive")
        self._tick_size = tick_size
        self._core = _load_cpp_module().MatchingEngineCpp()

    def apply_event(self, event: MBOEvent) -> list[Fill]:
        rows = self._core.apply_event(
            event.ts_ns,
            event.action,
            _book_side_char(event.side),
            self._price_to_ticks(event.price),
            event.size,
            event.order_id,
        )
        return [self._fill_from_row(row) for row in rows]

    def apply_events_batch(
        self,
        events: CompiledEventSlice,
    ) -> list[Fill]:
        """Apply one compiled event slice and return passive fills."""

        rows = self._core.apply_events_batch(
            events.ts_ns,
            events.action,
            events.side,
            events.price_ticks,
            events.size,
            events.order_id,
        )
        return [self._fill_from_row(row) for row in rows]

    def advance_time(self, ts_ns: int) -> None:
        self._core.advance_time(ts_ns)

    def place_limit(
        self,
        side: Side,
        price: Price,
        size: int,
        tif: TimeInForce = "GTC",
    ) -> OrderResult:
        order_id, rows = self._core.place_limit(
            _order_side_char(side),
            self._price_to_ticks(price),
            size,
            tif,
        )
        resting_order_id = None if order_id < 0 else order_id
        return OrderResult(
            order_id=resting_order_id,
            fills=tuple(self._fill_from_row(row) for row in rows),
        )

    def place_market(self, side: Side, size: int) -> list[Fill]:
        rows = self._core.place_market(_order_side_char(side), size)
        return [self._fill_from_row(row) for row in rows]

    def cancel(self, order_id: OrderId) -> bool:
        return bool(self._core.cancel(order_id))

    def book_top(self) -> tuple[Price | None, Price | None]:
        bid_ticks, ask_ticks = self._core.book_top()
        return self._optional_price(bid_ticks), self._optional_price(ask_ticks)

    def book_depth(
        self,
        levels: int,
    ) -> tuple[tuple[PriceLevel, ...], tuple[PriceLevel, ...]]:
        bids, asks = self._core.book_depth(levels)
        return (
            tuple(
                PriceLevel(self._ticks_to_price(price), size)
                for price, size in bids
            ),
            tuple(
                PriceLevel(self._ticks_to_price(price), size)
                for price, size in asks
            ),
        )

    def position(self) -> int:
        return int(self._core.position())

    def own_orders(self) -> tuple[RestingOrder, ...]:
        return tuple(
            RestingOrder(
                order_id=order_id,
                side=_order_side_from_char(side),
                price=self._ticks_to_price(price_ticks),
                remaining_size=size,
                queue_ahead_size=queue_ahead,
            )
            for order_id, side, price_ticks, size, queue_ahead in (
                self._core.own_orders()
            )
        )

    def _price_to_ticks(self, price: Price) -> int:
        ticks = price / self._tick_size
        if ticks != ticks.to_integral_value():
            raise ValueError(
                f"price {price} is not aligned to tick_size {self._tick_size}"
            )
        return int(ticks)

    def _ticks_to_price(self, ticks: int) -> Price:
        return self._tick_size * Decimal(ticks)

    def _optional_price(self, ticks: int) -> Price | None:
        return None if ticks < 0 else self._ticks_to_price(ticks)

    def _fill_from_row(self, row: Any) -> Fill:
        return Fill(
            order_id=row.order_id,
            side=_order_side_from_char(row.side),
            price=self._ticks_to_price(row.price_ticks),
            size=row.size,
            ts_ns=row.ts_ns,
        )


def cpp_execution_engine_available() -> bool:
    """Return whether the optional compiled extension can be imported."""

    try:
        _load_cpp_module()
    except ImportError:
        return False
    return True


def _load_cpp_module() -> Any:
    try:
        from ordersim import _matching_engine_cpp
    except ImportError as exc:
        raise ImportError(
            "ordersim C++ engine is not built; install the project normally "
            'with `python -m pip install -e ".[dev]"` first'
        ) from exc
    return _matching_engine_cpp


def _book_side_char(side: str) -> str:
    return "B" if side == "bid" else "A"


def _order_side_char(side: str) -> str:
    return "B" if side == "buy" else "A"


def _order_side_from_char(side: str) -> Side:
    return "buy" if side == "B" else "sell"
