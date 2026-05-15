"""Shared parsing for canonical `MBOEvent` rows."""

from collections.abc import Iterable, Mapping
from decimal import Decimal, InvalidOperation
from typing import cast

from ordersim.types import BookSide, MBOAction, MBOEvent

REQUIRED_COLUMNS = ("ts_ns", "action", "side", "price", "size", "order_id")
VALID_ACTIONS: set[MBOAction] = {"add", "cancel", "modify", "trade"}
VALID_SIDES: set[BookSide] = {"bid", "ask"}


def validate_columns(
    fieldnames: Iterable[str] | None,
    *,
    source_name: str,
) -> None:
    """Validate that a canonical source exposes the required fields."""

    if fieldnames is None:
        raise ValueError(f"{source_name} source must include a header row")

    available = tuple(fieldnames)
    missing = [column for column in REQUIRED_COLUMNS if column not in available]
    if missing:
        raise ValueError(f"{source_name} source is missing required columns: {missing}")


def row_to_event(
    row: Mapping[str, object],
    *,
    row_label: str,
    source_name: str,
) -> MBOEvent:
    """Convert one canonical row into an `MBOEvent`."""

    try:
        action = _parse_action(str(row["action"]))
        side = _parse_side(str(row["side"]))
        return MBOEvent(
            ts_ns=int(row["ts_ns"]),
            action=action,
            side=side,
            price=Decimal(str(row["price"])),
            size=int(row["size"]),
            order_id=int(row["order_id"]),
        )
    except (InvalidOperation, KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"invalid {source_name} MBO row at {row_label}") from exc


def _parse_action(value: str) -> MBOAction:
    if value not in VALID_ACTIONS:
        raise ValueError(f"unknown action: {value!r}")
    return cast(MBOAction, value)


def _parse_side(value: str) -> BookSide:
    if value not in VALID_SIDES:
        raise ValueError(f"unknown side: {value!r}")
    return cast(BookSide, value)
