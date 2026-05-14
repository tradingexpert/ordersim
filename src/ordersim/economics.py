"""Execution economics computed directly from fills."""

from dataclasses import dataclass
from decimal import Decimal

from ordersim.specs import InstrumentSpec
from ordersim.types import Fill, Price, Side


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
