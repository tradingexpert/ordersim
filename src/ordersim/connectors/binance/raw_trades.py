"""Capture individual Binance USD-M trades through overlapping REST polls."""

import argparse
import asyncio
import uuid
from collections.abc import Sequence
from pathlib import Path

from ordersim.connectors.binance._recent_trades import (
    HttpRecentTradesClient,
    RawTradeCursor,
    RecentTradesBatch,
    RecentTradesClient,
)
from ordersim.connectors.binance._storage import RawCaptureSink
from ordersim.connectors.binance.schema import (
    BinanceRawTradeCaptureConfig,
    CaptureManifest,
)

RAW_TRADES_STREAM = "rest:/fapi/v1/trades"


async def capture_binance_raw_trades(
    config: BinanceRawTradeCaptureConfig,
    *,
    client: RecentTradesClient | None = None,
) -> CaptureManifest:
    """Capture individual trades until duration expiry or interruption."""

    active_client = client or HttpRecentTradesClient()
    sink = RawCaptureSink(config)
    interrupted = False
    tasks = [
        asyncio.create_task(
            _poll_symbol(
                config=config,
                sink=sink,
                client=active_client,
                symbol=symbol,
            )
        )
        for symbol in config.symbols
    ]
    try:
        if config.duration_seconds is None:
            await asyncio.Event().wait()
        else:
            await asyncio.sleep(config.duration_seconds)
    except asyncio.CancelledError:
        interrupted = True
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        manifest = sink.close()
    if interrupted:
        raise asyncio.CancelledError
    return manifest


async def _poll_symbol(
    *,
    config: BinanceRawTradeCaptureConfig,
    sink: RawCaptureSink,
    client: RecentTradesClient,
    symbol: str,
) -> None:
    connection_id = uuid.uuid4().hex
    cursor = RawTradeCursor()
    while True:
        try:
            batch = await client.recent_trades(symbol, config.request_limit)
            await _record_batch(
                sink=sink,
                symbol=symbol,
                connection_id=connection_id,
                cursor=cursor,
                batch=batch,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await sink.write(
                kind="raw_trade_poll_error",
                scope="market",
                symbol=symbol,
                connection_id=connection_id,
                stream=RAW_TRADES_STREAM,
                payload={
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                    "last_trade_id": cursor.last_trade_id,
                },
            )
            await asyncio.sleep(config.retry_delay_seconds)
            continue
        await asyncio.sleep(config.poll_interval_seconds)


async def _record_batch(
    *,
    sink: RawCaptureSink,
    symbol: str,
    connection_id: str,
    cursor: RawTradeCursor,
    batch: RecentTradesBatch,
) -> None:
    selection = cursor.select(batch.trades)
    first_trade_id = batch.trades[0]["id"] if batch.trades else None
    last_trade_id = batch.trades[-1]["id"] if batch.trades else None
    await sink.write(
        kind="raw_trade_poll",
        scope="market",
        symbol=symbol,
        connection_id=connection_id,
        stream=RAW_TRADES_STREAM,
        payload={
            "request_started_at_ns": batch.request_started_at_ns,
            "request_finished_at_ns": batch.request_finished_at_ns,
            "used_weight_1m": batch.used_weight_1m,
            "returned_count": len(batch.trades),
            "new_count": len(selection.trades),
            "first_trade_id": first_trade_id,
            "last_trade_id": last_trade_id,
        },
    )
    if selection.gap is not None:
        await sink.write(
            kind="raw_trade_gap",
            scope="market",
            symbol=symbol,
            connection_id=connection_id,
            stream=RAW_TRADES_STREAM,
            payload=selection.gap.as_dict(),
        )
    for trade in selection.trades:
        await sink.write(
            kind="raw_trade",
            scope="market",
            symbol=symbol,
            connection_id=connection_id,
            stream=RAW_TRADES_STREAM,
            payload=trade,
        )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Record individual Binance USD-M trades from REST."
    )
    parser.add_argument("output_dir", type=Path)
    parser.add_argument(
        "--symbol",
        action="append",
        required=True,
        dest="symbols",
        help="USD-M symbol; repeat for more than one (for example BTCUSDT).",
    )
    parser.add_argument(
        "--duration-hours",
        type=float,
        help="Stop after this many hours; otherwise run until interrupted.",
    )
    parser.add_argument(
        "--poll-interval-seconds",
        type=float,
        default=0.5,
        help="Seconds between requests per symbol (default: 0.5).",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    """Run the `ordersim-binance-raw-trades` command."""

    args = _parser().parse_args(argv)
    duration_seconds = (
        None if args.duration_hours is None else args.duration_hours * 60 * 60
    )
    config = BinanceRawTradeCaptureConfig(
        output_dir=args.output_dir,
        symbols=tuple(args.symbols),
        duration_seconds=duration_seconds,
        poll_interval_seconds=args.poll_interval_seconds,
    )
    try:
        manifest = asyncio.run(capture_binance_raw_trades(config))
    except KeyboardInterrupt:
        return
    print(
        f"raw-trade capture {manifest.run_id} complete: "
        f"{manifest.counts.get('raw_trade', 0)} trades"
    )


if __name__ == "__main__":
    main()
