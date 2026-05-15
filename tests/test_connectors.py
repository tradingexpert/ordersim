import builtins
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ordersim import (
    CsvSource,
    DatabentoMboSource,
    DataSource,
    InMemorySource,
    InstrumentSpec,
    MBOEvent,
    ParquetSource,
    Replay,
    normalize_events,
    write_parquet,
)
from ordersim.connectors import parquet as parquet_connector
from ordersim.fixtures.synthetic import SyntheticSource


def gc_spec() -> InstrumentSpec:
    return InstrumentSpec(
        symbol="GC",
        tick_size=Decimal("0.10"),
        point_value=Decimal("100"),
        commission_per_contract=Decimal("2.50"),
    )


class TinySource:
    def __init__(self, events: Iterable[MBOEvent]) -> None:
        self._events = tuple(events)

    def events(self) -> tuple[MBOEvent, ...]:
        return self._events


@dataclass(frozen=True, slots=True)
class DatabentoRecord:
    ts_event: int
    ts_recv: int
    action: str
    side: str
    price: int
    size: int
    order_id: int
    flags: int


def test_in_memory_source_returns_stored_events() -> None:
    events = SyntheticSource.small_mbo()
    source = InMemorySource.from_events("small-mbo", events)

    assert source.name == "small-mbo"
    assert source.events() == events


def test_normalize_events_accepts_plain_iterables() -> None:
    events = SyntheticSource.small_mbo()

    assert normalize_events(events) == events


def test_normalize_events_accepts_data_sources() -> None:
    source: DataSource = TinySource(SyntheticSource.small_mbo())

    assert normalize_events(source) == SyntheticSource.small_mbo()


def test_replay_accepts_data_source() -> None:
    source = InMemorySource.from_events("small-mbo", SyntheticSource.small_mbo())
    replay = Replay(data=source, instrument=gc_spec())

    def strategy(gateway) -> None:
        gateway.advance_to(1_000_000_100)
        gateway.place_market(side="buy", size=1)

    result = replay.run(strategy)

    assert result.final_position == 1
    assert result.fills[0].price == Decimal("101.0")


def write_csv(path: Path, rows: list[str]) -> Path:
    path.write_text("\n".join(rows) + "\n")
    return path


def write_raw_parquet(path: Path, rows: list[dict[str, object]]) -> Path:
    pq.write_table(pa.Table.from_pylist(rows), path)
    return path


def test_csv_source_reads_normalized_mbo_events(tmp_path: Path) -> None:
    path = write_csv(
        tmp_path / "events.csv",
        [
            "ts_ns,action,side,price,size,order_id,ignored",
            "1,add,ask,101.0,3,10,extra",
            "2,trade,ask,101.0,1,10,extra",
        ],
    )

    source = CsvSource(path)

    assert source.events() == (
        MBOEvent(
            ts_ns=1,
            action="add",
            side="ask",
            price=Decimal("101.0"),
            size=3,
            order_id=10,
        ),
        MBOEvent(
            ts_ns=2,
            action="trade",
            side="ask",
            price=Decimal("101.0"),
            size=1,
            order_id=10,
        ),
    )


def test_replay_accepts_csv_source(tmp_path: Path) -> None:
    path = write_csv(
        tmp_path / "events.csv",
        [
            "ts_ns,action,side,price,size,order_id",
            "1,add,ask,101.0,2,10",
        ],
    )
    replay = Replay(data=CsvSource(path), instrument=gc_spec())

    def strategy(gateway) -> None:
        gateway.advance_to(1)
        gateway.place_market(side="buy", size=1)

    result = replay.run(strategy)

    assert result.final_position == 1
    assert result.fills[0].price == Decimal("101.0")


def test_csv_source_requires_canonical_columns(tmp_path: Path) -> None:
    path = write_csv(
        tmp_path / "events.csv",
        [
            "ts_ns,action,side,price,size",
            "1,add,ask,101.0,2",
        ],
    )

    with pytest.raises(ValueError, match="missing required columns"):
        CsvSource(path).events()


def test_csv_source_reports_invalid_rows(tmp_path: Path) -> None:
    path = write_csv(
        tmp_path / "events.csv",
        [
            "ts_ns,action,side,price,size,order_id",
            "1,add,offer,101.0,2,10",
        ],
    )

    with pytest.raises(ValueError, match="invalid CSV MBO row at line 2"):
        CsvSource(path).events()


def test_csv_source_requires_header_row(tmp_path: Path) -> None:
    path = tmp_path / "events.csv"
    path.write_text("")

    with pytest.raises(ValueError, match="header row"):
        CsvSource(path).events()


def test_csv_source_reports_unknown_actions(tmp_path: Path) -> None:
    path = write_csv(
        tmp_path / "events.csv",
        [
            "ts_ns,action,side,price,size,order_id",
            "1,replace,ask,101.0,2,10",
        ],
    )

    with pytest.raises(ValueError, match="invalid CSV MBO row at line 2"):
        CsvSource(path).events()


def test_parquet_source_reads_normalized_mbo_events(tmp_path: Path) -> None:
    path = write_raw_parquet(
        tmp_path / "events.parquet",
        [
            {
                "ts_ns": 1,
                "action": "add",
                "side": "ask",
                "price": "101.0",
                "size": 3,
                "order_id": 10,
                "ignored": "extra",
            },
            {
                "ts_ns": 2,
                "action": "trade",
                "side": "ask",
                "price": "101.0",
                "size": 1,
                "order_id": 10,
                "ignored": "extra",
            },
        ],
    )

    assert ParquetSource(path).events() == (
        MBOEvent(
            ts_ns=1,
            action="add",
            side="ask",
            price=Decimal("101.0"),
            size=3,
            order_id=10,
        ),
        MBOEvent(
            ts_ns=2,
            action="trade",
            side="ask",
            price=Decimal("101.0"),
            size=1,
            order_id=10,
        ),
    )


def test_replay_accepts_parquet_source(tmp_path: Path) -> None:
    path = write_raw_parquet(
        tmp_path / "events.parquet",
        [
            {
                "ts_ns": 1,
                "action": "add",
                "side": "ask",
                "price": "101.0",
                "size": 2,
                "order_id": 10,
            }
        ],
    )
    replay = Replay(data=ParquetSource(path), instrument=gc_spec())

    def strategy(gateway) -> None:
        gateway.advance_to(1)
        gateway.place_market(side="buy", size=1)

    result = replay.run(strategy)

    assert result.final_position == 1
    assert result.fills[0].price == Decimal("101.0")


def test_write_parquet_materializes_canonical_events(tmp_path: Path) -> None:
    events = SyntheticSource.small_mbo()
    path = write_parquet(events, tmp_path / "events.parquet")

    assert path == tmp_path / "events.parquet"
    assert ParquetSource(path).events() == events


def test_write_parquet_accepts_data_sources(tmp_path: Path) -> None:
    source = InMemorySource.from_events("small-mbo", SyntheticSource.small_mbo())
    path = write_parquet(source, tmp_path / "nested" / "events.parquet")

    assert path.exists()
    assert ParquetSource(path).events() == SyntheticSource.small_mbo()


def test_write_parquet_materializes_empty_sources(tmp_path: Path) -> None:
    path = write_parquet((), tmp_path / "empty.parquet")

    assert ParquetSource(path).events() == ()


def test_parquet_source_requires_canonical_columns(tmp_path: Path) -> None:
    path = write_raw_parquet(
        tmp_path / "events.parquet",
        [
            {
                "ts_ns": 1,
                "action": "add",
                "side": "ask",
                "price": "101.0",
                "size": 2,
            }
        ],
    )

    with pytest.raises(ValueError, match="missing required columns"):
        ParquetSource(path).events()


def test_parquet_source_reports_invalid_rows(tmp_path: Path) -> None:
    path = write_raw_parquet(
        tmp_path / "events.parquet",
        [
            {
                "ts_ns": 1,
                "action": "add",
                "side": "offer",
                "price": "101.0",
                "size": 2,
                "order_id": 10,
            }
        ],
    )

    with pytest.raises(ValueError, match="invalid Parquet MBO row at row 1"):
        ParquetSource(path).events()


def test_parquet_source_reports_missing_optional_dependency(monkeypatch) -> None:
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "pyarrow.parquet":
            raise ImportError("missing")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(ImportError, match=r"ordersim\[parquet\]"):
        parquet_connector._load_pyarrow_parquet()


def test_write_parquet_reports_missing_optional_dependency(monkeypatch) -> None:
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "pyarrow":
            raise ImportError("missing")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(ImportError, match=r"ordersim\[parquet\]"):
        parquet_connector._load_pyarrow()


def test_databento_source_normalizes_raw_mbo_records() -> None:
    source = DatabentoMboSource(
        [
            DatabentoRecord(1, 11, "R", "N", 0, 0, 0, 128),
            DatabentoRecord(2, 12, "A", "B", 100_000_000_000, 3, 10, 128),
            DatabentoRecord(3, 13, "M", "B", 100_000_000_000, 2, 10, 128),
            DatabentoRecord(4, 14, "C", "B", 100_000_000_000, 1, 10, 128),
        ]
    )

    assert source.events() == (
        MBOEvent(
            ts_ns=2,
            action="add",
            side="bid",
            price=Decimal("100.000000000"),
            size=3,
            order_id=10,
        ),
        MBOEvent(
            ts_ns=3,
            action="modify",
            side="bid",
            price=Decimal("100.000000000"),
            size=2,
            order_id=10,
        ),
        MBOEvent(
            ts_ns=4,
            action="cancel",
            side="bid",
            price=Decimal("100.000000000"),
            size=1,
            order_id=10,
        ),
    )


def test_databento_source_collapses_fill_cancel_pair_for_replay() -> None:
    source = DatabentoMboSource(
        [
            DatabentoRecord(1, 11, "A", "B", 100_000_000_000, 1, 10, 128),
            DatabentoRecord(2, 12, "A", "B", 100_000_000_000, 1, 11, 128),
            DatabentoRecord(3, 13, "T", "A", 100_000_000_000, 2, 20, 0),
            DatabentoRecord(3, 13, "F", "B", 100_000_000_000, 1, 10, 0),
            DatabentoRecord(3, 13, "C", "B", 100_000_000_000, 1, 10, 0),
            DatabentoRecord(3, 13, "F", "B", 100_000_000_000, 1, 11, 0),
            DatabentoRecord(3, 13, "C", "B", 100_000_000_000, 1, 11, 128),
        ]
    )
    replay = Replay(data=source, instrument=gc_spec())

    def strategy(gateway) -> None:
        gateway.advance_to(1)
        gateway.place_limit(side="buy", price=Decimal("100.0"), size=1)
        gateway.advance_to(3)

    result = replay.run(strategy)

    assert source.events()[2] == MBOEvent(
        ts_ns=3,
        action="trade",
        side="bid",
        price=Decimal("100.000000000"),
        size=1,
        order_id=10,
    )
    assert result.final_position == 1
    assert [(fill.side, fill.price, fill.size) for fill in result.fills] == [
        ("buy", Decimal("100.000000000"), 1),
    ]


def test_databento_source_can_use_receive_timestamps() -> None:
    source = DatabentoMboSource(
        [DatabentoRecord(1, 11, "A", "A", 101_000_000_000, 1, 10, 128)],
        timestamp_field="ts_recv",
    )

    assert source.events()[0].ts_ns == 11


def test_databento_source_ignores_unsided_fills() -> None:
    source = DatabentoMboSource(
        [DatabentoRecord(1, 11, "F", "N", 101_000_000_000, 1, 10, 128)]
    )

    assert source.events() == ()


def test_databento_source_rejects_aggregated_records() -> None:
    source = DatabentoMboSource(
        [DatabentoRecord(1, 11, "A", "A", 101_000_000_000, 1, 10, 16 | 128)]
    )

    with pytest.raises(ValueError, match="F_MBP"):
        source.events()


def test_databento_source_rejects_midstream_clear() -> None:
    source = DatabentoMboSource(
        [
            DatabentoRecord(1, 11, "A", "A", 101_000_000_000, 1, 10, 128),
            DatabentoRecord(2, 12, "R", "N", 0, 0, 0, 128),
        ]
    )

    with pytest.raises(ValueError, match="mid-stream"):
        source.events()


def test_databento_source_accepts_mapping_records_and_bytes_values() -> None:
    source = DatabentoMboSource(
        [
            {
                "ts_event": 1,
                "ts_recv": 11,
                "action": b"A",
                "side": b"A",
                "price": 101_000_000_000,
                "size": 1,
                "order_id": 10,
                "flags": 0,
            }
        ]
    )

    assert source.events() == (
        MBOEvent(
            ts_ns=1,
            action="add",
            side="ask",
            price=Decimal("101.000000000"),
            size=1,
            order_id=10,
        ),
    )


def test_databento_source_rejects_unknown_timestamp_field() -> None:
    with pytest.raises(ValueError, match="timestamp_field"):
        DatabentoMboSource([], timestamp_field="local_time")  # type: ignore[arg-type]


def test_databento_source_rejects_unsupported_actions() -> None:
    source = DatabentoMboSource(
        [DatabentoRecord(1, 11, "Z", "A", 101_000_000_000, 1, 10, 128)]
    )

    with pytest.raises(ValueError, match="unsupported"):
        source.events()


def test_databento_source_rejects_unsided_book_updates() -> None:
    source = DatabentoMboSource(
        [DatabentoRecord(1, 11, "A", "N", 101_000_000_000, 1, 10, 128)]
    )

    with pytest.raises(ValueError, match="requires side"):
        source.events()


def test_databento_source_rejects_unknown_sides() -> None:
    source = DatabentoMboSource(
        [DatabentoRecord(1, 11, "A", "X", 101_000_000_000, 1, 10, 128)]
    )

    with pytest.raises(ValueError, match="unsupported Databento side"):
        source.events()


def test_databento_source_reports_missing_mapping_fields() -> None:
    source = DatabentoMboSource(
        [
            {
                "ts_event": 1,
                "ts_recv": 11,
                "action": "A",
                "side": "A",
                "price": 101_000_000_000,
                "size": 1,
                "flags": 128,
            }
        ]
    )

    with pytest.raises(ValueError, match="missing field 'order_id'"):
        source.events()


def test_databento_source_reports_missing_object_fields() -> None:
    class IncompleteRecord:
        ts_event = 1
        ts_recv = 11
        action = "A"
        side = "A"
        price = 101_000_000_000
        size = 1
        flags = 128

    source = DatabentoMboSource([IncompleteRecord()])  # type: ignore[list-item]

    with pytest.raises(ValueError, match="missing field 'order_id'"):
        source.events()


def test_databento_source_rejects_multicharacter_values() -> None:
    source = DatabentoMboSource(
        [DatabentoRecord(1, 11, "ADD", "A", 101_000_000_000, 1, 10, 128)]
    )

    with pytest.raises(ValueError, match="one-character"):
        source.events()
