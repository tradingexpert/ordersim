"""Replay-equivalence helpers for execution engine implementations."""

from dataclasses import dataclass

from ordersim.connectors import EventInput, normalize_events
from ordersim.latency import LatencyModelFactory
from ordersim.replay import Replay, ReplayResult
from ordersim.replay.simulator import Strategy
from ordersim.sim import ExecutionEngineFactory, default_execution_engine_factory
from ordersim.specs import InstrumentSpec


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
        raise AssertionError(_format_difference(result))
    return result


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
