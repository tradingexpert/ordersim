"""Stream typed records from completed raw Binance captures."""

import gzip
import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from ordersim.connectors.binance._parsing import (
    depth_stream_kind,
    is_stream,
    parse_aggregate_trade,
    parse_book_ticker,
    parse_depth_snapshot,
    parse_depth_update,
    parse_envelope,
    parse_individual_trade,
    parse_raw_trade,
    required_int,
)
from ordersim.connectors.binance.l2 import (
    BinanceAggregateTrade,
    BinanceBookTicker,
    BinanceCaptureEnvelope,
    BinanceDepthEvent,
    BinanceDepthSnapshot,
    BinanceDepthUpdate,
    BinanceIndividualTrade,
    BinanceRawTrade,
    DepthStreamKind,
)
from ordersim.connectors.binance.schema import CAPTURE_SCHEMA_VERSION


class BinanceSequenceError(ValueError):
    """Raised when a captured depth segment cannot be replayed continuously."""


@dataclass(frozen=True, slots=True)
class BinanceCaptureSource:
    """Stream normalized records from completed gzip capture files."""

    files: tuple[Path, ...]

    def __post_init__(self) -> None:
        paths = tuple(Path(path) for path in self.files)
        if not paths:
            raise ValueError("at least one capture file is required")
        missing = [str(path) for path in paths if not path.is_file()]
        if missing:
            raise FileNotFoundError(f"capture files do not exist: {missing}")
        object.__setattr__(self, "files", paths)

    @classmethod
    def from_manifest(cls, manifest_path: str | Path) -> "BinanceCaptureSource":
        """Build a source from one completed capture manifest."""

        path = Path(manifest_path)
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("capture manifest must be a JSON object")
        if required_int(raw, "schema_version") != CAPTURE_SCHEMA_VERSION:
            raise ValueError("unsupported capture manifest schema_version")
        names = raw.get("files")
        if not isinstance(names, list) or not all(
            isinstance(name, str) for name in names
        ):
            raise ValueError("capture manifest files must be a list of names")
        return cls(tuple(path.parent / name for name in names))

    def envelopes(self) -> Iterator[BinanceCaptureEnvelope]:
        """Yield validated raw envelopes in capture-file order."""

        for path in self.files:
            with gzip.open(path, mode="rt", encoding="utf-8") as rows:
                for line_number, line in enumerate(rows, start=1):
                    try:
                        raw = json.loads(line)
                        yield parse_envelope(raw)
                    except (TypeError, ValueError) as exc:
                        raise ValueError(
                            f"invalid capture row {path}:{line_number}: {exc}"
                        ) from exc

    def depth_snapshots(self) -> Iterator[BinanceDepthSnapshot]:
        """Yield every captured REST depth snapshot."""

        for envelope in self.envelopes():
            if envelope.kind == "depth_snapshot":
                yield parse_depth_snapshot(envelope)

    def depth_updates(
        self,
        *,
        stream_kind: DepthStreamKind = "depth",
    ) -> Iterator[BinanceDepthUpdate]:
        """Yield raw standard or RPI diff-depth updates."""

        for envelope in self.envelopes():
            kind = depth_stream_kind(envelope)
            if kind == stream_kind:
                yield parse_depth_update(envelope, stream_kind=kind)

    def validated_depth_events(self) -> Iterator[BinanceDepthEvent]:
        """Yield snapshot-anchored, sequence-continuous standard depth."""

        snapshots: dict[str, BinanceDepthSnapshot] = {}
        started: set[str] = set()
        previous_update_ids: dict[str, int] = {}

        for envelope in self.envelopes():
            if envelope.kind == "depth_snapshot":
                snapshot = parse_depth_snapshot(envelope)
                snapshots[envelope.connection_id] = snapshot
                yield snapshot
                continue
            if depth_stream_kind(envelope) != "depth":
                continue

            update = parse_depth_update(envelope, stream_kind="depth")
            connection_id = envelope.connection_id
            snapshot = snapshots.get(connection_id)
            if snapshot is None:
                raise BinanceSequenceError(
                    f"depth update before snapshot for connection {connection_id}"
                )
            if connection_id not in started:
                if update.final_update_id < snapshot.last_update_id:
                    continue
                if not (
                    update.first_update_id
                    <= snapshot.last_update_id
                    <= update.final_update_id
                ):
                    raise BinanceSequenceError(
                        "first depth update does not bridge snapshot "
                        f"{snapshot.last_update_id}: "
                        f"U={update.first_update_id}, u={update.final_update_id}"
                    )
                started.add(connection_id)
            else:
                expected = previous_update_ids[connection_id]
                if update.previous_update_id != expected:
                    raise BinanceSequenceError(
                        f"depth sequence gap for connection {connection_id}: "
                        f"expected pu={expected}, got {update.previous_update_id}"
                    )
            previous_update_ids[connection_id] = update.final_update_id
            yield update

    def aggregate_trades(self) -> Iterator[BinanceAggregateTrade]:
        """Yield normalized aggregate-trade messages."""

        for envelope in self.envelopes():
            if is_stream(envelope, "@aggTrade"):
                yield parse_aggregate_trade(envelope)

    def individual_trades(self) -> Iterator[BinanceIndividualTrade]:
        """Yield real-time, individually identified WebSocket trades."""

        for envelope in self.envelopes():
            if is_stream(envelope, "@trade"):
                yield parse_individual_trade(envelope)

    def raw_trades(self) -> Iterator[BinanceRawTrade]:
        """Yield individually identified REST trades with RPI flags."""

        for envelope in self.envelopes():
            if envelope.kind == "raw_trade":
                yield parse_raw_trade(envelope)

    def book_tickers(self) -> Iterator[BinanceBookTicker]:
        """Yield normalized best-bid/ask messages."""

        for envelope in self.envelopes():
            if is_stream(envelope, "@bookTicker"):
                yield parse_book_ticker(envelope)
