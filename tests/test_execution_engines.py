from decimal import Decimal

import pytest

from ordersim import InstrumentSpec, MatchingEngine, MBOEvent, Replay
from ordersim.sim import ExecutionEngine, default_execution_engine_factory
from ordersim.testing import (
    assert_equivalent_execution_engines,
    compare_execution_engines,
)
from ordersim.types import Fill, OrderResult


class ScriptedEngine:
    def __init__(self) -> None:
        self.events: list[MBOEvent] = []
        self.ts_ns = 0
        self.signed_position = 0

    def apply_event(self, event: MBOEvent) -> list[Fill]:
        self.events.append(event)
        self.ts_ns = event.ts_ns
        return []

    def advance_time(self, ts_ns: int) -> None:
        self.ts_ns = ts_ns

    def place_limit(
        self,
        side: str,
        price: Decimal,
        size: int,
        tif: str = "GTC",
    ) -> OrderResult:
        fill = Fill(order_id=10, price=price, size=size, ts_ns=self.ts_ns)
        self.signed_position += size if side == "buy" else -size
        return OrderResult(order_id=None, fills=(fill,))

    def place_market(self, side: str, size: int) -> list[Fill]:
        fill = Fill(order_id=11, price=Decimal("101.0"), size=size, ts_ns=self.ts_ns)
        self.signed_position += size if side == "buy" else -size
        return [fill]

    def cancel(self, order_id: int) -> bool:
        return order_id == 10

    def book_top(self) -> tuple[Decimal, Decimal]:
        return Decimal("100.0"), Decimal("101.0")

    def book_depth(self, levels: int) -> tuple[tuple[object, ...], tuple[object, ...]]:
        return (), ()

    def position(self) -> int:
        return self.signed_position


class NoFillEngine:
    def apply_event(self, event: MBOEvent) -> list[Fill]:
        return []

    def advance_time(self, ts_ns: int) -> None:
        pass

    def place_limit(
        self,
        side: str,
        price: Decimal,
        size: int,
        tif: str = "GTC",
    ) -> OrderResult:
        return OrderResult(order_id=None)

    def place_market(self, side: str, size: int) -> list[Fill]:
        return []

    def cancel(self, order_id: int) -> bool:
        return False

    def book_top(self) -> tuple[Decimal | None, Decimal | None]:
        return None, None

    def book_depth(self, levels: int) -> tuple[tuple[object, ...], tuple[object, ...]]:
        return (), ()

    def position(self) -> int:
        return 0


def gc_spec() -> InstrumentSpec:
    return InstrumentSpec(
        symbol="GC",
        tick_size=Decimal("0.10"),
        point_value=Decimal("100"),
    )


def tiny_events() -> tuple[MBOEvent, ...]:
    return (
        MBOEvent(
            ts_ns=1,
            action="add",
            side="ask",
            price=Decimal("101.0"),
            size=1,
            order_id=1,
        ),
    )


def test_default_execution_engine_factory_returns_reference_engine() -> None:
    engine = default_execution_engine_factory()

    assert engine.book_top() == (None, None)


def test_replay_accepts_execution_engine_factory() -> None:
    created: list[ScriptedEngine] = []

    def factory() -> ExecutionEngine:
        engine = ScriptedEngine()
        created.append(engine)
        return engine

    replay = Replay(
        data=tiny_events(),
        instrument=gc_spec(),
        execution_engine_factory=factory,
    )

    def strategy(gateway) -> None:
        gateway.advance_to(1)
        bid, _ask = gateway.book_top()
        gateway.place_limit(side="buy", price=bid, size=2)

    result = replay.run(strategy)

    assert len(created) == 1
    assert created[0].events == list(tiny_events())
    assert result.final_position == 2
    assert [(fill.price, fill.size) for fill in result.fills] == [
        (Decimal("100.0"), 2),
    ]


def test_run_many_uses_fresh_engine_per_strategy() -> None:
    created: list[ScriptedEngine] = []

    def factory() -> ExecutionEngine:
        engine = ScriptedEngine()
        created.append(engine)
        return engine

    replay = Replay(
        data=tiny_events(),
        instrument=gc_spec(),
        execution_engine_factory=factory,
    )

    def strategy(gateway) -> None:
        gateway.advance_to(1)

    replay.run_many({"a": strategy, "b": strategy})

    assert len(created) == 2
    assert created[0] is not created[1]
    assert [engine.events for engine in created] == [
        list(tiny_events()),
        list(tiny_events()),
    ]


def test_compare_execution_engines_reports_equivalent_results() -> None:
    def strategy(gateway) -> None:
        gateway.advance_to(1)
        gateway.place_market(side="buy", size=1)

    result = compare_execution_engines(
        data=tiny_events(),
        instrument=gc_spec(),
        strategy=strategy,
        candidate_factory=MatchingEngine,
    )

    assert result.equivalent is True
    assert result.reference == result.candidate


def test_assert_equivalent_execution_engines_returns_result() -> None:
    def strategy(gateway) -> None:
        gateway.advance_to(1)
        gateway.place_market(side="buy", size=1)

    result = assert_equivalent_execution_engines(
        data=tiny_events(),
        instrument=gc_spec(),
        strategy=strategy,
        candidate_factory=MatchingEngine,
    )

    assert result.equivalent is True


def test_assert_equivalent_execution_engines_reports_differences() -> None:
    def strategy(gateway) -> None:
        gateway.advance_to(1)
        gateway.place_market(side="buy", size=1)

    with pytest.raises(AssertionError) as exc_info:
        assert_equivalent_execution_engines(
            data=tiny_events(),
            instrument=gc_spec(),
            strategy=strategy,
            candidate_factory=NoFillEngine,
        )

    message = str(exc_info.value)
    assert "fills differ" in message
    assert "final positions differ" in message
    assert "order events differ" in message
