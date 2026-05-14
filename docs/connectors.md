# Connectors

Connectors translate vendor data into the public `MBOEvent` schema.

The public contract is intentionally small:

```python
class DataSource(Protocol):
    def events(self) -> Iterable[MBOEvent]: ...
```

A connector should hide SDK details, file layout, network access, and vendor
column names. Replay code should receive only normalized `MBOEvent` rows.

## Required Documentation

Every connector should state:

- source schema and vendor;
- timestamp units and timezone;
- whether timestamps are exchange-time or receive-time;
- price units and size units;
- order-id stability;
- lossy conversions or unsupported source events;
- assumptions needed to produce `MBOEvent`.

## Required Tests

Every connector should include a tiny public fixture or generator and at least
one deterministic replay test. The test should prove the connector can produce
events that a strategy can replay without private data.

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

`CsvSource` is not a vendor adapter. A Databento, LOBSTER, or exchange-specific
connector should convert its source schema into this canonical shape and
document any lossy conversion.
