import pytest

from ordersim import (
    ConstantLatency,
    EmpiricalBootstrap,
    EmpiricalPlayback,
    JitteredLatency,
    LatencyMeasurement,
    LatencySample,
)
from ordersim.latency import LatencyModel


def test_constant_latency_returns_two_explicit_legs() -> None:
    model = ConstantLatency(entry_ns=25, response_ns=75)

    assert model.sample(ts_ns=1_000) == LatencySample(entry_ns=25, response_ns=75)
    assert model.sample(ts_ns=2_000, regime="open") == LatencySample(
        entry_ns=25,
        response_ns=75,
    )


def test_latency_measurement_validates_public_units() -> None:
    measurement = LatencyMeasurement(
        ts_ns=1_000,
        entry_ns=25,
        response_ns=75,
        regime="cash-open",
    )

    assert measurement.regime == "cash-open"


def measurements() -> tuple[LatencyMeasurement, ...]:
    return (
        LatencyMeasurement(ts_ns=3, entry_ns=30, response_ns=300, regime="close"),
        LatencyMeasurement(ts_ns=1, entry_ns=10, response_ns=100, regime="open"),
        LatencyMeasurement(ts_ns=2, entry_ns=20, response_ns=200, regime="open"),
    )


def test_jittered_latency_is_reproducible_with_seed() -> None:
    first = JitteredLatency(
        entry_ns=100,
        response_ns=200,
        jitter_ns=10,
        seed=7,
    )
    second = JitteredLatency(
        entry_ns=100,
        response_ns=200,
        jitter_ns=10,
        seed=7,
    )

    first_samples = [first.sample(ts_ns=i) for i in range(5)]
    second_samples = [second.sample(ts_ns=i) for i in range(5)]

    assert first_samples == second_samples


def test_jittered_latency_stays_within_documented_bounds() -> None:
    model = JitteredLatency(
        entry_ns=100,
        response_ns=200,
        jitter_ns=10,
        seed=3,
    )

    samples = [model.sample(ts_ns=i) for i in range(50)]

    assert all(90 <= sample.entry_ns <= 110 for sample in samples)
    assert all(190 <= sample.response_ns <= 210 for sample in samples)


def test_zero_jitter_returns_the_baseline() -> None:
    model = JitteredLatency(
        entry_ns=100,
        response_ns=200,
        jitter_ns=0,
        seed=3,
    )

    assert model.sample(ts_ns=1) == LatencySample(entry_ns=100, response_ns=200)


def test_latency_models_reject_negative_values() -> None:
    with pytest.raises(ValueError, match="entry_ns must be non-negative"):
        ConstantLatency(entry_ns=-1)

    with pytest.raises(ValueError, match="response_ns must be non-negative"):
        LatencySample(entry_ns=1, response_ns=-1)

    with pytest.raises(ValueError, match="jitter_ns must be non-negative"):
        JitteredLatency(entry_ns=1, response_ns=1, jitter_ns=-1)

    with pytest.raises(ValueError, match="ts_ns must be non-negative"):
        ConstantLatency().sample(ts_ns=-1)


def test_latency_models_reject_non_integer_values() -> None:
    with pytest.raises(TypeError, match="entry_ns must be an int"):
        ConstantLatency(entry_ns=1.5)  # type: ignore[arg-type]


def test_empirical_playback_returns_measurements_in_timestamp_order() -> None:
    model = EmpiricalPlayback.from_measurements(measurements())

    assert model.sample(ts_ns=10) == LatencySample(entry_ns=10, response_ns=100)
    assert model.sample(ts_ns=11) == LatencySample(entry_ns=20, response_ns=200)
    assert model.sample(ts_ns=12) == LatencySample(entry_ns=30, response_ns=300)

    with pytest.raises(IndexError, match="empirical playback is exhausted"):
        model.sample(ts_ns=13)


def test_empirical_playback_can_reset() -> None:
    model = EmpiricalPlayback.from_measurements(measurements())

    assert model.sample(ts_ns=10) == LatencySample(entry_ns=10, response_ns=100)
    model.reset()

    assert model.sample(ts_ns=11) == LatencySample(entry_ns=10, response_ns=100)


def test_empirical_playback_can_filter_by_regime() -> None:
    model = EmpiricalPlayback.from_measurements(measurements())

    assert model.sample(ts_ns=10, regime="open") == LatencySample(
        entry_ns=10,
        response_ns=100,
    )
    assert model.sample(ts_ns=11, regime="open") == LatencySample(
        entry_ns=20,
        response_ns=200,
    )

    with pytest.raises(ValueError, match="no latency measurements for regime"):
        model.sample(ts_ns=12, regime="lunch")


def test_empirical_bootstrap_is_reproducible_with_seed() -> None:
    first = EmpiricalBootstrap.from_measurements(measurements(), seed=4)
    second = EmpiricalBootstrap.from_measurements(measurements(), seed=4)

    first_samples = [first.sample(ts_ns=i) for i in range(8)]
    second_samples = [second.sample(ts_ns=i) for i in range(8)]

    assert first_samples == second_samples


def test_empirical_bootstrap_samples_observed_measurements() -> None:
    model = EmpiricalBootstrap.from_measurements(measurements(), seed=5)
    observed = {
        LatencySample(entry_ns=10, response_ns=100),
        LatencySample(entry_ns=20, response_ns=200),
        LatencySample(entry_ns=30, response_ns=300),
    }

    samples = [model.sample(ts_ns=i) for i in range(20)]

    assert set(samples) <= observed


def test_empirical_bootstrap_can_filter_by_regime() -> None:
    model = EmpiricalBootstrap.from_measurements(measurements(), seed=7)

    samples = [model.sample(ts_ns=i, regime="open") for i in range(20)]

    assert set(samples) <= {
        LatencySample(entry_ns=10, response_ns=100),
        LatencySample(entry_ns=20, response_ns=200),
    }

    with pytest.raises(ValueError, match="no latency measurements for regime"):
        model.sample(ts_ns=20, regime="lunch")


def test_empirical_models_reject_empty_measurements() -> None:
    with pytest.raises(ValueError, match="measurements must not be empty"):
        EmpiricalPlayback.from_measurements(())

    with pytest.raises(ValueError, match="measurements must not be empty"):
        EmpiricalBootstrap.from_measurements(())


def test_latency_model_protocol_accepts_reference_models() -> None:
    model: LatencyModel = ConstantLatency(entry_ns=1, response_ns=2)

    assert model.sample(ts_ns=0) == LatencySample(entry_ns=1, response_ns=2)
