"""Latency model contracts and small reference models.

Latency is represented in two explicit legs:

- entry latency: local order send to simulated venue receipt;
- response latency: simulated venue event to local strategy observation.

The models in this module do not predict venue behavior. They make simple,
testable latency assumptions available to replay and venue code.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from random import Random
from typing import Protocol


@dataclass(frozen=True, slots=True)
class LatencySample:
    """One sampled two-leg latency observation."""

    entry_ns: int
    response_ns: int

    def __post_init__(self) -> None:
        _require_non_negative_int("entry_ns", self.entry_ns)
        _require_non_negative_int("response_ns", self.response_ns)


@dataclass(frozen=True, slots=True)
class LatencyMeasurement:
    """Observed latency row supplied by a user or connector."""

    ts_ns: int
    entry_ns: int
    response_ns: int
    regime: str | None = None

    def __post_init__(self) -> None:
        _require_non_negative_int("ts_ns", self.ts_ns)
        _require_non_negative_int("entry_ns", self.entry_ns)
        _require_non_negative_int("response_ns", self.response_ns)


class LatencyModel(Protocol):
    """A model that samples entry and response latency."""

    def sample(self, ts_ns: int, regime: str | None = None) -> LatencySample:
        """Return latency for an order or observation at ``ts_ns``."""


@dataclass(frozen=True, slots=True)
class ConstantLatency:
    """Fixed two-leg latency model."""

    entry_ns: int = 0
    response_ns: int = 0

    def __post_init__(self) -> None:
        _require_non_negative_int("entry_ns", self.entry_ns)
        _require_non_negative_int("response_ns", self.response_ns)

    def sample(self, ts_ns: int, regime: str | None = None) -> LatencySample:
        """Return the same latency sample every time."""

        _require_non_negative_int("ts_ns", ts_ns)
        return LatencySample(self.entry_ns, self.response_ns)


class JitteredLatency:
    """Uniform jitter around a fixed two-leg latency baseline.

    Each sampled leg is drawn from ``base +/- jitter_ns`` and clamped at zero.
    Supplying ``seed`` makes the sample sequence reproducible.
    """

    __slots__ = ("_rng", "entry_ns", "jitter_ns", "response_ns")

    entry_ns: int
    response_ns: int
    jitter_ns: int
    _rng: Random

    def __init__(
        self,
        *,
        entry_ns: int,
        response_ns: int,
        jitter_ns: int,
        seed: int | None = None,
    ) -> None:
        _require_non_negative_int("entry_ns", entry_ns)
        _require_non_negative_int("response_ns", response_ns)
        _require_non_negative_int("jitter_ns", jitter_ns)
        self.entry_ns = entry_ns
        self.response_ns = response_ns
        self.jitter_ns = jitter_ns
        self._rng = Random(seed)

    def sample(self, ts_ns: int, regime: str | None = None) -> LatencySample:
        """Return a seeded uniformly jittered latency sample."""

        _require_non_negative_int("ts_ns", ts_ns)
        return LatencySample(
            entry_ns=self._jitter(self.entry_ns),
            response_ns=self._jitter(self.response_ns),
        )

    def _jitter(self, base_ns: int) -> int:
        if self.jitter_ns == 0:
            return base_ns
        return max(0, base_ns + self._rng.randint(-self.jitter_ns, self.jitter_ns))


class EmpiricalPlayback:
    """Replay observed latency samples in timestamp order.

    Playback is finite by design. It is intended for debugging and regression
    tests against one recorded latency series, not for extrapolating beyond the
    measurements supplied by the user.
    """

    __slots__ = ("_cursors", "_samples", "_samples_by_regime")

    _cursors: dict[str | None, int]
    _samples: tuple[LatencySample, ...]
    _samples_by_regime: dict[str | None, tuple[LatencySample, ...]]

    def __init__(self, measurements: Iterable[LatencyMeasurement]) -> None:
        ordered = tuple(sorted(measurements, key=lambda measurement: measurement.ts_ns))
        if not ordered:
            raise ValueError("measurements must not be empty")

        self._samples = tuple(_sample_from_measurement(row) for row in ordered)
        self._samples_by_regime = _samples_by_regime(ordered)
        self._cursors = {}

    @classmethod
    def from_measurements(
        cls,
        measurements: Iterable[LatencyMeasurement],
    ) -> "EmpiricalPlayback":
        """Build playback from observed latency measurements."""

        return cls(measurements)

    def sample(self, ts_ns: int, regime: str | None = None) -> LatencySample:
        """Return the next recorded sample for ``regime``."""

        _require_non_negative_int("ts_ns", ts_ns)
        samples = self._select_samples(regime)
        cursor = self._cursors.get(regime, 0)
        if cursor >= len(samples):
            raise IndexError("empirical playback is exhausted")
        self._cursors[regime] = cursor + 1
        return samples[cursor]

    def reset(self) -> None:
        """Reset playback cursors to the start of each series."""

        self._cursors.clear()

    def _select_samples(self, regime: str | None) -> tuple[LatencySample, ...]:
        if regime is None:
            return self._samples
        samples = self._samples_by_regime.get(regime, ())
        if not samples:
            raise ValueError(f"no latency measurements for regime: {regime!r}")
        return samples


class EmpiricalBootstrap:
    """Sample observed latency rows with replacement.

    Bootstrap is intended for robustness studies where the user wants many
    plausible latency paths consistent with observed measurements.
    """

    __slots__ = ("_rng", "_samples", "_samples_by_regime")

    _rng: Random
    _samples: tuple[LatencySample, ...]
    _samples_by_regime: dict[str | None, tuple[LatencySample, ...]]

    def __init__(
        self,
        measurements: Iterable[LatencyMeasurement],
        *,
        seed: int | None = None,
    ) -> None:
        ordered = tuple(sorted(measurements, key=lambda measurement: measurement.ts_ns))
        if not ordered:
            raise ValueError("measurements must not be empty")

        self._samples = tuple(_sample_from_measurement(row) for row in ordered)
        self._samples_by_regime = _samples_by_regime(ordered)
        self._rng = Random(seed)

    @classmethod
    def from_measurements(
        cls,
        measurements: Iterable[LatencyMeasurement],
        *,
        seed: int | None = None,
    ) -> "EmpiricalBootstrap":
        """Build seeded bootstrap from observed latency measurements."""

        return cls(measurements, seed=seed)

    def sample(self, ts_ns: int, regime: str | None = None) -> LatencySample:
        """Return one sampled observed latency row."""

        _require_non_negative_int("ts_ns", ts_ns)
        samples = self._select_samples(regime)
        return self._rng.choice(samples)

    def _select_samples(self, regime: str | None) -> tuple[LatencySample, ...]:
        if regime is None:
            return self._samples
        samples = self._samples_by_regime.get(regime, ())
        if not samples:
            raise ValueError(f"no latency measurements for regime: {regime!r}")
        return samples


def _sample_from_measurement(measurement: LatencyMeasurement) -> LatencySample:
    return LatencySample(
        entry_ns=measurement.entry_ns,
        response_ns=measurement.response_ns,
    )


def _samples_by_regime(
    measurements: tuple[LatencyMeasurement, ...],
) -> dict[str | None, tuple[LatencySample, ...]]:
    regimes = {measurement.regime for measurement in measurements}
    return {
        regime: tuple(
            _sample_from_measurement(measurement)
            for measurement in measurements
            if measurement.regime == regime
        )
        for regime in regimes
        if regime is not None
    }


def _require_non_negative_int(name: str, value: int) -> None:
    if not isinstance(value, int):
        raise TypeError(f"{name} must be an int")
    if value < 0:
        raise ValueError(f"{name} must be non-negative")
