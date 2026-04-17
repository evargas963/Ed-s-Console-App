"""
sse_adapter.py — Server-Sent Events transport for live market data
==================================================================
Abstract interface for SSE-based OHLCV streams.
Use when the data provider exposes bar updates via SSE.

The playbook engine consumes normalized bars from market_data_adapter;
this module defines the contract for SSE providers.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable, Optional

BarCallback = Callable[[list[dict]], None]


class SSEBarStream(ABC):
    """Abstract SSE stream that emits OHLCV bars."""

    @abstractmethod
    def connect(self, ticker: str, url: Optional[str] = None) -> None:
        """Connect to SSE endpoint for ticker."""
        pass

    @abstractmethod
    def disconnect(self) -> None:
        """Disconnect and clean up."""
        pass

    @abstractmethod
    def set_bar_callback(self, cb: BarCallback) -> None:
        """Set callback for new bars."""
        pass

    @abstractmethod
    def is_connected(self) -> bool:
        """Return True if connected."""
        pass


def sse_bars_stub(ticker: str, on_bar: BarCallback) -> None:
    """Stub; implement for your SSE provider."""
    raise NotImplementedError(
        "SSE bar stream not implemented. Use polling_adapter for REST-based data."
    )
