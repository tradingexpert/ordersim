# Data Guide

The default `ordersim` data path is:

```text
raw vendor data -> connector -> canonical Parquet -> repeated replay
```

Normalize once at the boundary. Persist the normalized result. Replay the
canonical result.

That path keeps vendor-specific choices out of strategy experiments and gives
repeated runs one durable local format.

## Which Source To Use

| Situation | Use |
|---|---|
| Repeated research over a real dataset | `ParquetSource` |
| First normalization from a vendor format | vendor connector, then `write_parquet(...)` |
| One-off connector smoke test or inspection | direct connector replay |
| Tiny human-readable example | `CsvSource` |
| Test or package fixture | `InMemorySource` |

`CsvSource` is deliberately simple and reviewable. It is not the preferred
storage format for large research datasets.

## Recommended Workflow

For a vendor source such as Databento:

```python
import databento as db

from ordersim import DatabentoMboSource, ParquetSource, Replay, write_parquet

store = db.DBNStore.from_file("GLBX.MDP3-ES-20260102.mbo.dbn.zst")
raw_source = DatabentoMboSource(store)

write_parquet(raw_source, "canonical/ES/2026-01-02.parquet")

source = ParquetSource("canonical/ES/2026-01-02.parquet")
replay = Replay(data=source, instrument=spec)
```

On the first pass, the connector owns source-specific work: vendor columns,
timestamp semantics, price units, and unsupported events. After
materialization, repeated research runs consume the same canonical Parquet
schema.

## Why Materialize

Canonical Parquet is the preferred repeated-research format because it:

- avoids re-normalizing the same raw vendor data on every run;
- keeps experiments independent from vendor SDK behavior after ingestion;
- gives humans and AI agents one stable schema to inspect and reuse;
- makes connector outputs reviewable before strategy results depend on them;
- is a better fit than CSV for larger local datasets.

`write_parquet(...)` is explicit on purpose. Connectors do not hide cache
policies or silently change where data comes from.

## Practical Layout

For multi-day research, prefer one canonical file per instrument and session or
day instead of one giant mutable file:

```text
canonical/
  ES/
    2026-01-02.parquet
    2026-01-05.parquet
  GC/
    2026-01-02.parquet
```

This is a convention, not a required package layout. It keeps refreshes,
inspection, and selective replay straightforward.

## Direct Connector Replay

Direct connector replay is still useful when:

- writing or debugging a connector;
- checking a small raw file once;
- inspecting how a source normalizes before persisting it.

For repeated strategy work, prefer materialized Parquet after that first pass.

## Data Rules That Must Survive Normalization

All canonical sources must preserve the public `MBOEvent` contract:

- `ts_ns` is integer UTC Unix-epoch nanoseconds;
- `action` is one of `add`, `cancel`, `modify`, or `trade`;
- `side` is the resting book side, `bid` or `ask`;
- `price` remains exact at the public boundary;
- `size` is an integer quantity;
- `order_id` is stable enough for order-level replay.

If a vendor source cannot preserve one of those properties, document the loss in
the connector and decide whether the connector is valid for the research task.

Binance USD-M depth is one such lower-fidelity source. The Binance capture tool
records raw L2 depth, individual and aggregate trades, and integrity metadata,
but its output is not accepted by `Replay` as observed MBO.

This boundary is also what enables crypto research in `ordersim`. Rather than
falling back to touch-fill rules, the reconstruction path turns L2 and
individual-trade evidence into an auditable virtual MBO stream that can run
through the ordinary queue-aware execution engines. It preserves what was
observed, labels what was inferred, and keeps multiple queue assumptions
comparable.

After a capture completes, use `BinanceCaptureSource` to stream exact typed
snapshots, sequence-validated depth updates, trades, and book tickers. The main
capture preserves Binance's individual `@trade` stream. Run
`ordersim-binance-raw-trades` beside it for REST reconciliation and RPI trade
flags; retain `aggTrade` only as another reconciliation feed. That typed source
is the input boundary for the named virtual-L3 reconstruction model:

```text
raw capture -> BinanceCaptureSource -> named model -> modeled MBO + manifest
```

Use `BinanceMBOReconstructor` to produce canonical `MBOEvent` rows for one
snapshot-anchored connection segment. Use
`ordersim-binance-reconstruction-study` first on a new capture or symbol to
measure alignment, inferred flow, required replenishment, and the difference
between the named queue policies. Reconnect segments remain separate because
canonical MBO has no implicit clear-book event.

There is deliberately no direct
`BinanceCaptureSource -> Replay` path. See `docs/connectors.md` for the capture
and validation contract, and `docs/binance-reconstruction-study.md` for the
full-capture results and public realism challenge.

## Related Docs

- Connector details: `docs/connectors.md`
- Canonical schema: `docs/schema.md`
- Replay assumptions: `docs/assumptions.md`
