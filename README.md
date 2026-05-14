# ordersim

An inspectable, deterministic, Python-native execution simulator for replaying
real order-book data.

`ordersim` is built for researchers who need to audit every order intent,
compare many strategies on the exact same replay, and let humans or AI agents
write strategies against a small gateway API.

## What It Does

- Replays order-book data and simulates order execution with explicit order
  lifecycle events: place, cancel, fill, and passive fill.
- Runs multi-strategy A/B comparisons on the same replay while keeping each
  strategy's orders, position, and portfolio state isolated.
- Exposes a small, regular Python API that is easy to read, debug, test, and
  extend.

## What It Is Not

- It is not a general backtesting framework. You own the strategy loop.
- It is not a live trading system.
- It is not a signal library.
- It is not a speed-first HFT framework.

The design goal is clarity per line of code. Raw event throughput is secondary
to understanding why an order did or did not fill.

## Why This Exists

Most backtests hide execution behavior behind aggregate PnL. That is not enough
when the strategy depends on queue position, latency, cancel timing, partial
fills, and passive resting orders.

`ordersim` treats the order-intent log as a first-class artifact. A run should
answer:

- What did the strategy try to do?
- What did the simulated venue receive?
- Which orders filled immediately?
- Which orders rested?
- Which orders were cancelled?
- Which fills arrived passively later?
- Do two strategy variants behave differently on the same market replay?

## When To Use hftbacktest Instead

Use `hftbacktest` when you need a mature, speed-oriented HFT backtesting
framework with Rust/Numba acceleration, queue-position models, latency models,
and crypto-focused examples.

Use `ordersim` when you want a smaller Python library focused on inspectable
execution replay:

| Need | Better Fit |
|---|---|
| HFT throughput and optimized hot loops | `hftbacktest` |
| Crypto live-trading examples | `hftbacktest` |
| Pure Python debuggability | `ordersim` |
| Full order-intent audit logs | `ordersim` |
| Deterministic multi-strategy comparisons on one replay | `ordersim` |
| A small gateway API for human or AI-written strategies | `ordersim` |

The projects serve different workflows.

## Install

`ordersim` is in early public setup and is not published to PyPI yet. The
planned install path for the first release is:

```bash
pip install ordersim
```

Optional vendor connectors will be installed separately as extras:

```bash
pip install "ordersim[databento]"
```

Normalized CSV input works without optional dependencies:

```python
from ordersim import CsvSource

source = CsvSource("events.csv")
```

## A Tiny Example

This example uses synthetic fixture data shipped with the package, so it does
not require a market-data subscription. A runnable version lives in
`examples/canonical.py`.

```python
from decimal import Decimal

from ordersim import Replay
from ordersim.fixtures.synthetic import SyntheticSource
from ordersim.specs import InstrumentSpec


def strategy(gateway):
    gateway.advance_to(1_000_000_100)
    bid, ask = gateway.book_top()

    result = gateway.place_limit(
        side="buy",
        price=bid,
        size=1,
    )

    gateway.advance_to(gateway.now_ns() + 1_000_000_000)

    if gateway.position() == 0:
        if result.order_id is not None:
            gateway.cancel(result.order_id)
        gateway.place_market(side="buy", size=1)


spec = InstrumentSpec(
    symbol="GC",
    tick_size=Decimal("0.10"),
    point_value=Decimal("100"),
    commission_per_contract=Decimal("2.50"),
)

events = []
replay = Replay(
    data=SyntheticSource.small_mbo(),
    instrument=spec,
    record_to=events,
)

result = replay.run(strategy)

print(result.fills)
print(result.order_events)
print(result.execution_summary)
print(result.equity_curve)
```

The important output is not just final realized PnL. The important output is
the fill ledger, equity curve, and event log showing what the strategy tried to
do and what the simulated venue did in response.

Strategies advance replay time explicitly with `gateway.advance_to(...)`; the
library supplies execution semantics, not a strategy framework.

Replay can also apply entry latency before orders and cancels reach the
simulated venue:

```python
from ordersim import ConstantLatency

replay = Replay(
    data=SyntheticSource.small_mbo(),
    instrument=spec,
    latency_model_factory=lambda: ConstantLatency(entry_ns=25_000_000),
)
```

## Multi-Strategy Replay

`ordersim` can run several strategy variants over the same market replay while
keeping private state isolated:

```python
result = replay.run_many(
    {
        "baseline": baseline_strategy,
        "wider_quote": wider_quote_strategy,
        "faster_cancel": faster_cancel_strategy,
    }
)
```

The intended guarantee is solo-equivalence: the fills for `baseline` inside
`run_many()` should match the fills from running `baseline` by itself on the
same input.

## Status

Planned release sequence:

- `v0.1`: pure Python, inspectable by default.
- `v0.2`: optional compiled execution engine, required to pass Python
  equivalence fixtures before release.
- `v1.0`: research-grade execution lab with notebook-first workflows,
  connector recipes, latency model gallery, and public replay-equivalence
  harness.

## Documentation

- Assumptions: `docs/assumptions.md`
- Execution economics: `docs/economics.md`
- Execution engines: `docs/execution-engines.md`
- Latency models: `docs/latency.md`
- Connectors: `docs/connectors.md`
- Engineering standards: `docs/engineering-standards.md`
- Example: `examples/canonical.py`
- Schema reference: `docs/schema.md`
- AI agent guide: `AGENTS.md`

For execution-engine work, `SyntheticSource.execution_equivalence_mbo()` gives
contributors a tiny public queue-priority fixture to use with the equivalence
harness.

Compiled or alternative execution engines should pass
`ordersim.testing.assert_execution_equivalence_suite(...)` before they are
trusted.

## Contributing

The easiest first contribution is a data connector.

Good connector PRs:

- implement the `DataSource` protocol;
- include a tiny fixture or generator;
- document timestamp, price, size, and order-id semantics;
- add at least one replay test.

For simple examples, prefer the canonical `CsvSource` schema before adding a
new vendor-specific connector.

## License

MIT.
