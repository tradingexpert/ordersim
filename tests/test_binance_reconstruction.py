from dataclasses import replace
from decimal import Decimal
from typing import cast

import pytest

from ordersim.connectors.binance import (
    BinanceDepthSnapshot,
    BinanceDepthUpdate,
    BinanceIndividualTrade,
    BinanceMBOReconstructor,
    BinancePriceLevel,
    BinanceReconstructionConfig,
    BinanceReconstructionPolicy,
)
from ordersim.sim import (
    CppMatchingEngine,
    MatchingEngine,
    cpp_execution_engine_available,
)


def level(price: str, quantity: str) -> BinancePriceLevel:
    return BinancePriceLevel(price=Decimal(price), quantity=Decimal(quantity))


def snapshot(*, bid_quantity: str = "10") -> BinanceDepthSnapshot:
    return BinanceDepthSnapshot(
        symbol="BTCUSDT",
        connection_id="depth-1",
        received_at_ns=90,
        received_monotonic_ns=900,
        last_update_id=100,
        bids=(level("100", bid_quantity),),
        asks=(level("101", "8"),),
    )


def update(
    update_id: int,
    *,
    bids: tuple[BinancePriceLevel, ...] = (),
    asks: tuple[BinancePriceLevel, ...] = (),
) -> BinanceDepthUpdate:
    return BinanceDepthUpdate(
        symbol="BTCUSDT",
        connection_id="depth-1",
        stream_kind="depth",
        event_time_ns=update_id * 10,
        transaction_time_ns=update_id * 10,
        received_at_ns=update_id * 10 + 1,
        received_monotonic_ns=update_id * 100,
        first_update_id=update_id,
        final_update_id=update_id,
        previous_update_id=update_id - 1,
        bids=bids,
        asks=asks,
    )


def trade(
    trade_id: int,
    *,
    quantity: str,
    buyer_is_maker: bool = True,
    price: str = "100",
) -> BinanceIndividualTrade:
    return BinanceIndividualTrade(
        symbol="BTCUSDT",
        connection_id="trades-1",
        event_time_ns=trade_id * 10,
        trade_time_ns=trade_id * 10,
        received_at_ns=trade_id * 10 + 2,
        received_monotonic_ns=trade_id * 100,
        trade_id=trade_id,
        price=Decimal(price),
        quantity=Decimal(quantity),
        buyer_is_maker=buyer_is_maker,
    )


def model(
    policy: BinanceReconstructionPolicy = "queue-conservative",
) -> BinanceMBOReconstructor:
    return BinanceMBOReconstructor(
        BinanceReconstructionConfig(
            quantity_step=Decimal("1"),
            policy=policy,
        )
    )


def test_reconstruction_reaches_every_observed_depth_endpoint() -> None:
    reconstructor = model()
    bootstrap = reconstructor.bootstrap(snapshot(), update(100))

    step = reconstructor.apply_update(
        update(110, bids=(level("100", "9"),)),
        trades=(trade(105, quantity="4"),),
    )

    assert reconstructor.level_quantity("bid", Decimal("100")) == 9
    assert reconstructor.level_quantity("ask", Decimal("101")) == 8
    assert step.metrics.trade_units == 4
    assert step.metrics.inferred_add_units == 3
    assert step.metrics.inferred_cancel_units == 0
    assert bootstrap.metrics.snapshot_add_units == 18


def test_trade_at_unchanged_level_requires_visible_replenishment() -> None:
    reconstructor = model("queue-optimistic")
    reconstructor.bootstrap(snapshot(bid_quantity="2"), update(100))

    step = reconstructor.apply_update(
        update(110),
        trades=(trade(105, quantity="3"),),
    )

    assert reconstructor.level_quantity("bid", Decimal("100")) == 2
    assert [event.action for event in step.events] == ["add", "trade", "add"]
    assert step.metrics.required_replenishment_units == 1
    assert step.metrics.inferred_add_units == 3


def test_reconstructed_events_run_in_the_reference_matching_engine() -> None:
    reconstructor = model()
    engine = MatchingEngine()

    bootstrap = reconstructor.bootstrap(snapshot(), update(100))
    step = reconstructor.apply_update(
        update(
            110,
            bids=(level("100", "7"),),
            asks=(level("101", "6"),),
        ),
        trades=(
            trade(104, quantity="2"),
            trade(
                106,
                quantity="1",
                buyer_is_maker=False,
                price="101",
            ),
        ),
    )

    for event in bootstrap.events + step.events:
        engine.apply_event(event)

    bids, asks = engine.book_depth(1)
    assert [(row.price, row.size) for row in bids] == [(Decimal("100"), 7)]
    assert [(row.price, row.size) for row in asks] == [(Decimal("101"), 6)]


@pytest.mark.skipif(
    not cpp_execution_engine_available(),
    reason="optional C++ execution engine is not built",
)
def test_reconstructed_events_have_equivalent_python_and_cpp_execution() -> None:
    reconstructor = model()
    bootstrap = reconstructor.bootstrap(snapshot(), update(100))
    step = reconstructor.apply_update(
        update(110, bids=(level("100", "5"),)),
        trades=(trade(105, quantity="11"),),
    )
    python_engine = MatchingEngine()
    cpp_engine = CppMatchingEngine(tick_size=Decimal("1"))

    for event in bootstrap.events:
        python_engine.apply_event(event)
        cpp_engine.apply_event(event)
    python_order = python_engine.place_limit("buy", Decimal("100"), 1)
    cpp_order = cpp_engine.place_limit("buy", Decimal("100"), 1)

    python_fills = [
        fill for event in step.events for fill in python_engine.apply_event(event)
    ]
    cpp_fills = [
        fill for event in step.events for fill in cpp_engine.apply_event(event)
    ]

    assert python_order.order_id == cpp_order.order_id
    assert python_fills == cpp_fills
    assert python_engine.book_depth(1) == cpp_engine.book_depth(1)


def test_named_policies_bound_cancellation_effect_on_queue_position() -> None:
    queue_ahead: dict[str, int] = {}

    for policy in ("queue-conservative", "queue-optimistic"):
        reconstructor = model(policy)
        engine = MatchingEngine()
        bootstrap = reconstructor.bootstrap(snapshot(), update(100))
        for event in bootstrap.events:
            engine.apply_event(event)

        own_order_id = engine.place_limit("buy", Decimal("100"), 1).order_id
        assert own_order_id is not None

        addition = reconstructor.apply_update(
            update(110, bids=(level("100", "15"),))
        )
        cancellation = reconstructor.apply_update(
            update(120, bids=(level("100", "10"),))
        )
        for event in addition.events + cancellation.events:
            engine.apply_event(event)

        own_order = next(
            order for order in engine.own_orders() if order.order_id == own_order_id
        )
        queue_ahead[policy] = own_order.queue_ahead_size

    assert queue_ahead == {
        "queue-conservative": 10,
        "queue-optimistic": 5,
    }


def test_reconstruction_rejects_invalid_bridge_and_quantity_step() -> None:
    invalid_bridge = update(101)

    with pytest.raises(ValueError, match="does not span"):
        model().bootstrap(snapshot(), invalid_bridge)

    fractional = BinanceMBOReconstructor(
        BinanceReconstructionConfig(quantity_step=Decimal("0.01"))
    )
    with pytest.raises(ValueError, match="not divisible"):
        fractional.bootstrap(snapshot(bid_quantity="1.005"), update(100))


def test_trade_must_belong_to_the_depth_interval() -> None:
    reconstructor = model()
    reconstructor.bootstrap(snapshot(), update(100))

    with pytest.raises(ValueError, match="outside"):
        reconstructor.apply_update(
            update(110),
            trades=(trade(99, quantity="1"),),
        )


def test_configuration_and_bootstrap_boundaries_are_explicit() -> None:
    with pytest.raises(ValueError, match="quantity_step"):
        BinanceReconstructionConfig(quantity_step=Decimal("0"))
    with pytest.raises(ValueError, match="unsupported"):
        BinanceReconstructionConfig(
            quantity_step=Decimal("1"),
            policy=cast(BinanceReconstructionPolicy, "unknown"),
        )

    reconstructor = model()
    assert reconstructor.symbol is None
    with pytest.raises(RuntimeError, match="bootstrap"):
        reconstructor.apply_update(update(101))
    with pytest.raises(ValueError, match="standard depth"):
        reconstructor.bootstrap(
            snapshot(),
            replace(update(100), stream_kind="rpi_depth"),
        )
    with pytest.raises(ValueError, match="symbols differ"):
        reconstructor.bootstrap(
            snapshot(),
            replace(update(100), symbol="ETHUSDT"),
        )
    with pytest.raises(ValueError, match="connections differ"):
        reconstructor.bootstrap(
            snapshot(),
            replace(update(100), connection_id="depth-2"),
        )

    reconstructor.bootstrap(snapshot(), update(100))
    assert reconstructor.symbol == "BTCUSDT"
    with pytest.raises(RuntimeError, match="already"):
        reconstructor.bootstrap(snapshot(), update(100))


@pytest.mark.parametrize(
    ("changed", "message"),
    [
        ({"symbol": "ETHUSDT"}, "symbol differs"),
        ({"connection_id": "depth-2"}, "connection differs"),
        ({"stream_kind": "rpi_depth"}, "standard depth"),
        ({"transaction_time_ns": 999}, "moved backwards"),
    ],
)
def test_later_depth_updates_must_remain_in_one_segment(
    changed: dict[str, object],
    message: str,
) -> None:
    reconstructor = model()
    reconstructor.bootstrap(snapshot(), update(100))

    with pytest.raises(ValueError, match=message):
        reconstructor.apply_update(replace(update(110), **changed))


def test_trade_validation_and_best_price_removal() -> None:
    reconstructor = model()
    reconstructor.bootstrap(snapshot(), update(100))

    with pytest.raises(ValueError, match="symbols differ"):
        reconstructor.apply_update(
            update(110),
            trades=(replace(trade(105, quantity="1"), symbol="ETHUSDT"),),
        )
    with pytest.raises(ValueError, match="must be positive"):
        reconstructor.apply_update(
            update(110),
            trades=(replace(trade(105, quantity="1"), quantity=Decimal("0")),),
        )

    reconstructor.apply_update(
        update(
            110,
            bids=(level("100", "0"),),
            asks=(level("101", "0"),),
        )
    )
    assert reconstructor.book_top() == (None, None)


def test_zero_snapshot_levels_and_metrics_only_mode() -> None:
    empty_bid = snapshot(bid_quantity="0")
    reconstructor = BinanceMBOReconstructor(
        BinanceReconstructionConfig(
            quantity_step=Decimal("1"),
            emit_events=False,
        )
    )

    bootstrap = reconstructor.bootstrap(empty_bid, update(100))
    step = reconstructor.apply_update(
        update(110, bids=(level("100", "2"),))
    )
    traded = reconstructor.apply_update(
        update(120),
        trades=(trade(115, quantity="3"),),
    )
    removed = reconstructor.apply_update(
        update(
            130,
            bids=(level("100", "0"),),
            asks=(level("101", "0"),),
        )
    )

    assert bootstrap.events == ()
    assert step.events == ()
    assert traded.events == ()
    assert removed.events == ()
    assert reconstructor.book_top() == (None, None)
