# Latency Models

Latency models describe how long it takes an order or observation to travel
through the simulated execution path. They do not read market data and they do
not predict venue behavior.

`ordersim` represents latency in two legs:

- entry latency: local order send to simulated venue receipt;
- response latency: simulated venue event to local strategy observation.

The public protocol is intentionally small:

```python
class LatencyModel(Protocol):
    def sample(self, ts_ns: int, regime: str | None = None) -> LatencySample: ...
```

## Which Model Should I Use?

Use `EmpiricalBootstrap` when you have latency measurements and want the most
useful research default. It samples many plausible latency paths from the
measurements you supplied, stays reproducible with a seed, and avoids treating
one recorded afternoon as the only future path.

Use `ConstantLatency` for smoke tests, examples, and baseline comparisons. It
is easy to explain and should usually be the first model in a minimal example.

Use `EmpiricalPlayback` when you need exact regression against one recorded
latency series. It is intentionally not the recommended robustness model,
because exact playback repeats one historical realization.

Use `JitteredLatency` for quick sensitivity checks when you do not yet have
real measurements. Replace it with empirical measurements before making
research claims.

## Reference Models

`ConstantLatency` returns the same two-leg sample every time. It is useful for
smoke tests, baseline comparisons, and examples.

`JitteredLatency` samples uniformly from `base +/- jitter_ns` for each leg and
clamps at zero. Supplying a seed makes the sample sequence reproducible.

`EmpiricalPlayback` replays observed measurements in timestamp order. It is
finite and raises when the recorded series is exhausted. Use it for debugging
and exact regression against one recorded latency path.

`EmpiricalBootstrap` samples observed measurements with replacement. Supplying
a seed makes the sampled path reproducible. Use it for robustness studies when
you want many plausible paths drawn from the measurements you supplied.

Both empirical models can filter by `regime` when measurements include regime
labels.

## Replay Behavior

`Replay` accepts a `latency_model_factory`. A fresh model is created for each
strategy run, so seeded or stateful models do not leak state across `run_many`.

```python
from ordersim import ConstantLatency, Replay

replay = Replay(
    data=source,
    instrument=spec,
    latency_model_factory=lambda: ConstantLatency(entry_ns=25_000_000),
)
```

The current replay gateway applies the entry-latency leg to side-effecting
order calls: limit orders, market orders, and cancels. If market-data events
arrive before the simulated venue receives the order or cancel, those events
are applied first.

The response-latency leg is part of the public model contract, but replay does
not yet delay local strategy observation of fills.

## Planned Models

The longer-term latency library should add:

- parametric models for tail and sensitivity analysis;
- richer regime conditioning for time-of-day or user-defined states.

These are planned models, not current behavior.
