"""Streaming evidence study for Binance L2-to-virtual-MBO reconstruction."""

import argparse
import json
from collections import deque
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from ordersim.connectors.binance.l2 import (
    BinanceBookTicker,
    BinanceDepthSnapshot,
    BinanceDepthUpdate,
    BinanceIndividualTrade,
    BinanceObservedEvent,
)
from ordersim.connectors.binance.reconstruction import (
    BinanceMBOReconstructor,
    BinanceReconstructionConfig,
    BinanceReconstructionMetrics,
    BinanceReconstructionPolicy,
)
from ordersim.connectors.binance.source import BinanceCaptureSource

MODEL_NAME = "binance-virtual-mbo-minimum-flow-v1"
ALIGNMENT_NAME = "exchange-transaction-time"


@dataclass(frozen=True, slots=True)
class BinanceReconstructionStudyConfig:
    """Configuration for an offline reconstruction study over raw evidence."""

    symbol: str
    quantity_step: Decimal
    policies: tuple[BinanceReconstructionPolicy, ...] = (
        "queue-conservative",
        "queue-optimistic",
    )
    reorder_buffer_ns: int = 60_000_000_000
    until_received_at_ns: int | None = None

    def __post_init__(self) -> None:
        symbol = self.symbol.strip().upper()
        if not symbol:
            raise ValueError("symbol must not be empty")
        if self.quantity_step <= 0:
            raise ValueError("quantity_step must be positive")
        if not self.policies:
            raise ValueError("at least one reconstruction policy is required")
        if len(set(self.policies)) != len(self.policies):
            raise ValueError("reconstruction policies must be unique")
        if self.reorder_buffer_ns < 0:
            raise ValueError("reorder_buffer_ns must be non-negative")
        object.__setattr__(self, "symbol", symbol)


@dataclass(frozen=True, slots=True)
class BinanceReconstructionSegmentReport:
    """Evidence summary for one snapshot-anchored depth connection."""

    connection_id: str
    snapshot_last_update_id: int
    first_update_id: int
    last_update_id: int
    first_transaction_time_ns: int
    last_transaction_time_ns: int
    metrics_by_policy: Mapping[str, BinanceReconstructionMetrics]

    def as_dict(self) -> dict[str, object]:
        """Return a JSON-serializable segment manifest."""

        return {
            "connection_id": self.connection_id,
            "snapshot_last_update_id": self.snapshot_last_update_id,
            "first_update_id": self.first_update_id,
            "last_update_id": self.last_update_id,
            "first_transaction_time_ns": self.first_transaction_time_ns,
            "last_transaction_time_ns": self.last_transaction_time_ns,
            "metrics_by_policy": {
                policy: _metrics_as_dict(metrics)
                for policy, metrics in self.metrics_by_policy.items()
            },
        }


@dataclass(frozen=True, slots=True)
class BinanceReconstructionStudyReport:
    """JSON-ready evidence report for one symbol and capture boundary."""

    symbol: str
    quantity_step: Decimal
    policies: tuple[BinanceReconstructionPolicy, ...]
    reorder_buffer_ns: int
    until_received_at_ns: int | None
    observations: int
    depth_snapshots: int
    stale_depth_updates: int
    broken_depth_segments: int
    duplicate_trades: int
    zero_value_trade_messages: int
    max_trade_receive_delay_ns: int
    late_trades: int
    max_late_trade_lag_ns: int
    unassigned_trades: int
    exact_book_ticker_matches: int
    exact_book_ticker_mismatches: int
    segments: tuple[BinanceReconstructionSegmentReport, ...]
    totals_by_policy: Mapping[str, BinanceReconstructionMetrics]

    def as_dict(self) -> dict[str, object]:
        """Return a JSON-serializable model and evidence manifest."""

        return {
            "schema_version": 1,
            "model": MODEL_NAME,
            "alignment": ALIGNMENT_NAME,
            "symbol": self.symbol,
            "quantity_step": str(self.quantity_step),
            "policies": list(self.policies),
            "reorder_buffer_ns": self.reorder_buffer_ns,
            "until_received_at_ns": self.until_received_at_ns,
            "observations": self.observations,
            "depth_snapshots": self.depth_snapshots,
            "stale_depth_updates": self.stale_depth_updates,
            "broken_depth_segments": self.broken_depth_segments,
            "duplicate_trades": self.duplicate_trades,
            "zero_value_trade_messages": self.zero_value_trade_messages,
            "max_trade_receive_delay_ns": self.max_trade_receive_delay_ns,
            "late_trades": self.late_trades,
            "max_late_trade_lag_ns": self.max_late_trade_lag_ns,
            "unassigned_trades": self.unassigned_trades,
            "exact_book_ticker_matches": self.exact_book_ticker_matches,
            "exact_book_ticker_mismatches": self.exact_book_ticker_mismatches,
            "segments": [segment.as_dict() for segment in self.segments],
            "totals_by_policy": {
                policy: _metrics_as_dict(metrics)
                for policy, metrics in self.totals_by_policy.items()
            },
        }


@dataclass(slots=True)
class _MetricsAccumulator:
    depth_updates: int = 0
    levels_checked: int = 0
    trade_count: int = 0
    trade_units: int = 0
    snapshot_add_units: int = 0
    inferred_add_units: int = 0
    inferred_cancel_units: int = 0
    required_replenishment_units: int = 0
    pre_trade_add_units: int = 0

    def add(self, metrics: BinanceReconstructionMetrics) -> None:
        self.depth_updates += metrics.depth_updates
        self.levels_checked += metrics.levels_checked
        self.trade_count += metrics.trade_count
        self.trade_units += metrics.trade_units
        self.snapshot_add_units += metrics.snapshot_add_units
        self.inferred_add_units += metrics.inferred_add_units
        self.inferred_cancel_units += metrics.inferred_cancel_units
        self.required_replenishment_units += metrics.required_replenishment_units
        self.pre_trade_add_units += metrics.pre_trade_add_units

    def freeze(self) -> BinanceReconstructionMetrics:
        return BinanceReconstructionMetrics(
            depth_updates=self.depth_updates,
            levels_checked=self.levels_checked,
            trade_count=self.trade_count,
            trade_units=self.trade_units,
            snapshot_add_units=self.snapshot_add_units,
            inferred_add_units=self.inferred_add_units,
            inferred_cancel_units=self.inferred_cancel_units,
            required_replenishment_units=self.required_replenishment_units,
            pre_trade_add_units=self.pre_trade_add_units,
        )


@dataclass(slots=True)
class _ActiveSegment:
    snapshot: BinanceDepthSnapshot
    models: dict[BinanceReconstructionPolicy, BinanceMBOReconstructor]
    metrics: dict[BinanceReconstructionPolicy, _MetricsAccumulator]
    pending_updates: deque[BinanceDepthUpdate]
    book_tickers: deque[BinanceBookTicker]
    previous_final_update_id: int
    first_update_id: int
    last_update_id: int
    first_transaction_time_ns: int
    last_transaction_time_ns: int


class _StudyRunner:
    def __init__(self, config: BinanceReconstructionStudyConfig) -> None:
        self.config = config
        self.observations = 0
        self.depth_snapshots = 0
        self.stale_depth_updates = 0
        self.broken_depth_segments = 0
        self.duplicate_trades = 0
        self.zero_value_trade_messages = 0
        self.max_trade_receive_delay_ns = 0
        self.late_trades = 0
        self.max_late_trade_lag_ns = 0
        self.unassigned_trades = 0
        self.exact_book_ticker_matches = 0
        self.exact_book_ticker_mismatches = 0
        self._last_trade_id: int | None = None
        self._trades: list[BinanceIndividualTrade] = []
        self._snapshot: BinanceDepthSnapshot | None = None
        self._segment: _ActiveSegment | None = None
        self._segments: list[BinanceReconstructionSegmentReport] = []
        self._totals = {
            policy: _MetricsAccumulator() for policy in config.policies
        }

    def run(
        self,
        observations: Iterable[BinanceObservedEvent],
    ) -> BinanceReconstructionStudyReport:
        for observation in observations:
            if observation.symbol != self.config.symbol:
                continue
            self.observations += 1
            self._accept(observation)
            watermark = observation.received_at_ns - self.config.reorder_buffer_ns
            self._flush_ready(watermark)

        self._finish_segment()
        self.unassigned_trades += len(self._trades)
        self._trades.clear()
        return BinanceReconstructionStudyReport(
            symbol=self.config.symbol,
            quantity_step=self.config.quantity_step,
            policies=self.config.policies,
            reorder_buffer_ns=self.config.reorder_buffer_ns,
            until_received_at_ns=self.config.until_received_at_ns,
            observations=self.observations,
            depth_snapshots=self.depth_snapshots,
            stale_depth_updates=self.stale_depth_updates,
            broken_depth_segments=self.broken_depth_segments,
            duplicate_trades=self.duplicate_trades,
            zero_value_trade_messages=self.zero_value_trade_messages,
            max_trade_receive_delay_ns=self.max_trade_receive_delay_ns,
            late_trades=self.late_trades,
            max_late_trade_lag_ns=self.max_late_trade_lag_ns,
            unassigned_trades=self.unassigned_trades,
            exact_book_ticker_matches=self.exact_book_ticker_matches,
            exact_book_ticker_mismatches=self.exact_book_ticker_mismatches,
            segments=tuple(self._segments),
            totals_by_policy={
                policy: totals.freeze() for policy, totals in self._totals.items()
            },
        )

    def _accept(self, observation: BinanceObservedEvent) -> None:
        if isinstance(observation, BinanceDepthSnapshot):
            self._start_snapshot(observation)
        elif isinstance(observation, BinanceDepthUpdate):
            self._accept_depth(observation)
        elif isinstance(observation, BinanceIndividualTrade):
            self._accept_trade(observation)
        elif isinstance(observation, BinanceBookTicker):
            self._accept_book_ticker(observation)

    def _start_snapshot(self, snapshot: BinanceDepthSnapshot) -> None:
        self.depth_snapshots += 1
        self._finish_segment()
        self.unassigned_trades += len(self._trades)
        self._trades.clear()
        self._snapshot = snapshot

    def _accept_depth(self, update: BinanceDepthUpdate) -> None:
        if self._snapshot is None:
            return
        if update.connection_id != self._snapshot.connection_id:
            return
        if self._segment is None:
            if update.final_update_id < self._snapshot.last_update_id:
                self.stale_depth_updates += 1
                return
            if not (
                update.first_update_id
                <= self._snapshot.last_update_id
                <= update.final_update_id
            ):
                self.broken_depth_segments += 1
                self._snapshot = None
                return
            self._bootstrap(update)
            return
        if update.previous_update_id != self._segment.previous_final_update_id:
            self.broken_depth_segments += 1
            self._finish_segment()
            self._snapshot = None
            return
        self._segment.pending_updates.append(update)
        self._segment.previous_final_update_id = update.final_update_id

    def _bootstrap(self, update: BinanceDepthUpdate) -> None:
        assert self._snapshot is not None
        models = {
            policy: BinanceMBOReconstructor(
                BinanceReconstructionConfig(
                    quantity_step=self.config.quantity_step,
                    policy=policy,
                    emit_events=False,
                )
            )
            for policy in self.config.policies
        }
        metrics = {policy: _MetricsAccumulator() for policy in self.config.policies}
        for policy, model in models.items():
            step = model.bootstrap(self._snapshot, update)
            metrics[policy].add(step.metrics)
            self._totals[policy].add(step.metrics)
        self._segment = _ActiveSegment(
            snapshot=self._snapshot,
            models=models,
            metrics=metrics,
            pending_updates=deque(),
            book_tickers=deque(),
            previous_final_update_id=update.final_update_id,
            first_update_id=update.final_update_id,
            last_update_id=update.final_update_id,
            first_transaction_time_ns=update.transaction_time_ns,
            last_transaction_time_ns=update.transaction_time_ns,
        )
        before = len(self._trades)
        self._trades = [
            trade
            for trade in self._trades
            if trade.trade_time_ns > update.transaction_time_ns
        ]
        self.unassigned_trades += before - len(self._trades)

    def _accept_trade(self, trade: BinanceIndividualTrade) -> None:
        if self._last_trade_id is not None and trade.trade_id <= self._last_trade_id:
            self.duplicate_trades += 1
            return
        self._last_trade_id = trade.trade_id
        if trade.price <= 0 or trade.quantity <= 0:
            self.zero_value_trade_messages += 1
            return
        self.max_trade_receive_delay_ns = max(
            self.max_trade_receive_delay_ns,
            trade.received_at_ns - trade.trade_time_ns,
        )
        if self._segment is not None:
            previous_time = next(
                iter(self._segment.models.values())
            ).previous_transaction_time_ns
            if previous_time is not None and trade.trade_time_ns <= previous_time:
                self.late_trades += 1
                self.max_late_trade_lag_ns = max(
                    self.max_late_trade_lag_ns,
                    previous_time - trade.trade_time_ns,
                )
                return
        self._trades.append(trade)

    def _accept_book_ticker(self, ticker: BinanceBookTicker) -> None:
        segment = self._segment
        if segment is None or ticker.connection_id != segment.snapshot.connection_id:
            return
        segment.book_tickers.append(ticker)

    def _flush_ready(self, watermark_received_at_ns: int) -> None:
        segment = self._segment
        if segment is None:
            return
        while (
            segment.pending_updates
            and segment.pending_updates[0].received_at_ns <= watermark_received_at_ns
        ):
            self._flush_update(segment.pending_updates.popleft())

    def _flush_update(self, update: BinanceDepthUpdate) -> None:
        segment = self._segment
        if segment is None:
            return
        previous_time = next(iter(segment.models.values())).previous_transaction_time_ns
        assert previous_time is not None
        aligned: list[BinanceIndividualTrade] = []
        retained: list[BinanceIndividualTrade] = []
        for trade in self._trades:
            if trade.trade_time_ns <= previous_time:
                self.late_trades += 1
                self.max_late_trade_lag_ns = max(
                    self.max_late_trade_lag_ns,
                    previous_time - trade.trade_time_ns,
                )
            elif trade.trade_time_ns <= update.transaction_time_ns:
                aligned.append(trade)
            else:
                retained.append(trade)
        self._trades = retained

        for policy, model in segment.models.items():
            step = model.apply_update(update, aligned)
            segment.metrics[policy].add(step.metrics)
            self._totals[policy].add(step.metrics)

        self._compare_book_ticker(update)
        segment.last_update_id = update.final_update_id
        segment.last_transaction_time_ns = update.transaction_time_ns

    def _compare_book_ticker(self, update: BinanceDepthUpdate) -> None:
        segment = self._segment
        if segment is None:
            return
        tickers: list[BinanceBookTicker] = []
        while (
            segment.book_tickers
            and segment.book_tickers[0].update_id <= update.final_update_id
        ):
            ticker = segment.book_tickers.popleft()
            if ticker.update_id == update.final_update_id:
                tickers.append(ticker)
        if not tickers:
            return
        model = next(iter(segment.models.values()))
        bid_price, ask_price = model.book_top()
        for ticker in tickers:
            matches = (
                bid_price == ticker.bid_price
                and ask_price == ticker.ask_price
                and bid_price is not None
                and ask_price is not None
                and model.level_quantity("bid", bid_price)
                == _quantity_units(ticker.bid_quantity, self.config.quantity_step)
                and model.level_quantity("ask", ask_price)
                == _quantity_units(ticker.ask_quantity, self.config.quantity_step)
            )
            if matches:
                self.exact_book_ticker_matches += 1
            else:
                self.exact_book_ticker_mismatches += 1

    def _finish_segment(self) -> None:
        segment = self._segment
        if segment is None:
            return
        while segment.pending_updates:
            self._flush_update(segment.pending_updates.popleft())
        self._segments.append(
            BinanceReconstructionSegmentReport(
                connection_id=segment.snapshot.connection_id,
                snapshot_last_update_id=segment.snapshot.last_update_id,
                first_update_id=segment.first_update_id,
                last_update_id=segment.last_update_id,
                first_transaction_time_ns=segment.first_transaction_time_ns,
                last_transaction_time_ns=segment.last_transaction_time_ns,
                metrics_by_policy={
                    policy: metrics.freeze()
                    for policy, metrics in segment.metrics.items()
                },
            )
        )
        self._segment = None


def run_binance_reconstruction_study(
    source: BinanceCaptureSource,
    config: BinanceReconstructionStudyConfig,
) -> BinanceReconstructionStudyReport:
    """Run the reconstruction study without loading the capture into memory."""

    return _StudyRunner(config).run(
        source.observations(
            until_received_at_ns=config.until_received_at_ns,
            symbol=config.symbol,
        )
    )


def _quantity_units(quantity: Decimal, quantity_step: Decimal) -> int:
    units = quantity / quantity_step
    integral = units.to_integral_value()
    if units != integral:
        raise ValueError(
            f"quantity {quantity} is not divisible by quantity_step {quantity_step}"
        )
    return int(integral)


def _metrics_as_dict(metrics: BinanceReconstructionMetrics) -> dict[str, int]:
    return {
        "depth_updates": metrics.depth_updates,
        "levels_checked": metrics.levels_checked,
        "trade_count": metrics.trade_count,
        "trade_units": metrics.trade_units,
        "snapshot_add_units": metrics.snapshot_add_units,
        "inferred_add_units": metrics.inferred_add_units,
        "inferred_cancel_units": metrics.inferred_cancel_units,
        "required_replenishment_units": metrics.required_replenishment_units,
        "pre_trade_add_units": metrics.pre_trade_add_units,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Study Binance L2 and individual trades as virtual MBO."
    )
    parser.add_argument("capture_dir", type=Path)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--quantity-step", type=Decimal, required=True)
    parser.add_argument("--until-received-at-ns", type=int)
    parser.add_argument("--reorder-buffer-ms", type=int, default=60_000)
    parser.add_argument(
        "--policy",
        action="append",
        choices=("queue-conservative", "queue-optimistic"),
        dest="policies",
    )
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    """Run the `ordersim-binance-reconstruction-study` command."""

    args = _parser().parse_args(argv)
    policies = tuple(args.policies or ("queue-conservative", "queue-optimistic"))
    config = BinanceReconstructionStudyConfig(
        symbol=args.symbol,
        quantity_step=args.quantity_step,
        policies=policies,
        reorder_buffer_ns=args.reorder_buffer_ms * 1_000_000,
        until_received_at_ns=args.until_received_at_ns,
    )
    report = run_binance_reconstruction_study(
        BinanceCaptureSource.from_directory(args.capture_dir),
        config,
    )
    rendered = json.dumps(report.as_dict(), indent=2, sort_keys=True) + "\n"
    if args.output is None:
        print(rendered, end="")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")


if __name__ == "__main__":
    main()
