from benchmarks.execution_engine_throughput import build_workload, run_engine
from ordersim import MatchingEngine


def test_execution_engine_benchmark_workload_is_balanced() -> None:
    events = build_workload(cycles=3)
    engine = MatchingEngine()

    run_engine(engine, events)

    assert len(events) == 18
    assert engine.book_top() == (None, None)
