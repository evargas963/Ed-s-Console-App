"""RC-68: the terrain engine must RETAIN the live per-strike map, not discard it.

compute_exposures_by_strike already runs on every ~60s terrain refresh; its result was used to
pick the walls and then thrown away, which forced /api/terrain/strikes to render the per-strike
gamma+volume histogram from the FROZEN option_chain_morning_full archive. MEASURED 2026-07-27 on
SPY: a 09:47 capture served at 11:31 understated session volume by 281 percent (1,095,874 shown
vs 4,176,672 live), with ~500K missing on strike 740 alone.

These lock the retention and its numeric contract so the panel can never silently regress to the
archive, and so a NaN vendor leaf can never enter the histogram as a value.
"""
from __future__ import annotations

from types import SimpleNamespace

from terrain_engine import (
    TerrainSnapshot,
)


def _exp(**kw):
    return SimpleNamespace(**kw)






def test_unknown_dte_belongs_to_neither_near_nor_far_f8():
    """Cursor-audit F8: the /api/terrain/strikes prior-day path split near/far with its OWN 999.0
    sentinel — a duplicate of the RC-290-fixed canonical _dte_of — so a contract whose DTE could
    not be read was rendered in the far (MONTHLY+) chip and omitted from the near (≤7DTE) chip. It
    now uses _dte_of, which returns None for an unreadable DTE (belonging to NEITHER scope). This
    locks that invariant on the shared splitter the endpoint calls."""
    from terrain_engine import _dte_of

    contracts = [
        {"strikePrice": 100.0, "daysToExpiration": 0},               # near (0-DTE)
        {"strikePrice": 101.0, "daysToExpiration": 3},               # near
        {"strikePrice": 102.0, "daysToExpiration": 30},              # far
        {"strikePrice": 103.0, "daysToExpiration": float("nan")},    # unknown -> neither
        {"strikePrice": 104.0},                                      # missing -> neither
        {"strikePrice": 105.0, "daysToExpiration": float("inf")},    # junk -> neither
    ]
    assert _dte_of(contracts[3]) is None
    assert _dte_of(contracts[4]) is None
    assert _dte_of(contracts[5]) is None
    # the exact near/far split the endpoint now performs
    near = {c["strikePrice"] for c in contracts if (d := _dte_of(c)) is not None and d <= 7}
    far = {c["strikePrice"] for c in contracts if (d := _dte_of(c)) is not None and d > 7}
    assert near == {100.0, 101.0}, f"near must be the ≤7DTE contracts only, got {near}"
    assert far == {102.0}, f"far must be >7DTE only (no unknown-DTE leak into MONTHLY+), got {far}"
    # the F8 defect was the parse-failed contracts landing in far — they now appear in NEITHER
    assert (near | far).isdisjoint({103.0, 104.0, 105.0})




def test_per_strike_is_excluded_from_to_dict_but_timestamp_is_not():
    """per_strike is hundreds of entries — too heavy for every poll (same reason `profile` is
    excluded). computed_ts_utc MUST survive: every consumer has to be able to render an age."""
    snap = TerrainSnapshot(ticker="SPY", spot=740.0)
    d = snap.to_dict()
    assert "per_strike" not in d
    assert "profile" not in d
    assert "computed_ts_utc" in d


def test_the_per_strike_panel_serves_the_true_reason_it_has_no_rows(monkeypatch, caplog):
    """/api/terrain/strikes served "no levels published for this ticker yet" when the read of the
    published levels raised (swallowed at debug) and when they were published with no per-strike
    rows. Each case serves its own reason; the raise is logged at warning. Real SPY chain of
    2026-09-22 (tests/fixtures/real_spy_0dte_chain.json, its same-day expiry), published at 16:05
    ET (every contract past its settlement) and with no spot; the raising read a stand-in."""
    import json
    import logging
    from datetime import datetime
    from pathlib import Path

    import server
    from terrain_engine import compute_terrain
    from time_et import ET

    fx = json.loads((Path(__file__).parent / "fixtures" / "real_spy_0dte_chain.json").read_text(encoding="utf-8"))
    monkeypatch.setattr(server, "resolve_spot", lambda tk, **k: (None, None, None))

    def served(published):
        monkeypatch.setattr(server, "terrain_cache_get", published)
        return json.loads(server.get_terrain_strikes(ticker="SPY").body)["today"]["absent_reason"]

    def read_fails(tk, t):
        raise OSError("the terrain cache is unreadable")
    server.log.addHandler(caplog.handler)                  # the console's logger does not propagate
    try:
        assert served(read_fails) == "the published levels could not be read: OSError: the terrain cache is unreadable"
    finally:
        server.log.removeHandler(caplog.handler)
    assert any("could not be read" in r.getMessage() and r.levelno == logging.WARNING for r in caplog.records)
    assert served(lambda tk, t: None) == "no levels published for this ticker yet"
    expired = compute_terrain("SPY", fx["chain"], fx["spot"], now=datetime(2026, 9, 22, 16, 5, tzinfo=ET))
    assert served(lambda tk, t: {**expired.to_dict(), "_per_strike": expired.per_strike}) == (
        "no strike of the chain has open interest and a valid gamma (a contract past its settlement has none)")
    no_spot = compute_terrain("SPY", fx["chain"], None)
    assert served(lambda tk, t: {**no_spot.to_dict(), "_per_strike": no_spot.per_strike}) == (
        "the levels were not computed: no spot price")


def test_snapshot_defaults_are_absent_not_fabricated():
    snap = TerrainSnapshot(ticker="SPY", spot=740.0)
    assert snap.per_strike == {}
    assert snap.computed_ts_utc is None, "absence must read as absence, never a fake timestamp"
