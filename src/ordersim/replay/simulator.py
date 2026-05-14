"""Small replay runner built around the reference matching engine."""

from collections.abc import Callable, MutableSequence
from dataclasses import dataclass
from typing import Any

from ordersim.connectors import EventInput, normalize_events
from ordersim.gateway import OrderGateway
from ordersim.recording import RecordingGateway
from ordersim.sim import (
    ExecutionEngine,
    ExecutionEngineFactory,
    PriceLevel,
    default_execution_engine_factory,
)
from ordersim.specs import InstrumentSpec
from ordersim.types import (
    Fill,
    OrderEvent,
    OrderId,
    OrderResult,
    Price,
    Side,
    TimeInForce,
)

Strategy = Callable[[OrderGateway], Any]


@dataclass(frozen=True, slots=True)
class ReplayResult:
    """Result returned by one replay run."""

    fills: tuple[Fill, ...]
    order_events: tuple[OrderEvent, ...]
    final_position: int


class ReplayGateway:
    """Order gateway that advances a matching engine through MBO events."""

    def __init__(
        self,
        data: EventInput,
        engine: ExecutionEngine | None = None,
    ) -> None:
        self._data = tuple(
            sorted(normalize_events(data), key=lambda event: event.ts_ns)
        )
        self._engine = engine or default_execution_engine_factory()
        self._cursor = 0
        self._now_ns = 0
        self._fills: list[Fill] = []

    @property
    def fills(self) -> tuple[Fill, ...]:
        """All active and passive fills observed by this gateway."""

        return tuple(self._fills)

    def advance_to(self, ts_ns: int) -> list[Fill]:
        """Advance replay time and return passive fills since the last call."""

        if ts_ns < self._now_ns:
            raise ValueError("cannot move replay time backwards")

        fills: list[Fill] = []
        while (
            self._cursor < len(self._data)
            and self._data[self._cursor].ts_ns <= ts_ns
        ):
            event = self._data[self._cursor]
            fills.extend(self._engine.apply_event(event))
            self._cursor += 1

        self._now_ns = ts_ns
        self._engine.advance_time(ts_ns)
        self._fills.extend(fills)
        return fills

    def place_limit(
        self,
        side: Side,
        price: Price,
        size: int,
        tif: TimeInForce = "GTC",
    ) -> OrderResult:
        """Place a limit order through the matching engine."""

        result = self._engine.place_limit(side=side, price=price, size=size, tif=tif)
        self._fills.extend(result.fills)
        return result

    def place_market(self, side: Side, size: int) -> list[Fill]:
        """Place a market order through the matching engine."""

        fills = self._engine.place_market(side=side, size=size)
        self._fills.extend(fills)
        return fills

    def cancel(self, order_id: OrderId) -> bool:
        """Cancel a resting own order."""

        return self._engine.cancel(order_id)

    def book_top(self) -> tuple[Price | None, Price | None]:
        """Return ``(best_bid, best_ask)``."""

        return self._engine.book_top()

    def book_depth(
        self,
        levels: int,
    ) -> tuple[tuple[PriceLevel, ...], tuple[PriceLevel, ...]]:
        """Return visible top bid and ask levels."""

        return self._engine.book_depth(levels)

    def position(self) -> int:
        """Return signed position from active and passive fills."""

        return self._engine.position()

    def now_ns(self) -> int:
        """Return current replay time in integer nanoseconds."""

        return self._now_ns


class Replay:
    """Run one or more strategies over the same immutable MBO event stream."""

    def __init__(
        self,
        data: EventInput,
        instrument: InstrumentSpec,
        record_to: MutableSequence[OrderEvent] | None = None,
        execution_engine_factory: ExecutionEngineFactory | None = None,
    ) -> None:
        self.data = tuple(sorted(normalize_events(data), key=lambda event: event.ts_ns))
        self.instrument = instrument
        self.record_to = record_to
        self._execution_engine_factory = (
            execution_engine_factory or default_execution_engine_factory
        )
        for event in self.data:
            instrument.assert_price_aligned(event.price)

    def run(
        self,
        strategy: Strategy,
        *,
        strategy_name: str = "default",
    ) -> ReplayResult:
        """Run one strategy and return fills plus its order-intent log."""

        gateway = ReplayGateway(self.data, engine=self._execution_engine_factory())
        order_events: list[OrderEvent] = []
        recording_gateway = RecordingGateway(
            gateway,
            order_events,
            strategy=strategy_name,
        )

        strategy(recording_gateway)

        if self.record_to is not None:
            self.record_to.extend(order_events)

        return ReplayResult(
            fills=gateway.fills,
            order_events=tuple(order_events),
            final_position=gateway.position(),
        )

    def run_many(self, strategies: dict[str, Strategy]) -> dict[str, ReplayResult]:
        """Run named strategies independently over the same replay data."""

        return {
            name: self.run(strategy, strategy_name=name)
            for name, strategy in strategies.items()
        }
