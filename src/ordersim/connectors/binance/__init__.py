"""Binance market-data capture tools.

This package records observed Level 2 data and trades. It does not claim to
recover exchange-native Level 3 events.
"""

from ordersim.connectors.binance.capture import capture_binance
from ordersim.connectors.binance.l2 import (
    BinanceAggregateTrade,
    BinanceBookTicker,
    BinanceCaptureEnvelope,
    BinanceDepthEvent,
    BinanceDepthSnapshot,
    BinanceDepthUpdate,
    BinancePriceLevel,
    DepthStreamKind,
)
from ordersim.connectors.binance.schema import BinanceCaptureConfig, CaptureManifest
from ordersim.connectors.binance.source import (
    BinanceCaptureSource,
    BinanceSequenceError,
)

__all__ = [
    "BinanceAggregateTrade",
    "BinanceBookTicker",
    "BinanceCaptureConfig",
    "BinanceCaptureEnvelope",
    "BinanceCaptureSource",
    "BinanceDepthEvent",
    "BinanceDepthSnapshot",
    "BinanceDepthUpdate",
    "BinancePriceLevel",
    "BinanceSequenceError",
    "CaptureManifest",
    "DepthStreamKind",
    "capture_binance",
]
