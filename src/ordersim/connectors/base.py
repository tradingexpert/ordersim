"""Connector contracts for normalized market-data sources."""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol, TypeAlias

from ordersim.types import MBOEvent


class DataSource(Protocol):
    """A source that yields normalized market-by-order events.

    Connectors should hide vendor SDK details and expose only `MBOEvent` rows at
    the public boundary. Timestamp units, order-id stability, price units, and
    lossy conversions belong in connector documentation and tests.
    """

    def events(self) -> Iterable[MBOEvent]:
        """Yield normalized MBO events."""


EventInput: TypeAlias = Iterable[MBOEvent] | DataSource


@dataclass(frozen=True, slots=True)
class InMemorySource:
    """Small data source backed by an in-memory event tuple."""

    name: str
    _events: tuple[MBOEvent, ...]

    @classmethod
    def from_events(
        cls,
        name: str,
        events: Iterable[MBOEvent],
    ) -> "InMemorySource":
        """Create an in-memory source from any iterable of events."""

        return cls(name=name, _events=tuple(events))

    def events(self) -> tuple[MBOEvent, ...]:
        """Return stored events."""

        return self._events


def normalize_events(data: EventInput) -> tuple[MBOEvent, ...]:
    """Return normalized events from an iterable or `DataSource`."""

    events_method = getattr(data, "events", None)
    if callable(events_method):
        return tuple(events_method())
    return tuple(data)
