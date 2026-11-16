"""Each live window the console keeps in memory covers the longest window its screen reads.

Operator 2026-11-15: keep them, and know whether each keeps "too much of this data, too little or
is it the right amount". Too little cuts a screen short; the records keep every message whatever
the window (docs/DATA_FLOW.md §2 D4). The book heatmap's windows are refused past the books kept
(server.bookmap), so its limit cannot cut a window short in silence.

Real data: SPY's LEVELONE_EQUITIES messages of 2026-11-13 10:00:00-10:02:00 ET as the daemon
recorded them (tests/fixtures/real_spy_levelone_2026_11_13_1000et.json), SPY's /pricehistory
1-minute answer of 2026-10-07 (tests/feed_live_helper.price_history) and Schwab's /markets answers
held for the tests (tests/conftest.py).
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from app.options.order_flow.engine import OF_TAPE_WINDOW_5M_SEC
from app.options.order_flow.state import MAX_TAPE_PRINTS
from liquidity_value_engine import HOLD_WINDOW_SESSIONS
from state import bar_store
from tests.feed_live_helper import price_history
from time_et import sessions

_MSGS = json.loads(
    (Path(__file__).parent / "fixtures" / "real_spy_levelone_2026_11_13_1000et.json").read_text(
        encoding="utf-8"
    )
)["messages"]


def test_the_tape_holds_the_longest_pressure_window_at_the_busiest_rate_schwab_streams():
    """The tape's prints cover the 5-minute pressure window at SPY's busiest minute streamed.

    Measured 2026-11-15 on six tickers over the 2026-11-13 session: at most 59 prints a minute
    (Schwab's stream sends changes about once a second), so 500 prints hold about 8.5 minutes.
    """
    held: dict[str, object] = {}
    per_minute: Counter = Counter()
    last = None
    for m in _MSGS:
        held.update(
            {
                f: m["item"][f]
                for f in ("TRADE_TIME_MILLIS", "LAST_PRICE", "LAST_SIZE")
                if f in m["item"]
            }
        )
        triple = (held.get("TRADE_TIME_MILLIS"), held.get("LAST_PRICE"), held.get("LAST_SIZE"))
        if triple[1] is not None and triple != last:
            last = triple
            per_minute[int(m["ts_recv"] // 60)] += 1
    busiest = max(per_minute.values())
    assert busiest > 0
    assert MAX_TAPE_PRINTS / busiest * 60.0 >= OF_TAPE_WINDOW_5M_SEC


def test_the_bars_hold_the_sessions_the_hold_rates_read_and_schwabs_extended_hours():
    """BARS_KEPT holds the hold rates' sessions of regular minutes and Schwab's 1-minute history.

    The hold rates read HOLD_WINDOW_SESSIONS completed sessions; a session's regular minutes are
    its regular window as Schwab's /markets sent it; the 1-minute history with extended hours is
    Schwab's answer as sent.
    """
    held = sessions()
    regular = next(s for s in held.values() if s.regular)
    minutes = sum((end - start).total_seconds() for start, end in regular.regular) / 60.0
    extended = len(price_history("SPY", "1m")["body"]["candles"])
    assert HOLD_WINDOW_SESSIONS * minutes + extended <= bar_store.BARS_KEPT
