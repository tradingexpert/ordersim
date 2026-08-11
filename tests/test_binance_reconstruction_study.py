import gzip
import json
from decimal import Decimal
from pathlib import Path

import pytest

from ordersim.connectors.binance import (
    BinanceCaptureSource,
)
from ordersim.connectors.binance.reconstruction_study import (
    BinanceReconstructionStudyConfig,
    main,
    run_binance_reconstruction_study,
)


def row(
    *,
    kind: str,
    payload: dict[str, object],
    received_at_ns: int,
    stream: str | None = None,
    scope: str = "public",
    connection_id: str = "depth-1",
    symbol: str = "BTCUSDT",
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "received_at_ns": received_at_ns,
        "received_monotonic_ns": received_at_ns + 1,
        "kind": kind,
        "scope": scope,
        "symbol": symbol,
        "connection_id": connection_id,
        "stream": stream,
        "payload": payload,
    }


def study_rows() -> list[dict[str, object]]:
    return [
        row(
            kind="message",
            stream="btcusdt@depth@100ms",
            received_at_ns=80_000_000,
            payload={
                "e": "depthUpdate",
                "E": 80,
                "T": 80,
                "s": "BTCUSDT",
                "U": 80,
                "u": 80,
                "pu": 79,
                "b": [],
                "a": [],
            },
        ),
        row(
            kind="depth_snapshot",
            received_at_ns=90_000_000,
            payload={
                "lastUpdateId": 100,
                "bids": [["100", "10"]],
                "asks": [["101", "8"]],
            },
        ),
        row(
            kind="message",
            stream="btcusdt@depth@100ms",
            received_at_ns=95_000_000,
            payload={
                "e": "depthUpdate",
                "E": 95,
                "T": 95,
                "s": "BTCUSDT",
                "U": 99,
                "u": 99,
                "pu": 98,
                "b": [],
                "a": [],
            },
        ),
        row(
            kind="message",
            stream="btcusdt@depth@100ms",
            received_at_ns=101_000_000,
            payload={
                "e": "depthUpdate",
                "E": 100,
                "T": 100,
                "s": "BTCUSDT",
                "U": 100,
                "u": 100,
                "pu": 99,
                "b": [],
                "a": [],
            },
        ),
        row(
            kind="message",
            scope="market",
            connection_id="trades-1",
            stream="btcusdt@trade",
            received_at_ns=106_000_000,
            payload={
                "e": "trade",
                "E": 105,
                "T": 105,
                "s": "BTCUSDT",
                "t": 700,
                "p": "100",
                "q": "4",
                "m": True,
            },
        ),
        row(
            kind="message",
            scope="market",
            connection_id="trades-1",
            stream="btcusdt@trade",
            received_at_ns=107_000_000,
            payload={
                "e": "trade",
                "E": 106,
                "T": 106,
                "s": "BTCUSDT",
                "t": 701,
                "p": "0",
                "q": "0",
                "m": False,
                "X": "NA",
            },
        ),
        row(
            kind="message",
            scope="market",
            connection_id="trades-1",
            stream="btcusdt@trade",
            received_at_ns=108_000_000,
            payload={
                "e": "trade",
                "E": 107,
                "T": 107,
                "s": "BTCUSDT",
                "t": 700,
                "p": "100",
                "q": "4",
                "m": True,
            },
        ),
        row(
            kind="message",
            stream="btcusdt@depth@100ms",
            received_at_ns=111_000_000,
            payload={
                "e": "depthUpdate",
                "E": 110,
                "T": 110,
                "s": "BTCUSDT",
                "U": 101,
                "u": 101,
                "pu": 100,
                "b": [["100", "9"]],
                "a": [],
            },
        ),
        row(
            kind="message",
            stream="btcusdt@bookTicker",
            received_at_ns=112_000_000,
            payload={
                "e": "bookTicker",
                "E": 110,
                "T": 110,
                "s": "BTCUSDT",
                "u": 101,
                "b": "100",
                "B": "9",
                "a": "101",
                "A": "8",
            },
        ),
    ]


def write_capture(tmp_path: Path, rows: list[dict[str, object]]) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "binance-run-20260808T170000Z.jsonl.gz"
    with gzip.open(path, mode="wt", encoding="utf-8") as file:
        for capture_row in rows:
            file.write(json.dumps(capture_row) + "\n")
    return path


def test_study_aligns_trades_and_compares_named_reconstructions(
    tmp_path: Path,
) -> None:
    capture = write_capture(tmp_path, study_rows())
    source = BinanceCaptureSource((capture,))

    report = run_binance_reconstruction_study(
        source,
        BinanceReconstructionStudyConfig(
            symbol="btcusdt",
            quantity_step=Decimal("1"),
        ),
    )

    assert report.symbol == "BTCUSDT"
    assert report.depth_snapshots == 1
    assert len(report.segments) == 1
    assert report.exact_book_ticker_matches == 1
    assert report.exact_book_ticker_mismatches == 0
    assert report.stale_depth_updates == 1
    assert report.zero_value_trade_messages == 1
    assert report.duplicate_trades == 1
    assert report.max_trade_receive_delay_ns == 1_000_000
    assert report.late_trades == 0
    assert report.unassigned_trades == 0

    conservative = report.totals_by_policy["queue-conservative"]
    optimistic = report.totals_by_policy["queue-optimistic"]
    assert conservative.depth_updates == optimistic.depth_updates == 2
    assert conservative.trade_units == optimistic.trade_units == 4
    assert conservative.inferred_add_units == optimistic.inferred_add_units == 3
    assert conservative.pre_trade_add_units == 3
    assert optimistic.pre_trade_add_units == 0


def test_study_report_is_an_explicit_model_manifest(tmp_path: Path) -> None:
    write_capture(tmp_path, study_rows())
    report = run_binance_reconstruction_study(
        BinanceCaptureSource.from_directory(tmp_path),
        BinanceReconstructionStudyConfig(
            symbol="BTCUSDT",
            quantity_step=Decimal("1"),
            policies=("queue-conservative",),
            until_received_at_ns=112_000_000,
        ),
    )

    manifest = report.as_dict()

    assert manifest["model"] == "binance-virtual-mbo-minimum-flow-v1"
    assert manifest["alignment"] == "exchange-transaction-time"
    assert manifest["quantity_step"] == "1"
    assert manifest["until_received_at_ns"] == 112_000_000
    assert manifest["policies"] == ["queue-conservative"]


def test_capture_source_cutoff_stops_before_later_rows(tmp_path: Path) -> None:
    capture = write_capture(tmp_path, study_rows())
    source = BinanceCaptureSource((capture,))

    observations = tuple(source.observations(until_received_at_ns=106_000_000))

    assert len(observations) == 5
    assert observations[-1].received_at_ns == 106_000_000
    assert tuple(source.observations(symbol="ETHUSDT")) == ()


@pytest.mark.parametrize(
    ("changed", "message"),
    [
        ({"symbol": "  "}, "symbol"),
        ({"quantity_step": Decimal("0")}, "quantity_step"),
        ({"policies": ()}, "at least one"),
        (
            {"policies": ("queue-conservative", "queue-conservative")},
            "unique",
        ),
        ({"reorder_buffer_ns": -1}, "non-negative"),
    ],
)
def test_study_configuration_rejects_ambiguous_inputs(
    changed: dict[str, object],
    message: str,
) -> None:
    values: dict[str, object] = {
        "symbol": "BTCUSDT",
        "quantity_step": Decimal("1"),
    }
    values.update(changed)

    with pytest.raises(ValueError, match=message):
        BinanceReconstructionStudyConfig(**values)  # type: ignore[arg-type]


def test_study_marks_sequence_breaks_and_ticker_mismatches(tmp_path: Path) -> None:
    rows = study_rows()
    depth_payload = rows[-2]["payload"]
    assert isinstance(depth_payload, dict)
    depth_payload["pu"] = 999
    capture = write_capture(tmp_path / "broken", rows)

    broken = run_binance_reconstruction_study(
        BinanceCaptureSource((capture,)),
        BinanceReconstructionStudyConfig(
            symbol="BTCUSDT",
            quantity_step=Decimal("1"),
        ),
    )

    assert broken.broken_depth_segments == 1

    rows = study_rows()
    ticker_payload = rows[-1]["payload"]
    assert isinstance(ticker_payload, dict)
    ticker_payload["B"] = "10"
    capture = write_capture(tmp_path / "mismatch", rows)
    mismatch = run_binance_reconstruction_study(
        BinanceCaptureSource((capture,)),
        BinanceReconstructionStudyConfig(
            symbol="BTCUSDT",
            quantity_step=Decimal("1"),
        ),
    )

    assert mismatch.exact_book_ticker_mismatches == 1


def test_study_ignores_other_symbols_and_depth_connections(tmp_path: Path) -> None:
    rows = study_rows()
    rows.insert(
        0,
        row(
            kind="message",
            symbol="ETHUSDT",
            connection_id="eth-depth",
            stream="ethusdt@bookTicker",
            received_at_ns=70_000_000,
            payload={
                "e": "bookTicker",
                "E": 70,
                "T": 70,
                "s": "ETHUSDT",
                "u": 1,
                "b": "10",
                "B": "1",
                "a": "11",
                "A": "1",
            },
        ),
    )
    rows.insert(
        3,
        row(
            kind="message",
            connection_id="other-depth",
            stream="btcusdt@depth@100ms",
            received_at_ns=92_000_000,
            payload={
                "e": "depthUpdate",
                "E": 92,
                "T": 92,
                "s": "BTCUSDT",
                "U": 100,
                "u": 100,
                "pu": 99,
                "b": [],
                "a": [],
            },
        ),
    )
    capture = write_capture(tmp_path, rows)

    report = run_binance_reconstruction_study(
        BinanceCaptureSource((capture,)),
        BinanceReconstructionStudyConfig(
            symbol="BTCUSDT",
            quantity_step=Decimal("1"),
        ),
    )

    assert report.observations == len(rows) - 1
    assert len(report.segments) == 1


def test_study_rejects_an_update_that_cannot_bridge_snapshot(tmp_path: Path) -> None:
    rows = study_rows()
    bridge_payload = rows[3]["payload"]
    assert isinstance(bridge_payload, dict)
    bridge_payload["U"] = 101
    bridge_payload["u"] = 101
    capture = write_capture(tmp_path, rows)

    report = run_binance_reconstruction_study(
        BinanceCaptureSource((capture,)),
        BinanceReconstructionStudyConfig(
            symbol="BTCUSDT",
            quantity_step=Decimal("1"),
        ),
    )

    assert report.broken_depth_segments == 1
    assert report.segments == ()


def test_study_rejects_ticker_quantity_that_cannot_be_scaled(tmp_path: Path) -> None:
    rows = study_rows()
    ticker_payload = rows[-1]["payload"]
    assert isinstance(ticker_payload, dict)
    ticker_payload["B"] = "9.5"
    capture = write_capture(tmp_path, rows)

    with pytest.raises(ValueError, match="not divisible"):
        run_binance_reconstruction_study(
            BinanceCaptureSource((capture,)),
            BinanceReconstructionStudyConfig(
                symbol="BTCUSDT",
                quantity_step=Decimal("1"),
            ),
        )


def test_study_counts_late_and_unassigned_trades(tmp_path: Path) -> None:
    rows = study_rows()
    rows.append(
        row(
            kind="message",
            scope="market",
            connection_id="trades-1",
            stream="btcusdt@trade",
            received_at_ns=120_000_000,
            payload={
                "e": "trade",
                "E": 109,
                "T": 109,
                "s": "BTCUSDT",
                "t": 702,
                "p": "100",
                "q": "1",
                "m": True,
            },
        )
    )
    rows.append(
        row(
            kind="message",
            scope="market",
            connection_id="trades-1",
            stream="btcusdt@trade",
            received_at_ns=121_000_000,
            payload={
                "e": "trade",
                "E": 115,
                "T": 115,
                "s": "BTCUSDT",
                "t": 703,
                "p": "100",
                "q": "1",
                "m": True,
            },
        )
    )
    capture = write_capture(tmp_path, rows)

    report = run_binance_reconstruction_study(
        BinanceCaptureSource((capture,)),
        BinanceReconstructionStudyConfig(
            symbol="BTCUSDT",
            quantity_step=Decimal("1"),
            reorder_buffer_ns=0,
        ),
    )

    assert report.late_trades == 1
    assert report.max_late_trade_lag_ns == 1_000_000
    assert report.max_trade_receive_delay_ns == 11_000_000
    assert report.unassigned_trades == 1


def test_study_cli_writes_json_or_stdout(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    write_capture(tmp_path, study_rows())
    output = tmp_path / "reports" / "study.json"
    common = [
        str(tmp_path),
        "--symbol",
        "BTCUSDT",
        "--quantity-step",
        "1",
        "--policy",
        "queue-conservative",
    ]

    main(common)
    assert '"model": "binance-virtual-mbo-minimum-flow-v1"' in capsys.readouterr().out

    main([*common, "--output", str(output)])
    assert json.loads(output.read_text(encoding="utf-8"))["symbol"] == "BTCUSDT"
