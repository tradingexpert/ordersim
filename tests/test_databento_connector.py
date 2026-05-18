from dataclasses import dataclass
from decimal import Decimal

import pytest

from ordersim import DatabentoMboSource, InstrumentSpec, MBOEvent, Replay


def gc_spec() -> InstrumentSpec:
    return InstrumentSpec(
        symbol="GC",
        tick_size=Decimal("0.10"),
        point_value=Decimal("100"),
        commission_per_contract=Decimal("2.50"),
    )


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
        size=2,
        order_id=20,
    )
    assert result.final_position == 1
    assert [(fill.side, fill.price, fill.size) for fill in result.fills] == [
        ("buy", Decimal("100.000000000"), 1),
    ]


def test_databento_trade_quantity_can_reach_own_orders_after_public_fills() -> None:
    source = DatabentoMboSource(
        [
            DatabentoRecord(1, 11, "A", "B", 100_000_000_000, 5, 10, 128),
            DatabentoRecord(2, 12, "A", "A", 101_000_000_000, 5, 11, 128),
            DatabentoRecord(3, 13, "T", "A", 100_000_000_000, 7, 20, 0),
            DatabentoRecord(3, 13, "F", "B", 100_000_000_000, 5, 10, 0),
            DatabentoRecord(3, 13, "C", "B", 100_000_000_000, 5, 10, 128),
        ]
    )
    replay = Replay(data=source, instrument=gc_spec())

    def strategy(gateway) -> None:
        gateway.advance_to(2)
        gateway.place_limit(side="buy", price=Decimal("100.0"), size=2)
        gateway.advance_to(3)

    result = replay.run(strategy)

    assert source.events()[2] == MBOEvent(
        ts_ns=3,
        action="trade",
        side="bid",
        price=Decimal("100.000000000"),
        size=7,
        order_id=20,
    )
    assert [(fill.side, fill.price, fill.size) for fill in result.fills] == [
        ("buy", Decimal("100.000000000"), 2),
    ]
    assert result.resting_orders == ()


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


def test_databento_source_infers_unsided_trade_from_sided_fill() -> None:
    source = DatabentoMboSource(
        [
            DatabentoRecord(1, 11, "T", "N", 100_000_000_000, 2, 20, 0),
            DatabentoRecord(1, 11, "F", "B", 100_000_000_000, 2, 10, 128),
        ]
    )

    assert source.events() == (
        MBOEvent(
            ts_ns=1,
            action="trade",
            side="bid",
            price=Decimal("100.000000000"),
            size=2,
            order_id=20,
        ),
    )


def test_databento_source_ignores_trade_without_usable_resting_side() -> None:
    source = DatabentoMboSource(
        [DatabentoRecord(1, 11, "T", "N", 100_000_000_000, 2, 20, 128)]
    )

    assert source.events() == ()


def test_databento_source_inverts_buy_aggressor_to_ask_trade() -> None:
    source = DatabentoMboSource(
        [DatabentoRecord(1, 11, "T", "B", 101_000_000_000, 2, 20, 128)]
    )

    assert source.events() == (
        MBOEvent(
            ts_ns=1,
            action="trade",
            side="ask",
            price=Decimal("101.000000000"),
            size=2,
            order_id=20,
        ),
    )


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
