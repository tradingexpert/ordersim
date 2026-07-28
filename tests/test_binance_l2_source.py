import gzip
import json
from decimal import Decimal
from pathlib import Path

import pytest

from ordersim.connectors.binance import (
    BinanceCaptureSource,
    BinanceDepthSnapshot,
    BinanceDepthUpdate,
    BinanceIndividualTrade,
    BinancePriceLevel,
    BinanceSequenceError,
)


def capture_row(
    *,
    kind: str,
    scope: str = "public",
    symbol: str = "BTCUSDT",
    connection_id: str = "public-1",
    stream: str | None = None,
    payload: object,
    received_at_ns: int = 1_000,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "received_at_ns": received_at_ns,
        "received_monotonic_ns": received_at_ns + 100,
        "kind": kind,
        "scope": scope,
        "symbol": symbol,
        "connection_id": connection_id,
        "stream": stream,
        "payload": payload,
    }


def standard_rows() -> list[dict[str, object]]:
    return [
        capture_row(
            kind="connection_open",
            payload={"streams": ["btcusdt@depth@100ms"]},
        ),
        capture_row(
            kind="depth_snapshot",
            payload={
                "lastUpdateId": 100,
                "bids": [["100.10", "2.500"]],
                "asks": [["100.20", "3.750"]],
            },
            received_at_ns=2_000,
        ),
        capture_row(
            kind="message",
            stream="btcusdt@depth@100ms",
            payload={
                "e": "depthUpdate",
                "E": 10,
                "T": 9,
                "s": "BTCUSDT",
                "U": 90,
                "u": 99,
                "pu": 89,
                "b": [["100.10", "2.000"]],
                "a": [],
            },
            received_at_ns=3_000,
        ),
        capture_row(
            kind="message",
            stream="btcusdt@depth@100ms",
            payload={
                "e": "depthUpdate",
                "E": 11,
                "T": 10,
                "s": "BTCUSDT",
                "U": 99,
                "u": 101,
                "pu": 99,
                "b": [["100.10", "1.500"], ["100.00", "0"]],
                "a": [["100.20", "3.000"]],
            },
            received_at_ns=4_000,
        ),
        capture_row(
            kind="message",
            stream="btcusdt@depth@100ms",
            payload={
                "e": "depthUpdate",
                "E": 12,
                "T": 11,
                "s": "BTCUSDT",
                "U": 102,
                "u": 103,
                "pu": 101,
                "b": [],
                "a": [["100.20", "2.250"]],
            },
            received_at_ns=5_000,
        ),
        capture_row(
            kind="message",
            stream="btcusdt@bookTicker",
            payload={
                "e": "bookTicker",
                "E": 12,
                "T": 11,
                "s": "BTCUSDT",
                "u": 103,
                "b": "100.10",
                "B": "1.500",
                "a": "100.20",
                "A": "2.250",
            },
            received_at_ns=5_100,
        ),
        capture_row(
            kind="message",
            stream="btcusdt@rpiDepth@500ms",
            payload={
                "e": "depthUpdate",
                "E": 12,
                "T": 11,
                "s": "BTCUSDT",
                "U": 200,
                "u": 201,
                "pu": 199,
                "b": [["100.10", "0.250"]],
                "a": [],
            },
            received_at_ns=5_200,
        ),
        capture_row(
            kind="connection_open",
            scope="market",
            connection_id="market-1",
            payload={"streams": ["btcusdt@aggTrade"]},
        ),
        capture_row(
            kind="message",
            scope="market",
            connection_id="market-1",
            stream="btcusdt@aggTrade",
            payload={
                "e": "aggTrade",
                "E": 13,
                "T": 12,
                "s": "BTCUSDT",
                "a": 500,
                "p": "100.20",
                "q": "1.250",
                "nq": "1.000",
                "f": 700,
                "l": 702,
                "m": True,
            },
            received_at_ns=6_000,
        ),
    ]


def write_capture(
    tmp_path: Path,
    rows: list[object],
    *,
    with_manifest: bool = False,
) -> tuple[Path, Path | None]:
    capture_path = tmp_path / "binance-run-20260728T100000Z.jsonl.gz"
    with gzip.open(capture_path, mode="wt", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, separators=(",", ":")) + "\n")

    if not with_manifest:
        return capture_path, None
    manifest_path = tmp_path / "manifest-run.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "run_id": "run",
                "files": [capture_path.name],
            }
        ),
        encoding="utf-8",
    )
    return capture_path, manifest_path


def test_source_normalizes_exact_depth_trade_and_ticker_records(
    tmp_path: Path,
) -> None:
    capture_path, _ = write_capture(tmp_path, standard_rows())
    source = BinanceCaptureSource((capture_path,))

    snapshots = tuple(source.depth_snapshots())
    depth = tuple(source.depth_updates())
    rpi_depth = tuple(source.depth_updates(stream_kind="rpi_depth"))
    trades = tuple(source.aggregate_trades())
    individual_trades = tuple(source.individual_trades())
    tickers = tuple(source.book_tickers())

    assert snapshots == (
        BinanceDepthSnapshot(
            symbol="BTCUSDT",
            connection_id="public-1",
            received_at_ns=2_000,
            received_monotonic_ns=2_100,
            last_update_id=100,
            bids=(
                BinancePriceLevel(
                    price=Decimal("100.10"),
                    quantity=Decimal("2.500"),
                ),
            ),
            asks=(
                BinancePriceLevel(
                    price=Decimal("100.20"),
                    quantity=Decimal("3.750"),
                ),
            ),
        ),
    )
    assert len(depth) == 3
    assert depth[1].event_time_ns == 11_000_000
    assert depth[1].transaction_time_ns == 10_000_000
    assert depth[1].bids[1].quantity == Decimal("0")
    assert rpi_depth[0].stream_kind == "rpi_depth"
    assert trades[0].price == Decimal("100.20")
    assert trades[0].quantity == Decimal("1.250")
    assert trades[0].normal_quantity == Decimal("1.000")
    assert trades[0].buyer_is_maker is True
    assert individual_trades == ()
    assert tickers[0].bid_price == Decimal("100.10")
    assert tickers[0].ask_quantity == Decimal("2.250")


def test_validated_depth_events_drop_stale_updates_and_bridge_snapshot(
    tmp_path: Path,
) -> None:
    capture_path, _ = write_capture(tmp_path, standard_rows())
    source = BinanceCaptureSource((capture_path,))

    events = tuple(source.validated_depth_events())

    assert isinstance(events[0], BinanceDepthSnapshot)
    assert [event.final_update_id for event in events[1:]] == [101, 103]
    assert all(isinstance(event, BinanceDepthUpdate) for event in events[1:])


def test_source_can_be_built_from_completed_manifest(tmp_path: Path) -> None:
    capture_path, manifest_path = write_capture(
        tmp_path,
        standard_rows(),
        with_manifest=True,
    )

    source = BinanceCaptureSource.from_manifest(manifest_path)

    assert source.files == (capture_path,)
    assert len(tuple(source.envelopes())) == len(standard_rows())


def test_aggregate_trade_preserves_missing_normal_quantity(tmp_path: Path) -> None:
    rows = standard_rows()
    trade_payload = rows[-1]["payload"]
    assert isinstance(trade_payload, dict)
    trade_payload.pop("nq")
    capture_path, _ = write_capture(tmp_path, rows)

    trade = next(BinanceCaptureSource((capture_path,)).aggregate_trades())

    assert trade.normal_quantity is None


def test_source_normalizes_individual_websocket_trade(tmp_path: Path) -> None:
    row = capture_row(
        kind="message",
        scope="market",
        connection_id="individual-1",
        stream="btcusdt@trade",
        payload={
            "e": "trade",
            "E": 20,
            "T": 19,
            "s": "BTCUSDT",
            "t": 700,
            "p": "100.20",
            "q": "0.125",
            "m": False,
            "X": "MARKET",
            "st": 1,
        },
        received_at_ns=21_000,
    )
    capture_path, _ = write_capture(tmp_path, [row])

    trades = tuple(BinanceCaptureSource((capture_path,)).individual_trades())

    assert trades == (
        BinanceIndividualTrade(
            symbol="BTCUSDT",
            connection_id="individual-1",
            event_time_ns=20_000_000,
            trade_time_ns=19_000_000,
            received_at_ns=21_000,
            received_monotonic_ns=21_100,
            trade_id=700,
            price=Decimal("100.20"),
            quantity=Decimal("0.125"),
            buyer_is_maker=False,
        ),
    )


def test_validated_depth_rejects_gap_after_bridge(tmp_path: Path) -> None:
    rows = standard_rows()
    payload = rows[4]["payload"]
    assert isinstance(payload, dict)
    payload["pu"] = 999
    capture_path, _ = write_capture(tmp_path, rows)

    with pytest.raises(BinanceSequenceError, match="expected pu=101, got 999"):
        tuple(BinanceCaptureSource((capture_path,)).validated_depth_events())


def test_validated_depth_rejects_update_before_snapshot(tmp_path: Path) -> None:
    rows = standard_rows()
    rows.pop(1)
    capture_path, _ = write_capture(tmp_path, rows)

    with pytest.raises(BinanceSequenceError, match="before snapshot"):
        tuple(BinanceCaptureSource((capture_path,)).validated_depth_events())


def test_validated_depth_rejects_update_that_does_not_bridge_snapshot(
    tmp_path: Path,
) -> None:
    rows = standard_rows()
    payload = rows[3]["payload"]
    assert isinstance(payload, dict)
    payload["U"] = 101
    capture_path, _ = write_capture(tmp_path, rows)

    with pytest.raises(BinanceSequenceError, match="does not bridge"):
        tuple(BinanceCaptureSource((capture_path,)).validated_depth_events())


def test_capture_source_rejects_missing_or_empty_file_lists(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="at least one"):
        BinanceCaptureSource(())
    with pytest.raises(FileNotFoundError, match="do not exist"):
        BinanceCaptureSource((tmp_path / "missing.jsonl.gz",))


@pytest.mark.parametrize(
    ("manifest", "message"),
    [
        ([], "JSON object"),
        ({"schema_version": 2, "files": []}, "schema_version"),
        ({"schema_version": 1, "files": "one"}, "list of names"),
    ],
)
def test_manifest_validation(
    tmp_path: Path,
    manifest: object,
    message: str,
) -> None:
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        BinanceCaptureSource.from_manifest(path)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"schema_version": 2}, "schema_version"),
        ({"received_at_ns": "1"}, "received_at_ns"),
        ({"kind": "unknown"}, "unsupported value"),
        ({"scope": "unknown"}, "unsupported value"),
        ({"stream": 1}, "stream"),
        ({"payload": []}, "payload"),
    ],
)
def test_capture_envelope_validation_reports_file_and_line(
    tmp_path: Path,
    change: dict[str, object],
    message: str,
) -> None:
    row = standard_rows()[0]
    row.update(change)
    capture_path, _ = write_capture(tmp_path, [row])

    with pytest.raises(ValueError, match=rf":1:.*{message}"):
        tuple(BinanceCaptureSource((capture_path,)).envelopes())


def test_capture_envelope_must_be_an_object(tmp_path: Path) -> None:
    capture_path, _ = write_capture(tmp_path, [[]])

    with pytest.raises(ValueError, match="JSON object"):
        tuple(BinanceCaptureSource((capture_path,)).envelopes())


def test_normalization_rejects_payload_symbol_mismatch(tmp_path: Path) -> None:
    rows = standard_rows()
    payload = rows[-1]["payload"]
    assert isinstance(payload, dict)
    payload["s"] = "ETHUSDT"
    capture_path, _ = write_capture(tmp_path, rows)

    with pytest.raises(ValueError, match="does not match"):
        tuple(BinanceCaptureSource((capture_path,)).aggregate_trades())


@pytest.mark.parametrize(
    ("row_index", "field", "value", "reader", "message"),
    [
        (1, "bids", "not-levels", "snapshot", "must be a list"),
        (1, "bids", [["100"]], "snapshot", "invalid level"),
        (-1, "s", "", "trade", "non-empty string"),
        (-1, "m", "true", "trade", "boolean"),
        (-1, "p", 100, "trade", "decimal strings"),
        (-1, "p", "not-a-decimal", "trade", "invalid decimal"),
    ],
)
def test_normalization_rejects_malformed_vendor_fields(
    tmp_path: Path,
    row_index: int,
    field: str,
    value: object,
    reader: str,
    message: str,
) -> None:
    rows = standard_rows()
    payload = rows[row_index]["payload"]
    assert isinstance(payload, dict)
    payload[field] = value
    capture_path, _ = write_capture(tmp_path, rows)
    source = BinanceCaptureSource((capture_path,))

    records = (
        source.depth_snapshots() if reader == "snapshot" else source.aggregate_trades()
    )
    with pytest.raises(ValueError, match=message):
        tuple(records)


@pytest.mark.parametrize(
    ("price", "quantity", "message"),
    [
        (Decimal("0"), Decimal("1"), "price"),
        (Decimal("1"), Decimal("-1"), "quantity"),
    ],
)
def test_price_level_rejects_invalid_values(
    price: Decimal,
    quantity: Decimal,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        BinancePriceLevel(price=price, quantity=quantity)
