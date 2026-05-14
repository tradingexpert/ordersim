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

Optional data connectors are installed separately:

```bash
pip install "ordersim[databento]"
```

## A Tiny Example

This is the target API shape for `v0.1`.

This example uses synthetic fixture data shipped with the package, so it does
not require a market-data subscription.

```python
from decimal import Decimal

from ordersim import Replay
from ordersim.connectors.synthetic import SyntheticSource
from ordersim.specs import InstrumentSpec


def strategy(gateway):
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
```

The important output is not just final PnL. The important output is the event
log showing what the strategy tried to do and what the simulated venue did in
response.

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
- `v0.2`: optional compiled matching backend, required to pass Python
  equivalence fixtures before release.
- `v1.0`: research-grade execution lab with notebook-first workflows,
  connector recipes, latency model gallery, and public replay-equivalence
  harness.

## Documentation

- Assumptions: `docs/assumptions.md`
- Engineering standards: `docs/engineering-standards.md`
- AI agent guide: `AGENTS.md`

API, schema, and extension recipe docs will land with the first package
skeleton.

## Contributing

The easiest first contribution is a data connector.

Good connector PRs:

- implement the `DataSource` protocol;
- include a tiny fixture or generator;
- document timestamp, price, size, and order-id semantics;
- add at least one replay test.

## License

MIT.
