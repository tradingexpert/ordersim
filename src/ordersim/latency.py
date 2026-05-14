"""Latency model contracts and small reference models.

Latency is represented in two explicit legs:

- entry latency: local order send to simulated venue receipt;
- response latency: simulated venue event to local strategy observation.

The models in this module do not predict venue behavior. They make simple,
testable latency assumptions available to replay and venue code.
"""

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


def _require_non_negative_int(name: str, value: int) -> None:
    if not isinstance(value, int):
        raise TypeError(f"{name} must be an int")
    if value < 0:
        raise ValueError(f"{name} must be non-negative")
