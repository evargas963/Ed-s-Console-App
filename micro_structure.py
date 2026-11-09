"""One OHLCV bar, as the program's readers of Schwab's candles hold it."""

from dataclasses import (
    dataclass,
)


@dataclass
class Candle:
    """Single OHLCV bar."""

    ts: float  # epoch seconds
    open: float
    high: float
    low: float
    close: float
    volume: float | None = None
