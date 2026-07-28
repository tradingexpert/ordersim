"""Schemas and integrity checks for Binance market-data capture."""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

CAPTURE_SCHEMA_VERSION = 1
JsonObject = dict[str, object]
RECENT_TRADES_REQUEST_WEIGHT = 5
RAW_TRADE_WEIGHT_BUDGET_PER_MINUTE = 1_800


@dataclass(frozen=True, slots=True)
class BinanceCaptureConfig:
    """Configuration for one raw Binance USD-M futures capture."""

    capture_type: ClassVar[str] = "websocket"

    output_dir: Path
    symbols: tuple[str, ...]
    duration_seconds: float | None = None
    include_rpi: bool = False
    snapshot_limit: int = 1000
    reconnect_delay_seconds: float = 2.0

    def __post_init__(self) -> None:
        symbols = tuple(symbol.strip().upper() for symbol in self.symbols)
        if not symbols:
            raise ValueError("at least one symbol is required")
        if any(not symbol.isalnum() for symbol in symbols):
            raise ValueError("symbols must contain only letters and numbers")
        if len(set(symbols)) != len(symbols):
            raise ValueError("symbols must be unique")
        if self.duration_seconds is not None and self.duration_seconds <= 0:
            raise ValueError("duration_seconds must be positive")
        if self.snapshot_limit not in (5, 10, 20, 50, 100, 500, 1000):
            raise ValueError("unsupported Binance snapshot_limit")
        if self.reconnect_delay_seconds < 0:
            raise ValueError("reconnect_delay_seconds must be non-negative")

        object.__setattr__(self, "output_dir", Path(self.output_dir))
        object.__setattr__(self, "symbols", symbols)

    def public_streams(self, symbol: str) -> tuple[str, ...]:
        """Return the public-book streams captured for one symbol."""

        prefix = symbol.lower()
        streams = [
            f"{prefix}@depth@100ms",
            f"{prefix}@bookTicker",
        ]
        if self.include_rpi:
            streams.append(f"{prefix}@rpiDepth@500ms")
        return tuple(streams)

    def market_streams(self, symbol: str) -> tuple[str, ...]:
        """Return the trade streams captured for one symbol."""

        return (f"{symbol.lower()}@aggTrade",)


@dataclass(frozen=True, slots=True)
class BinanceRawTradeCaptureConfig:
    """Configuration for polling individual Binance USD-M trades."""

    capture_type: ClassVar[str] = "raw_trades"

    output_dir: Path
    symbols: tuple[str, ...]
    duration_seconds: float | None = None
    poll_interval_seconds: float = 0.5
    request_limit: int = 1000
    retry_delay_seconds: float = 2.0

    def __post_init__(self) -> None:
        symbols = tuple(symbol.strip().upper() for symbol in self.symbols)
        if not symbols:
            raise ValueError("at least one symbol is required")
        if any(not symbol.isalnum() for symbol in symbols):
            raise ValueError("symbols must contain only letters and numbers")
        if len(set(symbols)) != len(symbols):
            raise ValueError("symbols must be unique")
        if self.duration_seconds is not None and self.duration_seconds <= 0:
            raise ValueError("duration_seconds must be positive")
        if self.poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be positive")
        if not 1 <= self.request_limit <= 1000:
            raise ValueError("request_limit must be between 1 and 1000")
        if self.retry_delay_seconds < 0:
            raise ValueError("retry_delay_seconds must be non-negative")
        if (
            self.estimated_request_weight_per_minute
            > RAW_TRADE_WEIGHT_BUDGET_PER_MINUTE
        ):
            raise ValueError(
                "raw-trade polling would exceed the conservative "
                f"{RAW_TRADE_WEIGHT_BUDGET_PER_MINUTE} weight/minute budget"
            )

        object.__setattr__(self, "output_dir", Path(self.output_dir))
        object.__setattr__(self, "symbols", symbols)

    @property
    def include_rpi(self) -> bool:
        """Return false because this recorder does not capture depth."""

        return False

    @property
    def estimated_request_weight_per_minute(self) -> float:
        """Return the configured recent-trades request weight per minute."""

        return (
            len(self.symbols)
            * RECENT_TRADES_REQUEST_WEIGHT
            * 60
            / self.poll_interval_seconds
        )


@dataclass(frozen=True, slots=True)
class DepthSequenceGap:
    """One discontinuity in a Binance diff-depth stream."""

    expected_previous_update_id: int
    reported_previous_update_id: int
    first_update_id: int
    final_update_id: int

    def as_dict(self) -> dict[str, int]:
        """Return a JSON-compatible representation."""

        return {
            "expected_previous_update_id": self.expected_previous_update_id,
            "reported_previous_update_id": self.reported_previous_update_id,
            "first_update_id": self.first_update_id,
            "final_update_id": self.final_update_id,
        }


class DepthSequenceTracker:
    """Validate `pu` continuity within one WebSocket connection."""

    def __init__(self) -> None:
        self._previous_final_update_id: int | None = None

    def observe(self, payload: Mapping[str, object]) -> DepthSequenceGap | None:
        """Observe one depth payload and return a gap when continuity breaks."""

        first_update_id = _required_int(payload, "U")
        final_update_id = _required_int(payload, "u")
        previous_update_id = _required_int(payload, "pu")
        if final_update_id < first_update_id:
            raise ValueError("depth payload has u < U")

        expected = self._previous_final_update_id
        self._previous_final_update_id = final_update_id
        if expected is None or previous_update_id == expected:
            return None
        return DepthSequenceGap(
            expected_previous_update_id=expected,
            reported_previous_update_id=previous_update_id,
            first_update_id=first_update_id,
            final_update_id=final_update_id,
        )


@dataclass(frozen=True, slots=True)
class CaptureManifest:
    """Summary of one recorder process."""

    schema_version: int
    run_id: str
    started_at_ns: int
    ended_at_ns: int
    symbols: tuple[str, ...]
    include_rpi: bool
    counts: dict[str, int]
    files: tuple[str, ...]
    capture_type: str = "websocket"

    def as_dict(self) -> JsonObject:
        """Return a JSON-compatible representation."""

        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "started_at_ns": self.started_at_ns,
            "ended_at_ns": self.ended_at_ns,
            "symbols": list(self.symbols),
            "include_rpi": self.include_rpi,
            "capture_type": self.capture_type,
            "counts": self.counts,
            "files": list(self.files),
        }


def _required_int(payload: Mapping[str, object], field: str) -> int:
    value = payload.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"Binance field {field!r} must be an integer")
    return value
