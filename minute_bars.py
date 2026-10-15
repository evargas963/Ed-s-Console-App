"""Each ticker's completed 1-minute bars: Schwab's own 1-minute price history (/pricehistory: its
last 10 days, extended hours) with each streamed CHART_EQUITY bar standing over its minute.

The one producer of the 1-minute series (docs/DATA_FLOW.md §3.4): the console keeps one store for
its calculations (server._minutes), the capture daemon one for the screen (live_ui), each fed the
same Schwab messages, so each holds the same bars. A minute Schwab did not deliver is absent, never
filled in.
"""
from __future__ import annotations

import threading
from typing import Any

from micro_structure import Candle, pricehistory_bars
from time_et import ct_label

#: the newest bars kept per ticker
BARS_KEPT = 24_000
#: the newest bars the 1-minute chart draws
CHART_1M_BARS = 1200
#: what a streamed bar did to its ticker's bars (MinuteBars.take): a new newest minute, the newest
#: minute again, or a minute anywhere else (the series is then sent whole)
APPEND, REPLACE, INSERT = "append", "replace", "insert"


def last_bar(c: Candle) -> dict:
    """A series' newest bar as every chart names it: its start (epoch s) and that start labelled."""
    return {"t": float(c.ts), "label": ct_label(c.ts)}


class MinuteBars:
    """Each ticker's bars, oldest first, the newest BARS_KEPT (`bars`: ticker -> [Candle])."""

    def __init__(self) -> None:
        self.bars: "dict[str, list[Candle]]" = {}
        self.lock = threading.Lock()

    def take_history(self, tk: str, candles: "list[dict[str, Any]]") -> None:
        """Schwab's /pricehistory 1-minute answer for `tk` (its candles as sent): each candle with
        every field a number kept, each streamed bar already held standing over its minute."""
        with self.lock:
            merged = {c.ts: c for c in pricehistory_bars(candles)}
            if tk in self.bars:
                merged.update((c.ts, c) for c in self.bars[tk])
            self.bars[tk] = [merged[t] for t in sorted(merged)][-BARS_KEPT:]

    def take(self, tk: str, bar: Candle) -> str:
        """A streamed bar into `tk`'s bars: a minute already held is replaced (Schwab's newest bar
        for it), a new one takes its place in time; the oldest beyond BARS_KEPT leave. What it did:
        APPEND (the newest), REPLACE (the newest minute again) or INSERT (anywhere else)."""
        with self.lock:
            held = self.bars.setdefault(tk, [])
            i = len(held)                       # bars arrive in time order: found at once
            while i and held[i - 1].ts > bar.ts:
                i -= 1
            if i and held[i - 1].ts == bar.ts:
                held[i - 1] = bar
                op = REPLACE if i == len(held) else INSERT
            else:
                held.insert(i, bar)
                op = APPEND if i == len(held) - 1 else INSERT
            del held[:-BARS_KEPT]
            return op

    def newest(self, tk: str, limit: int) -> "list[Candle]":
        """`tk`'s newest `limit` bars, oldest first."""
        with self.lock:
            return list(self.bars[tk][-int(limit):]) if tk in self.bars else []
