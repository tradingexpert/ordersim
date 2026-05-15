"""Databento MBO connector."""

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal, Protocol, TypeAlias, cast

from ordersim.types import BookSide, MBOAction, MBOEvent

F_LAST = 1 << 7
F_MBP = 1 << 4
PRICE_SCALE = Decimal("0.000000001")

TimestampField = Literal["ts_event", "ts_recv"]


class DatabentoMboRecord(Protocol):
    """Raw Databento MBO record shape consumed by `DatabentoMboSource`."""

    ts_event: int
    ts_recv: int
    action: str
    side: str
    price: int
    size: int
    order_id: int
    flags: int


DatabentoRecordInput: TypeAlias = DatabentoMboRecord | Mapping[str, object]


@dataclass(frozen=True, slots=True)
class DatabentoMboSource:
    """Normalize raw Databento MBO records into public `MBOEvent` rows.

    `records` can be an iterable of raw Databento records such as a `DBNStore`,
    or mappings with the same field names. Databento prices are expected in raw
    integer nanounits. `ts_event` is the default timestamp because it is the
    matching-engine timestamp; use `timestamp_field="ts_recv"` only when the
    capture-server receive timestamp is the desired research clock.
    """

    records: Iterable[DatabentoRecordInput]
    timestamp_field: TimestampField = "ts_event"

    def __post_init__(self) -> None:
        if self.timestamp_field not in ("ts_event", "ts_recv"):
            raise ValueError("timestamp_field must be 'ts_event' or 'ts_recv'")

    def events(self) -> tuple[MBOEvent, ...]:
        """Return normalized simulator events."""

        normalized: list[MBOEvent] = []
        saw_visible_book_event = False
        for group in _event_groups(self.records):
            paired_fill_order_ids = {
                _as_int(_field(record, "order_id"))
                for record in group
                if _as_char(_field(record, "action")) == "F"
                and _as_char(_field(record, "side")) in ("A", "B")
            }
            for record in group:
                event, visible_book_event = _normalize_record(
                    record,
                    timestamp_field=self.timestamp_field,
                    paired_fill_order_ids=paired_fill_order_ids,
                    allow_leading_clear=not saw_visible_book_event,
                )
                if visible_book_event:
                    saw_visible_book_event = True
                if event is not None:
                    normalized.append(event)
        return tuple(normalized)


def _event_groups(
    records: Iterable[DatabentoRecordInput],
) -> Iterator[tuple[DatabentoRecordInput, ...]]:
    group: list[DatabentoRecordInput] = []
    for record in records:
        group.append(record)
        if _as_int(_field(record, "flags")) & F_LAST:
            yield tuple(group)
            group.clear()
    if group:
        yield tuple(group)


def _normalize_record(
    record: DatabentoRecordInput,
    *,
    timestamp_field: TimestampField,
    paired_fill_order_ids: set[int],
    allow_leading_clear: bool,
) -> tuple[MBOEvent | None, bool]:
    flags = _as_int(_field(record, "flags"))
    if flags & F_MBP:
        raise ValueError("aggregated Databento F_MBP records are not MBO-safe")

    action = _as_char(_field(record, "action"))
    side = _as_char(_field(record, "side"))
    order_id = _as_int(_field(record, "order_id"))

    if action in ("T", "N"):
        return None, False
    if action == "R":
        if allow_leading_clear:
            return None, False
        raise ValueError("mid-stream Databento clear events are not supported")
    if action == "F":
        if side == "N":
            return None, False
        return (
            _event_from_record(
                record,
                timestamp_field=timestamp_field,
                action="trade",
                side=_book_side(side),
            ),
            False,
        )
    if action == "C" and order_id in paired_fill_order_ids:
        return None, False
    if action not in ("A", "C", "M"):
        raise ValueError(f"unsupported Databento MBO action: {action!r}")
    if side == "N":
        raise ValueError(f"Databento action {action!r} requires side A or B")

    public_action = {"A": "add", "C": "cancel", "M": "modify"}[action]
    return (
        _event_from_record(
            record,
            timestamp_field=timestamp_field,
            action=cast(MBOAction, public_action),
            side=_book_side(side),
        ),
        True,
    )


def _event_from_record(
    record: DatabentoRecordInput,
    *,
    timestamp_field: TimestampField,
    action: MBOAction,
    side: BookSide,
) -> MBOEvent:
    return MBOEvent(
        ts_ns=_as_int(_field(record, timestamp_field)),
        action=action,
        side=side,
        price=Decimal(_as_int(_field(record, "price"))) * PRICE_SCALE,
        size=_as_int(_field(record, "size")),
        order_id=_as_int(_field(record, "order_id")),
    )


def _book_side(side: str) -> BookSide:
    if side == "A":
        return "ask"
    if side == "B":
        return "bid"
    raise ValueError(f"unsupported Databento side: {side!r}")


def _field(record: DatabentoRecordInput, name: str) -> Any:
    if isinstance(record, Mapping):
        try:
            return record[name]
        except KeyError as exc:
            raise ValueError(f"Databento record is missing field {name!r}") from exc
    try:
        return getattr(record, name)
    except AttributeError as exc:
        raise ValueError(f"Databento record is missing field {name!r}") from exc


def _as_char(value: object) -> str:
    if isinstance(value, bytes):
        value = value.decode("ascii")
    text = str(value)
    if len(text) != 1:
        raise ValueError(f"expected one-character Databento value, got {value!r}")
    return text


def _as_int(value: object) -> int:
    return int(value)
