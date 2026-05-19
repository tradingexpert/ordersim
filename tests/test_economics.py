from decimal import Decimal

import pytest

from ordersim import (
    CompiledValuationMarks,
    EquityPoint,
    Fill,
    InstrumentSpec,
    PositionLot,
    ValuationMark,
    build_equity_curve,
    summarize_fills,
)


def int64_bytes(values: tuple[int, ...]) -> bytes:
    from array import array

    return array("q", values).tobytes()


def gc_spec() -> InstrumentSpec:
    return InstrumentSpec(
        symbol="GC",
        tick_size=Decimal("0.10"),
        point_value=Decimal("100"),
        commission_per_contract=Decimal("2.50"),
    )


def test_summarize_fills_returns_empty_ledger_for_no_fills() -> None:
    summary = summarize_fills((), gc_spec())

    assert summary.contract_volume == 0
    assert summary.gross_notional == Decimal("0")
    assert summary.signed_notional == Decimal("0")
    assert summary.commission == Decimal("0")
    assert summary.realized_pnl == Decimal("0")
    assert summary.net_realized_pnl == Decimal("0")
    assert summary.final_position == 0
    assert summary.open_lots == ()


def test_summarize_fills_computes_fifo_realized_pnl_and_open_lots() -> None:
    fills = (
        Fill(order_id=1, side="buy", price=Decimal("100.0"), size=2, ts_ns=1),
        Fill(order_id=2, side="sell", price=Decimal("101.0"), size=1, ts_ns=2),
        Fill(order_id=3, side="sell", price=Decimal("99.0"), size=2, ts_ns=3),
    )

    summary = summarize_fills(fills, gc_spec())

    assert summary.contract_volume == 5
    assert summary.gross_notional == Decimal("49900.0")
    assert summary.signed_notional == Decimal("9900.0")
    assert summary.commission == Decimal("12.50")
    assert summary.realized_pnl == Decimal("0.0")
    assert summary.net_realized_pnl == Decimal("-12.50")
    assert summary.final_position == -1
    assert summary.open_lots == (
        PositionLot(side="sell", price=Decimal("99.0"), size=1),
    )


def test_summarize_fills_closes_short_lots_with_fifo_pnl() -> None:
    fills = (
        Fill(order_id=1, side="sell", price=Decimal("101.0"), size=2, ts_ns=1),
        Fill(order_id=2, side="buy", price=Decimal("99.0"), size=1, ts_ns=2),
    )

    summary = summarize_fills(fills, gc_spec())

    assert summary.realized_pnl == Decimal("200.0")
    assert summary.net_realized_pnl == Decimal("192.50")
    assert summary.final_position == -1
    assert summary.open_lots == (
        PositionLot(side="sell", price=Decimal("101.0"), size=1),
    )


def test_build_equity_curve_marks_open_lots_and_drawdown() -> None:
    fills = (
        Fill(order_id=1, side="buy", price=Decimal("100.0"), size=1, ts_ns=1),
        Fill(order_id=2, side="sell", price=Decimal("100.0"), size=1, ts_ns=4),
    )
    marks = (
        ValuationMark(ts_ns=2, price=Decimal("101.0")),
        ValuationMark(ts_ns=3, price=Decimal("99.0")),
        ValuationMark(ts_ns=4, price=Decimal("100.0")),
    )

    curve = build_equity_curve(fills, marks, gc_spec())

    assert curve == (
        EquityPoint(
            ts_ns=2,
            mark_price=Decimal("101.0"),
            realized_pnl=Decimal("0"),
            unrealized_pnl=Decimal("100.0"),
            commission=Decimal("2.50"),
            equity=Decimal("97.50"),
            drawdown=Decimal("0.00"),
        ),
        EquityPoint(
            ts_ns=3,
            mark_price=Decimal("99.0"),
            realized_pnl=Decimal("0"),
            unrealized_pnl=Decimal("-100.0"),
            commission=Decimal("2.50"),
            equity=Decimal("-102.50"),
            drawdown=Decimal("200.00"),
        ),
        EquityPoint(
            ts_ns=4,
            mark_price=Decimal("100.0"),
            realized_pnl=Decimal("0.0"),
            unrealized_pnl=Decimal("0"),
            commission=Decimal("5.00"),
            equity=Decimal("-5.00"),
            drawdown=Decimal("102.50"),
        ),
    )


def test_build_equity_curve_returns_no_points_without_marks() -> None:
    fills = (
        Fill(order_id=1, side="buy", price=Decimal("100.0"), size=1, ts_ns=1),
    )

    assert build_equity_curve(fills, (), gc_spec()) == ()


def test_build_equity_curve_accepts_compact_valuation_marks() -> None:
    fills = (
        Fill(order_id=1, side="buy", price=Decimal("100.0"), size=1, ts_ns=1),
        Fill(order_id=2, side="sell", price=Decimal("100.0"), size=1, ts_ns=4),
    )
    marks = CompiledValuationMarks.from_bytes(
        ts_ns=int64_bytes((2, 3, 4)),
        mid_ticks_x2=int64_bytes((2020, 1980, 2000)),
        tick_size=Decimal("0.10"),
    )

    curve = build_equity_curve(fills, marks, gc_spec())

    assert [point.mark_price for point in curve] == [
        Decimal("101.0"),
        Decimal("99.0"),
        Decimal("100.0"),
    ]
    assert curve[-1].equity == Decimal("-5.00")


def test_build_equity_curve_accepts_mixed_public_and_compact_marks() -> None:
    marks = [
        ValuationMark(ts_ns=1, price=Decimal("100.0")),
        CompiledValuationMarks.from_bytes(
            ts_ns=int64_bytes((2,)),
            mid_ticks_x2=int64_bytes((2010,)),
            tick_size=Decimal("0.10"),
        ),
    ]

    curve = build_equity_curve((), marks, gc_spec())

    assert [(point.ts_ns, point.mark_price) for point in curve] == [
        (1, Decimal("100.0")),
        (2, Decimal("100.5")),
    ]


def test_compact_valuation_marks_reject_mismatched_columns() -> None:
    with pytest.raises(ValueError, match="equal length"):
        CompiledValuationMarks.from_bytes(
            ts_ns=int64_bytes((1, 2)),
            mid_ticks_x2=int64_bytes((2000,)),
            tick_size=Decimal("0.10"),
        )
