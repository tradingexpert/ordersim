"""Helpers for advancing replay state to execution boundaries."""

from collections.abc import Sequence
from dataclasses import dataclass

from ordersim.replay.compiled_events import CompiledEventColumns
from ordersim.sim import ExecutionEngine
from ordersim.types import Fill, MBOEvent


@dataclass(frozen=True, slots=True)
class BoundaryAdvance:
    """Result from advancing until the first passive fill or slice end."""

    events_consumed: int
    fills: tuple[Fill, ...]

    @property
    def stopped_on_fill(self) -> bool:
        """Whether advancement stopped because a passive fill appeared."""

        return bool(self.fills)


def advance_until_fill_boundary(
    engine: ExecutionEngine,
    events: Sequence[MBOEvent],
    *,
    start: int = 0,
    stop: int | None = None,
    compiled_events: CompiledEventColumns | None = None,
) -> BoundaryAdvance:
    """Advance an engine until a passive fill appears or the slice ends.

    This is the small bridge between scalar replay and compiled replay. If the
    engine exposes a compiled boundary method and compiled columns are provided,
    the engine advances through the slice internally. Otherwise this helper
    falls back to the readable scalar path.
    """

    end = len(events) if stop is None else stop
    _validate_slice(start=start, stop=end, length=len(events))
    if start == end:
        return BoundaryAdvance(events_consumed=0, fills=())

    apply_compiled = getattr(engine, "apply_events_until_fill", None)
    if compiled_events is not None and apply_compiled is not None:
        events_consumed, fills = apply_compiled(compiled_events.slice(start, end))
        return BoundaryAdvance(
            events_consumed=events_consumed,
            fills=tuple(fills),
        )

    fills: list[Fill] = []
    for offset, event in enumerate(events[start:end], start=1):
        event_fills = engine.apply_event(event)
        if event_fills:
            fills.extend(event_fills)
            return BoundaryAdvance(events_consumed=offset, fills=tuple(fills))

    return BoundaryAdvance(events_consumed=end - start, fills=())


def _validate_slice(*, start: int, stop: int, length: int) -> None:
    if start < 0:
        raise ValueError("start must be non-negative")
    if stop < start:
        raise ValueError("stop must be greater than or equal to start")
    if stop > length:
        raise ValueError("stop cannot exceed the number of events")
