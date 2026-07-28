"""Mechanical conversion from Binance JSON fields to typed records."""

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import cast

from ordersim.connectors.binance.l2 import (
    BinanceAggregateTrade,
    BinanceBookTicker,
    BinanceCaptureEnvelope,
    BinanceDepthSnapshot,
    BinanceDepthUpdate,
    BinancePriceLevel,
    BinanceRawTrade,
    CaptureKind,
    CaptureScope,
    DepthStreamKind,
)
from ordersim.connectors.binance.schema import CAPTURE_SCHEMA_VERSION


def parse_envelope(raw: object) -> BinanceCaptureEnvelope:
    """Convert one decoded JSON value into a validated capture envelope."""

    if not isinstance(raw, dict):
        raise ValueError("capture row must be a JSON object")
    version = required_int(raw, "schema_version")
    if version != CAPTURE_SCHEMA_VERSION:
        raise ValueError(f"unsupported capture schema_version {version}")
    kind = required_choice(
        raw,
        "kind",
        (
            "connection_open",
            "connection_error",
            "depth_snapshot",
            "message",
            "raw_trade",
            "raw_trade_gap",
            "raw_trade_poll",
            "raw_trade_poll_error",
            "sequence_gap",
        ),
    )
    scope = required_choice(raw, "scope", ("public", "market"))
    stream = raw.get("stream")
    if stream is not None and not isinstance(stream, str):
        raise ValueError("capture field 'stream' must be a string or null")
    payload = raw.get("payload")
    if not isinstance(payload, dict):
        raise ValueError("capture field 'payload' must be an object")
    return BinanceCaptureEnvelope(
        schema_version=version,
        received_at_ns=required_int(raw, "received_at_ns"),
        received_monotonic_ns=required_int(raw, "received_monotonic_ns"),
        kind=cast(CaptureKind, kind),
        scope=cast(CaptureScope, scope),
        symbol=required_str(raw, "symbol"),
        connection_id=required_str(raw, "connection_id"),
        stream=stream,
        payload=payload,
    )


def parse_depth_snapshot(
    envelope: BinanceCaptureEnvelope,
) -> BinanceDepthSnapshot:
    """Normalize one captured REST depth snapshot."""

    return BinanceDepthSnapshot(
        symbol=envelope.symbol,
        connection_id=envelope.connection_id,
        received_at_ns=envelope.received_at_ns,
        received_monotonic_ns=envelope.received_monotonic_ns,
        last_update_id=required_int(envelope.payload, "lastUpdateId"),
        bids=price_levels(envelope.payload, "bids"),
        asks=price_levels(envelope.payload, "asks"),
    )


def parse_depth_update(
    envelope: BinanceCaptureEnvelope,
    *,
    stream_kind: DepthStreamKind,
) -> BinanceDepthUpdate:
    """Normalize one captured standard or RPI depth update."""

    payload = envelope.payload
    check_payload_symbol(envelope)
    return BinanceDepthUpdate(
        symbol=envelope.symbol,
        connection_id=envelope.connection_id,
        stream_kind=stream_kind,
        event_time_ns=milliseconds_to_nanoseconds(payload, "E"),
        transaction_time_ns=milliseconds_to_nanoseconds(payload, "T"),
        received_at_ns=envelope.received_at_ns,
        received_monotonic_ns=envelope.received_monotonic_ns,
        first_update_id=required_int(payload, "U"),
        final_update_id=required_int(payload, "u"),
        previous_update_id=required_int(payload, "pu"),
        bids=price_levels(payload, "b"),
        asks=price_levels(payload, "a"),
    )


def parse_aggregate_trade(
    envelope: BinanceCaptureEnvelope,
) -> BinanceAggregateTrade:
    """Normalize one captured aggregate trade."""

    payload = envelope.payload
    check_payload_symbol(envelope)
    normal_quantity = (
        required_decimal(payload, "nq") if payload.get("nq") is not None else None
    )
    return BinanceAggregateTrade(
        symbol=envelope.symbol,
        connection_id=envelope.connection_id,
        event_time_ns=milliseconds_to_nanoseconds(payload, "E"),
        trade_time_ns=milliseconds_to_nanoseconds(payload, "T"),
        received_at_ns=envelope.received_at_ns,
        received_monotonic_ns=envelope.received_monotonic_ns,
        aggregate_trade_id=required_int(payload, "a"),
        price=required_decimal(payload, "p"),
        quantity=required_decimal(payload, "q"),
        normal_quantity=normal_quantity,
        first_trade_id=required_int(payload, "f"),
        last_trade_id=required_int(payload, "l"),
        buyer_is_maker=required_bool(payload, "m"),
    )


def parse_raw_trade(envelope: BinanceCaptureEnvelope) -> BinanceRawTrade:
    """Normalize one individually identified REST trade."""

    payload = envelope.payload
    return BinanceRawTrade(
        symbol=envelope.symbol,
        connection_id=envelope.connection_id,
        received_at_ns=envelope.received_at_ns,
        received_monotonic_ns=envelope.received_monotonic_ns,
        trade_id=required_int(payload, "id"),
        price=required_decimal(payload, "price"),
        quantity=required_decimal(payload, "qty"),
        quote_quantity=required_decimal(payload, "quoteQty"),
        trade_time_ns=milliseconds_to_nanoseconds(payload, "time"),
        buyer_is_maker=required_bool(payload, "isBuyerMaker"),
        is_rpi_trade=required_bool(payload, "isRPITrade"),
    )


def parse_book_ticker(envelope: BinanceCaptureEnvelope) -> BinanceBookTicker:
    """Normalize one captured real-time book ticker."""

    payload = envelope.payload
    check_payload_symbol(envelope)
    return BinanceBookTicker(
        symbol=envelope.symbol,
        connection_id=envelope.connection_id,
        event_time_ns=milliseconds_to_nanoseconds(payload, "E"),
        transaction_time_ns=milliseconds_to_nanoseconds(payload, "T"),
        received_at_ns=envelope.received_at_ns,
        received_monotonic_ns=envelope.received_monotonic_ns,
        update_id=required_int(payload, "u"),
        bid_price=required_decimal(payload, "b"),
        bid_quantity=required_decimal(payload, "B"),
        ask_price=required_decimal(payload, "a"),
        ask_quantity=required_decimal(payload, "A"),
    )


def depth_stream_kind(
    envelope: BinanceCaptureEnvelope,
) -> DepthStreamKind | None:
    """Identify a standard or RPI depth message."""

    if envelope.kind != "message" or envelope.stream is None:
        return None
    if "@rpiDepth@" in envelope.stream:
        return "rpi_depth"
    if "@depth@" in envelope.stream:
        return "depth"
    return None


def is_stream(envelope: BinanceCaptureEnvelope, suffix: str) -> bool:
    """Return whether an envelope is a message for the requested stream."""

    return (
        envelope.kind == "message"
        and envelope.stream is not None
        and envelope.stream.endswith(suffix)
    )


def check_payload_symbol(envelope: BinanceCaptureEnvelope) -> None:
    payload_symbol = required_str(envelope.payload, "s")
    if payload_symbol != envelope.symbol:
        raise ValueError(
            f"payload symbol {payload_symbol!r} does not match "
            f"envelope symbol {envelope.symbol!r}"
        )


def price_levels(
    payload: Mapping[str, object],
    field: str,
) -> tuple[BinancePriceLevel, ...]:
    rows = payload.get(field)
    if not isinstance(rows, list):
        raise ValueError(f"Binance field {field!r} must be a list")
    levels: list[BinancePriceLevel] = []
    for row in rows:
        if not isinstance(row, list) or len(row) < 2:
            raise ValueError(f"Binance field {field!r} has an invalid level")
        levels.append(
            BinancePriceLevel(
                price=decimal_value(row[0], field),
                quantity=decimal_value(row[1], field),
            )
        )
    return tuple(levels)


def milliseconds_to_nanoseconds(
    payload: Mapping[str, object],
    field: str,
) -> int:
    return required_int(payload, field) * 1_000_000


def required_int(payload: Mapping[str, object], field: str) -> int:
    value = payload.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"Binance field {field!r} must be an integer")
    return value


def required_str(payload: Mapping[str, object], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError(f"Binance field {field!r} must be a non-empty string")
    return value


def required_bool(payload: Mapping[str, object], field: str) -> bool:
    value = payload.get(field)
    if not isinstance(value, bool):
        raise ValueError(f"Binance field {field!r} must be a boolean")
    return value


def required_decimal(payload: Mapping[str, object], field: str) -> Decimal:
    return decimal_value(payload.get(field), field)


def decimal_value(value: object, field: str) -> Decimal:
    if not isinstance(value, str):
        raise ValueError(f"Binance field {field!r} must contain decimal strings")
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(
            f"Binance field {field!r} contains an invalid decimal"
        ) from exc


def required_choice(
    payload: Mapping[str, object],
    field: str,
    choices: tuple[str, ...],
) -> str:
    value = required_str(payload, field)
    if value not in choices:
        raise ValueError(f"Binance field {field!r} has unsupported value {value!r}")
    return value
