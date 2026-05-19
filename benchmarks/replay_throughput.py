"""Measure full audited replay throughput."""

import argparse
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from statistics import median
from time import perf_counter

from benchmarks.workloads import build_mixed_mbo_workload
from ordersim import (
    InstrumentSpec,
    MatchingEngine,
    MBOEvent,
    Replay,
    cpp_execution_engine_available,
)


@dataclass(frozen=True, slots=True)
class BenchmarkResult:
    """One measured replay path."""

    path_name: str
    event_count: int
    median_seconds: float

    @property
    def events_per_second(self) -> float:
        """Return median replay throughput."""

        return self.event_count / self.median_seconds


def gc_spec() -> InstrumentSpec:
    """Return the small benchmark instrument definition."""

    return InstrumentSpec(
        symbol="GC",
        tick_size=Decimal("0.10"),
        point_value=Decimal("100"),
    )


def advance_to_end(last_ts_ns: int) -> Callable:
    """Build the smallest strategy that consumes the full replay."""

    def strategy(gateway) -> None:
        gateway.advance_to(last_ts_ns)

    return strategy


def run_replay(
    events: tuple[MBOEvent, ...],
    *,
    execution_engine_factory=None,
) -> None:
    """Construct one replay and run it through the final event."""

    replay = Replay(
        data=events,
        instrument=gc_spec(),
        execution_engine_factory=execution_engine_factory,
    )
    replay.run(advance_to_end(events[-1].ts_ns))


def measure(
    path_name: str,
    runner: Callable[[], None],
    *,
    event_count: int,
    repeats: int,
    warmups: int,
) -> BenchmarkResult:
    """Measure median elapsed time for one replay runner."""

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
    """Render one replay result as a compact terminal row."""

    return (
        f"{result.path_name:<28}"
        f"{result.event_count:>10,} events  "
        f"{result.median_seconds:>8.4f} s  "
        f"{result.events_per_second:>12,.0f} events/s"
    )


def main() -> None:
    """Run replay throughput benchmarks from the command line."""

    parser = argparse.ArgumentParser(
        description="Measure full audited replay throughput."
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
    python_result = measure(
        "Replay + Python engine",
        lambda: run_replay(events, execution_engine_factory=MatchingEngine),
        event_count=len(events),
        repeats=args.repeats,
        warmups=args.warmups,
    )
    default_result = measure(
        "Replay + default engine",
        lambda: run_replay(events),
        event_count=len(events),
        repeats=args.repeats,
        warmups=args.warmups,
    )

    print("Full audited replay throughput")
    print("------------------------------")
    print(format_result(python_result))
    print(format_result(default_result))
    print(
        "default engine speedup vs Python"
        f"  {default_result.events_per_second / python_result.events_per_second:>7.2f}x"
    )
    if not cpp_execution_engine_available():
        print("CppMatchingEngine unavailable; the default path used Python.")


if __name__ == "__main__":
    main()
