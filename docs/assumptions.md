# Assumptions

`ordersim` is an execution simulator, not a market oracle. It replays observed
order-book events and simulates how strategy orders would interact with that
replay under explicitly named assumptions.

The goal is not to claim perfect market realism. The goal is to make every
assumption visible, testable, and replaceable.

## Data Assumptions

The highest-fidelity path expects order-level data:

- add events;
- cancel events;
- modify events;
- trade or fill events;
- stable order identifiers;
- event timestamps.

This is often called Level 3, L3, MBO, or market-by-order data.

The normalized public event type is `MBOEvent`; see `docs/schema.md`.

Lower-fidelity data can be supported, but must be named honestly. A Level 2 or
MBP source provides aggregated size by price level, not individual queue
members. Queue-position behavior inferred from MBP is necessarily a model, not
an observation.

## Queue Assumptions

When the strategy places a resting limit order, the default model assumes the
order joins the back of the visible queue at that price.

Public trades and public cancels then consume queue ahead according to the
matching model. When queue ahead reaches zero, subsequent eligible volume can
fill the strategy order.

The reference Python matching engine keeps an explicit FIFO for each
`(side, price)` level. Public MBO add events and strategy orders append to that
FIFO. Public cancels remove or reduce the referenced public order. Public trades
consume from the front of the FIFO, so own resting orders are passively filled
only after visible queue ahead has been consumed.

Public modifies at the same price keep their current queue position. Public
modifies that change price or side remove the old queue entry and append the
order to the back of the new level. Exchange-specific priority rules can be
added later as named fill models.

This model does not claim to know hidden liquidity, exchange-specific priority
exceptions, implied orders, pro-rata allocation, self-match prevention rules, or
venue-specific edge cases unless a specific fill model documents them.

## Order Lifecycle Assumptions

The simulator distinguishes:

- order intent: what the strategy attempted;
- venue receipt: what the simulated venue accepted after latency;
- active fills: fills returned by the place call;
- passive fills: fills that materialize later while an order rests;
- cancels: cancellation attempts and their results.

Fills always carry the strategy side. Active fills inherit the submitted order
side. Passive fills map own bids to buys and own asks to sells.

Final PnL alone is not enough. The order-intent log is a first-class output.

## Execution Economics Assumptions

Replay results include a realized fill ledger computed from `InstrumentSpec`.
The ledger uses FIFO lots, contract `point_value`, and
`commission_per_contract`.

The realized ledger is not full portfolio accounting. It does not model margin,
funding, or broker statement rules. Its purpose is narrower: make realized
execution economics deterministic and auditable from the fills.

Replay also exposes a mark-to-market equity curve when valuation marks are
available. The default replay valuation mark is midpoint after a book event or
order action when both bid and ask exist. Drawdown is computed from this marked
equity curve as a positive drop from the prior high-water mark.

Midpoint valuation is a default, not a universal truth. Bid, ask, last-trade,
settlement, and user-supplied marks can be added as explicit valuation models.

## Latency Assumptions

Latency is modeled in two legs:

- entry latency: local order send to simulated venue receipt;
- response latency: simulated venue event to local strategy observation.

Current public models include constant latency, seeded uniform jitter,
empirical playback, and seeded empirical bootstrap. Planned models include
parametric sampling. Random models must be seedable.

The recommended research default is seeded empirical bootstrap when latency
measurements are available. Constant latency is best for examples and
baselines. Exact playback is best for debugging one recorded path, not for
claiming robustness.

Replay applies the entry-latency leg to limit orders, market orders, and
cancels. Market-data events that occur before simulated venue receipt are
processed before the order action reaches the execution engine.

The response-latency leg is currently exposed by the public model contract but
is not yet used to delay local strategy observation of fills.

Different strategies in the same replay may use different latency models. This
is useful for A/B tests and for studying execution sensitivity.

## On Replay Accuracy For Latency

Replaying recorded latency measurements is sometimes presented as the most
accurate latency model available. It is the most faithful to a specific
realization, but it is not the most informative about how a strategy will
perform in production. The distinction matters.

Past is not future. Recorded latencies reflect the network, exchange load, and
market conditions of the recording window. Tomorrow's distribution can differ
mildly through steady-state drift or sharply through infrastructure and regime
changes.

A recorded series is one draw from the underlying distribution. Replaying it
tells you how the strategy performs against that one realization, not across the
distribution. This is the latency analogue of backtesting a strategy on one
price path.

Repeated replay can also create spurious determinism. The same latency value
appears at the same replay point on every run. A strategy whose apparent edge
depends on the timing of one tail event can look reproducible without being
robust.

Tail events are under-represented in short recordings. P99.9 latency events are
rare by definition, but they can dominate strategy survival in production.

For debugging and regression tests, exact playback is useful. For robustness
questions, bootstrap and parametric models are usually more informative because
they sample many plausible latency paths consistent with the measurements.

In one sentence:

> Replaying recorded latency tells you how the strategy survived one particular
> afternoon. Sampling from the distribution your measurements imply tells you
> how the strategy might survive afternoons it has not seen yet.

## Engine Assumptions

The pure Python engine is the reference implementation because it is readable
and debuggable.

Compiled execution engines may be added for scale, but they are not allowed to
change semantics. An engine is acceptable only when the public equivalence
harness shows the same fills, final state, and order-intent log as the Python
engine for the same replay and strategy actions.

Engines consume normalized `MBOEvent` rows. Vendor data ingestion belongs to
connectors, not to the execution engine.

Performance modes that reduce fidelity must be named as separate models. They
must not be hidden behind words like "fast" or "optimized."

## What We Do Not Claim

`ordersim` does not claim:

- institutional-grade performance;
- live trading safety;
- exchange-certified matching behavior;
- predictive latency modeling;
- that one historical replay is enough to validate a strategy;
- that queue-position modeling is unique to this project.

What it does claim:

- every assumption should be named;
- every public model should be testable;
- every order intent should be auditable;
- multi-strategy comparisons should be deterministic by default.
