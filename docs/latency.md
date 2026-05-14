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

## Planned Models

The longer-term latency library should add:

- parametric models for tail and sensitivity analysis;
- richer regime conditioning for time-of-day or user-defined states.

These are planned models, not current behavior.
