"""Public dataclasses and aliases for ordersim."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal, TypeAlias

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
    """A single execution fill observed by the strategy."""

    order_id: OrderId
    price: Price
    size: int
    ts_ns: int


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
