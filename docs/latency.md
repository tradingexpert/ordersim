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

## Planned Models

The longer-term latency library should add:

- empirical playback for exact regression against one recorded series;
- empirical bootstrap for distributional robustness studies;
- parametric models for tail and sensitivity analysis;
- regime conditioning for time-of-day or user-defined states.

These are planned models, not current behavior.
