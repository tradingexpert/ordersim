"""Public dataclasses and aliases for ordersim."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal, TypeAlias

BookSide: TypeAlias = Literal["bid", "ask"]
MBOAction: TypeAlias = Literal["add", "cancel", "modify", "trade"]
OrderId: TypeAlias = int
Price: TypeAlias = Decimal
Side: TypeAlias = Literal["buy", "sell"]
TimeInForce: TypeAlias = Literal["GTC", "IOC"]
EventKind: TypeAlias = Literal[
    "place_limit",
    "place_market",
    "cancel",
    "fill",
    "fill_passive",
]


@dataclass(frozen=True, slots=True)
class Fill:
    """A single execution fill observed by the strategy.

    `side` is the strategy side of the fill, not the resting public book side.
    A passive fill of an own bid order is therefore `side="buy"`.
    """

    order_id: OrderId
    side: Side
    price: Price
    size: int
    ts_ns: int


@dataclass(frozen=True, slots=True)
class MBOEvent:
    """One normalized market-by-order event.

    `ts_ns` is an integer UTC Unix-epoch timestamp in nanoseconds.
    `side` is the resting book side affected by the event. For a trade, that
    means the side of the resting order that traded, not the aggressor side.
    """

    ts_ns: int
    action: MBOAction
    side: BookSide
    price: Price
    size: int
    order_id: OrderId

    def __post_init__(self) -> None:
        if self.ts_ns < 0:
            raise ValueError("ts_ns must be non-negative")
        if self.price <= 0:
            raise ValueError("price must be positive")
        if self.size <= 0:
            raise ValueError("size must be positive")
        if self.order_id < 0:
            raise ValueError("order_id must be non-negative")


@dataclass(frozen=True, slots=True)
class OrderResult:
    """Result of a limit-order placement.

    `order_id` is present when some quantity rests on the book. `fills` contains
    any immediate fills caused by the order.
    """

    order_id: OrderId | None
    fills: tuple[Fill, ...] = ()


@dataclass(frozen=True, slots=True)
class OrderEvent:
    """Flat audit-log row emitted by `RecordingGateway`."""

    strategy: str
    kind: EventKind
    ts_ns: int | None
    order_id: OrderId | None = None
    side: Side | None = None
    price: Price | None = None
    size: int | None = None
    tif: TimeInForce | None = None
    fill_price: Price | None = None
    fill_size: int | None = None
    n_fills: int | None = None
    source: str | None = None
    accepted: bool | None = None
