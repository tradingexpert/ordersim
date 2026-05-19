from decimal import Decimal

import pytest

from ordersim import (
    CppMatchingEngine,
    InstrumentSpec,
    MBOEvent,
    cpp_execution_engine_available,
)
from ordersim.replay.compiled_events import CompiledEventColumns
from ordersim.sim import cpp_matching_engine
from ordersim.testing import assert_execution_equivalence_suite

pytestmark = pytest.mark.skipif(
    not cpp_execution_engine_available(),
    reason="optional C++ execution engine is not built",
)


def gc_spec() -> InstrumentSpec:
    return InstrumentSpec(
        symbol="GC",
        tick_size=Decimal("0.10"),
        point_value=Decimal("100"),
    )


def test_cpp_execution_engine_passes_public_equivalence_suite() -> None:
    spec = gc_spec()

    results = assert_execution_equivalence_suite(
        instrument=spec,
        candidate_factory=lambda: CppMatchingEngine(tick_size=spec.tick_size),
    )

    assert all(result.equivalent for result in results)


def test_cpp_execution_engine_rejects_unaligned_strategy_price() -> None:
    engine = CppMatchingEngine(tick_size=Decimal("0.10"))

    with pytest.raises(ValueError, match="not aligned"):
        engine.place_limit(side="buy", price=Decimal("100.05"), size=1)


def test_cpp_execution_engine_rejects_nonpositive_tick_size() -> None:
    with pytest.raises(ValueError, match="tick_size must be positive"):
        CppMatchingEngine(tick_size=Decimal("0"))


def test_cpp_execution_engine_reports_unavailable_import(monkeypatch) -> None:
    def missing_module() -> None:
        raise ImportError("missing extension")

    monkeypatch.setattr(cpp_matching_engine, "_load_cpp_module", missing_module)

    assert cpp_execution_engine_available() is False


def test_cpp_execution_engine_exposes_decimal_book_state() -> None:
    engine = CppMatchingEngine(tick_size=Decimal("0.10"))

    engine.apply_event(
        MBOEvent(
            ts_ns=1,
            action="add",
            side="bid",
            price=Decimal("100.0"),
            size=2,
            order_id=1,
        )
    )
    engine.apply_event(
        MBOEvent(
            ts_ns=2,
            action="add",
            side="ask",
            price=Decimal("101.0"),
            size=3,
            order_id=2,
        )
    )

    assert engine.book_top() == (Decimal("100.00"), Decimal("101.00"))
    bids, asks = engine.book_depth(1)
    assert bids[0].price == Decimal("100.00")
    assert asks[0].price == Decimal("101.00")


def test_cpp_execution_engine_applies_compiled_event_batches() -> None:
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
        MBOEvent(
            ts_ns=3,
            action="trade",
            side="bid",
            price=Decimal("100.0"),
            size=2,
            order_id=3,
        ),
    )
    columns = CompiledEventColumns.from_events(events, tick_size=Decimal("0.10"))
    engine = CppMatchingEngine(tick_size=Decimal("0.10"))

    resting = engine.place_limit(side="buy", price=Decimal("100.0"), size=1)
    fills = engine.apply_events_batch(columns.slice(0, len(events)))

    assert resting.order_id is not None
    fill_rows = [
        (fill.order_id, fill.side, fill.price, fill.size, fill.ts_ns)
        for fill in fills
    ]
    assert fill_rows == [
        (resting.order_id, "buy", Decimal("100.00"), 1, 3),
    ]


def test_cpp_execution_engine_applies_compiled_batches_with_marks() -> None:
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
        MBOEvent(
            ts_ns=3,
            action="trade",
            side="bid",
            price=Decimal("100.0"),
            size=2,
            order_id=3,
        ),
    )
    columns = CompiledEventColumns.from_events(events, tick_size=Decimal("0.10"))
    engine = CppMatchingEngine(tick_size=Decimal("0.10"))

    resting = engine.place_limit(side="buy", price=Decimal("100.0"), size=1)
    fills, marks = engine.apply_events_batch_with_marks(
        columns.slice(0, len(events))
    )

    assert resting.order_id is not None
    assert [(fill.order_id, fill.price, fill.ts_ns) for fill in fills] == [
        (resting.order_id, Decimal("100.00"), 3),
    ]
    assert [(mark.ts_ns, mark.price) for mark in marks] == [
        (2, Decimal("100.50")),
    ]


def test_cpp_execution_engine_stops_compiled_batch_at_passive_fill() -> None:
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
    columns = CompiledEventColumns.from_events(events, tick_size=Decimal("0.10"))
    engine = CppMatchingEngine(tick_size=Decimal("0.10"))

    resting = engine.place_limit(side="buy", price=Decimal("100.0"), size=1)
    events_applied, fills = engine.apply_events_until_fill(
        columns.slice(0, len(events))
    )

    assert resting.order_id is not None
    assert events_applied == 2
    assert [(fill.order_id, fill.ts_ns, fill.size) for fill in fills] == [
        (resting.order_id, 2, 1),
    ]
    assert engine.book_top() == (None, None)

    remaining_fills = engine.apply_events_batch(
        columns.slice(events_applied, len(events))
    )

    assert remaining_fills == []
    assert engine.book_top() == (None, Decimal("101.00"))


def test_cpp_execution_engine_reports_full_batch_without_passive_fill() -> None:
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
    columns = CompiledEventColumns.from_events(events, tick_size=Decimal("0.10"))
    engine = CppMatchingEngine(tick_size=Decimal("0.10"))

    events_applied, fills = engine.apply_events_until_fill(
        columns.slice(0, len(events))
    )

    assert events_applied == len(events)
    assert fills == []
    assert engine.book_top() == (Decimal("100.00"), Decimal("101.00"))


def test_compiled_event_columns_reject_unaligned_prices() -> None:
    events = (
        MBOEvent(
            ts_ns=1,
            action="add",
            side="ask",
            price=Decimal("101.05"),
            size=1,
            order_id=1,
        ),
    )

    with pytest.raises(ValueError, match="not aligned"):
        CompiledEventColumns.from_events(events, tick_size=Decimal("0.10"))
