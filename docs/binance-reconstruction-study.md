# Binance L2 Reconstruction Study

This note records the first empirical validation of `ordersim`'s Binance
L2-to-virtual-MBO path. It is evidence for a named model, not a claim that
aggregated depth reveals Binance's true FIFO order queue.

## Capture

The study used locally captured Binance USD-M futures evidence from
2026-08-08 through 2026-08-10:

- standard full diff depth at 100 ms;
- individual `@trade` messages;
- real-time book ticker;
- REST snapshots anchoring every depth connection;
- aggregate trades, RPI depth, and REST individual trades retained as
  supplemental audit evidence.

The primary continuous window ends at `2026-08-10T17:12:57Z`, immediately
before a machine-wide network outage. Later recovery records remain in the raw
archive but were excluded. Raw capture files are research data and are not
committed to this repository.

## Method

Individual trades are aligned to consecutive depth endpoints using Binance
transaction timestamps. A 60-second local receive-time buffer allows the
independent depth and trade connections to arrive out of order. This is an
offline evidence-alignment window, not simulated exchange latency.

The first full ETH pass showed why this must be measured: a two-second buffer
left 13,422 trades late, and a ten-second buffer left 71. The 60-second pass
left none; its maximum executable-trade receive delay was 29.121 seconds. Each
study report records both maximum receive delay and any residual late-trade
lag so the buffer can be reassessed for a different capture environment.

For each side and price level:

```text
ending quantity = starting quantity + adds - cancels - traded quantity
```

The model infers the smallest non-negative add and cancel quantities satisfying
that identity. It then applies two queue assumptions:

- `queue-conservative`: infer additions before the first trade at the level and
  cancel newest modeled liquidity first;
- `queue-optimistic`: add only as needed and cancel oldest modeled liquidity
  first.

Both policies must reproduce every observed depth endpoint. Joinable
book-ticker rows provide an independent check of top-of-book price and
quantity. Every reconnect starts a separate snapshot-anchored segment.

## Results

| Measure | BTCUSDT | ETHUSDT |
|---|---:|---:|
| Snapshot-anchored segments | 4 | 3 |
| Depth endpoints reconstructed | 1,668,215 | 1,659,917 |
| Executable individual trades aligned | 2,847,061 | 4,498,386 |
| Broken depth segments | 0 | 0 |
| Late trades after validated buffer | 0 | 0 |
| Exact book-ticker matches | 44,277 / 44,277 | 72,104 / 72,104 |
| Zero-value `@trade` messages excluded | 11,850 | 12,741 |
| Boundary-unassigned trades | 2,052 | 91 |
| Observed trade quantity | 158,708.331 BTC | 4,524,196.266 ETH |
| Required within-window replenishment | 17,306.673 BTC | 662,705.196 ETH |
| Replenishment / trade quantity | 10.90% | 14.65% |

The book-ticker denominator includes only rows whose update ID exactly matches
a processed depth endpoint. It is not the count of all captured book-ticker
messages.

Zero-price, zero-quantity `@trade` messages are preserved in raw capture. Their
raw payload includes undocumented fields such as `X=NA`; the study counts them
but does not assign execution semantics or emit invalid zero-sized MBO rows.

## Interpretation

The results support the exchange-time alignment and minimum-flow accounting:

- all depth segments remained sequence-continuous;
- no executable trade arrived too late for the validated alignment buffer;
- every independently joinable top-of-book state matched exactly;
- the required replenishment ratio is measurable rather than hidden.

They do not identify the true order-level queue. Both named policies can match
the same L2 endpoints while producing different queue-ahead paths for a
hypothetical resting order. Strategy conclusions that change materially
between the two policies should be reported as model-sensitive.

## Reproduce

Run the study against a completed raw capture directory:

```bash
ordersim-binance-reconstruction-study captures/binance \
  --symbol BTCUSDT \
  --quantity-step 0.001 \
  --reorder-buffer-ms 60000 \
  --until-received-at-ns 1786381977000000000 \
  --output reports/btcusdt-reconstruction.json
```

The JSON report is a model manifest: it records the policy names, quantity
unit, cutoff, segment identifiers, alignment exceptions, inferred flow, and
book-ticker checks.

## Open Validation Questions

Useful contributions include:

- cancellation-allocation models supported by published microstructure work;
- comparisons against private MBO for a venue or interval where both L2 and L3
  are available;
- passive-fill sensitivity experiments across the conservative and optimistic
  bounds;
- evidence about Binance's zero-value `@trade` messages without relying on
  undocumented fields as stable production contracts.
