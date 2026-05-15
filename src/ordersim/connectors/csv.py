"""CSV connector for the normalized MBO schema."""

import csv
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from ordersim.connectors._canonical import row_to_event, validate_columns
from ordersim.types import MBOEvent


@dataclass(frozen=True, slots=True)
class CsvSource:
    """Read normalized `MBOEvent` rows from a CSV file.

    The expected columns are exactly the public `MBOEvent` fields:
    `ts_ns`, `action`, `side`, `price`, `size`, and `order_id`.
    `ts_ns` must already be normalized UTC Unix-epoch nanoseconds. Extra
    columns are ignored.
    """

    path: str | Path

    def events(self) -> tuple[MBOEvent, ...]:
        """Return normalized events from the CSV file."""

        with Path(self.path).open(newline="") as file:
            return tuple(_read_events(file))


def _read_events(file: TextIO) -> Iterable[MBOEvent]:
    reader = csv.DictReader(file)
    validate_columns(reader.fieldnames, source_name="CSV")
    for row_number, row in enumerate(reader, start=2):
        yield row_to_event(row, row_label=f"line {row_number}", source_name="CSV")
