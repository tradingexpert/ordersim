"""Execution economics computed directly from fills."""

from dataclasses import dataclass
from decimal import Decimal

from ordersim.specs import InstrumentSpec
from ordersim.types import Fill, Price, Side
from ordersim.valuation import (
    CompiledValuationMarks,
    ValuationMark,
    ValuationMarkInput,
    iter_valuation_mark_pairs,
)

__all__ = [
    "CompiledValuationMarks",
    "EquityPoint",
    "ExecutionSummary",
    "PositionLot",
    "ValuationMark",
    "ValuationMarkInput",
    "build_equity_curve",
    "summarize_fills",
]


@dataclass(frozen=True, slots=True)
class PositionLot:
    """One remaining open FIFO lot after processing fills."""

    side: Side
    price: Price
    size: int


@dataclass(frozen=True, slots=True)
class ExecutionSummary:
    """Deterministic fill ledger summary.

    `signed_notional` uses strategy convention: buys are negative and sells are
    positive. Futures margin, funding, variation margin, and mark-to-market PnL
    are deliberately outside this simple realized ledger.
    """

    contract_volume: int
    gross_notional: Decimal
    signed_notional: Decimal
    commission: Decimal
    realized_pnl: Decimal
    net_realized_pnl: Decimal
    final_position: int
    open_lots: tuple[PositionLot, ...]


@dataclass(frozen=True, slots=True)
class EquityPoint:
    """One point on a mark-to-market equity curve."""

    ts_ns: int
    mark_price: Price
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    commission: Decimal
    equity: Decimal
    drawdown: Decimal

def summarize_fills(
    fills: tuple[Fill, ...] | list[Fill],
    instrument: InstrumentSpec,
) -> ExecutionSummary:
    """Summarize fills using FIFO realized PnL.

    Args:
        fills: Strategy fills in execution order.
        instrument: Contract economics used for notional, PnL, and commission.

    Returns:
        A deterministic realized ledger summary.
    """

    open_lots: list[PositionLot] = []
    contract_volume = 0
    gross_notional = Decimal("0")
    signed_notional = Decimal("0")
    commission = Decimal("0")
    realized_pnl = Decimal("0")

    for fill in fills:
        fill_notional = fill.price * fill.size * instrument.point_value
        contract_volume += fill.size
        gross_notional += fill_notional
        signed_notional += fill_notional if fill.side == "sell" else -fill_notional
        commission += instrument.commission_per_contract * fill.size
        realized_pnl += _apply_fill_to_lots(open_lots, fill, instrument)

    final_position = sum(
        lot.size if lot.side == "buy" else -lot.size for lot in open_lots
    )
    return ExecutionSummary(
        contract_volume=contract_volume,
        gross_notional=gross_notional,
        signed_notional=signed_notional,
        commission=commission,
        realized_pnl=realized_pnl,
        net_realized_pnl=realized_pnl - commission,
        final_position=final_position,
        open_lots=tuple(open_lots),
    )


def build_equity_curve(
    fills: tuple[Fill, ...] | list[Fill],
    marks: ValuationMarkInput,
    instrument: InstrumentSpec,
) -> tuple[EquityPoint, ...]:
    """Build a mark-to-market equity curve from fills and valuation marks.

    Fills at the same timestamp as a mark are processed before that mark. Equity
    is `realized_pnl + unrealized_pnl - commission`.
    """

    sorted_fills = tuple(sorted(fills, key=lambda fill: fill.ts_ns))
    if isinstance(marks, CompiledValuationMarks):
        return _build_equity_curve_from_compiled_marks(
            sorted_fills,
            marks,
            instrument,
        )

    sorted_marks = tuple(
        sorted(iter_valuation_mark_pairs(marks), key=lambda mark: mark[0])
    )
    open_lots: list[PositionLot] = []
    realized_pnl = Decimal("0")
    commission = Decimal("0")
    high_water_mark = Decimal("0")
    points: list[EquityPoint] = []
    fill_index = 0

    for mark_ts_ns, mark_price in sorted_marks:
        while (
            fill_index < len(sorted_fills)
            and sorted_fills[fill_index].ts_ns <= mark_ts_ns
        ):
            fill = sorted_fills[fill_index]
            realized_pnl += _apply_fill_to_lots(open_lots, fill, instrument)
            commission += instrument.commission_per_contract * fill.size
            fill_index += 1

        unrealized_pnl = _unrealized_pnl(open_lots, mark_price, instrument)
        equity = realized_pnl + unrealized_pnl - commission
        high_water_mark = max(high_water_mark, equity)
        points.append(
            EquityPoint(
                ts_ns=mark_ts_ns,
                mark_price=mark_price,
                realized_pnl=realized_pnl,
                unrealized_pnl=unrealized_pnl,
                commission=commission,
                equity=equity,
                drawdown=high_water_mark - equity,
            )
        )

    return tuple(points)


def _build_equity_curve_from_compiled_marks(
    sorted_fills: tuple[Fill, ...],
    marks: CompiledValuationMarks,
    instrument: InstrumentSpec,
) -> tuple[EquityPoint, ...]:
    open_lots: list[PositionLot] = []
    realized_pnl = Decimal("0")
    commission = Decimal("0")
    high_water_mark = Decimal("0")
    points: list[EquityPoint] = []
    fill_index = 0

    for ts_ns, mid_ticks_x2 in zip(marks.ts_ns, marks.mid_ticks_x2, strict=True):
        while (
            fill_index < len(sorted_fills)
            and sorted_fills[fill_index].ts_ns <= ts_ns
        ):
            fill = sorted_fills[fill_index]
            realized_pnl += _apply_fill_to_lots(open_lots, fill, instrument)
            commission += instrument.commission_per_contract * fill.size
            fill_index += 1

        mark_price = marks.tick_size * Decimal(mid_ticks_x2) / 2
        unrealized_pnl = _unrealized_pnl(open_lots, mark_price, instrument)
        equity = realized_pnl + unrealized_pnl - commission
        high_water_mark = max(high_water_mark, equity)
        points.append(
            EquityPoint(
                ts_ns=ts_ns,
                mark_price=mark_price,
                realized_pnl=realized_pnl,
                unrealized_pnl=unrealized_pnl,
                commission=commission,
                equity=equity,
                drawdown=high_water_mark - equity,
            )
        )

    return tuple(points)


def _apply_fill_to_lots(
    open_lots: list[PositionLot],
    fill: Fill,
    instrument: InstrumentSpec,
) -> Decimal:
    remaining = fill.size
    realized_pnl = Decimal("0")
    opposite_side = "sell" if fill.side == "buy" else "buy"

    while remaining > 0 and open_lots and open_lots[0].side == opposite_side:
        lot = open_lots[0]
        closed_size = min(remaining, lot.size)
        realized_pnl += _closed_lot_pnl(
            open_side=lot.side,
            open_price=lot.price,
            close_price=fill.price,
            size=closed_size,
            point_value=instrument.point_value,
        )

        remaining -= closed_size
        if closed_size == lot.size:
            open_lots.pop(0)
        else:
            open_lots[0] = PositionLot(
                side=lot.side,
                price=lot.price,
                size=lot.size - closed_size,
            )

    if remaining > 0:
        open_lots.append(
            PositionLot(side=fill.side, price=fill.price, size=remaining)
        )

    return realized_pnl


def _closed_lot_pnl(
    *,
    open_side: Side,
    open_price: Price,
    close_price: Price,
    size: int,
    point_value: Decimal,
) -> Decimal:
    if open_side == "buy":
        return (close_price - open_price) * size * point_value
    return (open_price - close_price) * size * point_value


def _unrealized_pnl(
    open_lots: list[PositionLot],
    mark_price: Price,
    instrument: InstrumentSpec,
) -> Decimal:
    total = Decimal("0")
    for lot in open_lots:
        total += _closed_lot_pnl(
            open_side=lot.side,
            open_price=lot.price,
            close_price=mark_price,
            size=lot.size,
            point_value=instrument.point_value,
        )
    return total
