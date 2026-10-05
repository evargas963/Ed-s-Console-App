"""Audit round 2 (2026-08-25) — the prior session's bars carry coverage honesty. (The capture
daemon's record of Schwab's 1-minute bars is the ONE bar history, loaded into the console's
memory at startup, so this stamp guards every level read.)

WHAT WAS MEASURED: the >=LEVELS_PRIOR_SESSION_MIN_BARS floor existed only on the
accumulator path (t12/RC-227), while the banked fallback fires precisely WHEN coverage
is low — MTA sessions banked at 188/236/316 of 390 RTH bars served next-day PDH/PDL as
prior-day fact from a tape missing up to half the session, silently. The fix stamps the
prior_day family degraded with the measured count (levels still serve — a low count is
ambiguous between thin trading and a collection gap, so absence-of-warning was the defect,
not the values' existence).

Real data: Schwab's SPY and TSLA bars of Thu 2026-10-01 (390 regular-session minutes each) and
Fri 10-02 (291 each: the capture daemon was down for the rest), as the daemon recorded them.
"""
from __future__ import annotations

from datetime import datetime

import server
from liquidity_value_engine import _MATERIALIZED_SNAPSHOTS
from tests.feed_live_helper import daemon_bars, forget_daemon_bars, record_daemon_bars
from time_et import ET

_ROWS = daemon_bars("real_daemon_bars_spy_tsla_spx_2026_10_01_02.json", "SPY", "TSLA")
_PAIR = ("SPY", "TSLA")


def _published(now: datetime) -> dict:
    """Each ticker's price levels published at `now` from the recorded bars, loaded as the
    console's start loads them; nothing is left behind."""
    def forget():
        for tk in _PAIR:
            server._bars.pop(tk, None)
            for key in [k for k in _MATERIALIZED_SNAPSHOTS if k[0] == tk]:
                del _MATERIALIZED_SNAPSHOTS[key]

    forget()
    record_daemon_bars(_ROWS)
    try:
        server._load_bars()                           # the console's start
        out = {}
        for tk in _PAIR:
            server._publish_price_levels(tk, now)
            out[tk] = server.canonical_price_level_snapshot(tk, now)
        return out
    finally:
        forget_daemon_bars(_ROWS)
        forget()


def test_thin_banked_prior_session_is_stamped_degraded():
    """Mon 2026-10-05: the prior session, Friday, holds 291 of 390 regular-session bars."""
    for tk, snap in _published(datetime(2026, 10, 5, 12, 0, tzinfo=ET)).items():
        assert snap.price("PDH") is not None, (tk, "the thin tape still serves — the defect was silence, not existence")
        stamps = [d for d in snap.degraded if d.get("family") == "prior_day"]
        assert stamps and "prior session 2026-10-02" in stamps[0]["reason"], (tk, snap.degraded)
        assert "partial tape" in stamps[0]["reason"], (tk, stamps)
        assert "291" in stamps[0]["reason"], (tk, stamps)


def test_full_banked_prior_session_carries_no_stamp():
    """Fri 2026-10-02: the prior session, Thursday, holds all 390 regular-session bars."""
    for tk, snap in _published(datetime(2026, 10, 2, 12, 0, tzinfo=ET)).items():
        assert snap.price("PDH") is not None, tk
        assert [d for d in snap.degraded if d.get("family") == "prior_day"] == [], tk
