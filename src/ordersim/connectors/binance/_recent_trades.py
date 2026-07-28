"""HTTP transport and trade-ID tracking for Binance raw trades."""

import asyncio
import json
import time
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol

from ordersim.connectors.binance.schema import JsonObject

RECENT_TRADES_URL = "https://fapi.binance.com/fapi/v1/trades"


@dataclass(frozen=True, slots=True)
class RecentTradesBatch:
    """One response from the Binance recent-trades endpoint."""

    trades: tuple[JsonObject, ...]
    request_started_at_ns: int
    request_finished_at_ns: int
    used_weight_1m: int | None


class RecentTradesClient(Protocol):
    """Fetch individual recent trades for one symbol."""

    async def recent_trades(
        self,
        symbol: str,
        limit: int,
    ) -> RecentTradesBatch:
        """Return one recent-trades response."""


FetchUrl = Callable[[str], tuple[bytes, Mapping[str, str]]]


class HttpRecentTradesClient:
    """Standard-library client for Binance individual recent trades."""

    def __init__(self, *, fetch_url: FetchUrl | None = None) -> None:
        self._fetch_url = fetch_url or _fetch_url

    async def recent_trades(
        self,
        symbol: str,
        limit: int,
    ) -> RecentTradesBatch:
        """Fetch and validate one recent-trades response."""

        query = urllib.parse.urlencode({"symbol": symbol, "limit": limit})
        started_at_ns = time.time_ns()
        raw, headers = await asyncio.to_thread(
            self._fetch_url,
            f"{RECENT_TRADES_URL}?{query}",
        )
        finished_at_ns = time.time_ns()
        payload = json.loads(raw)
        trades = _validate_trades(payload)
        return RecentTradesBatch(
            trades=trades,
            request_started_at_ns=started_at_ns,
            request_finished_at_ns=finished_at_ns,
            used_weight_1m=_optional_header_int(headers, "x-mbx-used-weight-1m"),
        )


@dataclass(frozen=True, slots=True)
class RawTradeGap:
    """One missing range in the observed individual trade IDs."""

    expected_trade_id: int
    first_received_trade_id: int

    def as_dict(self) -> dict[str, int]:
        """Return a JSON-compatible representation."""

        return {
            "expected_trade_id": self.expected_trade_id,
            "first_received_trade_id": self.first_received_trade_id,
            "missing_count": self.first_received_trade_id - self.expected_trade_id,
        }


@dataclass(frozen=True, slots=True)
class RawTradeSelection:
    """New trades and any gap found in one overlapping response."""

    trades: tuple[JsonObject, ...]
    gap: RawTradeGap | None


class RawTradeCursor:
    """Deduplicate overlapping responses and expose missing trade IDs."""

    def __init__(self) -> None:
        self._last_trade_id: int | None = None

    @property
    def last_trade_id(self) -> int | None:
        """Return the greatest trade ID observed so far."""

        return self._last_trade_id

    def select(self, trades: tuple[JsonObject, ...]) -> RawTradeSelection:
        """Return only unseen trades, preserving endpoint order."""

        trade_ids = tuple(_trade_id(trade) for trade in trades)
        adjacent_ids = zip(trade_ids, trade_ids[1:], strict=False)
        if any(right <= left for left, right in adjacent_ids):
            raise ValueError("Binance recent trades must have increasing IDs")

        previous = self._last_trade_id
        if previous is None:
            new_trades = trades
        else:
            new_trades = tuple(
                trade
                for trade, trade_id in zip(trades, trade_ids, strict=True)
                if trade_id > previous
            )

        gap = None
        if previous is not None and new_trades:
            first_new_id = _trade_id(new_trades[0])
            if first_new_id > previous + 1:
                gap = RawTradeGap(
                    expected_trade_id=previous + 1,
                    first_received_trade_id=first_new_id,
                )

        if new_trades:
            self._last_trade_id = _trade_id(new_trades[-1])
        return RawTradeSelection(trades=new_trades, gap=gap)


def _validate_trades(payload: object) -> tuple[JsonObject, ...]:
    if not isinstance(payload, list):
        raise ValueError("Binance recent-trades response must be a list")
    trades: list[JsonObject] = []
    for trade in payload:
        if not isinstance(trade, dict):
            raise ValueError("Binance recent trade must be a JSON object")
        _trade_id(trade)
        _required_int(trade, "time")
        _required_str(trade, "price")
        _required_str(trade, "qty")
        _required_str(trade, "quoteQty")
        _required_bool(trade, "isBuyerMaker")
        _required_bool(trade, "isRPITrade")
        trades.append(trade)
    return tuple(trades)


def _trade_id(trade: Mapping[str, object]) -> int:
    return _required_int(trade, "id")


def _required_int(payload: Mapping[str, object], field: str) -> int:
    value = payload.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"Binance raw-trade field {field!r} must be an integer")
    return value


def _required_str(payload: Mapping[str, object], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str):
        raise ValueError(f"Binance raw-trade field {field!r} must be a string")
    return value


def _required_bool(payload: Mapping[str, object], field: str) -> bool:
    value = payload.get(field)
    if not isinstance(value, bool):
        raise ValueError(f"Binance raw-trade field {field!r} must be a boolean")
    return value


def _optional_header_int(
    headers: Mapping[str, str],
    field: str,
) -> int | None:
    value = next(
        (
            header_value
            for header_name, header_value in headers.items()
            if header_name.lower() == field.lower()
        ),
        None,
    )
    if value is None:
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"Binance header {field!r} must be an integer") from exc


def _fetch_url(url: str) -> tuple[bytes, Mapping[str, str]]:
    request = urllib.request.Request(url, headers={"User-Agent": "ordersim"})
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.read(), dict(response.headers.items())
