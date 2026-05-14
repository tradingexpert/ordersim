from decimal import Decimal
from typing import cast

import pytest

from ordersim import MatchingEngine, MBOEvent
from ordersim.sim.matching_engine import PriceLevel
from ordersim.types import Fill


def event(
    ts_ns: int,
    action: str,
    side: str,
    price: str,
    size: int,
    order_id: int,
) -> MBOEvent:
    return MBOEvent(
        ts_ns=ts_ns,
        action=action,
        side=side,
        price=Decimal(price),
        size=size,
        order_id=order_id,
    )


def test_limit_order_joins_back_of_visible_queue() -> None:
    engine = MatchingEngine()
    engine.apply_event(event(1, "add", "bid", "100.0", 5, 1))

    result = engine.place_limit(side="buy", price=Decimal("100.0"), size=2)

    assert result.order_id is not None
    assert result.fills == ()
    assert engine.own_orders_snapshot() == (
        (result.order_id, "bid", Decimal("100.0"), 2, 5),
    )
    assert engine.book_top() == (Decimal("100.0"), None)
    assert engine.book_depth(1)[0] == (PriceLevel(Decimal("100.0"), 7),)


def test_public_cancel_reduces_queue_ahead_without_filling_own_order() -> None:
    engine = MatchingEngine()
    engine.apply_event(event(1, "add", "bid", "100.0", 5, 1))
    result = engine.place_limit(side="buy", price=Decimal("100.0"), size=2)

    fills = engine.apply_event(event(2, "cancel", "bid", "100.0", 3, 1))

    assert fills == []
    assert engine.own_orders_snapshot() == (
        (result.order_id, "bid", Decimal("100.0"), 2, 2),
    )
    assert engine.book_depth(1)[0] == (PriceLevel(Decimal("100.0"), 4),)


def test_public_cancel_removes_public_order_when_size_reaches_zero() -> None:
    engine = MatchingEngine()
    engine.apply_event(event(1, "add", "ask", "101.0", 3, 1))

    engine.apply_event(event(2, "cancel", "ask", "101.0", 3, 1))

    assert engine.public_orders == {}
    assert engine.book_top() == (None, None)


def test_unknown_public_cancel_only_adjusts_visible_book() -> None:
    engine = MatchingEngine()
    engine.apply_event(event(1, "cancel", "bid", "100.0", 3, 404))

    assert engine.book_top() == (None, None)


def test_public_trade_consumes_queue_ahead_then_passively_fills_own_order() -> None:
    engine = MatchingEngine()
    engine.apply_event(event(1, "add", "bid", "100.0", 5, 1))
    result = engine.place_limit(side="buy", price=Decimal("100.0"), size=4)

    first_fills = engine.apply_event(event(2, "trade", "bid", "100.0", 3, 1))
    second_fills = engine.apply_event(event(3, "trade", "bid", "100.0", 4, 1))

    assert first_fills == []
    assert second_fills == [
        Fill(
            order_id=result.order_id,
            price=Decimal("100.0"),
            size=2,
            ts_ns=3,
        )
    ]
    assert engine.position() == 2
    assert engine.own_orders_snapshot() == (
        (result.order_id, "bid", Decimal("100.0"), 2, 0),
    )
    assert engine.pop_passive_fills() == second_fills
    assert engine.pop_passive_fills() == []


def test_multiple_own_orders_advance_fifo_at_same_price() -> None:
    engine = MatchingEngine()
    engine.apply_event(event(1, "add", "bid", "100.0", 5, 1))
    first = engine.place_limit(side="buy", price=Decimal("100.0"), size=2)
    second = engine.place_limit(side="buy", price=Decimal("100.0"), size=3)

    fills = engine.apply_event(event(2, "trade", "bid", "100.0", 10, 1))

    assert fills == [
        Fill(
            order_id=first.order_id,
            price=Decimal("100.0"),
            size=2,
            ts_ns=2,
        ),
        Fill(
            order_id=second.order_id,
            price=Decimal("100.0"),
            size=3,
            ts_ns=2,
        ),
    ]
    assert engine.own_orders_snapshot() == ()
    assert engine.position() == 5


def test_ask_side_passive_fill_decreases_position_and_removes_filled_order() -> None:
    engine = MatchingEngine()
    engine.apply_event(event(1, "add", "ask", "101.0", 2, 1))
    result = engine.place_limit(side="sell", price=Decimal("101.0"), size=3)

    fills = engine.apply_event(event(2, "trade", "ask", "101.0", 5, 1))

    assert fills == [
        Fill(
            order_id=result.order_id,
            price=Decimal("101.0"),
            size=3,
            ts_ns=2,
        )
    ]
    assert engine.position() == -3
    assert engine.own_orders_snapshot() == ()
    assert engine.book_top() == (None, None)


def test_public_modify_moves_order_to_back_of_new_price_level() -> None:
    engine = MatchingEngine()
    engine.apply_event(event(1, "add", "ask", "101.0", 3, 1))
    engine.apply_event(event(2, "add", "ask", "102.0", 4, 2))

    engine.apply_event(event(3, "modify", "ask", "102.0", 3, 1))

    assert engine.book_depth(2)[1] == (
        PriceLevel(Decimal("102.0"), 7),
    )


def test_public_modify_at_same_level_changes_visible_size() -> None:
    engine = MatchingEngine()
    engine.apply_event(event(1, "add", "ask", "101.0", 3, 1))

    engine.apply_event(event(2, "modify", "ask", "101.0", 5, 1))
    assert engine.book_depth(1)[1] == (PriceLevel(Decimal("101.0"), 5),)

    engine.apply_event(event(3, "modify", "ask", "101.0", 2, 1))
    assert engine.book_depth(1)[1] == (PriceLevel(Decimal("101.0"), 2),)

    engine.apply_event(event(4, "cancel", "ask", "101.0", 2, 1))
    assert engine.public_orders == {}
    assert engine.book_top() == (None, None)


def test_public_modify_for_unknown_order_adds_it() -> None:
    engine = MatchingEngine()

    engine.apply_event(event(1, "modify", "bid", "100.0", 4, 1))

    assert engine.book_depth(1)[0] == (PriceLevel(Decimal("100.0"), 4),)


def test_market_order_matches_best_prices_and_updates_position() -> None:
    engine = MatchingEngine()
    engine.apply_event(event(1, "add", "ask", "101.0", 2, 1))
    engine.apply_event(event(2, "add", "ask", "102.0", 5, 2))

    fills = engine.place_market(side="buy", size=4)

    assert [(fill.price, fill.size) for fill in fills] == [
        (Decimal("101.0"), 2),
        (Decimal("102.0"), 2),
    ]
    assert engine.position() == 4
    assert engine.book_depth(2)[1] == (PriceLevel(Decimal("102.0"), 3),)


def test_sell_market_order_matches_bids_from_highest_price() -> None:
    engine = MatchingEngine()
    engine.apply_event(event(1, "add", "bid", "100.0", 2, 1))
    engine.apply_event(event(2, "add", "bid", "99.5", 5, 2))

    fills = engine.place_market(side="sell", size=4)

    assert [(fill.price, fill.size) for fill in fills] == [
        (Decimal("100.0"), 2),
        (Decimal("99.5"), 2),
    ]
    assert engine.position() == -4


def test_ioc_limit_does_not_rest_remainder() -> None:
    engine = MatchingEngine()
    engine.apply_event(event(1, "add", "ask", "101.0", 1, 1))

    result = engine.place_limit(
        side="buy",
        price=Decimal("101.0"),
        size=3,
        tif="IOC",
    )

    assert [(fill.price, fill.size) for fill in result.fills] == [
        (Decimal("101.0"), 1),
    ]
    assert result.order_id is None
    assert engine.own_orders_snapshot() == ()


def test_cancel_removes_own_order_from_book() -> None:
    engine = MatchingEngine()
    result = engine.place_limit(side="sell", price=Decimal("101.0"), size=3)

    assert result.order_id is not None
    assert engine.cancel(result.order_id) is True
    assert engine.cancel(result.order_id) is False
    assert engine.book_top() == (None, None)
    assert engine.own_orders_snapshot() == ()


def test_engine_reports_event_time_and_rejects_invalid_orders() -> None:
    engine = MatchingEngine()

    engine.apply_event(event(10, "add", "ask", "101.0", 1, 1))

    assert engine.now_ns() == 10
    with pytest.raises(ValueError, match="size"):
        engine.place_market(side="buy", size=0)
    with pytest.raises(ValueError, match="price"):
        engine.place_limit(side="buy", price=Decimal("0"), size=1)


def test_unknown_event_action_is_rejected() -> None:
    engine = MatchingEngine()
    bad_event = event(1, "add", "ask", "101.0", 1, 1)
    object.__setattr__(bad_event, "action", cast(object, "bad"))

    with pytest.raises(ValueError, match="unknown MBO action"):
        engine.apply_event(bad_event)
