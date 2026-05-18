from collections.abc import Iterable
from decimal import Decimal

from ordersim import (
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
