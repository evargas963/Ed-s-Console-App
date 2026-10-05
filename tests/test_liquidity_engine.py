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






def test_imports():
    """All liquidity modules import cleanly."""
    from liquidity_models import SnapshotType, ZoneType
    assert SnapshotType.PREMARKET.value == "premarket"
    assert SnapshotType.LIVE.value == "live"
    assert ZoneType.RESISTANCE_LIQUIDITY.value == "resistance_liquidity"


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


def _bar(d: date, hh: int, mm: int, high: float, low: float, close: float = None,
         volume: float = 1000.0) -> dict:
    """One 1m bar at an explicit ET wall-clock time."""
    from datetime import datetime as _dt
    from time_et import ET as _ET
    ts = _dt(d.year, d.month, d.day, hh, mm, tzinfo=_ET)
    return {"timestamp": int(ts.timestamp() * 1000), "open": low,
            "high": high, "low": low, "close": close if close is not None else high,
            "volume": volume}


def _overnight(bars: list, session_date: date) -> dict:
    """The engine's overnight range as its producer gets it: bars normalized once, the prior
    session found once."""
    from liquidity_value_engine import _bars_to_list, get_overnight_levels, prior_trading_session_date
    norm = _bars_to_list(bars)
    return get_overnight_levels(norm, session_date, prior_trading_session_date(norm, session_date))


def test_overnight_window_monday_reaches_back_to_friday():
    """LP-01 Step 2 (RC-153): Monday's overnight starts at FRIDAY's 16:00 close. The old code
    used session_date - 1 day = SUNDAY, a day with no close and no bars, so Friday's entire
    post-16:00 tape was dropped and OVERNIGHT_HIGH/LOW described only Monday's pre-open."""
    friday, monday = date(2026, 7, 24), date(2026, 7, 27)
    bars = [
        _bar(friday, 10, 0, 100.0, 99.0),      # Friday RTH — establishes the prior session
        _bar(friday, 15, 59, 101.0, 100.0),    # Friday RTH, before the close
        _bar(friday, 17, 30, 108.0, 107.0),    # Friday AFTER 16:00 — inside the overnight
        _bar(monday, 4, 30, 96.0, 95.0),       # Monday pre-open — inside the overnight
        _bar(monday, 10, 0, 120.0, 90.0),      # Monday RTH — must NOT be in the overnight
    ]
    out = _overnight(bars, monday)
    assert out["overnight_high"] == 108.0, (
        f"Friday's post-close high is missing from Monday's overnight: {out}"
    )
    assert out["overnight_low"] == 95.0, f"overnight low wrong: {out}"
    assert out["overnight_high"] != 96.0, "overnight collapsed to Monday's pre-open only"


def test_overnight_window_midweek_uses_the_immediately_prior_session():
    """Tuesday's overnight starts at Monday's 16:00 — and Monday's RTH body stays out of it."""
    monday, tuesday = date(2026, 7, 27), date(2026, 7, 28)
    bars = [
        _bar(monday, 10, 0, 130.0, 70.0),      # Monday RTH — wide, must be EXCLUDED
        _bar(monday, 18, 0, 104.0, 103.0),     # Monday post-close — included
        _bar(tuesday, 8, 0, 99.0, 98.0),       # Tuesday pre-open — included
        _bar(tuesday, 9, 30, 140.0, 60.0),     # Tuesday RTH open bar — must be EXCLUDED
    ]
    out = _overnight(bars, tuesday)
    assert out["overnight_high"] == 104.0 and out["overnight_low"] == 98.0, (
        f"midweek overnight leaked an RTH bar: {out}"
    )


def test_overnight_window_spans_a_holiday_gap_without_inventing_a_session():
    """A closed day has no close for a range to start from. With Thursday shut, Friday's
    overnight must reach back to WEDNESDAY's 16:00 and include the Thursday bars in between —
    the interval is continuous, not two hand-picked calendar dates."""
    from liquidity_value_engine import prior_trading_session_date
    from liquidity_value_engine import _bars_to_list
    wed, thu, fri = date(2026, 7, 22), date(2026, 7, 23), date(2026, 7, 24)
    bars = [
        _bar(wed, 10, 0, 100.0, 99.0),         # Wednesday RTH — the real prior session
        _bar(wed, 17, 0, 106.0, 105.0),        # Wednesday post-close
        # The holiday itself: bars exist but NONE in RTH — a closed day trades no session.
        # (Placing one at 12:00 would make Thursday a real session, which is what the code
        # should conclude from that evidence; the fixture must mean what it claims.)
        _bar(thu, 3, 0, 111.0, 94.0),          # holiday extended-hours bar INSIDE the window
        _bar(fri, 8, 0, 97.0, 96.0),           # Friday pre-open
        _bar(fri, 10, 0, 200.0, 10.0),         # Friday RTH — excluded
    ]
    assert prior_trading_session_date(_bars_to_list(bars), fri) == wed, (
        "a day with no RTH bars was treated as the prior trading session"
    )
    out = _overnight(bars, fri)
    assert out["overnight_high"] == 111.0 and out["overnight_low"] == 94.0, (
        f"the holiday gap was skipped instead of spanned: {out}"
    )


def test_overnight_empty_is_empty_never_fabricated():
    """No bars in the window -> {}. Absence reads as absence."""
    tuesday = date(2026, 7, 28)
    only_rth = [_bar(date(2026, 7, 27), 11, 0, 100.0, 99.0),
                _bar(tuesday, 10, 0, 101.0, 98.0)]
    assert _overnight(only_rth, tuesday) == {}, "an overnight range was invented"
    assert _overnight([], tuesday) == {}


def test_overnight_without_a_prior_session_uses_only_this_session_premarket():
    """Fail-closed: with no prior RTH session in the buffer the interval has no start, so only
    this session's pre-open is used — never widened into a guess that sweeps older days."""
    tuesday = date(2026, 7, 28)
    bars = [
        _bar(date(2026, 7, 27), 20, 0, 300.0, 290.0),   # prior-day AFTER hours, no RTH anywhere
        _bar(tuesday, 8, 0, 99.0, 98.0),
    ]
    out = _overnight(bars, tuesday)
    assert out == {"overnight_high": 99.0, "overnight_low": 98.0}, (
        f"an unbounded window swept bars from a session that was never established: {out}"
    )


# ── LP-01 Step 3 (RC-154): no liquidity-pool claim on untested extremes ──────────────────
_POOL_WORDS = ("liquidity", "pool", "sweep", "stop hunt", "stop-hunt", "magnet")


def _step3_bars(session_date: date) -> list:
    """Bars that drive the taxonomy branch: a prior session, an overnight leg that undercuts
    the prior low, and an RTH open — i.e. exactly the shape that used to be labelled
    'sell-side liquidity'."""
    prev = date.fromordinal(session_date.toordinal() - 1)
    return [
        _bar(prev, 10, 0, 105.0, 100.0, close=104.0),
        _bar(prev, 15, 0, 106.0, 101.0, close=102.0),
        _bar(prev, 17, 0, 103.0, 99.0, close=99.5),      # after the close
        _bar(session_date, 6, 0, 100.0, 95.0, close=96.0),   # overnight UNDER the prior low
        _bar(session_date, 9, 45, 101.0, 96.0, close=100.0),  # RTH
    ]


def _step3_zones(session_date: date):
    from liquidity_models import PlaybookConfig
    from liquidity_value_engine import _bars_to_list, build_premarket_snapshot, build_price_level_snapshot
    snap = build_price_level_snapshot("SPY", session_date, _bars_to_list(_step3_bars(session_date)), bar_source="test")
    return build_premarket_snapshot("SPY", session_date, PlaybookConfig(), canonical=snap).zones


def test_no_pool_language_in_rendered_zone_payload():
    """Behaviour-bound: build the snapshot that used to produce 'Sell-side liquidity at
    overnight low' and assert no operator-facing field claims a pool."""
    session = date(2026, 7, 28)
    zones = _step3_zones(session)
    assert zones, "fixture produced no zones — the assertion would be vacuous"
    for z in zones:
        zt = str(getattr(z.zone_type, "value", z.zone_type))
        notes = (z.interpretation_notes or "").lower()
        assert "side_liquidity" not in zt, f"zone_type claims a pool: {zt}"
        assert z.zone_class != "liquidity", f"zone_class claims a pool: {z.zone_class}"
        for w in _POOL_WORDS:
            assert w not in notes, (
                f"interpretation_notes asserts {w!r} on an untested extreme: "
                f"{z.interpretation_notes!r} (zone_type={zt})"
            )


def test_cluster_price_levels():
    """Adjacent levels within 0.2% of the lower one merge; no reference price."""
    from liquidity_value_engine import cluster_price_levels_into_zones
    from liquidity_models import PlaybookConfig
    levels = [(500.0, "PDH"), (500.5, "PD_VAH"), (505.0, "ORB_HIGH")]
    clusters = cluster_price_levels_into_zones(levels, PlaybookConfig())
    assert [(lo, hi) for lo, hi, *_ in clusters] == [(500.0, 500.5), (505.0, 505.0)]












def test_no_lookahead_premarket():
    """Premarket snapshot does not use same-day RTH data."""
    from liquidity_value_engine import _bars_to_list, build_premarket_snapshot, build_price_level_snapshot
    from liquidity_models import PlaybookConfig
    session = date(2026, 3, 13)
    # Only previous day bars
    from datetime import timedelta
    prev_date = session - timedelta(days=1)
    bars = []
    for i in range(100):
        dt = datetime(prev_date.year, prev_date.month, prev_date.day, 10, 0 + i % 60, tzinfo=ET)
        bars.append(_mk_bar(dt, 500, 501, 499, 500, 1000))
    cfg = PlaybookConfig()
    snap = build_price_level_snapshot("SPY", session, _bars_to_list(bars), bar_source="test", config=cfg)
    out = build_premarket_snapshot("SPY", session, cfg, canonical=snap)
    assert out.raw_levels.get("prev_day")
    # No today POC/VAH/VAL in premarket raw: every "poc"-shaped key inside prev_day
    # must be the pd_-prefixed previous-day form, not an unprefixed today value that
    # leaked in. TEST_SYSTEM_REHAB_V2: was `"poc" not in prev_day or "pd_" in
    # raw_levels` -- the second arm checked ANY "pd_" occurrence anywhere in the
    # whole payload, satisfied unconditionally since prev_day always has pd_ keys,
    # so a leaked unprefixed "today_poc" inside prev_day would never be caught.
    prev_day = out.raw_levels.get("prev_day", {})
    poc_keys = [k for k in prev_day if "poc" in str(k).lower()]
    assert poc_keys, "prev_day carries no poc-shaped key at all"
    assert all(str(k).lower().startswith("pd_") for k in poc_keys), (
        f"prev_day contains a non-pd_-prefixed poc key: {poc_keys}")














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


