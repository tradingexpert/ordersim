"""Replay-equivalence helpers for execution engine implementations."""

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

from ordersim.connectors import EventInput, normalize_events
from ordersim.fixtures.synthetic import SyntheticSource
from ordersim.gateway import OrderGateway
from ordersim.latency import LatencyModelFactory
from ordersim.replay import Replay, ReplayResult
from ordersim.replay.simulator import Strategy
from ordersim.sim import ExecutionEngineFactory, default_execution_engine_factory
from ordersim.specs import InstrumentSpec
from ordersim.types import MBOEvent


@dataclass(frozen=True, slots=True)
class ExecutionEquivalenceResult:
    """Pair of replay results produced by reference and candidate engines."""

    reference: ReplayResult
    candidate: ReplayResult

    @property
    def equivalent(self) -> bool:
        """Return whether candidate behavior matches the reference behavior."""

        return (
            self.reference.fills == self.candidate.fills
            and self.reference.final_position == self.candidate.final_position
            and self.reference.order_events == self.candidate.order_events
        )


@dataclass(frozen=True, slots=True)
class ExecutionEquivalenceCase:
    """Named replay scenario used to test an execution engine."""

    name: str
    data: tuple[MBOEvent, ...]
    strategy: Strategy


def compare_execution_engines(
    *,
    data: EventInput,
    instrument: InstrumentSpec,
    strategy: Strategy,
    candidate_factory: ExecutionEngineFactory,
    reference_factory: ExecutionEngineFactory = default_execution_engine_factory,
    latency_model_factory: LatencyModelFactory | None = None,
    strategy_name: str = "equivalence",
) -> ExecutionEquivalenceResult:
    """Run the same replay through reference and candidate execution engines."""

    events = normalize_events(data)
    reference = Replay(
        data=events,
        instrument=instrument,
        execution_engine_factory=reference_factory,
        latency_model_factory=latency_model_factory,
    ).run(strategy, strategy_name=strategy_name)
    candidate = Replay(
        data=events,
        instrument=instrument,
        execution_engine_factory=candidate_factory,
        latency_model_factory=latency_model_factory,
    ).run(strategy, strategy_name=strategy_name)
    return ExecutionEquivalenceResult(reference=reference, candidate=candidate)


def assert_equivalent_execution_engines(
    *,
    data: EventInput,
    instrument: InstrumentSpec,
    strategy: Strategy,
    candidate_factory: ExecutionEngineFactory,
    reference_factory: ExecutionEngineFactory = default_execution_engine_factory,
    latency_model_factory: LatencyModelFactory | None = None,
    strategy_name: str = "equivalence",
) -> ExecutionEquivalenceResult:
    """Assert that a candidate execution engine matches the reference engine."""

    result = compare_execution_engines(
        data=data,
        instrument=instrument,
        strategy=strategy,
        candidate_factory=candidate_factory,
        reference_factory=reference_factory,
        latency_model_factory=latency_model_factory,
        strategy_name=strategy_name,
    )
    if not result.equivalent:
        raise AssertionError(
            f"execution equivalence case {strategy_name!r} failed; "
            f"{_format_difference(result)}"
        )
    return result


def execution_equivalence_cases() -> tuple[ExecutionEquivalenceCase, ...]:
    """Return the built-in execution-engine equivalence cases."""

    return (
        ExecutionEquivalenceCase(
            name="market-order-crosses-spread",
            data=(
                MBOEvent(
                    ts_ns=1,
                    action="add",
                    side="ask",
                    price=Decimal("101.0"),
                    size=2,
                    order_id=10,
                ),
            ),
            strategy=_market_order_crosses_spread,
        ),
        ExecutionEquivalenceCase(
            name="queue-ahead-passive-fill",
            data=SyntheticSource.execution_equivalence_mbo(),
            strategy=_queue_ahead_passive_fill,
        ),
    )


def assert_execution_equivalence_suite(
    *,
    instrument: InstrumentSpec,
    candidate_factory: ExecutionEngineFactory,
    cases: Iterable[ExecutionEquivalenceCase] | None = None,
    reference_factory: ExecutionEngineFactory = default_execution_engine_factory,
    latency_model_factory: LatencyModelFactory | None = None,
) -> tuple[ExecutionEquivalenceResult, ...]:
    """Assert that a candidate execution engine passes every equivalence case."""

    selected_cases = tuple(cases or execution_equivalence_cases())
    return tuple(
        assert_equivalent_execution_engines(
            data=case.data,
            instrument=instrument,
            strategy=case.strategy,
            candidate_factory=candidate_factory,
            reference_factory=reference_factory,
            latency_model_factory=latency_model_factory,
            strategy_name=case.name,
        )
        for case in selected_cases
    )


def _market_order_crosses_spread(gateway: OrderGateway) -> None:
    gateway.advance_to(1)
    gateway.place_market(side="buy", size=1)


def _queue_ahead_passive_fill(gateway: OrderGateway) -> None:
    gateway.advance_to(2)
    gateway.place_limit(side="buy", price=Decimal("100.0"), size=1)
    gateway.advance_to(5)


def _format_difference(result: ExecutionEquivalenceResult) -> str:
    differences: list[str] = []
    if result.reference.fills != result.candidate.fills:
        differences.append(
            f"fills differ: reference={result.reference.fills!r} "
            f"candidate={result.candidate.fills!r}"
        )
    if result.reference.final_position != result.candidate.final_position:
        differences.append(
            "final positions differ: "
            f"reference={result.reference.final_position!r} "
            f"candidate={result.candidate.final_position!r}"
        )
    if result.reference.order_events != result.candidate.order_events:
        differences.append(
            f"order events differ: reference={result.reference.order_events!r} "
            f"candidate={result.candidate.order_events!r}"
        )
    return "execution engines are not equivalent; " + "; ".join(differences)
