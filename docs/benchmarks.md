# Benchmarks

Benchmarks answer narrow performance questions without changing replay
semantics. They are machine-dependent comparisons, not universal throughput
promises.

## Shared Workload

The public benchmark scripts use the same deterministic mixed MBO workload.
Each six-event cycle performs:

1. bid add;
2. ask add;
3. bid modify;
4. bid trade;
5. ask cancel;
6. bid cancel.

The cycle ends with an empty visible book, so repeated cycles do not accumulate
state from earlier cycles.

## Direct Engine Throughput

Run:

```bash
python -m benchmarks.engine_throughput
```

This benchmark measures event ingestion through the execution engine itself:

| Path | What it measures |
|---|---|
| `MatchingEngine` scalar | `apply_event(MBOEvent)` on the Python reference engine |
| `CppMatchingEngine` scalar | `apply_event(MBOEvent)` one event at a time |
| `CppMatchingEngine` batch | `apply_events_batch(...)` over precompiled primitive columns |

The batch result excludes `CompiledEventColumns.from_events(...)` construction.
That conversion is meant to happen once before repeated compiled-engine runs;
including it would answer a different question.

## Full Replay Throughput

Run:

```bash
python -m benchmarks.replay_throughput
```

This benchmark measures the ordinary audited workflow:

```text
Replay(...) construction + strategy advance_to(end) + result assembly
```

It compares the explicit Python reference engine with the default engine chosen
by `Replay(...)`. Full replay is slower than direct engine ingestion because it
also performs the work that makes `ordersim` inspectable:

- event-by-event replay advancement;
- per-event valuation marks when both sides of the book exist;
- fill-ledger and equity-curve assembly;
- strategy-facing gateway calls.

## Interpreting Results

Direct engine throughput answers, "how quickly can the engine consume already
normalized events?"

Full replay throughput answers, "how quickly can the normal audited research
workflow produce a `ReplayResult`?"

Both numbers matter. They should not be collapsed into one claim.

## What This Exposes

The intended next performance step is boundary-batched replay. In that design,
the compiled engine can advance independently through market-data events until
the next point where Python must observe or decide:

- the strategy asks to advance only up to a timestamp;
- a passive fill occurs and strategy logic may need to react;
- a new order or cancel instruction reaches simulated venue time;
- replay needs a configured inspection or valuation mark.

That keeps the C++ path useful beyond direct engine benchmarks without giving
up the auditability of `ReplayResult`. It also keeps fill-connected strategies
honest: Python should regain control when execution state changes in a way the
strategy can observe.

The first engine primitive for that design is
`CppMatchingEngine.apply_events_until_fill(...)`. It consumes a compiled slice
until the first passive fill boundary and returns the event count needed to
resume replay at the correct row.

The corresponding Python helper is `advance_until_fill_boundary(...)`. It keeps
the boundary contract testable on the scalar reference engine and the compiled
engine, which is the step before changing the ordinary replay loop.

CI should keep benchmark code runnable; it should not enforce fixed speed
thresholds across hardware.
