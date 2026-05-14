"""Execution engine protocol.

Engines consume normalized `MBOEvent` rows and strategy order intents. Vendor
data connectors are separate; they normalize source data before replay.
"""

from collections.abc import Callable
from typing import Protocol

from ordersim.types import (
    Fill,
    MBOEvent,
    OrderId,
    OrderResult,
    Price,
    Side,
    TimeInForce,
)


class ExecutionEngine(Protocol):
    """Execution engine used by `ReplayGateway`.

    The pure Python `MatchingEngine` is the reference engine. A compiled
    engine may implement this same protocol only if it preserves observable
    replay behavior.
    """

    def apply_event(self, event: MBOEvent) -> list[Fill]:
        """Apply one market-data event and return passive fills."""

    def advance_time(self, ts_ns: int) -> None:
        """Advance engine time without applying a market-data event."""

    def place_limit(
        self,
        side: Side,
        price: Price,
        size: int,
        tif: TimeInForce = "GTC",
    ) -> OrderResult:
        """Place a strategy limit order."""

    def place_market(self, side: Side, size: int) -> list[Fill]:
        """Place a strategy market order."""

    def cancel(self, order_id: OrderId) -> bool:
        """Cancel a resting strategy order."""

    def book_top(self) -> tuple[Price | None, Price | None]:
        """Return ``(best_bid, best_ask)``."""

    def book_depth(self, levels: int) -> object:
        """Return a depth snapshot."""

    def position(self) -> int:
        """Return current signed position."""


ExecutionEngineFactory = Callable[[], ExecutionEngine]


def default_execution_engine_factory() -> ExecutionEngine:
    """Return the default pure Python reference engine."""

    from ordersim.sim.matching_engine import MatchingEngine

    return MatchingEngine()
