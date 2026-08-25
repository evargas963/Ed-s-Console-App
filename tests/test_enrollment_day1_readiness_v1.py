# institutional-synthetic-ok: crafted vendor payloads prove the RC-484 day-1 readiness paths.
"""RC-484 (operator requirement, 2026-08-25) — a newly enrolled ticker immediately
acquires available history and populates candles and mathematically available levels.

WHAT WAS MEASURED (audit round 2/3): every recent enrollee's first bar day WAS its first
data day (no seed ran at enrollment — the only 1m seed rode the viewer-gated
_fetch_state path); a previewed ticker's chart stayed empty all session (CRWV
2026-08-13: 127 snapshots, 0 banked bars, /api/bars1m had no fallback); the radar ring
stayed blind ~15 sessions because daily ATR read only local 1m bars. These tests pin the
three repairs: the enrollment one-shot 2-day 1m seed, the /api/bars1m accumulator
fallback, and the vendor daily-candle ATR fallback.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


def test_daily_candle_atr_matches_compute_atr_and_fails_closed():
    from math_volatility import compute_atr
    from terrain_atr import ATR_PERIOD, compute_atr_from_daily_candles

    candles = []
    px = 100.0
    for i in range(30):
        candles.append({
            "datetime": (1_755_000_000 + i * 86_400) * 1000,   # ms epoch, ascending days
            "open": px, "high": px + 2.0, "low": px - 1.0, "close": px + 0.5,
        })
        px += 0.5
    got = compute_atr_from_daily_candles(candles)
    want = compute_atr(
        [{"open": c["open"], "high": c["high"], "low": c["low"], "close": c["close"]}
         for c in candles], period=ATR_PERIOD)
    assert got is not None and abs(got - want) < 1e-9

    # Fail-closed: too few sessions, malformed rows, empty payload.
    assert compute_atr_from_daily_candles(candles[:ATR_PERIOD]) is None
    assert compute_atr_from_daily_candles([{"open": "x"}, None, 7]) is None
    assert compute_atr_from_daily_candles([]) is None


def test_enrollment_seed_banks_two_day_history(monkeypatch):
    import server as srv

    class _Resp:
        status_code = 200

        @staticmethod
        def json():
            return {"candles": [
                {"datetime": 1_755_000_000_000, "open": 1, "high": 2, "low": 0.5,
                 "close": 1.5, "volume": 10},
            ]}

    calls: list[tuple] = []

    def _fake_ph(client, ticker, *, frequency_minutes, period_days):
        calls.append((ticker, frequency_minutes, period_days))
        return _Resp()

    banked: list[tuple] = []

    class _FakeDB:
        @staticmethod
        def upsert_1m_bars(ticker, bars):
            banked.append((ticker, len(bars)))
            return len(bars)

    import schwab_client
    monkeypatch.setattr(schwab_client, "safe_get_price_history", _fake_ph)
    monkeypatch.setattr(srv, "get_client", lambda: object())
    monkeypatch.setattr(srv, "get_db", lambda: _FakeDB())
    srv._enrollment_history_seed("NEWT")
    assert calls == [("NEWT", 1, 2)], "one bounded vendor call: 1m x 2 days"
    assert banked == [("NEWT", 1)], "the payload lands in the ONE banked bar table"


def test_enrollment_seed_never_raises_on_vendor_failure(monkeypatch):
    import server as srv

    import schwab_client
    monkeypatch.setattr(schwab_client, "safe_get_price_history",
                        lambda *a, **k: None)
    monkeypatch.setattr(srv, "get_client", lambda: object())
    assert srv._enrollment_history_seed("NEWT") is None  # completes without raising


def test_bars1m_falls_through_to_live_accumulator_for_unbanked_ticker(tmp_path, monkeypatch):
    import json
    import sqlite3

    import server as srv

    dbp = tmp_path / "empty.db"
    con = sqlite3.connect(dbp)
    con.execute("CREATE TABLE price_bars_1m (ticker TEXT, bar_start_ts_utc REAL, open REAL, "
                "high REAL, low REAL, close REAL, volume REAL)")
    con.commit()
    con.close()

    class _StubDB:
        db_path = str(dbp)

    class _Candle:
        def __init__(self, ts):
            self.ts = ts
            self.open, self.high, self.low, self.close, self.volume = 1.0, 2.0, 0.5, 1.5, 9.0

    class _Acc:
        @staticmethod
        def get_bars(tk):
            return [_Candle(1_755_000_000 + i * 60) for i in range(3)]

    monkeypatch.setattr(srv, "get_db", lambda: _StubDB())
    monkeypatch.setattr(srv, "_candles_1m", _Acc())
    resp = srv.get_bars1m(ticker="PREV", limit=780)
    body = json.loads(resp.body)
    assert body["n"] == 3 and body["source"] == "live_accumulator_unbanked"
    assert body["bars"][0]["o"] == 1.0 and body["bars"][-1]["c"] == 1.5
