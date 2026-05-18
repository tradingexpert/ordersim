"""Internal columnar view of one canonical replay stream."""

from array import array
from dataclasses import dataclass
from decimal import Decimal

from ordersim.types import MBOEvent, Price

_ACTION_CODE = {
    "add": ord("A"),
    "cancel": ord("C"),
    "modify": ord("M"),
    "trade": ord("T"),
}
_SIDE_CODE = {
    "bid": ord("B"),
    "ask": ord("A"),
}


@dataclass(frozen=True, slots=True)
class CompiledEventColumns:
    """Primitive event columns shared by repeated compiled-engine runs."""

    ts_ns: array
    action: array
    side: array
    price_ticks: array
    size: array
    order_id: array

    @classmethod
    def from_events(
        cls,
        events: tuple[MBOEvent, ...],
        *,
        tick_size: Price,
    ) -> "CompiledEventColumns":
        """Compile immutable public events into integer columns once."""

        return cls(
            ts_ns=array("q", (event.ts_ns for event in events)),
            action=array("B", (_ACTION_CODE[event.action] for event in events)),
            side=array("B", (_SIDE_CODE[event.side] for event in events)),
            price_ticks=array(
                "q",
                (_price_to_ticks(event.price, tick_size) for event in events),
            ),
            size=array("i", (event.size for event in events)),
            order_id=array("q", (event.order_id for event in events)),
        )

    def slice(self, start: int, stop: int) -> "CompiledEventSlice":
        """Return zero-copy memory views for one replay interval."""

        return CompiledEventSlice(
            ts_ns=memoryview(self.ts_ns)[start:stop],
            action=memoryview(self.action)[start:stop],
            side=memoryview(self.side)[start:stop],
            price_ticks=memoryview(self.price_ticks)[start:stop],
            size=memoryview(self.size)[start:stop],
            order_id=memoryview(self.order_id)[start:stop],
        )


@dataclass(frozen=True, slots=True)
class CompiledEventSlice:
    """Zero-copy primitive columns for one contiguous replay interval."""

    ts_ns: memoryview
    action: memoryview
    side: memoryview
    price_ticks: memoryview
    size: memoryview
    order_id: memoryview


def _price_to_ticks(price: Decimal, tick_size: Price) -> int:
    ticks = price / tick_size
    if ticks != ticks.to_integral_value():
        raise ValueError(f"price {price} is not aligned to tick_size {tick_size}")
    return int(ticks)
