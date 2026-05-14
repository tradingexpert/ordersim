from decimal import Decimal

import pytest

from ordersim import InstrumentSpec, MBOEvent
from ordersim.fixtures.synthetic import SyntheticSource


def test_instrument_spec_converts_prices_to_ticks_and_back() -> None:
    spec = InstrumentSpec(
        symbol="GC",
        tick_size=Decimal("0.10"),
        point_value=Decimal("100"),
        commission_per_contract=Decimal("2.50"),
    )

    ticks = spec.price_to_ticks(Decimal("2012.30"))

    assert ticks == 20123
    assert spec.ticks_to_price(ticks) == Decimal("2012.30")


def test_instrument_spec_rejects_unaligned_prices() -> None:
    spec = InstrumentSpec(
        symbol="GC",
        tick_size=Decimal("0.10"),
        point_value=Decimal("100"),
    )

    with pytest.raises(ValueError, match="not aligned"):
        spec.price_to_ticks(Decimal("2012.34"))


def test_instrument_spec_asserts_price_alignment() -> None:
    spec = InstrumentSpec(
        symbol="GC",
        tick_size=Decimal("0.10"),
        point_value=Decimal("100"),
    )

    spec.assert_price_aligned(Decimal("2012.30"))

    with pytest.raises(ValueError, match="not aligned"):
        spec.assert_price_aligned(Decimal("2012.34"))


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        (
            {
                "symbol": "",
                "tick_size": Decimal("0.10"),
                "point_value": Decimal("100"),
            },
            "symbol",
        ),
        (
            {
                "symbol": "GC",
                "tick_size": Decimal("0"),
                "point_value": Decimal("100"),
            },
            "tick_size",
        ),
        (
            {
                "symbol": "GC",
                "tick_size": Decimal("0.10"),
                "point_value": Decimal("0"),
            },
            "point_value",
        ),
        (
            {
                "symbol": "GC",
                "tick_size": Decimal("0.10"),
                "point_value": Decimal("100"),
                "commission_per_contract": Decimal("-1"),
            },
            "commission",
        ),
    ],
)
def test_instrument_spec_validates_required_economics(
    kwargs: dict,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        InstrumentSpec(**kwargs)


def test_synthetic_source_small_mbo_is_readable_and_deterministic() -> None:
    events = SyntheticSource.small_mbo()

    assert events == SyntheticSource.small_mbo()
    assert {event.action for event in events} == {"add", "cancel", "modify", "trade"}
    assert [event.ts_ns for event in events] == sorted(event.ts_ns for event in events)
    assert all(isinstance(event, MBOEvent) for event in events)
    assert all(event.size > 0 for event in events)
    assert all(event.price.as_tuple().exponent <= 0 for event in events)


def test_synthetic_source_execution_equivalence_mbo_documents_queue_case() -> None:
    events = SyntheticSource.execution_equivalence_mbo()

    assert events == SyntheticSource.execution_equivalence_mbo()
    assert [event.action for event in events] == [
        "add",
        "add",
        "modify",
        "cancel",
        "trade",
    ]
    assert [event.ts_ns for event in events] == [1, 2, 3, 4, 5]
    assert events[-1].side == "bid"
    assert events[-1].size == 4


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        (
            {
                "ts_ns": -1,
                "action": "add",
                "side": "bid",
                "price": Decimal("100.0"),
                "size": 1,
                "order_id": 1,
            },
            "ts_ns",
        ),
        (
            {
                "ts_ns": 1,
                "action": "add",
                "side": "bid",
                "price": Decimal("0"),
                "size": 1,
                "order_id": 1,
            },
            "price",
        ),
        (
            {
                "ts_ns": 1,
                "action": "add",
                "side": "bid",
                "price": Decimal("100.0"),
                "size": 0,
                "order_id": 1,
            },
            "size",
        ),
        (
            {
                "ts_ns": 1,
                "action": "add",
                "side": "bid",
                "price": Decimal("100.0"),
                "size": 1,
                "order_id": -1,
            },
            "order_id",
        ),
    ],
)
def test_mbo_event_validates_replay_inputs(kwargs: dict, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        MBOEvent(**kwargs)
