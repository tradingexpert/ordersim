# Schema

`ordersim` normalizes market data into small Python dataclasses before replay.
The schema is intentionally boring so connectors can be reviewed without
knowing the vendor SDK.

## `MBOEvent`

`MBOEvent` represents one Level 3 / market-by-order event.

| Field | Type | Meaning |
|---|---|---|
| `ts_ns` | `int` | Event timestamp in integer nanoseconds. |
| `action` | `"add" \| "cancel" \| "modify" \| "trade"` | Book action. |
| `side` | `"bid" \| "ask"` | Resting book side affected by the event. |
| `price` | `Decimal` | Exact event price. |
| `size` | `int` | Event quantity in contracts/lots. |
| `order_id` | `int` | Stable source order id. |

For trades, `side` is the resting book side that traded, not the aggressor
side. For example, a market buy that trades against an ask resting order is
represented with `side="ask"`.

## `InstrumentSpec`

`InstrumentSpec` holds execution-relevant instrument economics.

| Field | Type | Meaning |
|---|---|---|
| `symbol` | `str` | Human-readable instrument symbol. |
| `tick_size` | `Decimal` | Minimum price increment. |
| `point_value` | `Decimal` | Currency value of one point. |
| `commission_per_contract` | `Decimal` | Round-turn convention is caller-defined. |

The spec includes helpers to convert exact prices to integer ticks and back.
Connectors should validate prices against the target instrument spec before
feeding events into matching or replay code.

## Synthetic Fixture

`ordersim.fixtures.synthetic.SyntheticSource.small_mbo()` returns a tiny
deterministic event stream with all four core actions: add, trade, cancel, and
modify.

The fixture ships in the package because examples and tests should run without
private data or a paid data subscription. It is not a connector and is not meant
to be statistically realistic.

## `DataSource`

A `DataSource` is any object with an `events()` method that yields normalized
`MBOEvent` rows. Replay accepts either a `DataSource` or a plain iterable of
`MBOEvent`.

Connector-specific input schemas belong in connector documentation. The replay
boundary should remain the normalized `MBOEvent` schema above.
