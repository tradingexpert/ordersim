import asyncio
import builtins
import gzip
import json
import runpy
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

import ordersim.connectors.binance._transport as transport_module
import ordersim.connectors.binance.capture as capture_module
from ordersim.connectors.binance._storage import RawCaptureSink
from ordersim.connectors.binance._transport import (
    INDIVIDUAL_TRADE_STREAM_URL,
    MARKET_STREAM_URL,
    PUBLIC_STREAM_URL,
    WebSocketTransport,
    _read_url,
    combined_messages,
    decode_combined_message,
)
from ordersim.connectors.binance.capture import (
    _capture_connection,
    _capture_with_reconnect,
    capture_binance,
    main,
)
from ordersim.connectors.binance.schema import (
    BinanceCaptureConfig,
    CaptureManifest,
    DepthSequenceTracker,
    TradeSequenceTracker,
)


def test_capture_config_names_the_highest_resolution_standard_streams(
    tmp_path: Path,
) -> None:
    config = BinanceCaptureConfig(
        output_dir=tmp_path,
        symbols=("btcusdt", "ETHUSDT"),
        duration_seconds=10,
        include_rpi=True,
    )

    assert config.symbols == ("BTCUSDT", "ETHUSDT")
    assert config.public_streams("BTCUSDT") == (
        "btcusdt@depth@100ms",
        "btcusdt@bookTicker",
        "btcusdt@rpiDepth@500ms",
    )
    assert config.market_streams("BTCUSDT") == ("btcusdt@aggTrade",)
    assert config.individual_trade_streams("BTCUSDT") == ("btcusdt@trade",)


@pytest.mark.parametrize(
    ("symbols", "duration", "limit", "delay", "message"),
    [
        ((), None, 1000, 2, "at least one symbol"),
        (("BTC-USDT",), None, 1000, 2, "letters and numbers"),
        (("BTCUSDT", "btcusdt"), None, 1000, 2, "unique"),
        (("BTCUSDT",), 0, 1000, 2, "positive"),
        (("BTCUSDT",), None, 200, 2, "snapshot_limit"),
        (("BTCUSDT",), None, 1000, -1, "non-negative"),
    ],
)
def test_capture_config_rejects_invalid_values(
    tmp_path: Path,
    symbols: tuple[str, ...],
    duration: float | None,
    limit: int,
    delay: float,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        BinanceCaptureConfig(
            output_dir=tmp_path,
            symbols=symbols,
            duration_seconds=duration,
            snapshot_limit=limit,
            reconnect_delay_seconds=delay,
        )


def test_depth_sequence_tracker_reports_discontinuity() -> None:
    tracker = DepthSequenceTracker()

    assert tracker.observe({"U": 10, "u": 12, "pu": 9}) is None
    assert tracker.observe({"U": 13, "u": 15, "pu": 12}) is None
    gap = tracker.observe({"U": 20, "u": 22, "pu": 19})

    assert gap is not None
    assert gap.as_dict() == {
        "expected_previous_update_id": 15,
        "reported_previous_update_id": 19,
        "first_update_id": 20,
        "final_update_id": 22,
    }


def test_depth_sequence_tracker_rejects_malformed_payloads() -> None:
    tracker = DepthSequenceTracker()

    with pytest.raises(ValueError, match="must be an integer"):
        tracker.observe({"U": "10", "u": 12, "pu": 9})
    with pytest.raises(ValueError, match="u < U"):
        tracker.observe({"U": 12, "u": 10, "pu": 9})


def test_trade_sequence_tracker_reports_missing_and_repeated_ids() -> None:
    tracker = TradeSequenceTracker()

    assert tracker.observe({"t": 100}) is None
    assert tracker.observe({"t": 101}) is None
    missing = tracker.observe({"t": 104})
    repeated = tracker.observe({"t": 104})

    assert missing is not None
    assert missing.as_dict() == {
        "expected_trade_id": 102,
        "received_trade_id": 104,
        "missing_count": 2,
    }
    assert repeated is not None
    assert repeated.as_dict() == {
        "expected_trade_id": 105,
        "received_trade_id": 104,
        "missing_count": 0,
    }


def test_trade_sequence_tracker_rejects_malformed_payload() -> None:
    with pytest.raises(ValueError, match="must be an integer"):
        TradeSequenceTracker().observe({"t": "100"})


def test_combined_message_decoder_preserves_exact_strings() -> None:
    stream, payload = decode_combined_message(
        b'{"stream":"btcusdt@aggTrade","data":{"p":"123.4500","q":"0.010"}}'
    )

    assert stream == "btcusdt@aggTrade"
    assert payload == {"p": "123.4500", "q": "0.010"}


@pytest.mark.parametrize(
    "raw",
    [
        "[]",
        '{"stream":1,"data":{}}',
        '{"stream":"btcusdt@depth@100ms","data":[]}',
    ],
)
def test_combined_message_decoder_rejects_non_envelopes(raw: str) -> None:
    with pytest.raises(ValueError):
        decode_combined_message(raw)


class FakeWebSocket:
    def __init__(self, messages: list[str]) -> None:
        self._messages = messages

    def __aiter__(self) -> AsyncIterator[str]:
        return self._iterate()

    async def _iterate(self) -> AsyncIterator[str]:
        for message in self._messages:
            yield message


def test_combined_messages_iterates_decoded_records() -> None:
    websocket = FakeWebSocket(
        ['{"stream":"btcusdt@bookTicker","data":{"b":"100","a":"101"}}']
    )

    async def collect() -> list[tuple[str, dict[str, object]]]:
        return [item async for item in combined_messages(websocket)]

    assert asyncio.run(collect()) == [
        ("btcusdt@bookTicker", {"b": "100", "a": "101"})
    ]


class FakeTransport:
    def __init__(self, messages: list[tuple[str, dict[str, object]]]) -> None:
        self.messages = messages
        self.connected_urls: list[str] = []
        self.snapshot_calls: list[tuple[str, int]] = []

    @asynccontextmanager
    async def connect(
        self, url: str
    ) -> AsyncIterator[AsyncIterator[tuple[str, dict[str, object]]]]:
        self.connected_urls.append(url)

        async def iterate() -> AsyncIterator[tuple[str, dict[str, object]]]:
            for message in self.messages:
                yield message

        yield iterate()

    async def depth_snapshot(self, symbol: str, limit: int) -> dict[str, object]:
        self.snapshot_calls.append((symbol, limit))
        return {
            "lastUpdateId": 9,
            "bids": [["100.0", "2.0"]],
            "asks": [["101.0", "3.0"]],
        }


class BlockingTransport(FakeTransport):
    def __init__(self) -> None:
        super().__init__([])
        self.connected = asyncio.Event()

    @asynccontextmanager
    async def connect(
        self, url: str
    ) -> AsyncIterator[AsyncIterator[tuple[str, dict[str, object]]]]:
        self.connected_urls.append(url)
        self.connected.set()

        async def wait_forever() -> AsyncIterator[tuple[str, dict[str, object]]]:
            await asyncio.Event().wait()
            yield "", {}

        yield wait_forever()


def _read_capture_records(output_dir: Path) -> list[dict[str, object]]:
    capture_file = next(output_dir.glob("*.jsonl.gz"))
    with gzip.open(capture_file, mode="rt", encoding="utf-8") as file:
        return [json.loads(line) for line in file]


def test_public_connection_records_snapshot_messages_and_gap(tmp_path: Path) -> None:
    config = BinanceCaptureConfig(
        output_dir=tmp_path,
        symbols=("BTCUSDT",),
        include_rpi=True,
    )
    transport = FakeTransport(
        [
            ("btcusdt@depth@100ms", {"U": 10, "u": 12, "pu": 9}),
            ("btcusdt@bookTicker", {"b": "100", "a": "101"}),
            ("btcusdt@depth@100ms", {"U": 20, "u": 22, "pu": 19}),
        ]
    )
    sink = RawCaptureSink(config)

    asyncio.run(
        _capture_connection(
            config=config,
            sink=sink,
            transport=transport,
            symbol="BTCUSDT",
            scope="public",
            connection_id="public-1",
        )
    )
    manifest = sink.close()
    records = _read_capture_records(tmp_path)

    assert transport.connected_urls == [
        PUBLIC_STREAM_URL
        + "btcusdt@depth@100ms/btcusdt@bookTicker/"
        + "btcusdt@rpiDepth@500ms"
    ]
    assert transport.snapshot_calls == [("BTCUSDT", 1000)]
    assert [record["kind"] for record in records] == [
        "connection_open",
        "depth_snapshot",
        "message",
        "message",
        "message",
        "sequence_gap",
    ]
    assert records[2]["payload"] == {"U": 10, "u": 12, "pu": 9}
    assert manifest.counts == {
        "connection_open": 1,
        "depth_snapshot": 1,
        "message": 3,
        "sequence_gap": 1,
    }


def test_market_connection_records_trades_without_snapshot(tmp_path: Path) -> None:
    config = BinanceCaptureConfig(output_dir=tmp_path, symbols=("BTCUSDT",))
    transport = FakeTransport(
        [("btcusdt@aggTrade", {"p": "100.1", "q": "0.25", "m": True})]
    )
    sink = RawCaptureSink(config)

    asyncio.run(
        _capture_connection(
            config=config,
            sink=sink,
            transport=transport,
            symbol="BTCUSDT",
            scope="market",
            connection_id="market-1",
        )
    )
    sink.close()

    assert transport.connected_urls == [MARKET_STREAM_URL + "btcusdt@aggTrade"]
    assert transport.snapshot_calls == []
    assert _read_capture_records(tmp_path)[1]["payload"] == {
        "p": "100.1",
        "q": "0.25",
        "m": True,
    }


def test_individual_trade_connection_records_ids_and_gap(tmp_path: Path) -> None:
    config = BinanceCaptureConfig(output_dir=tmp_path, symbols=("BTCUSDT",))
    transport = FakeTransport(
        [
            ("btcusdt@trade", {"t": 100, "p": "100.1", "q": "0.25"}),
            ("btcusdt@trade", {"t": 103, "p": "100.2", "q": "0.50"}),
        ]
    )
    sink = RawCaptureSink(config)

    asyncio.run(
        _capture_connection(
            config=config,
            sink=sink,
            transport=transport,
            symbol="BTCUSDT",
            scope="individual",
            connection_id="individual-1",
        )
    )
    sink.close()
    records = _read_capture_records(tmp_path)

    assert transport.connected_urls == [
        INDIVIDUAL_TRADE_STREAM_URL + "btcusdt@trade"
    ]
    assert transport.snapshot_calls == []
    assert [record["kind"] for record in records] == [
        "connection_open",
        "message",
        "message",
        "trade_gap",
    ]
    assert records[-1]["payload"] == {
        "expected_trade_id": 101,
        "received_trade_id": 103,
        "missing_count": 2,
    }


def test_capture_connection_rejects_unknown_scope(tmp_path: Path) -> None:
    config = BinanceCaptureConfig(output_dir=tmp_path, symbols=("BTCUSDT",))
    sink = RawCaptureSink(config)

    with pytest.raises(ValueError, match="unsupported Binance capture scope"):
        asyncio.run(
            _capture_connection(
                config=config,
                sink=sink,
                transport=FakeTransport([]),
                symbol="BTCUSDT",
                scope="unknown",
                connection_id="unknown-1",
            )
        )
    sink.close()


def test_websocket_transport_uses_injected_network_functions() -> None:
    calls: list[tuple[str, int, int]] = []

    @asynccontextmanager
    async def fake_connect(
        url: str, *, open_timeout: int, ping_timeout: int
    ) -> AsyncIterator[FakeWebSocket]:
        calls.append((url, open_timeout, ping_timeout))
        yield FakeWebSocket(
            ['{"stream":"btcusdt@aggTrade","data":{"p":"100","q":"1"}}']
        )

    def fake_read_url(url: str) -> bytes:
        assert "symbol=BTCUSDT" in url
        assert "limit=1000" in url
        return b'{"lastUpdateId":9,"bids":[],"asks":[]}'

    transport = WebSocketTransport(connect=fake_connect, read_url=fake_read_url)

    async def exercise() -> tuple[list[tuple[str, dict[str, object]]], object]:
        async with transport.connect("wss://example") as messages:
            received = [message async for message in messages]
        snapshot = await transport.depth_snapshot("BTCUSDT", 1000)
        return received, snapshot

    messages, snapshot = asyncio.run(exercise())

    assert calls == [("wss://example", 20, 20)]
    assert messages == [("btcusdt@aggTrade", {"p": "100", "q": "1"})]
    assert snapshot == {"lastUpdateId": 9, "bids": [], "asks": []}


def test_websocket_transport_rejects_non_object_snapshot() -> None:
    transport = WebSocketTransport(
        connect=lambda *args, **kwargs: None,
        read_url=lambda url: b"[]",
    )

    with pytest.raises(ValueError, match="JSON object"):
        asyncio.run(transport.depth_snapshot("BTCUSDT", 1000))


def test_websocket_transport_loads_optional_dependency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_import = builtins.__import__
    sentinel_connect = object()

    def fake_import(
        name: str,
        globals: object = None,
        locals: object = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> object:
        if name == "websockets.asyncio.client":
            return SimpleNamespace(connect=sentinel_connect)
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    transport = WebSocketTransport()

    assert transport._connect is sentinel_connect


def test_websocket_transport_explains_missing_optional_dependency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_import = builtins.__import__

    def fake_import(
        name: str,
        globals: object = None,
        locals: object = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> object:
        if name == "websockets.asyncio.client":
            raise ImportError("not installed")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(RuntimeError, match=r"ordersim\[binance\]"):
        WebSocketTransport()


def test_read_url_uses_ordersim_user_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponse:
        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return b'{"ok":true}'

    def fake_urlopen(request: object, *, timeout: int) -> FakeResponse:
        assert request.get_header("User-agent") == "ordersim"
        assert timeout == 20
        return FakeResponse()

    monkeypatch.setattr(transport_module.urllib.request, "urlopen", fake_urlopen)

    assert _read_url("https://example.test") == b'{"ok":true}'


def test_sink_writes_manifest_with_capture_files(tmp_path: Path) -> None:
    config = BinanceCaptureConfig(output_dir=tmp_path, symbols=("BTCUSDT",))
    sink = RawCaptureSink(config)

    asyncio.run(
        sink.write(
            kind="message",
            scope="market",
            symbol="BTCUSDT",
            connection_id="one",
            stream="btcusdt@aggTrade",
            payload={"p": "100.00000000", "q": "1.500"},
        )
    )
    manifest = sink.close()
    manifest_file = next(tmp_path.glob("manifest-*.json"))
    stored_manifest = json.loads(manifest_file.read_text(encoding="utf-8"))

    assert manifest.symbols == ("BTCUSDT",)
    assert manifest.counts == {"message": 1}
    assert stored_manifest["files"] == list(manifest.files)
    assert _read_capture_records(tmp_path)[0]["payload"] == {
        "p": "100.00000000",
        "q": "1.500",
    }


def test_sink_can_close_without_any_messages(tmp_path: Path) -> None:
    config = BinanceCaptureConfig(output_dir=tmp_path, symbols=("BTCUSDT",))

    manifest = RawCaptureSink(config).close()

    assert manifest.counts == {}
    assert manifest.files == ()


def test_sink_rotates_at_hour_boundary(tmp_path: Path) -> None:
    config = BinanceCaptureConfig(output_dir=tmp_path, symbols=("BTCUSDT",))
    sink = RawCaptureSink(config)

    sink._rotate(0)
    sink._rotate(3_600_000_000_000)
    manifest = sink.close()

    assert len(manifest.files) == 2


def test_finite_capture_closes_connections_and_writes_manifest(
    tmp_path: Path,
) -> None:
    config = BinanceCaptureConfig(
        output_dir=tmp_path,
        symbols=("BTCUSDT",),
        duration_seconds=0.01,
    )
    transport = BlockingTransport()

    manifest = asyncio.run(capture_binance(config, transport=transport))

    assert manifest.counts["connection_open"] == 3
    assert manifest.counts["depth_snapshot"] == 1
    assert len(transport.connected_urls) == 3
    assert next(tmp_path.glob("manifest-*.json")).exists()


def test_cancelled_capture_still_writes_manifest(tmp_path: Path) -> None:
    config = BinanceCaptureConfig(output_dir=tmp_path, symbols=("BTCUSDT",))
    transport = BlockingTransport()

    async def exercise() -> None:
        task = asyncio.create_task(capture_binance(config, transport=transport))
        await transport.connected.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(exercise())

    assert next(tmp_path.glob("manifest-*.json")).exists()


def test_reconnect_loop_records_connection_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = BinanceCaptureConfig(
        output_dir=tmp_path,
        symbols=("BTCUSDT",),
        reconnect_delay_seconds=0,
    )
    sink = RawCaptureSink(config)
    attempts = 0
    second_attempt = asyncio.Event()

    async def fake_capture_connection(**kwargs: object) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ConnectionError("test disconnect")
        second_attempt.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(
        capture_module,
        "_capture_connection",
        fake_capture_connection,
    )

    async def exercise() -> None:
        task = asyncio.create_task(
            _capture_with_reconnect(
                config=config,
                sink=sink,
                transport=FakeTransport([]),
                symbol="BTCUSDT",
                scope="public",
            )
        )
        await second_attempt.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(exercise())
    sink.close()
    records = _read_capture_records(tmp_path)

    assert records[0]["kind"] == "connection_error"
    assert records[0]["payload"] == {
        "error_type": "ConnectionError",
        "message": "test disconnect",
    }


def test_main_builds_capture_config_and_reports_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    received: list[BinanceCaptureConfig] = []

    async def fake_capture(config: BinanceCaptureConfig) -> CaptureManifest:
        received.append(config)
        return CaptureManifest(
            schema_version=1,
            run_id="run-one",
            started_at_ns=1,
            ended_at_ns=2,
            symbols=config.symbols,
            include_rpi=config.include_rpi,
            counts={"message": 3},
            files=("one.jsonl.gz",),
        )

    monkeypatch.setattr(capture_module, "capture_binance", fake_capture)

    main(
        [
            str(tmp_path),
            "--symbol",
            "BTCUSDT",
            "--duration-hours",
            "2",
            "--include-rpi",
        ]
    )

    assert received[0].duration_seconds == 7200
    assert received[0].include_rpi is True
    assert capsys.readouterr().out == "capture run-one complete: 3 records\n"


def test_main_handles_keyboard_interrupt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def interrupt(coroutine: object) -> None:
        coroutine.close()
        raise KeyboardInterrupt

    monkeypatch.setattr(capture_module.asyncio, "run", interrupt)

    assert main([str(tmp_path), "--symbol", "BTCUSDT"]) is None


def test_module_entry_point_calls_main(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[bool] = []
    monkeypatch.setattr(capture_module, "main", lambda: called.append(True))

    runpy.run_module("ordersim.connectors.binance.__main__", run_name="__main__")

    assert called == [True]
