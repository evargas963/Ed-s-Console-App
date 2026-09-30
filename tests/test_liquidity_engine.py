"""
test_liquidity_engine.py — Unit tests for Liquidity & Value Playbook Engine
============================================================================

Run: pytest tests/test_liquidity_engine.py -v
  or: python tests/test_liquidity_engine.py
"""
from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from time_et import (
    ET,
)
def _mk_bar(dt: datetime, o: float, h: float, l: float, c: float, vol: float = 1000.0) -> dict:
    return {
        "timestamp": int(dt.timestamp() * 1000),
        "open": o, "high": h, "low": l, "close": c, "volume": vol,
    }






def test_bars_normalization():
    """Engine accepts list of dicts and produces correct internal format."""
    from liquidity_value_engine import _bars_to_list
    bars = [
        {"timestamp": 1710000000000, "open": 500, "high": 501, "low": 499, "close": 500.5, "volume": 1000},
    ]
    norm = _bars_to_list(bars)
    assert len(norm) == 1
    assert norm[0]["open"] == 500.0
    assert norm[0]["high"] == 501.0


def test_bars_normalization_preserves_missing_volume_as_missing():
    """S002: missing Schwab candle volume must not be silently converted to 0."""
    from liquidity_value_engine import _bars_to_list
    bars = [
        {"timestamp": 1710000000000, "open": 500, "high": 501, "low": 499, "close": 500.5},
    ]

    norm = _bars_to_list(bars)

    assert norm[0]["volume"] is None


def test_bars_normalization_drops_missing_ohlc_bar():
    """S003: incomplete Schwab OHLC bars must not become zero-price bars."""
    from liquidity_value_engine import _bars_to_list
    bars = [
        {"timestamp": 1710000000000, "open": 500, "high": 501, "close": 500.5, "volume": 1000},
    ]

    assert _bars_to_list(bars) == []
















def _typical_price_dump(bars, value_area_pct=0.70, tick_size=0.01):
    """The construction LP-01 Step 1 REPLACED, kept here only as the disagreement witness.

    A test that a new method 'works' proves nothing if the old one produced the same number.
    This reproduces the retired typical-price dump so the fixtures below can show the two
    genuinely differ where it matters.
    """
    from collections import defaultdict
    vol_by_price: dict = defaultdict(float)
    for b in bars:
        typical = (float(b["high"]) + float(b["low"]) + float(b["close"])) / 3.0
        vol_by_price[round(typical / tick_size) * tick_size] += float(b["volume"])
    if not vol_by_price:
        return None
    return round(max(vol_by_price, key=lambda p: vol_by_price[p]), 4)


def test_volume_profile_flat_bar_puts_all_volume_at_one_price():
    """A bar with high == low DID trade at exactly one price — distribution must not smear it."""
    from liquidity_models import volume_profile
    bars = [{"high": 100.0, "low": 100.0, "close": 100.0, "volume": 5000.0}]
    p = volume_profile(bars)
    poc, vah, val = p.poc, p.vah, p.val
    assert poc == 100.0, f"flat bar POC moved off its only traded price: {poc}"
    assert vah == 100.0 and val == 100.0, f"flat bar produced a width: {val}..{vah}"


def test_volume_profile_distributes_a_wide_bar_across_its_range():
    """The defect in one line: one wide bar's volume belongs across [low, high], not at
    (H+L+C)/3. With a single bar the distributed profile is FLAT, so every spanned price ties —
    while the dump puts 100% of it in one bin at the typical price."""
    from liquidity_models import volume_profile
    bars = [{"high": 101.0, "low": 100.0, "close": 100.9, "volume": 10100.0}]
    p = volume_profile(bars, value_area_pct=0.70)
    vah, val = p.vah, p.val
    assert val >= 100.0 and vah <= 101.0, f"value area escaped the bar's range: {val}..{vah}"
    assert (vah - val) > 0.5, (
        f"a 70% value area over a uniformly-distributed 1.00-wide bar must span ~0.70, got "
        f"{vah - val:.2f} — volume is still being dumped"
    )
    dump_poc = _typical_price_dump(bars)
    assert abs(dump_poc - 100.6333) < 0.01, "witness fixture drifted"
    assert vah > dump_poc > val, (
        "the retired dump concentrated everything at the typical price; the distributed "
        "profile must instead spread across the range that price sits inside"
    )


def test_volume_profile_poc_is_the_price_most_bars_traded_through():
    """Hand-worked: three bars all span 100.00-100.04; a fourth spans 100.03-100.07. Every bar
    covers 100.03-100.04, so those two bins carry the most volume and the POC must land there.
    The typical-price dump cannot find it — no bar's (H+L+C)/3 lands on 100.03/100.04."""
    from liquidity_models import volume_profile
    bars = [
        {"high": 100.04, "low": 100.00, "close": 100.00, "volume": 500.0},
        {"high": 100.04, "low": 100.00, "close": 100.00, "volume": 500.0},
        {"high": 100.04, "low": 100.00, "close": 100.00, "volume": 500.0},
        {"high": 100.07, "low": 100.03, "close": 100.07, "volume": 500.0},
    ]
    p = volume_profile(bars, value_area_pct=0.70)
    poc, vah, val = p.poc, p.vah, p.val
    assert poc in (100.03, 100.04), (
        f"POC {poc} is not in the band every bar traded through (100.03-100.04)"
    )
    dump_poc = _typical_price_dump(bars)
    assert dump_poc not in (100.03, 100.04), (
        "fixture no longer discriminates — the retired dump happens to agree here"
    )
    assert val <= poc <= vah


def test_volume_profile_rejects_nan_and_nonpositive_volume():
    """A NaN bin key poisons every comparison after it, and a zero-volume bar contributes
    nothing — absence must read as absence rather than a fabricated level."""
    from liquidity_models import volume_profile
    nan = float("nan")
    bars = [
        {"high": nan, "low": 100.0, "close": 100.0, "volume": 900.0},
        {"high": 100.0, "low": 100.0, "close": 100.0, "volume": 0.0},
        {"high": float("inf"), "low": 100.0, "close": 100.0, "volume": 900.0},
    ]
    assert volume_profile(bars) is None
    assert volume_profile([]) is None
    assert volume_profile([{"high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0}], tick_size=0.0) is None


def test_volume_profile_wide_bar_stays_bounded_and_still_distributed():
    """A pathological range against a 0.01 tick must not allocate unbounded bins, and must
    still SPREAD — the bound is a work cap, never a licence to dump."""
    from liquidity_models import MAX_BINS_PER_BAR, volume_profile
    bars = [{"high": 10000.0, "low": 0.01, "close": 5000.0, "volume": 1e6}]
    p = volume_profile(bars, value_area_pct=0.70)
    assert p is not None
    assert (p.vah - p.val) > 1000.0, "a 10,000-wide bar collapsed to a point — that is a dump"
    assert MAX_BINS_PER_BAR > 0


def test_no_zone_name_on_screen_claims_a_pool_of_orders():
    """No zone is a measured pool of resting orders: no name the screen shows says so."""
    from liquidity_models import ZONE_DISPLAY, ZoneType
    assert set(ZONE_DISPLAY) == set(ZoneType)
    for label, _side in ZONE_DISPLAY.values():
        assert not [w for w in ("liquidity", "pool", "sweep", "stop", "magnet") if w in label.lower()], label


def test_cluster_price_levels():
    """Adjacent levels within 0.2% of the lower one merge; no reference price."""
    from liquidity_value_engine import cluster_price_levels_into_zones
    from liquidity_models import PlaybookConfig
    levels = [(500.0, "PDH"), (500.5, "PD_VAH"), (505.0, "ORB_HIGH")]
    clusters = cluster_price_levels_into_zones(levels, PlaybookConfig())
    assert [(lo, hi) for lo, hi, *_ in clusters] == [(500.0, 500.5), (505.0, 505.0)]












def test_before_the_open_the_zones_hold_the_prior_days_levels_only():
    """With no bar of today's session, no level of today's exists to build a zone from.
    Stand-in (named): 100 hand-built bars of the prior day."""
    from liquidity_value_engine import _bars_to_list, build_price_level_snapshot, build_zones
    from liquidity_models import PlaybookConfig
    session = date(2026, 3, 13)
    from datetime import timedelta
    prev_date = session - timedelta(days=1)
    bars = []
    for i in range(100):
        dt = datetime(prev_date.year, prev_date.month, prev_date.day, 10, 0 + i % 60, tzinfo=ET)
        bars.append(_mk_bar(dt, 500, 501, 499, 500, 1000))
    cfg = PlaybookConfig()
    snap = build_price_level_snapshot("SPY", session, _bars_to_list(bars), bar_source="test", config=cfg)
    tags = {s["label"] for z in build_zones(snap, cfg, spot=None, extra_levels=[]) for s in z.source_levels}
    assert tags and tags <= {"PDH", "PDL", "PD_POC", "PD_VAH", "PD_VAL"}














def test_source_levels_use_actual_values():
    """source_levels stores actual level prices, not zone midpoint."""
    from liquidity_value_engine import cluster_price_levels_into_zones
    from liquidity_models import PlaybookConfig
    levels = [(100.0, "A"), (101.0, "B"), (105.0, "C")]
    cfg = PlaybookConfig(clustering_threshold_pct=0.1)
    clusters = cluster_price_levels_into_zones(levels, cfg)
    assert len(clusters) == 1
    lo, hi, mid, tags, source_pairs = clusters[0]
    assert mid == 102.5
    for p, t in source_pairs:
        if t == "A":
            assert p == 100.0
        elif t == "B":
            assert p == 101.0
        elif t == "C":
            assert p == 105.0


def test_max_zone_width():
    """max_zone_width prevents over-merged zones."""
    from liquidity_value_engine import cluster_price_levels_into_zones
    from liquidity_models import PlaybookConfig

    levels = [(100.0, "A"), (100.5, "B"), (101.0, "C"), (102.0, "D"), (103.0, "E")]
    cfg = PlaybookConfig(clustering_threshold_pct=0.02)
    clusters = cluster_price_levels_into_zones(levels, cfg)
    assert len(clusters) >= 1

    cfg_cap = PlaybookConfig(clustering_threshold_pct=0.02, max_zone_width=1.5)
    clusters_cap = cluster_price_levels_into_zones(levels, cfg_cap)
    for lo, hi, _, _, _ in clusters_cap:
        assert hi - lo <= 1.5 + 0.001, f"zone {lo}-{hi} exceeds max_zone_width 1.5"
    assert len(clusters_cap) >= len(clusters), "cap should produce more zones when width limited"


