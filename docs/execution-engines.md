# Execution Engines

`ordersim` deliberately has two execution paths:

- the C++ engine is the preferred default for ordinary replay when available;
- the Python engine is the readable reference used to inspect behavior and
  prove equivalence.

That split is intentional. It keeps a readable reference model while allowing
compiled paths to scale without changing public semantics.

Execution engines consume normalized `MBOEvent` rows and strategy order intents.
They do not read vendor data directly.

The architecture is:

```text
vendor data -> DataSource -> MBOEvent -> Replay -> ExecutionEngine
```

That means a Databento connector and a C++ execution engine are different
extension points:

- a connector normalizes source data into `MBOEvent`;
- an execution engine decides how strategy orders interact with those events.

## Reference Engine

`MatchingEngine` is the pure Python reference engine. It is intentionally
plain and inspectable. Public behavior should be judged against it.

## Default Selection

`Replay(...)` prefers `CppMatchingEngine` when the compiled extension is
available. Packaged wheels are expected to include that extension. The compiled
engine is the normal default once behavioral equivalence has been proven, so
users exercise the implementation the project intends to scale over time.

Ordinary audited `Replay(...)` currently still applies one event at a time so it
can preserve per-event valuation marks and result assembly. The compiled batch
path is a separate direct-engine API for callers who own the event loop.

If the extension is unavailable, `Replay(...)` falls back to `MatchingEngine`.
Pass `execution_engine_factory=MatchingEngine` when the Python version is the
better tool:

- stepping through queue behavior in a debugger;
- teaching or documenting the model;
- developing or reviewing a new engine;
- running in an environment where building extensions is not worthwhile.

Skipping the C++ engine is an observability choice, not a fidelity choice. The
two engines are expected to preserve the same public replay behavior.

## Compiled Engine Policy

A compiled execution engine may be used for scale, but it must implement the
`ExecutionEngine` protocol and preserve observable behavior:

- same input events;
- same strategy order intents;
- same fills;
- same final position;
- same own resting orders;
- same execution summary;
- same equity curve;
- same order-intent log where replay exposes it.

Non-default execution engines are selected by passing an engine factory to `Replay`:

```python
replay = Replay(
    data=source,
    instrument=spec,
    execution_engine_factory=my_execution_engine_factory,
)
```

`Replay.run_many(...)` creates a fresh engine for each strategy run, so each
strategy has isolated order state while sharing the same immutable event stream.

## C++ Engine

`CppMatchingEngine` is the first compiled implementation. The core
stores integer ticks; the Python wrapper accepts an explicit `tick_size` so the
public API remains exact-`Decimal`.

For callers that already hold normalized events in memory, the wrapper also
exposes a compiled batch-ingest path. It accepts primitive columns derived from
the same `MBOEvent` schema and returns passive fills without changing the public
matching semantics. Ordinary `Replay(...)` still applies one event at a time so
it can record the per-event valuation marks that build the default equity curve.

```python
from ordersim import CompiledEventColumns, CppMatchingEngine

columns = CompiledEventColumns.from_events(events, tick_size=spec.tick_size)
engine = CppMatchingEngine(tick_size=spec.tick_size)
fills = engine.apply_events_batch(columns.slice(0, len(events)))
```

The wrapper also exposes `apply_events_until_fill(...)`, which is the first
low-level primitive for boundary-batched replay. It lets the C++ engine consume
a compiled market-data slice independently until either the slice ends or a
passive fill occurs. The method returns both the number of events consumed and
the fills produced at the boundary, so a future replay loop can resume Python at
the exact point where strategy-visible execution state changed.

```python
events_consumed, fills = engine.apply_events_until_fill(
    columns.slice(start, stop),
)
```

This primitive does not change ordinary audited `Replay(...)` yet. It exists so
the faster path can be wired in carefully without weakening replay
inspectability.

`advance_until_fill_boundary(...)` is the Python-side helper that wraps this
idea. It uses the compiled boundary method when the engine and columns support
it, and otherwise falls back to scalar `apply_event(...)` calls. That lets tests
prove the same boundary behavior through the readable Python path and the C++
path before replay integration depends on it.

Install a source checkout normally to build the extension:

```bash
python -m pip install -e ".[dev]"
```

`Replay(...)` uses it automatically when it is importable. You can also select
it explicitly through the normal replay boundary:

```python
from ordersim import CppMatchingEngine, Replay

replay = Replay(
    data=source,
    instrument=spec,
    execution_engine_factory=lambda: CppMatchingEngine(
        tick_size=spec.tick_size,
    ),
)
```

`cpp_execution_engine_available()` reports whether the compiled extension is
currently importable. The Python engine remains a valid fallback for source
installs where the extension was not built or is intentionally omitted.

The repository also runs native C++ core tests in CI. Those tests catch
low-level engine regressions before Python enters the picture; the replay
equivalence suite is still required because native tests alone cannot prove the
public API remains identical.

For performance measurements, see `docs/benchmarks.md`. Direct engine
throughput and full replay throughput are intentionally measured separately
because they answer different questions.

## Equivalence Harness

Compiled or alternative execution engines must prove replay equivalence against
the Python `MatchingEngine` before release. Use the public test helper:

```python
from ordersim.testing import assert_equivalent_execution_engines

assert_equivalent_execution_engines(
    data=source,
    instrument=spec,
    strategy=strategy,
    candidate_factory=my_execution_engine_factory,
)
```

For a tiny public queue-priority case, use
`SyntheticSource.execution_equivalence_mbo()` as the data input. It exercises
add, modify, cancel, trade, queue-ahead consumption, and passive fill behavior
without requiring paid market data.

For the built-in smoke suite, use:

```python
from ordersim.testing import assert_execution_equivalence_suite

assert_execution_equivalence_suite(
    instrument=spec,
    candidate_factory=my_execution_engine_factory,
)
```

The suite currently includes:

- `market-order-crosses-spread`;
- `queue-ahead-passive-fill`.

The harness runs the same immutable event stream and strategy through the
reference engine and the candidate engine. It compares:

- fills;
- final position;
- own resting orders;
- execution summary;
- equity curve;
- order-intent log.

This is the required path for future C++ engines. Performance can improve, but
observable replay behavior must not change.
