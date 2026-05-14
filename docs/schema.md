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

## `Fill`

`Fill` represents one execution observed by a strategy.

| Field | Type | Meaning |
|---|---|---|
| `order_id` | `int` | Simulated strategy order id. |
| `side` | `"buy" \| "sell"` | Strategy side of the execution. |
| `price` | `Decimal` | Exact fill price. |
| `size` | `int` | Filled quantity in contracts/lots. |
| `ts_ns` | `int` | Simulated venue timestamp in integer nanoseconds. |

For passive fills, `side` still means the strategy side. A resting own bid that
is later filled by public trade volume is therefore reported as `side="buy"`.
This keeps fills directly usable for audit trails and future cash/PnL
accounting without reconstructing intent from surrounding events.

## `InstrumentSpec`

`InstrumentSpec` holds execution-relevant instrument economics.

| Field | Type | Meaning |
|---|---|---|
| `symbol` | `str` | Human-readable instrument symbol. |
| `tick_size` | `Decimal` | Minimum price increment. |
| `point_value` | `Decimal` | Currency value of one point. |
| `commission_per_contract` | `Decimal` | Commission charged per filled contract in the realized ledger. |

The spec includes helpers to convert exact prices to integer ticks and back.
Connectors should validate prices against the target instrument spec before
feeding events into matching or replay code.

## `ExecutionSummary`

`ExecutionSummary` is the realized fill ledger returned by
`ReplayResult.execution_summary`.

| Field | Type | Meaning |
|---|---|---|
| `contract_volume` | `int` | Total filled contracts/lots. |
| `gross_notional` | `Decimal` | Sum of absolute fill notional. |
| `signed_notional` | `Decimal` | Sells positive, buys negative. |
| `commission` | `Decimal` | Total fill commission. |
| `realized_pnl` | `Decimal` | FIFO realized PnL before commission. |
| `net_realized_pnl` | `Decimal` | `realized_pnl - commission`. |
| `final_position` | `int` | Signed open position after all fills. |
| `open_lots` | `tuple[PositionLot, ...]` | Remaining FIFO lots. |

See `docs/economics.md` for the assumptions and explicit non-goals.

## `ValuationMark` And `EquityPoint`

`ValuationMark` is an input mark used to value open lots.

| Field | Type | Meaning |
|---|---|---|
| `ts_ns` | `int` | Mark timestamp in integer nanoseconds. |
| `price` | `Decimal` | Price used for open-lot valuation. |

`EquityPoint` is one output row from a mark-to-market equity curve.

| Field | Type | Meaning |
|---|---|---|
| `ts_ns` | `int` | Valuation timestamp. |
| `mark_price` | `Decimal` | Price used to value open lots. |
| `realized_pnl` | `Decimal` | FIFO realized PnL through the mark. |
| `unrealized_pnl` | `Decimal` | Open-lot PnL at `mark_price`. |
| `commission` | `Decimal` | Commission accrued through the mark. |
| `equity` | `Decimal` | Realized plus unrealized PnL minus commission. |
| `drawdown` | `Decimal` | Positive drop from the equity high-water mark. |

## Synthetic Fixture

`ordersim.fixtures.synthetic.SyntheticSource.small_mbo()` returns a tiny
deterministic event stream with all four core actions: add, trade, cancel, and
modify.

`SyntheticSource.execution_equivalence_mbo()` returns a queue-aware fixture for
execution-engine equivalence tests. It creates both sides of the book, modifies
the ask, partially cancels queue ahead on the bid, then trades through the bid
queue so a resting strategy order can be passively filled.

The fixture ships in the package because examples and tests should run without
private data or a paid data subscription. It is not a connector and is not meant
to be statistically realistic.

## `DataSource`

A `DataSource` is any object with an `events()` method that yields normalized
`MBOEvent` rows. Replay accepts either a `DataSource` or a plain iterable of
`MBOEvent`.

Connector-specific input schemas belong in connector documentation. The replay
boundary should remain the normalized `MBOEvent` schema above.

## Normalized CSV Schema

`CsvSource` reads a headered CSV with the public `MBOEvent` fields:

```text
ts_ns,action,side,price,size,order_id
```

Extra columns are ignored. Field meanings and units are the same as `MBOEvent`.
This is a normalized interchange schema, not a vendor-specific raw-data schema.
