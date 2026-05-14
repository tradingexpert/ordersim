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

This ledger does not claim to model:

- mark-to-market PnL for open positions;
- variation margin;
- funding;
- interest;
- account equity;
- margin requirements;
- exchange or broker statement rules.

Those are portfolio-accounting concerns. The public contract here is narrower:
given a sequence of fills and an `InstrumentSpec`, produce a deterministic,
auditable realized ledger.

## Direct Use

```python
from ordersim import summarize_fills

summary = summarize_fills(result.fills, spec)
```

`Replay.run(...)` calls the same helper and exposes the result as
`result.execution_summary`.
