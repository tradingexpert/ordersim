from decimal import Decimal

import pytest

from ordersim import (
    ConstantLatency,
    EmpiricalPlayback,
    InstrumentSpec,
    LatencyMeasurement,
    MBOEvent,
    PriceLevel,
    Replay,
)
from ordersim.fixtures.synthetic import SyntheticSource
from ordersim.types import OrderEvent


def gc_spec() -> InstrumentSpec:
    return InstrumentSpec(
        symbol="GC",
        tick_size=Decimal("0.10"),
        point_value=Decimal("100"),
        commission_per_contract=Decimal("2.50"),
    )


def read_book_then_cross_spread(gateway) -> None:
    gateway.advance_to(1_000_000_100)
    bid, ask = gateway.book_top()

    assert bid == Decimal("100.0")
    assert ask == Decimal("101.0")

    result = gateway.place_limit(side="buy", price=bid, size=1)
    gateway.advance_to(1_000_000_200)

    if gateway.position() == 0:
        if result.order_id is not None:
            gateway.cancel(result.order_id)
        gateway.place_market(side="buy", size=1)


def test_replay_runs_strategy_and_records_order_intent() -> None:
    record_to: list[OrderEvent] = []
    replay = Replay(
        data=SyntheticSource.small_mbo(),
        instrument=gc_spec(),
        record_to=record_to,
    )

    result = replay.run(read_book_then_cross_spread, strategy_name="baseline")

    assert result.final_position == 1
    assert [(fill.price, fill.size) for fill in result.fills] == [
        (Decimal("101.0"), 1),
    ]
    assert result.execution_summary.contract_volume == 1
    assert result.execution_summary.signed_notional == Decimal("-10100.0")
    assert result.execution_summary.commission == Decimal("2.50")
    assert result.execution_summary.net_realized_pnl == Decimal("-2.50")
    assert [event.kind for event in result.order_events] == [
        "place_limit",
        "cancel",
        "place_market",
        "fill",
    ]
    assert [event.kind for event in record_to] == [
        "place_limit",
        "cancel",
        "place_market",
        "fill",
    ]
    assert all(event.strategy == "baseline" for event in result.order_events)


def test_replay_run_many_preserves_solo_equivalence() -> None:
    replay = Replay(data=SyntheticSource.small_mbo(), instrument=gc_spec())

    solo = replay.run(read_book_then_cross_spread, strategy_name="baseline")
    many = replay.run_many(
        {
            "baseline": read_book_then_cross_spread,
            "copy": read_book_then_cross_spread,
        }
    )

    assert many["baseline"].fills == solo.fills
    assert many["baseline"].final_position == solo.final_position
    assert many["copy"].fills == solo.fills


def test_replay_gateway_exposes_book_depth() -> None:
    replay = Replay(data=SyntheticSource.small_mbo(), instrument=gc_spec())

    def strategy(gateway) -> None:
        gateway.advance_to(1_000_000_100)

        bids, asks = gateway.book_depth(1)

        assert bids == (PriceLevel(Decimal("100.0"), 12),)
        assert asks == (PriceLevel(Decimal("101.0"), 10),)

    result = replay.run(strategy)

    assert result.fills == ()
    assert result.order_events == ()


def test_replay_rejects_unaligned_event_prices() -> None:
    events = [
        MBOEvent(
            ts_ns=1,
            action="add",
            side="ask",
            price=Decimal("101.05"),
            size=1,
            order_id=1,
        )
    ]

    with pytest.raises(ValueError, match="not aligned"):
        Replay(data=events, instrument=gc_spec())


def test_replay_gateway_rejects_backwards_time() -> None:
    replay = Replay(data=SyntheticSource.small_mbo(), instrument=gc_spec())

    def strategy(gateway) -> None:
        gateway.advance_to(1_000_000_100)
        gateway.advance_to(1)

    with pytest.raises(ValueError, match="backwards"):
        replay.run(strategy)


def test_replay_applies_entry_latency_before_market_order() -> None:
    events = (
        MBOEvent(
            ts_ns=1,
            action="add",
            side="ask",
            price=Decimal("101.0"),
            size=1,
            order_id=1,
        ),
        MBOEvent(
            ts_ns=10,
            action="cancel",
            side="ask",
            price=Decimal("101.0"),
            size=1,
            order_id=1,
        ),
        MBOEvent(
            ts_ns=12,
            action="add",
            side="ask",
            price=Decimal("102.0"),
            size=1,
            order_id=2,
        ),
    )
    replay = Replay(
        data=events,
        instrument=gc_spec(),
        latency_model_factory=lambda: ConstantLatency(entry_ns=10),
    )

    def strategy(gateway) -> None:
        gateway.advance_to(5)
        gateway.place_market(side="buy", size=1)

    result = replay.run(strategy)

    assert [(fill.price, fill.ts_ns) for fill in result.fills] == [
        (Decimal("102.0"), 15),
    ]


def test_recording_gateway_records_passive_fill_during_cancel_latency() -> None:
    events = (
        MBOEvent(
            ts_ns=1,
            action="add",
            side="bid",
            price=Decimal("100.0"),
            size=1,
            order_id=1,
        ),
        MBOEvent(
            ts_ns=5,
            action="trade",
            side="bid",
            price=Decimal("100.0"),
            size=2,
            order_id=1,
        ),
    )
    replay = Replay(
        data=events,
        instrument=gc_spec(),
        latency_model_factory=lambda: EmpiricalPlayback.from_measurements(
            (
                LatencyMeasurement(ts_ns=1, entry_ns=0, response_ns=0),
                LatencyMeasurement(ts_ns=2, entry_ns=10, response_ns=0),
            )
        ),
    )

    def strategy(gateway) -> None:
        gateway.advance_to(1)
        result = gateway.place_limit(side="buy", price=Decimal("100.0"), size=1)

        assert result.order_id is not None
        accepted = gateway.cancel(result.order_id)

        assert accepted is False

    result = replay.run(strategy)

    assert result.final_position == 1
    assert [event.kind for event in result.order_events] == [
        "place_limit",
        "fill_passive",
        "cancel",
    ]
    assert result.order_events[1].fill_price == Decimal("100.0")
    assert result.order_events[1].ts_ns == 5


def test_run_many_uses_fresh_latency_model_per_strategy() -> None:
    created = 0
    events = (
        MBOEvent(
            ts_ns=1,
            action="add",
            side="ask",
            price=Decimal("101.0"),
            size=2,
            order_id=1,
        ),
    )

    def latency_factory() -> EmpiricalPlayback:
        nonlocal created
        created += 1
        return EmpiricalPlayback.from_measurements(
            (LatencyMeasurement(ts_ns=1, entry_ns=0, response_ns=0),)
        )

    replay = Replay(
        data=events,
        instrument=gc_spec(),
        latency_model_factory=latency_factory,
    )

    def strategy(gateway) -> None:
        gateway.advance_to(1)
        gateway.place_market(side="buy", size=1)

    results = replay.run_many({"a": strategy, "b": strategy})

    assert created == 2
    assert results["a"].fills == results["b"].fills
