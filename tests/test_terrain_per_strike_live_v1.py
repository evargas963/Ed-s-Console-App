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

from terrain_engine import TerrainSnapshot, _per_strike_map


def _exp(**kw):
    return SimpleNamespace(**kw)


def test_per_strike_map_carries_gex_and_session_volume():
    exposures = {740.0: _exp(net_gex=1.5e9), 741.0: _exp(net_gex=-2.0e9)}
    contracts = [
        {"strikePrice": 740.0, "totalVolume": 300000},
        {"strikePrice": 740.0, "totalVolume": 200000},   # calls + puts accumulate
        {"strikePrice": 741.0, "totalVolume": 375000},
    ]
    m = _per_strike_map(exposures, contracts)
    assert sorted(m) == [740.0, 741.0]
    assert m[740.0]["volume"] == 500000.0
    assert m[741.0]["volume"] == 375000.0
    assert m[740.0]["net_gex"] == 1.5e9


def test_per_strike_map_rejects_nan_volume_and_nan_strike():
    """A NaN vendor leaf must read as ABSENCE, never as a value (RC-38 class). A NaN strike must
    never become a dict key — that corrupted sorted strike sets in the original defect."""
    exposures = {740.0: _exp(net_gex=1.0)}
    contracts = [
        {"strikePrice": 740.0, "totalVolume": 100},
        {"strikePrice": 740.0, "totalVolume": float("nan")},
        {"strikePrice": 740.0, "totalVolume": float("inf")},
        {"strikePrice": float("nan"), "totalVolume": 999999},
    ]
    m = _per_strike_map(exposures, contracts)
    assert m[740.0]["volume"] == 100.0, "NaN/inf volume must not accumulate"
    assert all(k == k for k in m), "a NaN strike must never become a key"


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


def test_per_strike_map_ignores_strikes_outside_the_exposure_universe():
    """One chain in, one map out: a contract whose strike produced no exposure is not invented."""
    m = _per_strike_map({740.0: _exp(net_gex=1.0)},
                        [{"strikePrice": 999.0, "totalVolume": 5000}])
    assert 999.0 not in m
    # RC-290: no contract reported volume for 740.0, so its volume is UNKNOWN, not zero.
    # This asserted 0.0, which is the fabricated-zero contract Cursor's audit executed:
    # a missing totalVolume and a real zero both rendered 0.0 on the strike-volume panel.
    assert m[740.0]["volume"] is None, "absent volume is being reported as a measured zero"


def test_per_strike_is_excluded_from_to_dict_but_timestamp_is_not():
    """per_strike is hundreds of entries — too heavy for every poll (same reason `profile` is
    excluded). computed_ts_utc MUST survive: every consumer has to be able to render an age."""
    snap = TerrainSnapshot(ticker="SPY", spot=740.0)
    d = snap.to_dict()
    assert "per_strike" not in d
    assert "profile" not in d
    assert "computed_ts_utc" in d


def test_snapshot_defaults_are_absent_not_fabricated():
    snap = TerrainSnapshot(ticker="SPY", spot=740.0)
    assert snap.per_strike == {}
    assert snap.computed_ts_utc is None, "absence must read as absence, never a fake timestamp"
