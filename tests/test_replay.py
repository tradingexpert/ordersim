from decimal import Decimal

import pytest

from ordersim import (
    CompiledValuationMarks,
    ConstantLatency,
    EmpiricalPlayback,
    InstrumentSpec,
    LatencyMeasurement,
    MBOEvent,
    PriceLevel,
    Replay,
    ReplayGateway,
    RestingOrder,
)
from ordersim.fixtures.synthetic import SyntheticSource
from ordersim.replay import simulator as replay_simulator
from ordersim.types import OrderEvent


def int64_bytes(values: tuple[int, ...]) -> bytes:
    from array import array

    return array("q", values).tobytes()


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
    assert result.equity_curve[-1].mark_price == Decimal("100.5")
    assert result.equity_curve[-1].equity == Decimal("-52.50")
    assert result.equity_curve[-1].drawdown == Decimal("52.50")
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


def test_replay_compiles_immutable_stream_once_for_run_many(monkeypatch) -> None:
    calls = 0
    original = replay_simulator.CompiledEventColumns.from_events

    def spy_from_events(cls, events, *, tick_size):
        nonlocal calls
        calls += 1
        return original(events, tick_size=tick_size)

    monkeypatch.setattr(
        replay_simulator.CompiledEventColumns,
        "from_events",
        classmethod(spy_from_events),
    )
    replay = Replay(data=SyntheticSource.small_mbo(), instrument=gc_spec())

    replay.run_many(
        {
            "baseline": read_book_then_cross_spread,
            "copy": read_book_then_cross_spread,
        }
    )

    assert calls == 1


def test_replay_uses_compiled_batch_path_when_engine_supports_it() -> None:
    class BatchEngine:
        def __init__(self) -> None:
            self.batch_calls = 0
            self.last_advanced_to = 0

        def apply_events_batch_with_marks(self, events):
            self.batch_calls += 1
            mark_count = len(events.ts_ns)
            return [], CompiledValuationMarks.from_bytes(
                ts_ns=int64_bytes(tuple(int(ts_ns) for ts_ns in events.ts_ns)),
                mid_ticks_x2=int64_bytes((2010,) * mark_count),
                tick_size=Decimal("0.10"),
            )

        def apply_event(self, event):
            raise AssertionError("scalar event path should not be used")

        def advance_time(self, ts_ns: int) -> None:
            self.last_advanced_to = ts_ns

        def place_limit(self, side, price, size, tif="GTC"):
            raise AssertionError("order placement is not used in this test")

        def place_market(self, side, size):
            raise AssertionError("order placement is not used in this test")

        def cancel(self, order_id):
            raise AssertionError("order cancellation is not used in this test")

        def book_top(self):
            return Decimal("100.0"), Decimal("101.0")

        def book_depth(self, levels):
            return (), ()

        def position(self):
            return 0

        def own_orders(self):
            return ()

    created: list[BatchEngine] = []

    def factory() -> BatchEngine:
        engine = BatchEngine()
        created.append(engine)
        return engine

    replay = Replay(
        data=SyntheticSource.small_mbo(),
        instrument=gc_spec(),
        execution_engine_factory=factory,
    )

    def strategy(gateway) -> None:
        gateway.advance_to(1_000_000_200)

    result = replay.run(strategy)

    assert len(created) == 1
    assert created[0].batch_calls == 1
    assert created[0].last_advanced_to == 1_000_000_200
    assert result.equity_curve[-1].mark_price == Decimal("100.5")


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
    assert result.equity_curve[-1].equity == Decimal("0")


def test_replay_gateway_constructor_accepts_event_input() -> None:
    gateway = ReplayGateway(SyntheticSource.small_mbo())

    gateway.advance_to(1_000_000_100)

    assert gateway.book_top() == (Decimal("100.0"), Decimal("101.0"))


def test_replay_exposes_own_resting_orders_with_queue_ahead() -> None:
    events = (
        MBOEvent(
            ts_ns=1,
            action="add",
            side="bid",
            price=Decimal("100.0"),
            size=3,
            order_id=1,
        ),
    )
    replay = Replay(data=events, instrument=gc_spec())

    def strategy(gateway) -> None:
        gateway.advance_to(1)
        result = gateway.place_limit(side="buy", price=Decimal("100.0"), size=2)

        assert result.order_id is not None
        assert gateway.own_orders() == (
            RestingOrder(
                order_id=result.order_id,
                side="buy",
                price=Decimal("100.0"),
                remaining_size=2,
                queue_ahead_size=3,
            ),
        )

    result = replay.run(strategy)

    assert result.resting_orders == (
        RestingOrder(
            order_id=1_000_000_000,
            side="buy",
            price=Decimal("100.0"),
            remaining_size=2,
            queue_ahead_size=3,
        ),
    )


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
