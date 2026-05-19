from decimal import Decimal

import pytest

from ordersim import (
    CompiledEventColumns,
    CppMatchingEngine,
    MatchingEngine,
    MBOEvent,
    advance_until_fill_boundary,
    cpp_execution_engine_available,
)


def boundary_events() -> tuple[MBOEvent, ...]:
    return (
        MBOEvent(
            ts_ns=1,
            action="add",
            side="bid",
            price=Decimal("100.0"),
            size=1,
            order_id=1,
        ),
        MBOEvent(
            ts_ns=2,
            action="trade",
            side="bid",
            price=Decimal("100.0"),
            size=2,
            order_id=2,
        ),
        MBOEvent(
            ts_ns=3,
            action="add",
            side="ask",
            price=Decimal("101.0"),
            size=1,
            order_id=3,
        ),
    )


def test_boundary_advance_scalar_path_stops_on_first_passive_fill() -> None:
    engine = MatchingEngine()
    resting = engine.place_limit(side="buy", price=Decimal("100.0"), size=1)

    advance = advance_until_fill_boundary(engine, boundary_events())

    assert resting.order_id is not None
    assert advance.events_consumed == 2
    assert advance.stopped_on_fill is True
    assert [(fill.order_id, fill.ts_ns, fill.size) for fill in advance.fills] == [
        (resting.order_id, 2, 1),
    ]
    assert engine.book_top() == (None, None)


@pytest.mark.skipif(
    not cpp_execution_engine_available(),
    reason="optional C++ execution engine is not built",
)
def test_boundary_advance_compiled_path_matches_scalar_boundary() -> None:
    events = boundary_events()
    columns = CompiledEventColumns.from_events(events, tick_size=Decimal("0.10"))
    scalar_engine = MatchingEngine()
    compiled_engine = CppMatchingEngine(tick_size=Decimal("0.10"))

    scalar_order = scalar_engine.place_limit(
        side="buy",
        price=Decimal("100.0"),
        size=1,
    )
    compiled_order = compiled_engine.place_limit(
        side="buy",
        price=Decimal("100.0"),
        size=1,
    )

    scalar_advance = advance_until_fill_boundary(scalar_engine, events)
    compiled_advance = advance_until_fill_boundary(
        compiled_engine,
        events,
        compiled_events=columns,
    )

    assert scalar_order.order_id is not None
    assert compiled_order.order_id is not None
    assert scalar_advance.events_consumed == compiled_advance.events_consumed
    assert scalar_advance.stopped_on_fill is True
    assert compiled_advance.stopped_on_fill is True
    assert [
        (fill.side, fill.price, fill.size, fill.ts_ns)
        for fill in scalar_advance.fills
    ] == [
        (fill.side, fill.price, fill.size, fill.ts_ns)
        for fill in compiled_advance.fills
    ]
    assert scalar_engine.book_top() == compiled_engine.book_top()


def test_boundary_advance_reports_slice_end_without_fill() -> None:
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
            ts_ns=2,
            action="add",
            side="ask",
            price=Decimal("101.0"),
            size=1,
            order_id=2,
        ),
    )
    engine = MatchingEngine()

    advance = advance_until_fill_boundary(engine, events, start=0, stop=2)

    assert advance.events_consumed == 2
    assert advance.stopped_on_fill is False
    assert advance.fills == ()
    assert engine.book_top() == (Decimal("100.0"), Decimal("101.0"))


def test_boundary_advance_accepts_empty_slice() -> None:
    events = boundary_events()
    engine = MatchingEngine()

    advance = advance_until_fill_boundary(engine, events, start=1, stop=1)

    assert advance.events_consumed == 0
    assert advance.stopped_on_fill is False
    assert advance.fills == ()


def test_boundary_advance_validates_slice_bounds() -> None:
    events = boundary_events()
    engine = MatchingEngine()

    with pytest.raises(ValueError, match="start"):
        advance_until_fill_boundary(engine, events, start=-1)

    with pytest.raises(ValueError, match="greater than or equal"):
        advance_until_fill_boundary(engine, events, start=2, stop=1)

    with pytest.raises(ValueError, match="number of events"):
        advance_until_fill_boundary(engine, events, stop=len(events) + 1)
