# ordersim

An inspectable, deterministic execution simulator for replaying real order-book
data, with a Python-facing API and equivalent Python/C++ execution engines.

Most backtests collapse execution into a final PnL line. `ordersim` exists to
inspect the path between order intent and actual fills.

![Same replay, same strategy, different latency](https://raw.githubusercontent.com/tradingexpert/ordersim/main/docs/assets/latency-demo.svg)

It is built for researchers who need to audit every order intent, compare many
strategies on the exact same replay, and let humans or AI agents write
strategies against a small gateway API.

## Scope

`ordersim` focuses on execution replay and execution-aware simulation. Areas of
interest include order-book replay, market replay, latency modeling,
queue-position effects, fill simulation, execution modeling, execution-aware
backtesting, and market microstructure research.

The replay core is independent of asset class, venue, and data vendor. It
operates on one canonical `MBOEvent` contract; integrations are responsible for
reaching that boundary without hiding the fidelity of their source data.

## Two Data Fidelity Paths

`ordersim` supports two explicit routes into the same queue-aware replay:

| Path | Source evidence | Current reference implementation | Replay input |
|---|---|---|---|
| Observed MBO | Order-level events with stable order IDs | Databento MBO | Observed `MBOEvent` rows |
| Reconstructed virtual MBO | Sequence-valid L2 depth plus individual trades | Binance USD-M | Modeled `MBOEvent` rows plus a reconstruction manifest |

Databento and Binance are the integrations available today, not boundaries of
the architecture. Futures, crypto, and equity datasets from additional venues
and vendors should join through one of these fidelity paths without changing
the replay or execution-engine APIs. Normalized CSV and Parquet remain
vendor-neutral interchange and storage formats.

### Observed MBO

When a source provides stable order IDs, its connector can normalize the
observed add, cancel, modify, and trade events directly into `MBOEvent`. This is
the highest-fidelity path. Databento is the current reference implementation.

### Reconstructed Virtual MBO for Crypto L2

Most crypto venues publish market-by-price depth, not the stable order IDs
needed for true market-by-order replay. `ordersim` takes a different path: it
combines sequence-validated L2 depth with individual trades, reconciles every
price-level endpoint, and emits a deterministic **virtual MBO** stream under
explicit queue assumptions.

That means crypto data can use the same inspectable, queue-aware Python/C++
execution engines as observed MBO data without pretending the inferred orders
were observed at the exchange.

The first full Binance USD-M study reconstructed:

- **7,345,447 of 7,347,590 valid captured trades (99.9708%)**;
- **all 3,328,132 processed L2 depth endpoints**;
- **116,381 of 116,381 independently joinable top-of-book states**.

The remaining trades occurred at snapshot or capture boundaries where the
available evidence could not place them safely. These results prove alignment
and book consistency, not knowledge of Binance's hidden FIFO queue. The
recommended conservative policy and an optimistic sensitivity policy expose
that uncertainty instead of burying it inside one fill rule.

#### The Crypto Realism Challenge

Have a more realistic L2 execution model? Compare it with evidence. Use paired
L2/L3 data or live passive-order outcomes, disclose the queue and latency
assumptions, and report fill occurrence, filled quantity, and time-to-fill on
held-out observations. The benchmark should reward predictive execution
realism, not simply the ability to reproduce an L2 endpoint.

See the [full reconstruction study](https://github.com/tradingexpert/ordersim/blob/main/docs/binance-reconstruction-study.md) and
join the [public validation challenge](https://github.com/tradingexpert/ordersim/issues/62).

## What It Does

- Replays order-book data and simulates order execution with explicit order
  lifecycle events: place, cancel, fill, and passive fill.
- Prefers a compiled C++ engine for ordinary replay when it is available, while
  keeping a plain Python reference engine for inspection and equivalence tests.
- Exposes own resting orders with visible queue-ahead size during replay.
- Runs multi-strategy A/B comparisons on the same replay while keeping each
  strategy's orders, position, and portfolio state isolated.
- Exposes a small, regular Python API that is easy to read, debug, test, and
  extend.
- Accepts observed MBO directly or reconstructed virtual MBO produced from
  lower-fidelity evidence under an explicit, named model.

## What It Is Not

- It is not a general backtesting framework. You own the strategy loop.
- It is not a live trading system.
- It is not a signal library.
- It is not a speed-first HFT framework.

The design goal is clarity per line of code. Raw event throughput is secondary
to understanding why an order did or did not fill, but compiled speed is welcome
when it preserves the same observable behavior.

## Why This Exists

Aggregate PnL is not enough
when the strategy depends on queue position, latency, cancel timing, partial
fills, and passive resting orders.

`ordersim` treats the order-intent log as a first-class artifact. A run should
answer:

- What did the strategy try to do?
- What did the simulated venue receive?
- Which orders filled immediately?
- Which orders rested?
- How much visible queue remained ahead of a resting order?
- Which orders were cancelled?
- Which fills arrived passively later?
- Do two strategy variants behave differently on the same market replay?

The editorial argument for this kind of inspection lives at [Trading Reality — Markets in Production](https://tradingreality.com)

## When To Use hftbacktest Instead

Use `hftbacktest` when you need a mature, speed-oriented HFT backtesting
framework with Rust/Numba acceleration, queue-position models, latency models,
and crypto-focused examples.

Use `ordersim` when you want a smaller library with a Python-facing API focused
on inspectable execution replay:

| Need | Better Fit |
|---|---|
| HFT throughput and optimized hot loops | `hftbacktest` |
| Crypto live-trading examples | `hftbacktest` |
| Pure Python debuggability | `ordersim` |
| Full order-intent audit logs | `ordersim` |
| Deterministic multi-strategy comparisons on one replay | `ordersim` |
| A small gateway API for human or AI-written strategies | `ordersim` |

The projects serve different workflows.

## Engine Design

The pure Python engine is still the reference implementation, because it is the
clearest place to inspect queue behavior and prove equivalence. Packaged wheels
include the compiled `CppMatchingEngine`; ordinary `Replay(...)` runs prefer it
because it is the compiled implementation the project intends to keep
equivalent and scale over time. The direct C++ batch-ingest path is already
substantially faster for callers that own the event loop; ordinary audited
`Replay(...)` currently remains event-by-event so it can record per-event
valuation marks. Source checkouts build the extension during normal
installation:

```bash
python -m pip install -e ".[dev]"
```

If the extension is unavailable, `Replay(...)` falls back to the Python engine.
Use the Python engine explicitly when you are debugging fill behavior, teaching
the model, developing a new engine, or working in an environment where compiling
extensions is not worth the friction:

```python
from ordersim import MatchingEngine, Replay

replay = Replay(
    data=source,
    instrument=spec,
    execution_engine_factory=MatchingEngine,
)
```

Compiled-engine work is accepted only when it passes the same public
equivalence fixtures as the Python engine.

## Install

Install the current release from PyPI with:

```bash
pip install ordersim
```

Current optional integrations and file formats are installed separately as
extras:

```bash
pip install "ordersim[databento]"
pip install "ordersim[parquet]"
pip install "ordersim[binance]"
```

Normalized CSV input works without optional dependencies:

```python
from ordersim import CsvSource

source = CsvSource("events.csv")
```

For repeated research runs, the recommended path is to reach the canonical
`MBOEvent` boundary once, materialize Parquet, and replay from that thereafter.
For example, the current observed-MBO integration uses Databento:

```python
import databento as db

from ordersim import DatabentoMboSource, ParquetSource, write_parquet

store = db.DBNStore.from_file("GLBX.MDP3-ES-20260102.mbo.dbn.zst")
raw_source = DatabentoMboSource(store)
write_parquet(raw_source, "events.parquet")

source = ParquetSource("events.parquet")
```

Direct source replay is still useful for one-off inspection and connector
development. With the current Databento integration:

```python
import databento as db

from ordersim import DatabentoMboSource

store = db.DBNStore.from_file("GLBX.MDP3-ES-20260102.mbo.dbn.zst")
source = DatabentoMboSource(store)
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

For a visual latency comparison, run `examples/latency_demo.py`.

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

`0.1.x` is live on PyPI. The current public line includes the Python reference
engine, packaged C++ default, canonical `MBOEvent` -> Parquet -> replay workflow,
latency models, economics, public execution-equivalence fixtures, and an
observed-MBO connector for Databento plus an evidence-first Binance USD-M
L2-to-virtual-MBO reference implementation. Both integrations feed the same
vendor- and asset-class-independent replay boundary.

Planned next milestones:

- `v0.2`: broaden connector recipes, latency experiments, and notebook-first
  research ergonomics while keeping the C++ and Python engines equivalent.
- `v1.0`: research-grade execution lab with notebook-first workflows,
  connector recipes, latency model gallery, and public replay-equivalence
  harness.

## Documentation

- Assumptions: `docs/assumptions.md`
- Execution economics: `docs/economics.md`
- Execution engines: `docs/execution-engines.md`
- Latency models: `docs/latency.md`
- Architecture: `docs/architecture.md`
- Data guide: `docs/data-guide.md`
- Connectors: `docs/connectors.md`
- Binance reconstruction study: `docs/binance-reconstruction-study.md`
- Releasing: `docs/releasing.md`
- Engineering standards: `docs/engineering-standards.md`
- Benchmarks: `docs/benchmarks.md`
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
- document source timestamp semantics, UTC normalization, price, size, and
  order-id semantics;
- add at least one replay test.

For simple examples, prefer the canonical `CsvSource` schema before adding a
new vendor-specific connector.

## License

MIT.

## Demo gallery

| Demo | What it shows | Why it matters |
|---|---|---|
| `canonical.py` | Basic replay and fill inspection | Shows how order intent becomes fills |
| `latency_demo.py` | Same strategy under different latency assumptions | Shows why execution timing changes outcomes |
| `queue_position_changes_fills.py` | Resting order queue position | Shows why visible queue ahead matters |
| `passive_orders_and_adverse_selection.py` | Passive fills and adverse selection | Shows why fills are not automatically good news |
| `backtest_vs_execution_replay.py` | Strategy assumption vs execution path | Shows the backtest-to-production gap |
