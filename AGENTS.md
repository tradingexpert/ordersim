# Agent Guide

`ordersim` is a Python execution simulator. Strategies call a small gateway
API. The simulator replays order-book data and returns fills plus an audit log
of order intent.

The gateway is the public contract. Most other modules are implementation
details.

## Core Design Rules

- Prefer boring, explicit Python over clever abstractions.
- Keep public APIs small, typed, and stable.
- Keep timestamps in integer nanoseconds at public boundaries.
- Keep sizes as integers.
- Keep prices exact at public boundaries. Use `Decimal` or integer ticks where
  precision matters.
- Do not hide fidelity changes behind performance flags.
- Do not add live-trading behavior.
- Do not add signal-generation logic.

## Where Things Live

Some paths below are already present; paths marked "planned" are the next
extraction targets and should not be imported until they exist.

| Path | Purpose | Public API? |
|---|---|---|
| `ordersim/gateway.py` | Gateway protocol used by strategies | Yes |
| `ordersim/recording.py` | Recording wrapper for order-intent logs | Yes |
| `ordersim/specs.py` | Instrument specifications | Public extension surface |
| `ordersim/types.py` | Public dataclasses and type aliases | Yes |
| `ordersim/fixtures/` | Tiny public fixtures for examples and tests | Public |
| `ordersim/connectors/` | Data sources | Planned public extension surface |
| `ordersim/replay/simulator.py` | Replay orchestration and `run_many` | Yes |
| `ordersim/replay/factory.py` | Builds feed, venue, OMS, portfolio | Planned internal |
| `ordersim/sim/matching_engine.py` | MBO matching and queue tracking reference | Yes |
| `ordersim/sim/feed.py` | Event replay cursor | Planned internal |
| `ordersim/sim/venue.py` | Latency-aware venue simulation | Planned internal |
| `ordersim/oms/strategy_oms.py` | Order lifecycle management | Planned internal |
| `examples/` | Complete user-facing examples | Planned public |
| `docs/` | Assumptions, schemas, recipes | Public |

## Public Gateway Contract

Strategies should only rely on the gateway surface:

```python
class OrderGateway(Protocol):
    def place_limit(
        self,
        side: str,
        price: Decimal,
        size: int,
        tif: str = "GTC",
    ) -> OrderResult: ...
    def place_market(self, side: str, size: int): ...
    def cancel(self, order_id: int) -> bool: ...
    def book_top(self): ...
    def book_depth(self, levels: int): ...
    def position(self) -> int: ...
    def advance_to(self, ts_ns: int): ...
    def now_ns(self) -> int: ...
```

If a strategy needs another method, ask whether the method belongs on the
gateway or whether the strategy should own that state itself.

## Extension Recipes

### Add a Data Connector

1. Wait for, or add, the public `DataSource` protocol.
2. Convert source data into the canonical MBO event schema.
3. Add a tiny fixture or generator that does not require private data.
4. Add a replay test that proves at least one limit order can rest, fill, and
   cancel correctly.
5. Document source-specific assumptions in `docs/schema.md`.

Do not make optional vendor SDKs core dependencies. Put them behind extras such
as `ordersim[databento]`.

### Add an Instrument Spec

1. Add a plain `InstrumentSpec`.
2. Include symbol, tick size, point value, and commission defaults.
3. Mark the values as examples, not trading advice.
4. Add a test that verifies integer tick conversion.

### Add a Latency Model

1. Implement the `LatencyModel` protocol.
2. Make randomness seedable.
3. Document the model's assumptions and failure modes.
4. Add a deterministic test with a fixed seed.

Latency models should make assumptions visible. They should not imply that a
recorded latency path is the only realistic future path.

### Add a Matching Backend

Backends are implementation details. They must not change behavior.

Any compiled backend must pass replay-equivalence tests against the Python
backend before release:

- same input events;
- same strategy actions;
- same fills;
- same final position;
- same order-intent log where the public API observes it.

## Things Not To Do

- Do not add a strategy framework.
- Do not add live-trading connectors.
- Do not add broker credentials or account-specific formats to examples.
- Do not commit large market-data files.
- Do not add a "fast mode" that silently drops queue position, response
  latency, passive fills, or cancels.
- Do not rename public imports without a deprecation path.
- Do not make examples depend on paid data.

## Documentation Standards

Every public symbol needs:

- type hints;
- a short docstring;
- arguments and return value when non-obvious;
- one example if the object is an entry point.

Every model needs:

- its assumption;
- its expected input schema;
- what it does not model;
- a failure mode.

## Test Standards

Core tests should prove behavior, not implementation details:

- a market order crosses the spread;
- a resting limit order joins the back of the queue;
- public cancels reduce queue ahead when applicable;
- passive fills are recorded;
- `run_many` preserves solo-equivalence;
- seeded latency models are reproducible.

If a change touches matching, venue, OMS, or replay ordering, run the
solo-equivalence tests before merging.
