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
| `F` | Normalized to resting-side `trade`. |
| `T` / `N` | Ignored because they do not identify resting-side book mutation. |

Databento's raw `Trade` record carries the aggressor side, while `Fill` carries
the resting side. `ordersim` needs resting-side execution volume to model
passive fills, so the connector uses `Fill` records for normalized `trade`
events. Databento also emits a paired `Cancel` for book mutation; within one
Databento publisher event group, the connector keeps the `Fill`-derived
`trade` and drops the paired `Cancel` so the simulator does not consume the
same visible quantity twice. Unsided `Fill` records are ignored because they do
not identify a visible resting book side to consume.

Leading Databento `R` clear records are ignored because a fresh `Replay` starts
from an empty book already. Mid-stream clear records are rejected: the current
public event schema has no clear-book action, so silently accepting them would
make replay state wrong. Records marked `F_MBP` are also rejected because they
represent aggregated price-level updates rather than order-level MBO.
