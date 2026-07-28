"""Network transport for Binance public market-data endpoints."""

import asyncio
import json
import urllib.request
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any, Protocol

from ordersim.connectors.binance.schema import JsonObject

PUBLIC_STREAM_URL = "wss://fstream.binance.com/public/stream?streams="
MARKET_STREAM_URL = "wss://fstream.binance.com/market/stream?streams="
INDIVIDUAL_TRADE_STREAM_URL = "wss://fstream.binance.com/stream?streams="
DEPTH_SNAPSHOT_URL = "https://fapi.binance.com/fapi/v1/depth"


class Transport(Protocol):
    def connect(
        self, url: str
    ) -> AbstractAsyncContextManager[AsyncIterator[tuple[str, JsonObject]]]:
        """Open one combined Binance WebSocket stream."""

    async def depth_snapshot(self, symbol: str, limit: int) -> JsonObject:
        """Fetch one Binance depth snapshot."""


class WebSocketTransport:
    """Optional-dependency transport for Binance public endpoints."""

    def __init__(
        self,
        *,
        connect: Callable[..., AbstractAsyncContextManager[Any]] | None = None,
        read_url: Callable[[str], bytes] | None = None,
    ) -> None:
        if connect is None:
            try:
                from websockets.asyncio.client import connect as websocket_connect
            except ImportError as exc:
                raise RuntimeError(
                    'Binance capture requires: pip install "ordersim[binance]"'
                ) from exc
            connect = websocket_connect
        self._connect = connect
        self._read_url = read_url or _read_url

    @asynccontextmanager
    async def connect(
        self, url: str
    ) -> AsyncIterator[AsyncIterator[tuple[str, JsonObject]]]:
        async with self._connect(url, open_timeout=20, ping_timeout=20) as websocket:
            yield combined_messages(websocket)

    async def depth_snapshot(self, symbol: str, limit: int) -> JsonObject:
        query = f"?symbol={symbol}&limit={limit}"
        raw = await asyncio.to_thread(self._read_url, DEPTH_SNAPSHOT_URL + query)
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("Binance depth snapshot must be a JSON object")
        return payload


async def combined_messages(
    websocket: AsyncIterator[str | bytes],
) -> AsyncIterator[tuple[str, JsonObject]]:
    async for raw in websocket:
        yield decode_combined_message(raw)


def decode_combined_message(raw: str | bytes) -> tuple[str, JsonObject]:
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("Binance stream message must be a JSON object")
    stream = payload.get("stream")
    data = payload.get("data")
    if not isinstance(stream, str) or not isinstance(data, dict):
        raise ValueError("expected a combined Binance stream envelope")
    return stream, data


def _read_url(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "ordersim"})
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.read()
