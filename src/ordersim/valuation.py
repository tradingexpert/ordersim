"""Valuation marks used to build mark-to-market equity curves."""

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from typing import TypeAlias

from ordersim.types import Price


@dataclass(frozen=True, slots=True)
class ValuationMark:
    """One public mark price used to value open lots."""

    ts_ns: int
    price: Price


@dataclass(frozen=True, slots=True)
class CompiledValuationMarks:
    """Compact valuation marks stored as timestamp and midpoint tick columns.

    `mid_ticks_x2` stores `bid_ticks + ask_ticks`, so half-tick midpoints stay
    exact until the public `Decimal` equity curve is built.
    """

    ts_ns: memoryview
    mid_ticks_x2: memoryview
    tick_size: Decimal

    @classmethod
    def from_bytes(
        cls,
        *,
        ts_ns: bytes,
        mid_ticks_x2: bytes,
        tick_size: Decimal,
    ) -> "CompiledValuationMarks":
        """Build compact marks from native int64 byte columns."""

        timestamps = memoryview(ts_ns).cast("q")
        mids = memoryview(mid_ticks_x2).cast("q")
        if len(timestamps) != len(mids):
            raise ValueError("valuation mark columns must have equal length")
        return cls(ts_ns=timestamps, mid_ticks_x2=mids, tick_size=tick_size)

    def __len__(self) -> int:
        return len(self.ts_ns)


ValuationMarkInput: TypeAlias = (
    tuple[ValuationMark | CompiledValuationMarks, ...]
    | list[ValuationMark | CompiledValuationMarks]
    | CompiledValuationMarks
)


def iter_valuation_mark_pairs(
    marks: ValuationMarkInput,
) -> Iterable[tuple[int, Price]]:
    """Yield `(timestamp, price)` pairs from public or compact mark inputs."""

    if isinstance(marks, CompiledValuationMarks):
        yield from iter_compiled_valuation_mark_pairs(marks)
        return

    for mark in marks:
        if isinstance(mark, CompiledValuationMarks):
            yield from iter_compiled_valuation_mark_pairs(mark)
        else:
            yield mark.ts_ns, mark.price


def iter_compiled_valuation_mark_pairs(
    marks: CompiledValuationMarks,
) -> Iterable[tuple[int, Price]]:
    """Yield Decimal midpoint prices from compact integer mark columns."""

    for ts_ns, mid_ticks_x2 in zip(marks.ts_ns, marks.mid_ticks_x2, strict=True):
        yield ts_ns, marks.tick_size * Decimal(mid_ticks_x2) / 2
