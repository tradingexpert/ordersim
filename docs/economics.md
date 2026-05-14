# Execution Economics

`ordersim` computes a small realized fill ledger for each replay result. The
ledger is intentionally simple: it summarizes observed fills without turning
the library into a portfolio accounting framework.

## What Is Included

`ReplayResult.execution_summary` reports:

| Field | Meaning |
|---|---|
| `contract_volume` | Total filled contracts/lots. |
| `gross_notional` | Sum of absolute fill notional: `price * size * point_value`. |
| `signed_notional` | Sells positive, buys negative. |
| `commission` | `commission_per_contract * filled contracts`. |
| `realized_pnl` | FIFO realized PnL for closed lots before commission. |
| `net_realized_pnl` | `realized_pnl - commission`. |
| `final_position` | Signed open position after all fills. |
| `open_lots` | Remaining FIFO lots after realized matching. |

`ReplayResult.equity_curve` reports mark-to-market points:

| Field | Meaning |
|---|---|
| `ts_ns` | Timestamp of the valuation mark. |
| `mark_price` | Price used to value open lots. |
| `realized_pnl` | FIFO realized PnL through the mark timestamp. |
| `unrealized_pnl` | Open-lot PnL valued at `mark_price`. |
| `commission` | Commission accrued through the mark timestamp. |
| `equity` | `realized_pnl + unrealized_pnl - commission`. |
| `drawdown` | Drop from the prior high-water mark, reported as a positive number. |

## FIFO Realized PnL

The ledger uses FIFO lots:

- buys open or add to long lots;
- sells close long lots first, then open short lots if quantity remains;
- sells open or add to short lots;
- buys close short lots first, then open long lots if quantity remains.

Long lots realize:

```text
(sell_price - buy_price) * size * point_value
```

Short lots realize:

```text
(sell_price - buy_price) * size * point_value
```

The formula is equivalent; only the open and close order changes.

## What Is Not Included

The realized ledger and midpoint equity curve do not claim to model:

- variation margin;
- funding;
- interest;
- account equity;
- margin requirements;
- exchange or broker statement rules.

Those are portfolio-accounting concerns. The public contract here is narrower:
given a sequence of fills, valuation marks, and an `InstrumentSpec`, produce a
deterministic, auditable execution ledger and marked equity curve.

## Equity Curve And Drawdown

Replay builds `equity_curve` from observed fills and midpoint valuation marks.
A midpoint mark is recorded when both bid and ask are available after replay
applies a book event or order action.

Replay only marks times it actually advances through. Full-session intraday
drawdown therefore requires the strategy or harness to advance through the
session window being studied, or to call `build_equity_curve(...)` directly with
an explicit mark series.

This makes intraday drawdown support explicit without pretending that midpoint
is the only valid valuation policy. Future valuation models can add bid, ask,
last-trade, settlement, or user-supplied marks while preserving the same
`EquityPoint` output shape.

For direct use:

```python
from ordersim import ValuationMark, build_equity_curve

curve = build_equity_curve(
    fills=result.fills,
    marks=(ValuationMark(ts_ns=1, price=mark_price),),
    instrument=spec,
)
```

## Direct Use

```python
from ordersim import summarize_fills

summary = summarize_fills(result.fills, spec)
```

`Replay.run(...)` calls the same helper and exposes the result as
`result.execution_summary`.
