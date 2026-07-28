"""Record raw Binance depth and trade evidence for modeled replay.

The recorder preserves exchange payloads and adds local receive timestamps,
connection identifiers, and sequence-gap records. Individual and aggregate
trades are both retained. The recorder deliberately does not turn aggregated
depth into `MBOEvent` rows; that inference belongs to a named reconstruction
model.
"""

import argparse
import asyncio
import uuid
from collections.abc import Sequence
from pathlib import Path

from ordersim.connectors.binance._storage import RawCaptureSink
from ordersim.connectors.binance._transport import (
    INDIVIDUAL_TRADE_STREAM_URL,
    MARKET_STREAM_URL,
    PUBLIC_STREAM_URL,
    Transport,
    WebSocketTransport,
)
from ordersim.connectors.binance.schema import (
    BinanceCaptureConfig,
    CaptureManifest,
    DepthSequenceTracker,
    TradeSequenceTracker,
)


async def capture_binance(
    config: BinanceCaptureConfig,
    *,
    transport: Transport | None = None,
) -> CaptureManifest:
    """Capture raw Binance evidence until duration expiry or interruption."""

    active_transport = transport or WebSocketTransport()
    sink = RawCaptureSink(config)
    interrupted = False
    tasks = [
        asyncio.create_task(
            _capture_with_reconnect(
                config=config,
                sink=sink,
                transport=active_transport,
                symbol=symbol,
                scope=scope,
            )
        )
        for symbol in config.symbols
        for scope in ("public", "market", "individual")
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


async def _capture_with_reconnect(
    *,
    config: BinanceCaptureConfig,
    sink: RawCaptureSink,
    transport: Transport,
    symbol: str,
    scope: str,
) -> None:
    capture_scope = "public" if scope == "public" else "market"
    while True:
        connection_id = uuid.uuid4().hex
        try:
            await _capture_connection(
                config=config,
                sink=sink,
                transport=transport,
                symbol=symbol,
                scope=scope,
                connection_id=connection_id,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await sink.write(
                kind="connection_error",
                scope=capture_scope,
                symbol=symbol,
                connection_id=connection_id,
                stream=None,
                payload={
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                },
            )
        await asyncio.sleep(config.reconnect_delay_seconds)


async def _capture_connection(
    *,
    config: BinanceCaptureConfig,
    sink: RawCaptureSink,
    transport: Transport,
    symbol: str,
    scope: str,
    connection_id: str,
) -> None:
    if scope == "public":
        streams = config.public_streams(symbol)
        base_url = PUBLIC_STREAM_URL
        capture_scope = "public"
    elif scope == "market":
        streams = config.market_streams(symbol)
        base_url = MARKET_STREAM_URL
        capture_scope = "market"
    elif scope == "individual":
        streams = config.individual_trade_streams(symbol)
        base_url = INDIVIDUAL_TRADE_STREAM_URL
        capture_scope = "market"
    else:
        raise ValueError(f"unsupported Binance capture scope {scope!r}")

    trackers: dict[str, DepthSequenceTracker] = {}
    trade_tracker = TradeSequenceTracker()
    async with transport.connect(base_url + "/".join(streams)) as messages:
        await sink.write(
            kind="connection_open",
            scope=capture_scope,
            symbol=symbol,
            connection_id=connection_id,
            stream=None,
            payload={"streams": list(streams)},
        )
        if scope == "public":
            snapshot = await transport.depth_snapshot(symbol, config.snapshot_limit)
            await sink.write(
                kind="depth_snapshot",
                scope=capture_scope,
                symbol=symbol,
                connection_id=connection_id,
                stream=None,
                payload=snapshot,
            )

        async for stream, payload in messages:
            await sink.write(
                kind="message",
                scope=capture_scope,
                symbol=symbol,
                connection_id=connection_id,
                stream=stream,
                payload=payload,
            )
            if stream.endswith("@trade"):
                gap = trade_tracker.observe(payload)
                if gap is not None:
                    await sink.write(
                        kind="trade_gap",
                        scope=capture_scope,
                        symbol=symbol,
                        connection_id=connection_id,
                        stream=stream,
                        payload=gap.as_dict(),
                    )
                continue
            if "@depth@" not in stream and "@rpiDepth@" not in stream:
                continue
            tracker = trackers.setdefault(stream, DepthSequenceTracker())
            gap = tracker.observe(payload)
            if gap is not None:
                await sink.write(
                    kind="sequence_gap",
                    scope=capture_scope,
                    symbol=symbol,
                    connection_id=connection_id,
                    stream=stream,
                    payload=gap.as_dict(),
                )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Record Binance USD-M depth and trade evidence."
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
        "--include-rpi",
        action="store_true",
        help="Also record the 500 ms RPI depth stream.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    """Run the `ordersim-binance-capture` command."""

    args = _parser().parse_args(argv)
    duration_seconds = (
        None if args.duration_hours is None else args.duration_hours * 60 * 60
    )
    config = BinanceCaptureConfig(
        output_dir=args.output_dir,
        symbols=tuple(args.symbols),
        duration_seconds=duration_seconds,
        include_rpi=args.include_rpi,
    )
    try:
        manifest = asyncio.run(capture_binance(config))
    except KeyboardInterrupt:
        return
    print(
        f"capture {manifest.run_id} complete: "
        f"{sum(manifest.counts.values())} records"
    )
