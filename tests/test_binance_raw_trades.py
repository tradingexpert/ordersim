import asyncio
import gzip
import json
import runpy
import sys
from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

import ordersim.connectors.binance._recent_trades as recent_trades_module
import ordersim.connectors.binance.raw_trades as raw_trades_module
from ordersim.connectors.binance._recent_trades import (
    HttpRecentTradesClient,
    RawTradeCursor,
    RecentTradesBatch,
    _fetch_url,
)
from ordersim.connectors.binance._storage import RawCaptureSink
from ordersim.connectors.binance.l2 import BinanceRawTrade
from ordersim.connectors.binance.raw_trades import (
    _poll_symbol,
    _record_batch,
    capture_binance_raw_trades,
    main,
)
from ordersim.connectors.binance.schema import BinanceRawTradeCaptureConfig
from ordersim.connectors.binance.source import BinanceCaptureSource


def raw_trade(trade_id: int) -> dict[str, object]:
    return {
        "id": trade_id,
        "price": "63893.80",
        "qty": "0.001",
        "quoteQty": "63.89",
        "time": 1_785_273_611_946 + trade_id,
        "isBuyerMaker": False,
        "isRPITrade": trade_id % 2 == 0,
    }


def batch(
    *trade_ids: int,
    used_weight_1m: int | None = 25,
) -> RecentTradesBatch:
    return RecentTradesBatch(
        trades=tuple(raw_trade(trade_id) for trade_id in trade_ids),
        request_started_at_ns=100,
        request_finished_at_ns=200,
        used_weight_1m=used_weight_1m,
    )


def read_records(output_dir: Path) -> list[dict[str, object]]:
    capture_file = next(output_dir.glob("*.jsonl.gz"))
    with gzip.open(capture_file, mode="rt", encoding="utf-8") as file:
        return [json.loads(line) for line in file]


def test_raw_trade_config_normalizes_symbols_and_budgets_weight(
    tmp_path: Path,
) -> None:
    config = BinanceRawTradeCaptureConfig(
        output_dir=tmp_path,
        symbols=("btcusdt", "ETHUSDT"),
        duration_seconds=60,
        poll_interval_seconds=0.5,
    )

    assert config.symbols == ("BTCUSDT", "ETHUSDT")
    assert config.include_rpi is False
    assert config.estimated_request_weight_per_minute == 1200


@pytest.mark.parametrize(
    ("symbols", "duration", "interval", "limit", "delay", "message"),
    [
        ((), None, 2, 1000, 2, "at least one symbol"),
        (("BTC-USDT",), None, 2, 1000, 2, "letters and numbers"),
        (("BTCUSDT", "btcusdt"), None, 2, 1000, 2, "unique"),
        (("BTCUSDT",), 0, 2, 1000, 2, "positive"),
        (("BTCUSDT",), None, 0, 1000, 2, "positive"),
        (("BTCUSDT",), None, 2, 0, 2, "between 1 and 1000"),
        (("BTCUSDT",), None, 2, 1001, 2, "between 1 and 1000"),
        (("BTCUSDT",), None, 2, 1000, -1, "non-negative"),
        (
            ("BTCUSDT", "ETHUSDT", "BNBUSDT"),
            None,
            0.25,
            1000,
            2,
            "weight/minute budget",
        ),
    ],
)
def test_raw_trade_config_rejects_invalid_values(
    tmp_path: Path,
    symbols: tuple[str, ...],
    duration: float | None,
    interval: float,
    limit: int,
    delay: float,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        BinanceRawTradeCaptureConfig(
            output_dir=tmp_path,
            symbols=symbols,
            duration_seconds=duration,
            poll_interval_seconds=interval,
            request_limit=limit,
            retry_delay_seconds=delay,
        )


def test_http_client_preserves_individual_trade_payloads() -> None:
    requested_urls: list[str] = []

    def fake_fetch(url: str) -> tuple[bytes, Mapping[str, str]]:
        requested_urls.append(url)
        return (
            json.dumps([raw_trade(10), raw_trade(11)]).encode(),
            {"X-MBX-USED-WEIGHT-1M": "125"},
        )

    response = asyncio.run(
        HttpRecentTradesClient(fetch_url=fake_fetch).recent_trades("BTCUSDT", 1000)
    )

    assert "symbol=BTCUSDT" in requested_urls[0]
    assert "limit=1000" in requested_urls[0]
    assert response.trades == (raw_trade(10), raw_trade(11))
    assert response.used_weight_1m == 125
    assert response.request_finished_at_ns >= response.request_started_at_ns


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({}, "must be a list"),
        ([[]], "JSON object"),
        ([{"id": "1"}], "'id' must be an integer"),
        ([{**raw_trade(1), "time": True}], "'time' must be an integer"),
        ([{**raw_trade(1), "price": 1}], "'price' must be a string"),
        ([{**raw_trade(1), "isRPITrade": "false"}], "must be a boolean"),
    ],
)
def test_http_client_rejects_malformed_trade_payloads(
    payload: object,
    message: str,
) -> None:
    client = HttpRecentTradesClient(
        fetch_url=lambda url: (json.dumps(payload).encode(), {})
    )

    with pytest.raises(ValueError, match=message):
        asyncio.run(client.recent_trades("BTCUSDT", 1000))


def test_http_client_rejects_malformed_weight_header() -> None:
    client = HttpRecentTradesClient(
        fetch_url=lambda url: (
            json.dumps([raw_trade(1)]).encode(),
            {"x-mbx-used-weight-1m": "many"},
        )
    )

    with pytest.raises(ValueError, match="header"):
        asyncio.run(client.recent_trades("BTCUSDT", 1000))


def test_http_client_allows_missing_weight_header() -> None:
    client = HttpRecentTradesClient(
        fetch_url=lambda url: (json.dumps([raw_trade(1)]).encode(), {})
    )

    response = asyncio.run(client.recent_trades("BTCUSDT", 1000))

    assert response.used_weight_1m is None


def test_fetch_url_sets_user_agent_and_returns_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeResponse:
        headers = {"x-mbx-used-weight-1m": "25"}

        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return b"[]"

    def fake_urlopen(request: object, *, timeout: int) -> FakeResponse:
        assert request.get_header("User-agent") == "ordersim"
        assert timeout == 20
        return FakeResponse()

    monkeypatch.setattr(
        recent_trades_module.urllib.request,
        "urlopen",
        fake_urlopen,
    )

    body, headers = _fetch_url("https://example.test")

    assert body == b"[]"
    assert headers["x-mbx-used-weight-1m"] == "25"


def test_cursor_deduplicates_overlap_and_accepts_late_ids() -> None:
    cursor = RawTradeCursor()

    first = cursor.select((raw_trade(10), raw_trade(11), raw_trade(12)))
    delayed = cursor.select((raw_trade(11), raw_trade(12), raw_trade(14)))
    recovered = cursor.select(
        (raw_trade(12), raw_trade(13), raw_trade(14), raw_trade(15))
    )

    assert [trade["id"] for trade in first.trades] == [10, 11, 12]
    assert [trade["id"] for trade in delayed.trades] == [14]
    assert delayed.gap is None
    assert [trade["id"] for trade in recovered.trades] == [13, 15]
    assert recovered.gap is None
    assert cursor.last_trade_id == 15


def test_cursor_reports_gap_after_endpoint_window_moves_past_it() -> None:
    cursor = RawTradeCursor()

    cursor.select((raw_trade(10), raw_trade(11), raw_trade(13)))
    gap = cursor.select((raw_trade(13), raw_trade(14)))

    assert gap.gap is not None
    assert gap.gap.as_dict() == {
        "expected_trade_id": 12,
        "first_received_trade_id": 13,
        "missing_count": 1,
    }
    assert [trade["id"] for trade in gap.trades] == [14]
    assert cursor.last_trade_id == 14


def test_cursor_handles_empty_and_fully_stale_responses() -> None:
    cursor = RawTradeCursor()

    assert cursor.select(()).trades == ()
    cursor.select((raw_trade(10), raw_trade(11)))
    stale = cursor.select((raw_trade(8), raw_trade(9)))

    assert stale.trades == ()
    assert stale.gap is None
    assert cursor.last_trade_id == 11


def test_cursor_rejects_non_increasing_trade_ids() -> None:
    cursor = RawTradeCursor()

    with pytest.raises(ValueError, match="increasing IDs"):
        cursor.select((raw_trade(10), raw_trade(10)))


def test_record_batch_writes_poll_gap_and_exact_new_trades(tmp_path: Path) -> None:
    config = BinanceRawTradeCaptureConfig(
        output_dir=tmp_path,
        symbols=("BTCUSDT",),
    )
    sink = RawCaptureSink(config)
    cursor = RawTradeCursor()

    async def exercise() -> None:
        await _record_batch(
            sink=sink,
            symbol="BTCUSDT",
            connection_id="raw-1",
            cursor=cursor,
            batch=batch(10, 11),
        )
        await _record_batch(
            sink=sink,
            symbol="BTCUSDT",
            connection_id="raw-1",
            cursor=cursor,
            batch=batch(11, 13),
        )
        await _record_batch(
            sink=sink,
            symbol="BTCUSDT",
            connection_id="raw-1",
            cursor=cursor,
            batch=batch(13, 14),
        )

    asyncio.run(exercise())
    manifest = sink.close()
    records = read_records(tmp_path)

    assert [record["kind"] for record in records] == [
        "raw_trade_poll",
        "raw_trade",
        "raw_trade",
        "raw_trade_poll",
        "raw_trade",
        "raw_trade_poll",
        "raw_trade_gap",
        "raw_trade",
    ]
    assert records[-1]["payload"] == raw_trade(14)
    assert records[3]["payload"]["new_count"] == 1
    assert manifest.capture_type == "raw_trades"
    assert manifest.counts == {
        "raw_trade": 4,
        "raw_trade_gap": 1,
        "raw_trade_poll": 3,
    }


def test_capture_source_normalizes_individual_raw_trades(tmp_path: Path) -> None:
    config = BinanceRawTradeCaptureConfig(
        output_dir=tmp_path,
        symbols=("BTCUSDT",),
    )
    sink = RawCaptureSink(config)

    asyncio.run(
        _record_batch(
            sink=sink,
            symbol="BTCUSDT",
            connection_id="raw-1",
            cursor=RawTradeCursor(),
            batch=batch(10),
        )
    )
    manifest = sink.close()

    trade = next(
        BinanceCaptureSource.from_manifest(
            tmp_path / f"manifest-{manifest.run_id}.json"
        ).raw_trades()
    )

    assert trade == BinanceRawTrade(
        symbol="BTCUSDT",
        connection_id="raw-1",
        received_at_ns=trade.received_at_ns,
        received_monotonic_ns=trade.received_monotonic_ns,
        trade_id=10,
        price=Decimal("63893.80"),
        quantity=Decimal("0.001"),
        quote_quantity=Decimal("63.89"),
        trade_time_ns=1_785_273_611_956_000_000,
        buyer_is_maker=False,
        is_rpi_trade=True,
    )


def test_capture_source_handles_file_without_raw_trades(tmp_path: Path) -> None:
    capture_path = tmp_path / "empty.jsonl.gz"
    with gzip.open(capture_path, mode="wt", encoding="utf-8"):
        pass

    assert tuple(BinanceCaptureSource((capture_path,)).raw_trades()) == ()


class FakeRecentTradesClient:
    def __init__(self, responses: dict[str, RecentTradesBatch]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, int]] = []

    async def recent_trades(
        self,
        symbol: str,
        limit: int,
    ) -> RecentTradesBatch:
        self.calls.append((symbol, limit))
        return self.responses[symbol]


def test_finite_capture_polls_each_symbol_and_writes_manifest(
    tmp_path: Path,
) -> None:
    config = BinanceRawTradeCaptureConfig(
        output_dir=tmp_path,
        symbols=("BTCUSDT", "ETHUSDT"),
        duration_seconds=0.01,
    )
    client = FakeRecentTradesClient(
        {
            "BTCUSDT": batch(10),
            "ETHUSDT": batch(20),
        }
    )

    manifest = asyncio.run(capture_binance_raw_trades(config, client=client))

    assert sorted(client.calls) == [("BTCUSDT", 1000), ("ETHUSDT", 1000)]
    assert manifest.counts == {"raw_trade": 2, "raw_trade_poll": 2}
    assert next(tmp_path.glob("manifest-*.json")).exists()


def test_poll_loop_records_errors_before_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = BinanceRawTradeCaptureConfig(
        output_dir=tmp_path,
        symbols=("BTCUSDT",),
        retry_delay_seconds=0,
    )
    sink = RawCaptureSink(config)
    second_attempt = asyncio.Event()
    attempts = 0

    class FailingClient:
        async def recent_trades(
            self,
            symbol: str,
            limit: int,
        ) -> RecentTradesBatch:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise ConnectionError("test failure")
            second_attempt.set()
            await asyncio.Event().wait()
            return batch()

    monkeypatch.setattr(
        raw_trades_module.uuid,
        "uuid4",
        lambda: SimpleNamespace(hex="raw-1"),
    )

    async def exercise() -> None:
        task = asyncio.create_task(
            _poll_symbol(
                config=config,
                sink=sink,
                client=FailingClient(),
                symbol="BTCUSDT",
            )
        )
        await second_attempt.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(exercise())
    sink.close()
    record = read_records(tmp_path)[0]

    assert record["kind"] == "raw_trade_poll_error"
    assert record["connection_id"] == "raw-1"
    assert record["payload"] == {
        "error_type": "ConnectionError",
        "message": "test failure",
        "last_trade_id": None,
    }


def test_cancelled_capture_still_writes_manifest(tmp_path: Path) -> None:
    config = BinanceRawTradeCaptureConfig(
        output_dir=tmp_path,
        symbols=("BTCUSDT",),
    )

    class BlockingClient:
        def __init__(self) -> None:
            self.started = asyncio.Event()

        async def recent_trades(
            self,
            symbol: str,
            limit: int,
        ) -> RecentTradesBatch:
            self.started.set()
            await asyncio.Event().wait()
            return batch()

    client = BlockingClient()

    async def exercise() -> None:
        task = asyncio.create_task(
            capture_binance_raw_trades(config, client=client)
        )
        await client.started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(exercise())

    assert next(tmp_path.glob("manifest-*.json")).exists()


def test_main_builds_config_and_reports_trade_count(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    observed: list[BinanceRawTradeCaptureConfig] = []

    async def fake_capture(
        config: BinanceRawTradeCaptureConfig,
    ) -> object:
        observed.append(config)
        return type(
            "Manifest",
            (),
            {"run_id": "run-1", "counts": {"raw_trade": 7}},
        )()

    monkeypatch.setattr(raw_trades_module, "capture_binance_raw_trades", fake_capture)

    main(
        [
            str(tmp_path),
            "--symbol",
            "BTCUSDT",
            "--duration-hours",
            "1.5",
            "--poll-interval-seconds",
            "2.5",
        ]
    )

    assert observed[0].duration_seconds == 5_400
    assert observed[0].poll_interval_seconds == 2.5
    assert "7 trades" in capsys.readouterr().out


def test_main_handles_keyboard_interrupt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def interrupted(config: BinanceRawTradeCaptureConfig) -> object:
        raise KeyboardInterrupt

    monkeypatch.setattr(raw_trades_module, "capture_binance_raw_trades", interrupted)

    main([str(tmp_path), "--symbol", "BTCUSDT"])


@pytest.mark.filterwarnings(
    "ignore:.*found in sys.modules.*:RuntimeWarning"
)
def test_module_entry_point_runs_main(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest = type(
        "Manifest",
        (),
        {"run_id": "run-1", "counts": {"raw_trade": 3}},
    )()

    def fake_run(coroutine: object) -> object:
        coroutine.close()
        return manifest

    monkeypatch.setattr(asyncio, "run", fake_run)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ordersim-binance-raw-trades",
            str(tmp_path),
            "--symbol",
            "BTCUSDT",
        ],
    )

    runpy.run_module(
        "ordersim.connectors.binance.raw_trades",
        run_name="__main__",
    )

    assert "3 trades" in capsys.readouterr().out
