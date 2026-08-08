# Schema

`ordersim` normalizes market data into small Python dataclasses before replay.
The schema is intentionally boring so connectors can be reviewed without
knowing the vendor SDK.

## Timestamp Convention

All public `ts_ns` fields are integer nanoseconds since the Unix epoch in UTC.
They are timezone-normalized values, not naive local wall-clock timestamps.

Connectors must convert vendor timestamps into UTC epoch nanoseconds before
emitting public dataclasses. If a source uses exchange-local wall time, the
connector owns timezone-aware parsing, including daylight-saving transitions,
before replay sees the event.

The replay layer operates only on normalized integer timestamps. It does not
carry Python timezone objects or infer timezone rules after normalization.

## Binance L2 Records

The Binance connector exposes typed records before the modeled-MBO boundary.
These records describe observed aggregated depth and trades; they do not claim
to contain stable exchange order IDs.

`BinancePriceLevel` holds an exact positive `Decimal` price and a non-negative
`Decimal` quantity. In a depth update, the quantity is the new absolute
quantity at that price; zero means remove the level.

| Record | Important fields | Meaning |
|---|---|---|
| `BinanceDepthSnapshot` | `last_update_id`, `bids`, `asks` | REST depth state anchoring one connection. |
| `BinanceDepthUpdate` | `first_update_id`, `final_update_id`, `previous_update_id`, `bids`, `asks` | One standard or RPI absolute-quantity diff-depth message. |
| `BinanceAggregateTrade` | `aggregate_trade_id`, `price`, `quantity`, `normal_quantity`, `buyer_is_maker` | Trades aggregated by price and taking side. |
| `BinanceIndividualTrade` | `trade_id`, `price`, `quantity`, `buyer_is_maker` | One real-time individually identified WebSocket trade. |
| `BinanceRawTrade` | `trade_id`, `price`, `quantity`, `quote_quantity`, `buyer_is_maker`, `is_rpi_trade` | One individually identified REST trade. |
| `BinanceBookTicker` | `update_id`, bid and ask price/quantity | Real-time best bid and ask observation. |

All records include `symbol`, `connection_id`, UTC receive nanoseconds, and
local monotonic receive nanoseconds. Stream messages also include exchange
event and transaction/trade times normalized from Binance milliseconds to UTC
nanoseconds.

Binance contract quantity can be fractional, so the connector preserves it as
`Decimal`. A future virtual-L3 reconstruction model must declare its quantity
unit and exact conversion rule before producing the canonical integer
`MBOEvent.size`. These L2 records are therefore not accepted directly by
`Replay`.

Raw-trade capture files also contain audit envelopes:

- `trade_gap` records a non-consecutive individual WebSocket trade ID;
- `raw_trade_poll` records request timing, returned ID bounds, and request
  weight;
- `raw_trade_gap` records a missing individual trade-ID range;
- `raw_trade_poll_error` records a failed request and the last retained ID.

These audit rows are available through `envelopes()` and are not emitted by
`raw_trades()`.

## `MBOEvent`

`MBOEvent` represents one Level 3 / market-by-order event.

| Field | Type | Meaning |
|---|---|---|
| `ts_ns` | `int` | UTC Unix-epoch timestamp in integer nanoseconds. |
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
| `ts_ns` | `int` | Simulated venue timestamp as UTC Unix-epoch nanoseconds. |

For passive fills, `side` still means the strategy side. A resting own bid that
is later filled by public trade volume is therefore reported as `side="buy"`.
This keeps fills directly usable for audit trails and future cash/PnL
accounting without reconstructing intent from surrounding events.

## `RestingOrder`

`RestingOrder` represents one own strategy order still resting on the simulated
book.

| Field | Type | Meaning |
|---|---|---|
| `order_id` | `int` | Simulated strategy order id. |
| `side` | `"buy" \| "sell"` | Strategy side of the resting order. |
| `price` | `Decimal` | Resting limit price. |
| `remaining_size` | `int` | Unfilled quantity still resting. |
| `queue_ahead_size` | `int` | Visible size ahead of the order at its price. |

`gateway.own_orders()` returns these rows during replay. `ReplayResult` keeps
the final rows as `resting_orders`.

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

`ValuationMark` lives in `ordersim.valuation` and is re-exported from
`ordersim`. It is an input mark used to value open lots.

| Field | Type | Meaning |
|---|---|---|
| `ts_ns` | `int` | Mark timestamp as UTC Unix-epoch nanoseconds. |
| `price` | `Decimal` | Price used for open-lot valuation. |

`CompiledValuationMarks` also lives in `ordersim.valuation`. It is the compact
internal form used by the C++ replay path. It stores mark timestamps and
midpoint prices as primitive integer columns:

| Field | Type | Meaning |
|---|---|---|
| `ts_ns` | `memoryview[int64]` | Mark timestamps as UTC Unix-epoch nanoseconds. |
| `mid_ticks_x2` | `memoryview[int64]` | `bid_ticks + ask_ticks`, preserving half-tick midpoints exactly. |
| `tick_size` | `Decimal` | Price multiplier used when public `Decimal` prices are built. |

`EquityPoint` is one output row from a mark-to-market equity curve.

| Field | Type | Meaning |
|---|---|---|
| `ts_ns` | `int` | Valuation timestamp as UTC Unix-epoch nanoseconds. |
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

## Normalized Parquet Schema

`ParquetSource` reads the same canonical fields as `CsvSource`:

```text
ts_ns,action,side,price,size,order_id
```

`write_parquet(...)` writes exactly this durable schema from any normalized
event iterable or `DataSource`. For repeated research runs, prefer this
canonical Parquet form after the initial vendor-normalization step.
