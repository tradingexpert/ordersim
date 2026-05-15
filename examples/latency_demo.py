"""Latency demo used by the README.

Run with:

    python examples/latency_demo.py
"""

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from ordersim import ConstantLatency, InstrumentSpec, Replay, ReplayResult
from ordersim.fixtures.synthetic import SyntheticSource


@dataclass(frozen=True, slots=True)
class DemoRun:
    """One replay outcome for a fixed entry-latency setting."""

    label: str
    entry_latency_ns: int
    queue_ahead_at_arrival: int
    fill_kind: str
    result: ReplayResult


def instrument() -> InstrumentSpec:
    """Return the tiny gold-futures contract used by the demo."""

    return InstrumentSpec(
        symbol="GC",
        tick_size=Decimal("0.10"),
        point_value=Decimal("100"),
        commission_per_contract=Decimal("2.50"),
    )


def _strategy(queue_ahead: list[int]):
    def strategy(gateway) -> None:
        gateway.advance_to(101)
        bid, _ask = gateway.book_top()
        if bid is None:
            return

        result = gateway.place_limit(side="buy", price=bid, size=1)
        own_orders = gateway.own_orders()
        if own_orders:
            queue_ahead.append(own_orders[0].queue_ahead_size)

        gateway.advance_to(130)
        if gateway.position() == 0:
            if result.order_id is not None:
                gateway.cancel(result.order_id)
            gateway.place_market(side="buy", size=1)

    return strategy


def run_case(label: str, entry_latency_ns: int) -> DemoRun:
    """Run the same strategy with one entry-latency setting."""

    queue_ahead: list[int] = []
    replay = Replay(
        data=SyntheticSource.latency_demo_mbo(),
        instrument=instrument(),
        latency_model_factory=lambda: ConstantLatency(
            entry_ns=entry_latency_ns,
        ),
    )
    result = replay.run(_strategy(queue_ahead), strategy_name=label)
    fill_kind = next(
        event.kind
        for event in result.order_events
        if event.kind in {"fill", "fill_passive"}
    )
    return DemoRun(
        label=label,
        entry_latency_ns=entry_latency_ns,
        queue_ahead_at_arrival=queue_ahead[0],
        fill_kind=fill_kind,
        result=result,
    )


def run() -> tuple[DemoRun, DemoRun]:
    """Return the fast and delayed outcomes for the same replay."""

    return (
        run_case("0 ns entry latency", entry_latency_ns=0),
        run_case("15 ns entry latency", entry_latency_ns=15),
    )


def render_svg(runs: tuple[DemoRun, DemoRun]) -> str:
    """Render the demo as a small standalone SVG."""

    fast, slow = runs
    fast_fill = fast.result.fills[0]
    slow_fill = slow.result.fills[0]
    fast_equity = fast.result.equity_curve[-1].equity
    slow_equity = slow.result.equity_curve[-1].equity

    lines = [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 520"',
        '     role="img" aria-labelledby="title desc">',
        "  <title id=\"title\">Same replay, same strategy, "
        "different entry latency</title>",
        "  <desc id=\"desc\">Zero entry latency reaches the bid before the "
        "trade and fills passively at 100.0. Fifteen nanoseconds of entry "
        "latency arrives after the trade and later crosses the spread at "
        "101.0.</desc>",
        '  <rect width="960" height="520" fill="#fbfbfa"/>',
        _text(
            48,
            48,
            26,
            "#171717",
            "Same replay. Same strategy. Different latency.",
        ),
        _text(
            48,
            78,
            16,
            "#4b5563",
            "Entry latency changes the execution path before final PnL appears.",
        ),
        "",
        _line(180, 150, 860, 150),
        _line(180, 280, 860, 280),
        _text(48, 155, 18, "#171717", "0 ns"),
        _text(48, 285, 18, "#171717", "15 ns"),
        "",
        _text(192, 120, 14, "#475569", "t=101 quote"),
        _text(332, 120, 14, "#475569", "t=105 cancel"),
        _text(470, 120, 14, "#475569", "t=110 trade"),
        _text(690, 120, 14, "#475569", "fallback cross"),
        "",
        _circle(220, 150, 9, "#2563eb"),
        _circle(360, 150, 9, "#64748b"),
        _circle(500, 150, 11, "#16a34a"),
        _text(204, 182, 14, "#171717", "joins queue"),
        _text(334, 182, 14, "#171717", "ahead shrinks"),
        _text(465, 182, 14, "#171717", "passive fill"),
        "",
        _circle(220, 280, 9, "#2563eb"),
        _circle(360, 280, 9, "#64748b"),
        _circle(500, 280, 9, "#ef4444"),
        _circle(640, 280, 9, "#2563eb"),
        _circle(780, 280, 11, "#f59e0b"),
        _text(196, 312, 14, "#171717", "send"),
        _text(334, 312, 14, "#171717", "cancel"),
        _text(476, 312, 14, "#171717", "missed"),
        _text(610, 312, 14, "#171717", "arrives late"),
        _text(748, 312, 14, "#171717", "market fill"),
        "",
        _rect(48, 364, 400, 112, "#ecfdf5"),
        _rect(480, 364, 400, 112, "#fff7ed"),
        _text(72, 396, 18, "#166534", fast.label),
        _text(504, 396, 18, "#9a3412", slow.label),
        _text(
            72,
            426,
            16,
            "#171717",
            f"queue ahead on arrival: {fast.queue_ahead_at_arrival}",
        ),
        _text(
            504,
            426,
            16,
            "#171717",
            f"queue ahead on arrival: {slow.queue_ahead_at_arrival}",
        ),
        _text(72, 450, 16, "#171717", f"{fast.fill_kind}: {fast_fill.price}"),
        _text(
            504,
            450,
            16,
            "#171717",
            f"{slow.fill_kind}: {slow_fill.price}",
        ),
        _text(72, 474, 16, "#171717", f"final equity: {fast_equity}"),
        _text(504, 474, 16, "#171717", f"final equity: {slow_equity}"),
        "</svg>",
    ]
    return "\n".join(lines) + "\n"


def _text(x: int, y: int, size: int, color: str, value: str) -> str:
    return (
        f'  <text x="{x}" y="{y}" font-family="Arial, sans-serif" '
        f'font-size="{size}" fill="{color}">{value}</text>'
    )


def _line(x1: int, y1: int, x2: int, y2: int) -> str:
    return (
        f'  <line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
        'stroke="#cbd5e1" stroke-width="2"/>'
    )


def _circle(cx: int, cy: int, radius: int, color: str) -> str:
    return f'  <circle cx="{cx}" cy="{cy}" r="{radius}" fill="{color}"/>'


def _rect(x: int, y: int, width: int, height: int, color: str) -> str:
    return (
        f'  <rect x="{x}" y="{y}" width="{width}" height="{height}" '
        f'rx="8" fill="{color}"/>'
    )


def write_svg(path: Path) -> None:
    """Write the current demo visualization to ``path``."""

    path.write_text(render_svg(run()), encoding="utf-8")


if __name__ == "__main__":
    for case in run():
        fill = case.result.fills[0]
        equity = case.result.equity_curve[-1].equity
        print(
            case.label,
            case.queue_ahead_at_arrival,
            case.fill_kind,
            fill.price,
            equity,
        )
