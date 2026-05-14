from collections.abc import Iterable
from decimal import Decimal
from pathlib import Path

import pytest

from ordersim import (
    CsvSource,
    DataSource,
    InMemorySource,
    InstrumentSpec,
    MBOEvent,
    Replay,
    normalize_events,
)
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
