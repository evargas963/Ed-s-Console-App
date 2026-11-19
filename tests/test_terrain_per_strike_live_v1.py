"""RC-68: the terrain engine must RETAIN the live per-strike map, not discard it.

compute_exposures_by_strike already runs on every ~60s terrain refresh; its result was used to
pick the walls and then thrown away, which forced /api/terrain/strikes to render the per-strike
gamma+volume histogram from the FROZEN option_chain_morning_full archive. MEASURED 2026-07-27 on
SPY: a 09:47 capture served at 11:31 understated session volume by 281 percent (1,095,874 shown
vs 4,176,672 live), with ~500K missing on strike 740 alone.

These lock the retention and its numeric contract so the panel can never silently regress to the
archive, and so a NaN vendor leaf can never enter the histogram as a value.

Real data: SPY's whole chain of 2026-11-09 11:06 ET, 35 expiries (tests/real_chains.py).
"""

from __future__ import annotations

from calc.terrain_engine import TerrainSnapshot, per_strike_view
from option_contract import read_chain
from tests.real_chains import SPY_FULL


def test_unknown_dte_belongs_to_neither_near_nor_far_f8():
    """Cursor-audit F8: an unknown DTE belongs to neither the near nor the far scope.

    The /api/terrain/strikes prior-day path split near/far with its OWN 999.0 sentinel, so a
    contract whose DTE could not be read was rendered in the far (MONTHLY+) chip and
    omitted from the near (≤7DTE) chip. The contract record's `days_to_expiry` is None for an
    unreadable DTE (belonging to NEITHER scope). This locks that invariant on the record the
    endpoint splits by. INDUCED CONDITIONS: three of NFLX's contracts with a daysToExpiration
    that is not a number, absent, and infinite.
    """
    rows = [dict(c) for c in SPY_FULL.chain]
    rows[0]["daysToExpiration"] = float("nan")
    del rows[1]["daysToExpiration"]
    rows[2]["daysToExpiration"] = float("inf")
    contracts = read_chain(rows)
    assert [c.days_to_expiry for c in contracts[:3]] == [None, None, None]
    # the exact near/far split the endpoint now performs, on the daysToExpiration Schwab sent
    near = {c.symbol for c in contracts if (d := c.days_to_expiry) is not None and d <= 7}
    far = {c.symbol for c in contracts if (d := c.days_to_expiry) is not None and d > 7}
    sent = rows[3:]
    assert near == {r["symbol"] for r in sent if r["daysToExpiration"] <= 7}
    assert far == {r["symbol"] for r in sent if r["daysToExpiration"] > 7}
    assert near and far  # SPY lists both: a 0-DTE expiry and expiries past a week
    # the F8 defect was the parse-failed contracts landing in far — they now appear in NEITHER
    assert (near | far).isdisjoint({r["symbol"] for r in rows[:3]})


def test_per_strike_is_excluded_from_to_dict_but_timestamp_is_not():
    """per_strike is hundreds of entries — too heavy for every poll.

    Same reason `profile` is excluded. computed_ts_utc MUST survive: every consumer has to be
    able to render an age.
    """
    snap = TerrainSnapshot(ticker=SPY_FULL.ticker, spot=SPY_FULL.spot)
    d = snap.to_dict()
    assert "per_strike" not in d
    assert "profile" not in d
    assert "computed_ts_utc" in d


def test_snapshot_defaults_are_absent_not_fabricated():
    snap = TerrainSnapshot(ticker=SPY_FULL.ticker, spot=SPY_FULL.spot)
    assert snap.per_strike == per_strike_view({}, {}), "no book priced: the producer's own view"
    assert set(snap.per_strike) == {"all", "near", "far", "dex", "oi", "vanna"}
    assert all(rows == [] for rows in snap.per_strike.values()), "no row is fabricated"
    assert snap.computed_ts_utc is None, "absence must read as absence, never a fake timestamp"
