# Execution Engines

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

## Compiled Engine Policy

A compiled execution engine may be added for scale, but it must implement the
`ExecutionEngine` protocol and preserve observable behavior:

- same input events;
- same strategy order intents;
- same fills;
- same final position;
- same own resting orders;
- same execution summary;
- same equity curve;
- same order-intent log where replay exposes it.

Compiled execution engines are selected by passing an engine factory to `Replay`:

```python
replay = Replay(
    data=source,
    instrument=spec,
    execution_engine_factory=my_execution_engine_factory,
)
```

`Replay.run_many(...)` creates a fresh engine for each strategy run, so each
strategy has isolated order state while sharing the same immutable event stream.

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
