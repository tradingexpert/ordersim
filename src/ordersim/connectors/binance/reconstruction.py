"""Deterministic virtual-MBO reconstruction from Binance L2 and trades.

The model preserves observed depth endpoints and individual trades. It does
not claim to recover exchange-native order IDs or the true placement of
cancellations inside a price-level queue.
"""

from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal, TypeAlias

from ordersim.connectors.binance.l2 import (
    BinanceDepthSnapshot,
    BinanceDepthUpdate,
    BinanceIndividualTrade,
    BinancePriceLevel,
)
from ordersim.types import BookSide, MBOEvent

BinanceReconstructionPolicy: TypeAlias = Literal[
    "queue-conservative",
    "queue-optimistic",
]


@dataclass(frozen=True, slots=True)
class BinanceReconstructionConfig:
    """Configuration for one deterministic virtual-MBO reconstruction.

    `quantity_step` maps Binance's exact decimal contract quantity to the
    integer sizes required by `MBOEvent`.

    `queue-conservative` places all minimally required additions before the
    first trade at a level and removes cancellations from the newest visible
    liquidity. `queue-optimistic` adds liquidity only when needed and removes
    cancellations from the oldest visible liquidity. The two policies bound
    queue-position effects; neither is presented as an observed FIFO queue.

    Set `emit_events=False` only for aggregate evidence studies. The same
    endpoint and flow calculations run, but returned `events` tuples are empty
    and explicit virtual-order queues are not retained.
    """

    quantity_step: Decimal
    policy: BinanceReconstructionPolicy = "queue-conservative"
    emit_events: bool = True

    def __post_init__(self) -> None:
        if self.quantity_step <= 0:
            raise ValueError("quantity_step must be positive")
        if self.policy not in ("queue-conservative", "queue-optimistic"):
            raise ValueError(f"unsupported reconstruction policy {self.policy!r}")


@dataclass(frozen=True, slots=True)
class BinanceReconstructionMetrics:
    """Evidence and inferred flow produced by one reconstruction step."""

    depth_updates: int = 0
    levels_checked: int = 0
    trade_count: int = 0
    trade_units: int = 0
    snapshot_add_units: int = 0
    inferred_add_units: int = 0
    inferred_cancel_units: int = 0
    required_replenishment_units: int = 0
    pre_trade_add_units: int = 0


@dataclass(frozen=True, slots=True)
class BinanceReconstructionStep:
    """Canonical events and metrics for one depth endpoint."""

    events: tuple[MBOEvent, ...]
    metrics: BinanceReconstructionMetrics


@dataclass(slots=True)
class _VirtualOrder:
    order_id: int
    size: int


class BinanceMBOReconstructor:
    """Incrementally reconstruct one snapshot-anchored Binance depth segment.

    Call `bootstrap(snapshot, bridge_update)` once, then call `apply_update`
    with each later standard depth update and the individual trades aligned to
    that update's exchange-time interval.
    """

    def __init__(self, config: BinanceReconstructionConfig) -> None:
        self.config = config
        self._symbol: str | None = None
        self._connection_id: str | None = None
        self._previous_transaction_time_ns: int | None = None
        self._queues: dict[tuple[BookSide, Decimal], deque[_VirtualOrder]] = {}
        self._level_units: dict[tuple[BookSide, Decimal], int] = {}
        self._next_order_id = 1
        self._best_bid: Decimal | None = None
        self._best_ask: Decimal | None = None

    @property
    def symbol(self) -> str | None:
        """The bootstrapped symbol, or `None` before bootstrap."""

        return self._symbol

    @property
    def previous_transaction_time_ns(self) -> int | None:
        """Exchange transaction time of the last applied depth update."""

        return self._previous_transaction_time_ns

    def bootstrap(
        self,
        snapshot: BinanceDepthSnapshot,
        bridge_update: BinanceDepthUpdate,
    ) -> BinanceReconstructionStep:
        """Anchor the virtual book and apply the first snapshot-bridging update."""

        if self._symbol is not None:
            raise RuntimeError("reconstructor is already bootstrapped")
        if bridge_update.stream_kind != "depth":
            raise ValueError("bridge_update must come from standard depth")
        if snapshot.symbol != bridge_update.symbol:
            raise ValueError("snapshot and bridge update symbols differ")
        if snapshot.connection_id != bridge_update.connection_id:
            raise ValueError("snapshot and bridge update connections differ")
        if not (
            bridge_update.first_update_id
            <= snapshot.last_update_id
            <= bridge_update.final_update_id
        ):
            raise ValueError("bridge update does not span snapshot last_update_id")

        self._symbol = snapshot.symbol
        self._connection_id = snapshot.connection_id
        ts_ns = bridge_update.transaction_time_ns
        events: list[MBOEvent] = []
        snapshot_units = 0

        for side, levels in (("bid", snapshot.bids), ("ask", snapshot.asks)):
            for level in self._sorted_levels(side, levels):
                size = self._to_units(level.quantity)
                if size == 0:
                    continue
                self._append_public(side, level.price, size)
                self._record_add(events, ts_ns, side, level.price, size)
                snapshot_units += size

        inferred_add, inferred_cancel, checked = self._apply_endpoint(
            bridge_update,
            events,
        )
        self._previous_transaction_time_ns = bridge_update.transaction_time_ns
        return BinanceReconstructionStep(
            events=tuple(events),
            metrics=BinanceReconstructionMetrics(
                depth_updates=1,
                levels_checked=checked,
                snapshot_add_units=snapshot_units,
                inferred_add_units=inferred_add,
                inferred_cancel_units=inferred_cancel,
            ),
        )

    def apply_update(
        self,
        update: BinanceDepthUpdate,
        trades: Iterable[BinanceIndividualTrade] = (),
    ) -> BinanceReconstructionStep:
        """Apply one later depth endpoint and its aligned individual trades."""

        previous_time = self._require_compatible_update(update)
        aligned_trades = tuple(
            sorted(trades, key=lambda trade: (trade.trade_time_ns, trade.trade_id))
        )
        for trade in aligned_trades:
            if trade.symbol != update.symbol:
                raise ValueError("trade and depth update symbols differ")
            if trade.price <= 0 or trade.quantity <= 0:
                raise ValueError("trade price and quantity must be positive")
            if not previous_time < trade.trade_time_ns <= update.transaction_time_ns:
                raise ValueError("trade is outside the depth update interval")

        endpoint_targets = self._endpoint_targets(update)
        trade_units_by_level: dict[tuple[BookSide, Decimal], int] = {}
        for trade in aligned_trades:
            key = (self._resting_side(trade), trade.price)
            trade_units_by_level[key] = (
                trade_units_by_level.get(key, 0) + self._to_units(trade.quantity)
            )

        keys = set(endpoint_targets) | set(trade_units_by_level)
        targets = {
            key: endpoint_targets.get(key, self._level_units.get(key, 0))
            for key in keys
        }
        minimum_adds: dict[tuple[BookSide, Decimal], int] = {}
        required_replenishment = 0
        for key in keys:
            before = self._level_units.get(key, 0)
            traded = trade_units_by_level.get(key, 0)
            target = targets.get(key, before)
            minimum_adds[key] = max(0, target + traded - before)
            required_replenishment += max(0, traded - before)

        events: list[MBOEvent] = []
        preadded: set[tuple[BookSide, Decimal]] = set()
        inferred_add = 0
        pre_trade_add = 0
        trade_units = 0

        for trade in aligned_trades:
            side = self._resting_side(trade)
            key = (side, trade.price)
            size = self._to_units(trade.quantity)
            if self.config.policy == "queue-conservative" and key not in preadded:
                addition = minimum_adds[key]
                if addition:
                    self._append_public(side, trade.price, addition)
                    self._record_add(
                        events,
                        trade.trade_time_ns,
                        side,
                        trade.price,
                        addition,
                    )
                    inferred_add += addition
                    pre_trade_add += addition
                preadded.add(key)
            elif self.config.policy == "queue-optimistic":
                shortfall = max(0, size - self._level_units.get(key, 0))
                if shortfall:
                    self._append_public(side, trade.price, shortfall)
                    self._record_add(
                        events,
                        trade.trade_time_ns,
                        side,
                        trade.price,
                        shortfall,
                    )
                    inferred_add += shortfall
                    pre_trade_add += shortfall

            self._consume_public(side, trade.price, size)
            if self.config.emit_events:
                events.append(
                    MBOEvent(
                        ts_ns=trade.trade_time_ns,
                        action="trade",
                        side=side,
                        price=trade.price,
                        size=size,
                        order_id=trade.trade_id,
                    )
                )
            trade_units += size

        endpoint_add, inferred_cancel, checked = self._apply_endpoint(
            update,
            events,
            targets=targets,
        )
        inferred_add += endpoint_add
        self._previous_transaction_time_ns = update.transaction_time_ns
        return BinanceReconstructionStep(
            events=tuple(events),
            metrics=BinanceReconstructionMetrics(
                depth_updates=1,
                levels_checked=checked,
                trade_count=len(aligned_trades),
                trade_units=trade_units,
                inferred_add_units=inferred_add,
                inferred_cancel_units=inferred_cancel,
                required_replenishment_units=required_replenishment,
                pre_trade_add_units=pre_trade_add,
            ),
        )

    def level_quantity(self, side: BookSide, price: Decimal) -> int:
        """Return reconstructed public quantity in integer quantity steps."""

        return self._level_units.get((side, price), 0)

    def book_top(self) -> tuple[Decimal | None, Decimal | None]:
        """Return the reconstructed public best bid and ask."""

        return self._best_bid, self._best_ask

    def _require_compatible_update(self, update: BinanceDepthUpdate) -> int:
        if self._symbol is None or self._previous_transaction_time_ns is None:
            raise RuntimeError("bootstrap must be called before apply_update")
        if update.symbol != self._symbol:
            raise ValueError("depth update symbol differs from bootstrap")
        if update.connection_id != self._connection_id:
            raise ValueError("depth update connection differs from bootstrap")
        if update.stream_kind != "depth":
            raise ValueError("only standard depth updates can be reconstructed")
        if update.transaction_time_ns < self._previous_transaction_time_ns:
            raise ValueError("depth transaction time moved backwards")
        return self._previous_transaction_time_ns

    def _apply_endpoint(
        self,
        update: BinanceDepthUpdate,
        events: list[MBOEvent],
        *,
        targets: dict[tuple[BookSide, Decimal], int] | None = None,
    ) -> tuple[int, int, int]:
        endpoint_targets = (
            self._endpoint_targets(update) if targets is None else targets
        )

        inferred_add = 0
        inferred_cancel = 0
        for side, price in sorted(endpoint_targets, key=self._level_sort_key):
            target = endpoint_targets[(side, price)]
            current = self._level_units.get((side, price), 0)
            if current < target:
                addition = target - current
                self._append_public(side, price, addition)
                self._record_add(
                    events,
                    update.transaction_time_ns,
                    side,
                    price,
                    addition,
                )
                inferred_add += addition
            elif current > target:
                cancellation = current - target
                events.extend(
                    self._cancel_public(
                        side,
                        price,
                        cancellation,
                        update.transaction_time_ns,
                    )
                )
                inferred_cancel += cancellation
            if self._level_units.get((side, price), 0) != target:
                raise AssertionError("reconstruction did not reach depth endpoint")
        return inferred_add, inferred_cancel, len(endpoint_targets)

    def _endpoint_targets(
        self,
        update: BinanceDepthUpdate,
    ) -> dict[tuple[BookSide, Decimal], int]:
        targets: dict[tuple[BookSide, Decimal], int] = {}
        for side, levels in (("bid", update.bids), ("ask", update.asks)):
            for level in levels:
                targets[(side, level.price)] = self._to_units(level.quantity)
        return targets

    def _append_public(self, side: BookSide, price: Decimal, size: int) -> None:
        key = (side, price)
        if self.config.emit_events:
            self._queues.setdefault(key, deque()).append(
                _VirtualOrder(order_id=self._next_order_id, size=size)
            )
            self._next_order_id += 1
        self._level_units[key] = self._level_units.get(key, 0) + size
        if side == "bid" and (self._best_bid is None or price > self._best_bid):
            self._best_bid = price
        elif side == "ask" and (self._best_ask is None or price < self._best_ask):
            self._best_ask = price

    def _consume_public(self, side: BookSide, price: Decimal, size: int) -> None:
        key = (side, price)
        if not self.config.emit_events:
            if self._level_units.get(key, 0) < size:
                raise AssertionError("trade exceeded reconstructed public quantity")
            self._level_units[key] -= size
            self._drop_empty_level(key)
            return

        queue = self._queues.get(key)
        remaining = size
        while remaining and queue:
            order = queue[0]
            consumed = min(order.size, remaining)
            order.size -= consumed
            remaining -= consumed
            self._level_units[key] -= consumed
            if order.size == 0:
                queue.popleft()
        if remaining:
            raise AssertionError("trade exceeded reconstructed public quantity")
        self._drop_empty_level(key)

    def _cancel_public(
        self,
        side: BookSide,
        price: Decimal,
        size: int,
        ts_ns: int,
    ) -> list[MBOEvent]:
        key = (side, price)
        if not self.config.emit_events:
            if self._level_units.get(key, 0) < size:
                raise AssertionError("cancel exceeded reconstructed public quantity")
            self._level_units[key] -= size
            self._drop_empty_level(key)
            return []

        queue = self._queues.get(key)
        remaining = size
        events: list[MBOEvent] = []
        while remaining and queue:
            order = queue[0] if self.config.policy == "queue-optimistic" else queue[-1]
            cancelled = min(order.size, remaining)
            if self.config.emit_events:
                events.append(
                    MBOEvent(
                        ts_ns=ts_ns,
                        action="cancel",
                        side=side,
                        price=price,
                        size=cancelled,
                        order_id=order.order_id,
                    )
                )
            order.size -= cancelled
            remaining -= cancelled
            self._level_units[key] -= cancelled
            if order.size == 0:
                if self.config.policy == "queue-optimistic":
                    queue.popleft()
                else:
                    queue.pop()
        if remaining:
            raise AssertionError("cancel exceeded reconstructed public quantity")
        self._drop_empty_level(key)
        return events

    def _drop_empty_level(self, key: tuple[BookSide, Decimal]) -> None:
        if self._level_units.get(key) == 0:
            self._level_units.pop(key, None)
            self._queues.pop(key, None)
            side, price = key
            if side == "bid" and price == self._best_bid:
                self._best_bid = max(
                    (
                        level_price
                        for level_side, level_price in self._level_units
                        if level_side == "bid"
                    ),
                    default=None,
                )
            elif side == "ask" and price == self._best_ask:
                self._best_ask = min(
                    (
                        level_price
                        for level_side, level_price in self._level_units
                        if level_side == "ask"
                    ),
                    default=None,
                )

    def _add_event(
        self,
        ts_ns: int,
        side: BookSide,
        price: Decimal,
        size: int,
    ) -> MBOEvent:
        order_id = self._queues[(side, price)][-1].order_id
        return MBOEvent(
            ts_ns=ts_ns,
            action="add",
            side=side,
            price=price,
            size=size,
            order_id=order_id,
        )

    def _record_add(
        self,
        events: list[MBOEvent],
        ts_ns: int,
        side: BookSide,
        price: Decimal,
        size: int,
    ) -> None:
        if self.config.emit_events:
            events.append(self._add_event(ts_ns, side, price, size))

    def _to_units(self, quantity: Decimal) -> int:
        units = quantity / self.config.quantity_step
        integral = units.to_integral_value()
        if units != integral:
            raise ValueError(
                f"quantity {quantity} is not divisible by quantity_step "
                f"{self.config.quantity_step}"
            )
        return int(integral)

    @staticmethod
    def _resting_side(trade: BinanceIndividualTrade) -> BookSide:
        return "bid" if trade.buyer_is_maker else "ask"

    @staticmethod
    def _sorted_levels(
        side: BookSide,
        levels: tuple[BinancePriceLevel, ...],
    ) -> tuple[BinancePriceLevel, ...]:
        return tuple(
            sorted(levels, key=lambda level: level.price, reverse=side == "bid")
        )

    @staticmethod
    def _level_sort_key(
        key: tuple[BookSide, Decimal],
    ) -> tuple[int, Decimal]:
        side, price = key
        return (0 if side == "bid" else 1, -price if side == "bid" else price)
