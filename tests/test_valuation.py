from decimal import Decimal

import pytest

from ordersim.valuation import (
    CompiledValuationMarks,
    ValuationMark,
    iter_valuation_mark_pairs,
)


def int64_bytes(values: tuple[int, ...]) -> bytes:
    from array import array

    return array("q", values).tobytes()


def test_compact_valuation_marks_reject_mismatched_columns() -> None:
    with pytest.raises(ValueError, match="equal length"):
        CompiledValuationMarks.from_bytes(
            ts_ns=int64_bytes((1, 2)),
            mid_ticks_x2=int64_bytes((2000,)),
            tick_size=Decimal("0.10"),
        )


def test_iter_valuation_mark_pairs_accepts_public_and_compact_marks() -> None:
    marks = [
        ValuationMark(ts_ns=1, price=Decimal("100.0")),
        CompiledValuationMarks.from_bytes(
            ts_ns=int64_bytes((2,)),
            mid_ticks_x2=int64_bytes((2010,)),
            tick_size=Decimal("0.10"),
        ),
    ]

    assert list(iter_valuation_mark_pairs(marks)) == [
        (1, Decimal("100.0")),
        (2, Decimal("100.5")),
    ]


def test_iter_valuation_mark_pairs_accepts_compact_marks_directly() -> None:
    marks = CompiledValuationMarks.from_bytes(
        ts_ns=int64_bytes((1, 2)),
        mid_ticks_x2=int64_bytes((2000, 2010)),
        tick_size=Decimal("0.10"),
    )

    assert list(iter_valuation_mark_pairs(marks)) == [
        (1, Decimal("100.0")),
        (2, Decimal("100.5")),
    ]
