import builtins
from decimal import Decimal
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ordersim import (
    InMemorySource,
    InstrumentSpec,
    MBOEvent,
    ParquetSource,
    Replay,
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


def write_raw_parquet(path: Path, rows: list[dict[str, object]]) -> Path:
    pq.write_table(pa.Table.from_pylist(rows), path)
    return path


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
