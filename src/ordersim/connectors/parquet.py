"""Parquet connector for the normalized MBO schema."""

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ordersim.connectors._canonical import row_to_event, validate_columns
from ordersim.connectors.base import EventInput, normalize_events
from ordersim.types import MBOEvent


@dataclass(frozen=True, slots=True)
class ParquetSource:
    """Read normalized `MBOEvent` rows from a Parquet file or dataset.

    The expected columns are the canonical public fields:
    `ts_ns`, `action`, `side`, `price`, `size`, and `order_id`.
    `ts_ns` must already be normalized UTC Unix-epoch nanoseconds. Extra
    columns are ignored.
    """

    path: str | Path

    def events(self) -> tuple[MBOEvent, ...]:
        """Return normalized events from the Parquet source."""

        parquet = _load_pyarrow_parquet()
        table = parquet.read_table(str(self.path))
        validate_columns(table.column_names, source_name="Parquet")
        return tuple(_read_events(table.to_pylist()))


def write_parquet(data: EventInput, path: str | Path) -> Path:
    """Write normalized events to the canonical Parquet schema.

    Materialize vendor-normalized events once, then replay repeated research
    runs from `ParquetSource` rather than re-reading raw vendor data each time.
    """

    parquet = _load_pyarrow_parquet()
    output_path = Path(path)
    rows = [_event_to_row(event) for event in normalize_events(data)]
    pa = _load_pyarrow()
    table = pa.Table.from_pylist(rows, schema=_canonical_schema(pa))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    parquet.write_table(table, str(output_path))
    return output_path


def _read_events(rows: Iterable[dict[str, object]]) -> Iterable[MBOEvent]:
    for row_number, row in enumerate(rows, start=1):
        yield row_to_event(
            row,
            row_label=f"row {row_number}",
            source_name="Parquet",
        )


def _load_pyarrow_parquet() -> Any:
    try:
        import pyarrow.parquet as parquet
    except ImportError as exc:
        raise ImportError(
            "ParquetSource requires pyarrow; install `ordersim[parquet]`"
        ) from exc
    return parquet


def _load_pyarrow() -> Any:
    try:
        import pyarrow as pa
    except ImportError as exc:
        raise ImportError(
            "write_parquet requires pyarrow; install `ordersim[parquet]`"
        ) from exc
    return pa


def _event_to_row(event: MBOEvent) -> dict[str, object]:
    return {
        "ts_ns": event.ts_ns,
        "action": event.action,
        "side": event.side,
        "price": str(event.price),
        "size": event.size,
        "order_id": event.order_id,
    }


def _canonical_schema(pa: Any) -> Any:
    return pa.schema(
        [
            ("ts_ns", pa.int64()),
            ("action", pa.string()),
            ("side", pa.string()),
            ("price", pa.string()),
            ("size", pa.int64()),
            ("order_id", pa.int64()),
        ]
    )
