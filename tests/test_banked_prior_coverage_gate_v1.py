# institutional-synthetic-ok: a crafted thin prior-session tape proves the banked coverage stamp fires.
"""Audit round 2 (2026-08-25) — the prior-session tape in price_bars_1m carries coverage
honesty. (price_bars_1m -- written only from Schwab's streamed 1-minute bars -- is the ONE bar
history, loaded into the console's memory at startup, so this stamp guards every level read.)

WHAT WAS MEASURED: the >=LEVELS_PRIOR_SESSION_MIN_BARS floor existed only on the
accumulator path (t12/RC-227), while the banked fallback fires precisely WHEN coverage
is low — MTA sessions banked at 188/236/316 of 390 RTH bars served next-day PDH/PDL as
prior-day fact from a tape missing up to half the session, silently. The fix stamps the
prior_day family degraded with the measured count (levels still serve — a low banked
count is ambiguous between thin trading and a collection gap, so absence-of-warning was
the defect, not the values' existence).
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

ET = ZoneInfo("America/New_York")


def _published(ticker: str, n_bars: int):
    """The price levels the producer publishes for Monday 2026-08-24 from a Friday tape of
    `n_bars` RTH minutes in price_bars_1m, loaded as the console's start loads it. Stand-in
    tickers ZZTHIN and ZZFULL carry the crafted tapes; nothing of them is left behind."""
    import server
    from liquidity_value_engine import _MATERIALIZED_SNAPSHOTS
    from micro_structure import Candle

    start = datetime(2026, 8, 21, 9, 30, tzinfo=ET)
    tape = [Candle(ts=(start + timedelta(minutes=i)).timestamp(), open=100.0 + i * 0.01, high=100.2 + i * 0.01,
                   low=99.8 + i * 0.01, close=100.1 + i * 0.01, volume=1000) for i in range(n_bars)]
    monday = datetime(2026, 8, 24, 12, 0, tzinfo=ET)

    def forget():
        con = sqlite3.connect(server.get_db().db_path)
        try:
            con.execute("DELETE FROM price_bars_1m WHERE ticker=?", (ticker,))
            con.commit()
        finally:
            con.close()
        server._bars.pop(ticker, None)
        for key in [k for k in _MATERIALIZED_SNAPSHOTS if k[0] == ticker]:
            del _MATERIALIZED_SNAPSHOTS[key]

    forget()
    try:
        server.get_db().upsert_1m_bars(ticker, tape)
        server._load_bars()                           # the console's start
        server._publish_price_levels(ticker, monday)
        return server.canonical_price_level_snapshot(ticker, monday)
    finally:
        forget()


def test_thin_banked_prior_session_is_stamped_degraded():
    snap = _published("ZZTHIN", 180)
    assert snap.price("PDH") is not None, "the thin tape still serves — the defect was silence, not existence"
    stamps = [d for d in snap.degraded if d.get("family") == "prior_day"]
    assert stamps and "prior session 2026-08-21" in stamps[0]["reason"], snap.degraded
    assert "partial tape" in stamps[0]["reason"], stamps
    assert "180" in stamps[0]["reason"], stamps


def test_full_banked_prior_session_carries_no_stamp():
    snap = _published("ZZFULL", 390)
    assert snap.bars_used == 390
    assert [d for d in snap.degraded if d.get("family") == "prior_day"] == []
