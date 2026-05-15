from decimal import Decimal

import pytest

from ordersim import (
    CppMatchingEngine,
    InstrumentSpec,
    MBOEvent,
    cpp_execution_engine_available,
)
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
