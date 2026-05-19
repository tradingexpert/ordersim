from decimal import Decimal

import pytest

from benchmarks.replay_throughput import advance_to_end, gc_spec, run_replay
from benchmarks.workloads import build_mixed_mbo_workload
from ordersim import MatchingEngine


def test_mixed_benchmark_workload_is_balanced() -> None:
    events = build_mixed_mbo_workload(cycles=3)
    engine = MatchingEngine()

    for event in events:
        engine.apply_event(event)

    assert len(events) == 18
    assert engine.book_top() == (None, None)


def test_mixed_benchmark_workload_rejects_empty_runs() -> None:
    with pytest.raises(ValueError, match="cycles must be positive"):
        build_mixed_mbo_workload(cycles=0)


def test_replay_benchmark_uses_a_complete_replay_run() -> None:
    events = build_mixed_mbo_workload(cycles=1)
    strategy = advance_to_end(events[-1].ts_ns)

    assert gc_spec().tick_size == Decimal("0.10")
    strategy_name = strategy.__name__
    run_replay(events, execution_engine_factory=MatchingEngine)

    assert strategy_name == "strategy"
