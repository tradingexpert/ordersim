# Connectors

Connectors translate vendor data into the public `MBOEvent` schema.

The public contract is intentionally small:

```python
class DataSource(Protocol):
    def events(self) -> Iterable[MBOEvent]: ...
```

A connector should hide SDK details, file layout, network access, and vendor
column names. Replay code should receive only normalized `MBOEvent` rows.

Normalized `ts_ns` values must be UTC Unix-epoch nanoseconds. Connectors may
read exchange-local, vendor-local, or already-UTC source timestamps, but they
must emit timezone-normalized UTC integers. If the source uses wall-clock local
time, conversion must be timezone-aware and must handle daylight-saving
transitions explicitly.

## Required Documentation

Every connector should state:

- source schema and vendor;
- source timestamp units and timezone;
- how source timestamps are converted into UTC Unix-epoch nanoseconds;
- whether timestamps are exchange-time or receive-time;
- price units and size units;
- order-id stability;
- lossy conversions or unsupported source events;
- assumptions needed to produce `MBOEvent`.

## Required Tests

Every connector should include a tiny public fixture or generator and at least
one deterministic replay test. The test should prove the connector can produce
events that a strategy can replay without private data.

## Recommended Workflow

For repeated research, normalize raw vendor data once, materialize the canonical
Parquet form, and replay from `ParquetSource` thereafter:

```python
import databento as db

from ordersim import DatabentoMboSource, ParquetSource, Replay, write_parquet

store = db.DBNStore.from_file("GLBX.MDP3-ES-20260102.mbo.dbn.zst")
raw_source = DatabentoMboSource(store)
write_parquet(raw_source, "events.parquet")

source = ParquetSource("events.parquet")
replay = Replay(data=source, instrument=spec)
```

This is the preferred path for durable research datasets. It keeps raw vendor
semantics at the ingestion boundary, gives repeated runs one canonical local
format, and avoids re-normalizing the same source on every replay.

Direct connector replay remains useful for smoke tests, one-off inspection, and
connector development. CSV remains useful for tiny examples and reviewable
fixtures.

## Binance L2 Capture

Binance USD-M futures publishes aggregated price-level depth rather than stable
market-by-order identifiers. The capture tool therefore records source evidence
but does not expose it as `MBOEvent` data.

Install the optional WebSocket dependency:

```bash
pip install "ordersim[binance]"
```

Record three days of standard depth, aggregate trades, real-time top-of-book,
and the optional RPI depth stream:

```bash
ordersim-binance-capture captures/binance \
  --symbol BTCUSDT \
  --symbol ETHUSDT \
  --duration-hours 72 \
  --include-rpi
```

The recorder uses Binance's USD-M futures sources:

| Evidence | Source behavior |
|---|---|
| Diff depth | Absolute price-level quantities at up to 100 ms updates. |
| Aggregate trades | Trades grouped by price and taking side over 100 ms. |
| Book ticker | Real-time best bid and ask for integrity checks. |
| RPI depth | Optional 500 ms depth including RPI orders. |
| REST snapshot | Initial visible book, requested after the depth stream opens. |

Each raw exchange payload is preserved inside a gzip JSONL envelope with:

- UTC receive time in nanoseconds;
- local monotonic receive time in nanoseconds;
- source scope and stream name;
- a connection identifier;
- the untouched JSON payload.

The recorder writes hourly files and one manifest per process. It also records
a `sequence_gap` row whenever a depth event's `pu` value does not equal the
prior event's `u` value within the same connection. A reconnect begins a new
connection segment and obtains a new REST snapshot.

These files are intentionally not canonical replay data. Binance depth has no
stable public order IDs, and individual additions and cancellations inside an
update window are not observable. A future named L2-to-virtual-L3 model will
consume the capture, document the inference policy, and only then emit modeled
`MBOEvent` rows.

Capture files are local research data and must not be committed to the
repository.

For the user-facing decision guide, see `docs/data-guide.md`.

## In-Memory Sources

Use `InMemorySource` for tests, examples, and tiny fixtures:

```python
source = InMemorySource.from_events("tiny", events)
replay = Replay(data=source, instrument=spec)
```

`InMemorySource` is not a vendor connector. It is the smallest useful
implementation of the `DataSource` contract.

## Normalized CSV Sources

Use `CsvSource` when you already have rows in the canonical `MBOEvent` schema:

```python
from ordersim import CsvSource, Replay

source = CsvSource("events.csv")
replay = Replay(data=source, instrument=spec)
```

The required CSV columns are:

```text
ts_ns,action,side,price,size,order_id
```

Extra columns are ignored. Prices are parsed as `Decimal`; timestamps, sizes,
and order ids are parsed as integers. The CSV source is intentionally strict
because it is a reviewable interchange format for examples, fixtures, and
simple user data.

`CsvSource` expects `ts_ns` to already be normalized UTC Unix-epoch
nanoseconds. It does not parse local datetime strings or infer timezone rules.

`CsvSource` is not a vendor adapter. A Databento, LOBSTER, or exchange-specific
connector should convert its source schema into this canonical shape and
document any lossy conversion.

## Normalized Parquet Sources

Use `ParquetSource` when you already have rows in the canonical `MBOEvent`
schema and want a columnar source for larger local datasets:

```python
from ordersim import ParquetSource, Replay

source = ParquetSource("events.parquet")
replay = Replay(data=source, instrument=spec)
```

Install the optional Parquet dependency when you need this reader:

```bash
pip install "ordersim[parquet]"
```

The required Parquet columns are the same canonical fields as CSV:

```text
ts_ns,action,side,price,size,order_id
```

`ParquetSource` expects `ts_ns` to already be normalized UTC Unix-epoch
nanoseconds. Prices should be stored as strings or exact decimal-compatible
values when possible; the reader converts them into public `Decimal` prices.
Extra columns are ignored.

`CsvSource` and `ParquetSource` intentionally share the same strict canonical
row parser so identical event rows normalize the same way in both formats.

Use `write_parquet(...)` to materialize any normalized iterable or `DataSource`
into the canonical Parquet schema:

```python
from ordersim import write_parquet

write_parquet(source, "events.parquet")
```

## Databento MBO Sources

Use `DatabentoMboSource` with raw Databento MBO records, such as records yielded
by an iterable `DBNStore`:

```python
import databento as db

from ordersim import DatabentoMboSource, Replay

store = db.DBNStore.from_file("GLBX.MDP3-ES-20260102.mbo.dbn.zst")
source = DatabentoMboSource(store)
replay = Replay(data=source, instrument=spec)
```

Install the optional Databento client when you need to fetch or read Databento
records:

```bash
pip install "ordersim[databento]"
```

### Databento Mapping

`DatabentoMboSource` expects raw MBO records with Databento's native integer
price units:

| Databento field | Normalized handling |
|---|---|
| `ts_event` | Default `ts_ns`; already UTC Unix-epoch nanoseconds. |
| `ts_recv` | Optional `ts_ns` when `timestamp_field="ts_recv"`. |
| `price` | Raw integer nanounits converted exactly to `Decimal`. |
| `A` / `M` / `C` | Normalized to `add` / `modify` / `cancel`. |
| `T` | Normalized to `trade`; the aggressor side is inverted into the resting book side. |
| `F` | Used to infer the resting side for unsided `T` rows, or as a fallback when a usable `T` row is absent. |
| `N` | Ignored because it does not identify book mutation. |

Databento's raw `Trade` record carries the aggressor side and the full trade
quantity, while `Fill` carries the resting side of public executions. The full
`Trade` quantity matters when simulated own orders rest inside the visible
queue: the quantity that reaches an own order may be larger than the public
fills present in the historical feed. When a usable `Trade` row exists,
`ordersim` therefore keeps that full quantity and derives the resting side by
inverting the aggressor side. For an unsided `Trade`, a single sided `Fill`
side in the same publisher event group can supply the resting side.

If a publisher event group has no usable `Trade` row, the connector falls back
to sided `Fill` rows as normalized `trade` events. Databento also emits paired
`Cancel` rows for public book mutation; within one publisher event group, the
connector drops cancels paired with fills so the simulator does not consume the
same visible quantity twice. Unsided `Fill` rows are ignored because they do not
identify a visible resting book side to consume.

Leading Databento `R` clear records are ignored because a fresh `Replay` starts
from an empty book already. Mid-stream clear records are rejected: the current
public event schema has no clear-book action, so silently accepting them would
make replay state wrong. Records marked `F_MBP` are also rejected because they
represent aggregated price-level updates rather than order-level MBO.
