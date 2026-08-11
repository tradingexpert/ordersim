"""Typed Binance Level 2 market-data records."""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal, TypeAlias

DepthStreamKind: TypeAlias = Literal["depth", "rpi_depth"]
CaptureKind: TypeAlias = Literal[
    "connection_open",
    "connection_error",
    "depth_snapshot",
    "message",
    "raw_trade",
    "raw_trade_gap",
    "raw_trade_poll",
    "raw_trade_poll_error",
    "sequence_gap",
    "trade_gap",
]
CaptureScope: TypeAlias = Literal["public", "market"]


@dataclass(frozen=True, slots=True)
class BinanceCaptureEnvelope:
    """One raw capture row with local receive metadata."""

    schema_version: int
    received_at_ns: int
    received_monotonic_ns: int
    kind: CaptureKind
    scope: CaptureScope
    symbol: str
    connection_id: str
    stream: str | None
    payload: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class BinancePriceLevel:
    """One absolute price and quantity pair from Binance."""

    price: Decimal
    quantity: Decimal

    def __post_init__(self) -> None:
        if self.price <= 0:
            raise ValueError("price must be positive")
        if self.quantity < 0:
            raise ValueError("quantity must be non-negative")


@dataclass(frozen=True, slots=True)
class BinanceDepthSnapshot:
    """One REST snapshot anchoring a diff-depth connection."""

    symbol: str
    connection_id: str
    received_at_ns: int
    received_monotonic_ns: int
    last_update_id: int
    bids: tuple[BinancePriceLevel, ...]
    asks: tuple[BinancePriceLevel, ...]


@dataclass(frozen=True, slots=True)
class BinanceDepthUpdate:
    """One absolute-quantity diff-depth update."""

    symbol: str
    connection_id: str
    stream_kind: DepthStreamKind
    event_time_ns: int
    transaction_time_ns: int
    received_at_ns: int
    received_monotonic_ns: int
    first_update_id: int
    final_update_id: int
    previous_update_id: int
    bids: tuple[BinancePriceLevel, ...]
    asks: tuple[BinancePriceLevel, ...]


@dataclass(frozen=True, slots=True)
class BinanceAggregateTrade:
    """Trades aggregated by Binance over price and taking side."""

    symbol: str
    connection_id: str
    event_time_ns: int
    trade_time_ns: int
    received_at_ns: int
    received_monotonic_ns: int
    aggregate_trade_id: int
    price: Decimal
    quantity: Decimal
    normal_quantity: Decimal | None
    first_trade_id: int
    last_trade_id: int
    buyer_is_maker: bool


@dataclass(frozen=True, slots=True)
class BinanceIndividualTrade:
    """One real-time, individually identified Binance trade."""

    symbol: str
    connection_id: str
    event_time_ns: int
    trade_time_ns: int
    received_at_ns: int
    received_monotonic_ns: int
    trade_id: int
    price: Decimal
    quantity: Decimal
    buyer_is_maker: bool


@dataclass(frozen=True, slots=True)
class BinanceRawTrade:
    """One individual trade returned by Binance USD-M REST."""

    symbol: str
    connection_id: str
    received_at_ns: int
    received_monotonic_ns: int
    trade_id: int
    price: Decimal
    quantity: Decimal
    quote_quantity: Decimal
    trade_time_ns: int
    buyer_is_maker: bool
    is_rpi_trade: bool


@dataclass(frozen=True, slots=True)
class BinanceBookTicker:
    """One real-time Binance best-bid/ask observation."""

    symbol: str
    connection_id: str
    event_time_ns: int
    transaction_time_ns: int
    received_at_ns: int
    received_monotonic_ns: int
    update_id: int
    bid_price: Decimal
    bid_quantity: Decimal
    ask_price: Decimal
    ask_quantity: Decimal


BinanceDepthEvent: TypeAlias = BinanceDepthSnapshot | BinanceDepthUpdate
BinanceObservedEvent: TypeAlias = (
    BinanceDepthSnapshot
    | BinanceDepthUpdate
    | BinanceIndividualTrade
    | BinanceBookTicker
)
