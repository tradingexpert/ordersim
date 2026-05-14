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

Final PnL alone is not enough. The order-intent log is a first-class output.

## Latency Assumptions

Latency is modeled in two legs:

- entry latency: local order send to simulated venue receipt;
- response latency: simulated venue event to local strategy observation.

Models may be constant, jittered, empirical playback, empirical bootstrap, or
parametric. Random models must be seedable.

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

## Backend Assumptions

The pure Python backend is the reference implementation because it is readable
and debuggable.

Compiled backends may be added for scale, but they are not allowed to change
semantics. A backend is acceptable only when public equivalence fixtures show
the same fills and final state as the Python backend for the same replay and
strategy actions.

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
