"""
websocket_adapter.py — WebSocket transport for live market data
================================================================
Abstract interface for WebSocket-based OHLCV streams.
Implementations depend on the data provider (e.g. Polygon, Alpaca, custom).

The playbook engine consumes normalized bars from market_data_adapter;
this module defines the contract for WebSocket providers.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable

# Bar callback: receives list of normalized bar dicts
BarCallback = Callable[[list[dict]], None]


class WebSocketBarStream(ABC):
    """Abstract WebSocket stream that emits OHLCV bars."""

    @abstractmethod
    def connect(self, ticker: str) -> None:
        """Connect and subscribe to ticker."""
        pass

    @abstractmethod
    def disconnect(self) -> None:
        """Disconnect and clean up."""
        pass

    @abstractmethod
    def set_bar_callback(self, cb: BarCallback) -> None:
        """Set callback for new bars (aggregated from ticks or provider bars)."""
        pass

    @abstractmethod
    def is_connected(self) -> bool:
        """Return True if connected."""
        pass


def websocket_bars_stub(ticker: str, on_bar: BarCallback) -> None:
    """
    Stub for providers that don't yet have WebSocket bar aggregation.
    Used as placeholder; replace with real implementation when integrating
    Polygon/Alpaca/etc WebSocket.
    """
    raise NotImplementedError(
        "WebSocket bar stream not implemented. "
        "Use polling_adapter for REST-based data, or implement WebSocketBarStream for your provider."
    )
