"""CSV connector for the normalized MBO schema."""

import csv
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import TextIO, cast

from ordersim.types import BookSide, MBOAction, MBOEvent

REQUIRED_COLUMNS = ("ts_ns", "action", "side", "price", "size", "order_id")
VALID_ACTIONS: set[MBOAction] = {"add", "cancel", "modify", "trade"}
VALID_SIDES: set[BookSide] = {"bid", "ask"}


@dataclass(frozen=True, slots=True)
class CsvSource:
    """Read normalized `MBOEvent` rows from a CSV file.

    The expected columns are exactly the public `MBOEvent` fields:
    `ts_ns`, `action`, `side`, `price`, `size`, and `order_id`.
    Extra columns are ignored.
    """

    path: str | Path

    def events(self) -> tuple[MBOEvent, ...]:
        """Return normalized events from the CSV file."""

        with Path(self.path).open(newline="") as file:
            return tuple(_read_events(file))


def _read_events(file: TextIO) -> Iterable[MBOEvent]:
    reader = csv.DictReader(file)
    _validate_columns(reader.fieldnames)
    for row_number, row in enumerate(reader, start=2):
        yield _row_to_event(row, row_number=row_number)


def _validate_columns(fieldnames: list[str] | None) -> None:
    if fieldnames is None:
        raise ValueError("CSV source must include a header row")

    missing = [column for column in REQUIRED_COLUMNS if column not in fieldnames]
    if missing:
        raise ValueError(f"CSV source is missing required columns: {missing}")


def _row_to_event(row: dict[str, str], *, row_number: int) -> MBOEvent:
    try:
        action = _parse_action(row["action"])
        side = _parse_side(row["side"])
        return MBOEvent(
            ts_ns=int(row["ts_ns"]),
            action=action,
            side=side,
            price=Decimal(row["price"]),
            size=int(row["size"]),
            order_id=int(row["order_id"]),
        )
    except (InvalidOperation, KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"invalid CSV MBO row at line {row_number}") from exc


def _parse_action(value: str) -> MBOAction:
    if value not in VALID_ACTIONS:
        raise ValueError(f"unknown action: {value!r}")
    return cast(MBOAction, value)


def _parse_side(value: str) -> BookSide:
    if value not in VALID_SIDES:
        raise ValueError(f"unknown side: {value!r}")
    return cast(BookSide, value)
