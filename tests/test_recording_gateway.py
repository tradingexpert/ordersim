from decimal import Decimal
from typing import Any

from ordersim import Fill, OrderEvent, OrderResult, RecordingGateway, RestingOrder
from ordersim.types import OrderId, Price, Side, TimeInForce


class FakeGateway:
    def __init__(self) -> None:
        self.now = 1_000
        self.cancelled: list[int] = []

    def advance_to(self, ts_ns: int) -> list[Fill]:
        self.now = ts_ns
        return [
            Fill(
                order_id=7,
                side="sell",
                price=Decimal("101.0"),
                size=2,
                ts_ns=ts_ns,
            )
        ]

    def place_limit(
        self,
        side: Side,
        price: Price,
        size: int,
        tif: TimeInForce = "GTC",
    ) -> OrderResult:
        return OrderResult(
            order_id=42,
            fills=(
                Fill(
                    order_id=41,
                    side=side,
                    price=price,
                    size=1,
                    ts_ns=self.now,
                ),
            ),
        )

    def place_market(self, side: Side, size: int) -> list[Fill]:
        return [
            Fill(
                order_id=99,
                side=side,
                price=Decimal("102.5"),
                size=size,
                ts_ns=self.now,
            )
        ]

    def cancel(self, order_id: OrderId) -> bool:
        self.cancelled.append(order_id)
        return True

    def book_top(self) -> tuple[Price, Price]:
        return Decimal("100.0"), Decimal("101.0")

    def book_depth(self, levels: int) -> Any:
        return {"levels": levels}

    def position(self) -> int:
        return 0

    def own_orders(self) -> tuple[RestingOrder, ...]:
        return (
            RestingOrder(
                order_id=42,
                side="buy",
                price=Decimal("100.0"),
                remaining_size=2,
                queue_ahead_size=3,
            ),
        )

    def now_ns(self) -> int:
        return self.now

    def private_helper(self) -> str:
        return "forwarded"


def test_recording_gateway_records_limit_attempt_and_fill() -> None:
    events: list[OrderEvent] = []
    gateway = RecordingGateway(FakeGateway(), events, strategy="alpha")

    result = gateway.place_limit(side="buy", price=Decimal("100.5"), size=3)

    assert result.order_id == 42
    assert events == [
        OrderEvent(
            strategy="alpha",
            kind="place_limit",
            ts_ns=1_000,
            order_id=42,
            side="buy",
            price=Decimal("100.5"),
            size=3,
            tif="GTC",
            n_fills=1,
        ),
        OrderEvent(
            strategy="alpha",
            kind="fill",
            ts_ns=1_000,
            order_id=41,
            side="buy",
            fill_price=Decimal("100.5"),
            fill_size=1,
            source="place_limit",
        ),
    ]


def test_recording_gateway_records_passive_fill_and_cancel() -> None:
    events: list[OrderEvent] = []
    inner = FakeGateway()
    gateway = RecordingGateway(inner, events, strategy="alpha")

    fills = gateway.advance_to(2_000)
    accepted = gateway.cancel(42)

    assert accepted is True
    assert fills == [
        Fill(
            order_id=7,
            side="sell",
            price=Decimal("101.0"),
            size=2,
            ts_ns=2_000,
        )
    ]
    assert inner.cancelled == [42]
    assert events == [
        OrderEvent(
            strategy="alpha",
            kind="fill_passive",
            ts_ns=2_000,
            order_id=7,
            side="sell",
            fill_price=Decimal("101.0"),
            fill_size=2,
        ),
        OrderEvent(
            strategy="alpha",
            kind="cancel",
            ts_ns=2_000,
            order_id=42,
            accepted=True,
        ),
    ]


def test_recording_gateway_records_market_attempt_and_fill() -> None:
    events: list[OrderEvent] = []
    gateway = RecordingGateway(FakeGateway(), events, strategy="alpha")

    fills = gateway.place_market(side="sell", size=2)

    assert fills == [
        Fill(
            order_id=99,
            side="sell",
            price=Decimal("102.5"),
            size=2,
            ts_ns=1_000,
        )
    ]
    assert events == [
        OrderEvent(
            strategy="alpha",
            kind="place_market",
            ts_ns=1_000,
            side="sell",
            size=2,
            n_fills=1,
        ),
        OrderEvent(
            strategy="alpha",
            kind="fill",
            ts_ns=1_000,
            order_id=99,
            side="sell",
            fill_price=Decimal("102.5"),
            fill_size=2,
            source="place_market",
        ),
    ]


def test_recording_gateway_forwards_read_only_methods_and_helpers() -> None:
    events: list[OrderEvent] = []
    gateway = RecordingGateway(FakeGateway(), events, strategy="alpha")

    assert gateway.book_top() == (Decimal("100.0"), Decimal("101.0"))
    assert gateway.book_depth(3) == {"levels": 3}
    assert gateway.position() == 0
    assert gateway.own_orders() == (
        RestingOrder(
            order_id=42,
            side="buy",
            price=Decimal("100.0"),
            remaining_size=2,
            queue_ahead_size=3,
        ),
    )
    assert gateway.now_ns() == 1_000
    assert gateway.private_helper() == "forwarded"
    assert events == []
