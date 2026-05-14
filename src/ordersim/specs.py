"""Instrument specifications and price/tick helpers."""

from dataclasses import dataclass
from decimal import Decimal, localcontext

from ordersim.types import Price


@dataclass(frozen=True, slots=True)
class InstrumentSpec:
    """Execution-relevant metadata for one tradable instrument.

    Values are explicit constructor arguments rather than hidden package
    defaults. Reference presets may be useful examples, but callers should own
    the exact economics they want to simulate.
    """

    symbol: str
    tick_size: Price
    point_value: Decimal
    commission_per_contract: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        if not self.symbol:
            raise ValueError("symbol must be non-empty")
        if self.tick_size <= 0:
            raise ValueError("tick_size must be positive")
        if self.point_value <= 0:
            raise ValueError("point_value must be positive")
        if self.commission_per_contract < 0:
            raise ValueError("commission_per_contract cannot be negative")

    def price_to_ticks(self, price: Price) -> int:
        """Convert an exact price to integer ticks.

        Raises:
            ValueError: if `price` is not exactly aligned to `tick_size`.
        """

        with localcontext() as ctx:
            ctx.prec = max(len(price.as_tuple().digits), 28) + 8
            ticks = price / self.tick_size

        if ticks != ticks.to_integral_value():
            raise ValueError(
                f"price {price} is not aligned to tick_size {self.tick_size}"
            )
        return int(ticks)

    def ticks_to_price(self, ticks: int) -> Price:
        """Convert integer ticks back to an exact price."""

        return self.tick_size * Decimal(ticks)

    def assert_price_aligned(self, price: Price) -> None:
        """Raise if a price cannot be represented as whole ticks."""

        self.price_to_ticks(price)
