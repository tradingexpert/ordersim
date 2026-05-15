"""Parquet connector for the normalized MBO schema."""

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ordersim.connectors._canonical import row_to_event, validate_columns
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
