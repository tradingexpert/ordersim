"""Compare raw Python and C++ execution-engine event throughput.

This benchmark measures the lowest-level public engine path:
``ExecutionEngine.apply_event(MBOEvent)``. It deliberately excludes replay,
strategy callbacks, and ``run_many`` orchestration so the result answers one
question cleanly: how quickly can each engine consume the same normalized MBO
event stream?
"""

import argparse
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from statistics import median
from time import perf_counter

from ordersim import CppMatchingEngine, MatchingEngine, MBOEvent
from ordersim.sim import ExecutionEngine, cpp_execution_engine_available

TICK_SIZE = Decimal("0.10")


@dataclass(frozen=True, slots=True)
class BenchmarkResult:
    """One engine's measured throughput over the benchmark workload."""

    engine_name: str
    event_count: int
    median_seconds: float

    @property
    def events_per_second(self) -> float:
        """Return median event throughput."""

        return self.event_count / self.median_seconds


def build_workload(cycles: int) -> tuple[MBOEvent, ...]:
    """Build deterministic MBO cycles that end with an empty visible book."""

    if cycles <= 0:
        raise ValueError("cycles must be positive")

    events: list[MBOEvent] = []
    ts_ns = 1
    for cycle in range(cycles):
        bid_order_id = 2 * cycle + 1
        ask_order_id = 2 * cycle + 2
        events.extend(
            (
                MBOEvent(
                    ts_ns=ts_ns,
                    action="add",
                    side="bid",
                    price=Decimal("100.0"),
                    size=5,
                    order_id=bid_order_id,
                ),
                MBOEvent(
                    ts_ns=ts_ns + 1,
                    action="add",
                    side="ask",
                    price=Decimal("101.0"),
                    size=5,
                    order_id=ask_order_id,
                ),
                MBOEvent(
                    ts_ns=ts_ns + 2,
                    action="modify",
                    side="bid",
                    price=Decimal("100.0"),
                    size=4,
                    order_id=bid_order_id,
                ),
                MBOEvent(
                    ts_ns=ts_ns + 3,
                    action="trade",
                    side="bid",
                    price=Decimal("100.0"),
                    size=2,
                    order_id=bid_order_id,
                ),
                MBOEvent(
                    ts_ns=ts_ns + 4,
                    action="cancel",
                    side="ask",
                    price=Decimal("101.0"),
                    size=5,
                    order_id=ask_order_id,
                ),
                MBOEvent(
                    ts_ns=ts_ns + 5,
                    action="cancel",
                    side="bid",
                    price=Decimal("100.0"),
                    size=2,
                    order_id=bid_order_id,
                ),
            )
        )
        ts_ns += 6
    return tuple(events)


def run_engine(engine: ExecutionEngine, events: Sequence[MBOEvent]) -> None:
    """Apply every benchmark event to one fresh engine."""

    for event in events:
        engine.apply_event(event)


def measure(
    engine_name: str,
    engine_factory: Callable[[], ExecutionEngine],
    events: Sequence[MBOEvent],
    *,
    repeats: int,
    warmups: int,
) -> BenchmarkResult:
    """Return median throughput timing for one engine factory."""

    if repeats <= 0:
        raise ValueError("repeats must be positive")
    if warmups < 0:
        raise ValueError("warmups must be non-negative")

    for _ in range(warmups):
        run_engine(engine_factory(), events)

    timings: list[float] = []
    for _ in range(repeats):
        started = perf_counter()
        run_engine(engine_factory(), events)
        timings.append(perf_counter() - started)

    return BenchmarkResult(
        engine_name=engine_name,
        event_count=len(events),
        median_seconds=median(timings),
    )


def format_result(result: BenchmarkResult) -> str:
    """Render one benchmark result as a compact terminal row."""

    return (
        f"{result.engine_name:<18}"
        f"{result.event_count:>10,} events  "
        f"{result.median_seconds:>8.4f} s  "
        f"{result.events_per_second:>12,.0f} events/s"
    )


def main() -> None:
    """Run the public benchmark from the command line."""

    parser = argparse.ArgumentParser(
        description="Compare raw Python and C++ execution-engine throughput."
    )
    parser.add_argument(
        "--cycles",
        type=int,
        default=20_000,
        help="number of six-event benchmark cycles to generate",
    )
    parser.add_argument(
        "--repeats",
        type=int,
        default=5,
        help="number of measured runs per engine",
    )
    parser.add_argument(
        "--warmups",
        type=int,
        default=1,
        help="number of discarded warmup runs per engine",
    )
    args = parser.parse_args()

    events = build_workload(args.cycles)
    python_result = measure(
        "MatchingEngine",
        MatchingEngine,
        events,
        repeats=args.repeats,
        warmups=args.warmups,
    )

    print("Execution-engine throughput")
    print("---------------------------")
    print(format_result(python_result))

    if not cpp_execution_engine_available():
        print(
            "CppMatchingEngine unavailable; install a built ordersim wheel "
            "or build it."
        )
        return

    cpp_result = measure(
        "CppMatchingEngine",
        lambda: CppMatchingEngine(tick_size=TICK_SIZE),
        events,
        repeats=args.repeats,
        warmups=args.warmups,
    )
    print(format_result(cpp_result))
    speedup = cpp_result.events_per_second / python_result.events_per_second
    print(f"speedup             {speedup:>8.2f}x")


if __name__ == "__main__":
    main()
