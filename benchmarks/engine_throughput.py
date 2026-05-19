"""Measure direct execution-engine event throughput."""

import argparse
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from statistics import median
from time import perf_counter

from benchmarks.workloads import build_mixed_mbo_workload
from ordersim import (
    CompiledEventColumns,
    CppMatchingEngine,
    MatchingEngine,
    MBOEvent,
    cpp_execution_engine_available,
)
from ordersim.sim import ExecutionEngine

TICK_SIZE = Decimal("0.10")


@dataclass(frozen=True, slots=True)
class BenchmarkResult:
    """One measured direct-engine path."""

    path_name: str
    event_count: int
    median_seconds: float

    @property
    def events_per_second(self) -> float:
        """Return median event throughput."""

        return self.event_count / self.median_seconds


def run_scalar(engine: ExecutionEngine, events: Sequence[MBOEvent]) -> None:
    """Apply one event at a time through the public compatibility API."""

    for event in events:
        engine.apply_event(event)


def run_batch(engine: CppMatchingEngine, columns: CompiledEventColumns) -> None:
    """Apply one compiled event slice through the C++ batch API."""

    engine.apply_events_batch(columns.slice(0, len(columns.ts_ns)))


def run_batch_with_marks(
    engine: CppMatchingEngine,
    columns: CompiledEventColumns,
) -> None:
    """Apply one compiled event slice and return compact valuation marks."""

    engine.apply_events_batch_with_marks(columns.slice(0, len(columns.ts_ns)))


def measure(
    path_name: str,
    runner: Callable[[], None],
    *,
    event_count: int,
    repeats: int,
    warmups: int,
) -> BenchmarkResult:
    """Measure median elapsed time for one benchmark runner."""

    if repeats <= 0:
        raise ValueError("repeats must be positive")
    if warmups < 0:
        raise ValueError("warmups must be non-negative")

    for _ in range(warmups):
        runner()

    timings: list[float] = []
    for _ in range(repeats):
        started = perf_counter()
        runner()
        timings.append(perf_counter() - started)

    return BenchmarkResult(
        path_name=path_name,
        event_count=event_count,
        median_seconds=median(timings),
    )


def format_result(result: BenchmarkResult) -> str:
    """Render one direct-engine result as a compact terminal row."""

    return (
        f"{result.path_name:<28}"
        f"{result.event_count:>10,} events  "
        f"{result.median_seconds:>8.4f} s  "
        f"{result.events_per_second:>12,.0f} events/s"
    )


def main() -> None:
    """Run direct-engine throughput benchmarks from the command line."""

    parser = argparse.ArgumentParser(
        description="Measure direct execution-engine throughput."
    )
    parser.add_argument(
        "--cycles",
        type=int,
        default=20_000,
        help="number of six-event mixed MBO cycles to generate",
    )
    parser.add_argument(
        "--repeats",
        type=int,
        default=5,
        help="number of measured runs per path",
    )
    parser.add_argument(
        "--warmups",
        type=int,
        default=1,
        help="number of discarded warmup runs per path",
    )
    args = parser.parse_args()

    events = build_mixed_mbo_workload(args.cycles)
    columns = CompiledEventColumns.from_events(events, tick_size=TICK_SIZE)
    results = [
        measure(
            "MatchingEngine scalar",
            lambda: run_scalar(MatchingEngine(), events),
            event_count=len(events),
            repeats=args.repeats,
            warmups=args.warmups,
        )
    ]

    print("Direct execution-engine throughput")
    print("----------------------------------")
    print(format_result(results[0]))

    if not cpp_execution_engine_available():
        print("CppMatchingEngine unavailable; compiled paths were skipped.")
        return

    cpp_scalar = measure(
        "CppMatchingEngine per-event",
        lambda: run_scalar(CppMatchingEngine(tick_size=TICK_SIZE), events),
        event_count=len(events),
        repeats=args.repeats,
        warmups=args.warmups,
    )
    cpp_batch = measure(
        "CppMatchingEngine batch",
        lambda: run_batch(CppMatchingEngine(tick_size=TICK_SIZE), columns),
        event_count=len(events),
        repeats=args.repeats,
        warmups=args.warmups,
    )
    cpp_batch_marks = measure(
        "CppMatchingEngine batch+marks",
        lambda: run_batch_with_marks(
            CppMatchingEngine(tick_size=TICK_SIZE),
            columns,
        ),
        event_count=len(events),
        repeats=args.repeats,
        warmups=args.warmups,
    )
    results.extend((cpp_scalar, cpp_batch, cpp_batch_marks))

    for result in results[1:]:
        print(format_result(result))

    python_eps = results[0].events_per_second
    scalar_speedup = cpp_scalar.events_per_second / python_eps
    batch_speedup = cpp_batch.events_per_second / python_eps
    batch_marks_speedup = cpp_batch_marks.events_per_second / python_eps
    print(f"per-event C++ speedup vs Python  {scalar_speedup:>7.2f}x")
    print(f"batch C++ speedup vs Python      {batch_speedup:>7.2f}x")
    print(f"batch+marks speedup vs Python    {batch_marks_speedup:>7.2f}x")


if __name__ == "__main__":
    main()
