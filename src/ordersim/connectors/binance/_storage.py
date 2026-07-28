"""Local storage for raw Binance capture envelopes."""

import asyncio
import gzip
import json
import time
import uuid
from collections import Counter
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from ordersim.connectors.binance.schema import (
    CAPTURE_SCHEMA_VERSION,
    BinanceCaptureConfig,
    BinanceRawTradeCaptureConfig,
    CaptureManifest,
    JsonObject,
)


class RawCaptureSink:
    """Serialize capture envelopes to hourly gzip JSONL files."""

    def __init__(
        self,
        config: BinanceCaptureConfig | BinanceRawTradeCaptureConfig,
    ) -> None:
        self._config = config
        self._run_id = uuid.uuid4().hex
        self._started_at_ns = time.time_ns()
        self._counts: Counter[str] = Counter()
        self._files: list[str] = []
        self._current_hour: str | None = None
        self._file: Any = None
        self._lock = asyncio.Lock()
        config.output_dir.mkdir(parents=True, exist_ok=True)

    async def write(
        self,
        *,
        kind: str,
        scope: str,
        symbol: str,
        connection_id: str,
        stream: str | None,
        payload: Mapping[str, object],
    ) -> None:
        """Write one raw payload with local capture metadata."""

        received_at_ns = time.time_ns()
        envelope: JsonObject = {
            "schema_version": CAPTURE_SCHEMA_VERSION,
            "received_at_ns": received_at_ns,
            "received_monotonic_ns": time.monotonic_ns(),
            "kind": kind,
            "scope": scope,
            "symbol": symbol,
            "connection_id": connection_id,
            "stream": stream,
            "payload": dict(payload),
        }
        async with self._lock:
            self._rotate(received_at_ns)
            self._file.write(
                json.dumps(envelope, separators=(",", ":"), ensure_ascii=True)
            )
            self._file.write("\n")
            self._counts[kind] += 1

    def close(self) -> CaptureManifest:
        """Close the active file and write the run manifest."""

        if self._file is not None:
            self._file.close()
            self._file = None
        manifest = CaptureManifest(
            schema_version=CAPTURE_SCHEMA_VERSION,
            run_id=self._run_id,
            started_at_ns=self._started_at_ns,
            ended_at_ns=time.time_ns(),
            symbols=self._config.symbols,
            include_rpi=self._config.include_rpi,
            counts=dict(sorted(self._counts.items())),
            files=tuple(self._files),
            capture_type=self._config.capture_type,
        )
        manifest_path = self._config.output_dir / f"manifest-{self._run_id}.json"
        manifest_path.write_text(
            json.dumps(manifest.as_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return manifest

    def _rotate(self, received_at_ns: int) -> None:
        hour = datetime.fromtimestamp(received_at_ns / 1_000_000_000, UTC).strftime(
            "%Y%m%dT%H0000Z"
        )
        if hour == self._current_hour:
            return
        if self._file is not None:
            self._file.close()
        filename = f"binance-{self._run_id}-{hour}.jsonl.gz"
        self._file = gzip.open(
            self._config.output_dir / filename,
            mode="at",
            encoding="utf-8",
            compresslevel=1,
        )
        self._current_hour = hour
        self._files.append(filename)
