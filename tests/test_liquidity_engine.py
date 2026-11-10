"""
test_liquidity_engine.py — Unit tests for Liquidity & Value Playbook Engine.

Run: pytest tests/test_liquidity_engine.py -v
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta

from liquidity_models import (
    MAX_BINS_PER_BAR,
    ZONE_DISPLAY,
    PlaybookConfig,
    SnapshotType,
    ZoneType,
    volume_profile,
)
from liquidity_value_engine import (
    bars_from_candles,
    build_premarket_snapshot,
    build_price_level_snapshot,
    cluster_price_levels_into_zones,
    get_overnight_levels,
)
from micro_structure import Candle
from time_et import (
    ET,
)


def _daily_candle(d: date, high: float, low: float, close: float) -> Candle:
    """Return a session's daily candle as Schwab dates it (midnight ET).

    It is built from the regular bars the test places in it.
    """
    # institutional-synthetic-ok: the session is the test's own placed bars
    ts = datetime(d.year, d.month, d.day, tzinfo=ET).timestamp()
    return Candle(ts=ts, open=low, high=high, low=low, close=close, volume=1000.0)


def _mk_bar(dt: datetime, o: float, h: float, lo: float, c: float, vol: float = 1000.0) -> Candle:
    return Candle(ts=dt.timestamp(), open=o, high=h, low=lo, close=c, volume=vol)


def test_imports():
    """All liquidity modules import cleanly."""
    assert SnapshotType.PREMARKET.value == "premarket"
    assert SnapshotType.LIVE.value == "live"
    assert ZoneType.RESISTANCE_LIQUIDITY.value == "resistance_liquidity"


def test_the_engine_takes_the_bar_writers_candles_as_they_are():
    """Each candle's fields as the bar writer checked them, an absent volume still absent."""
    (b,) = bars_from_candles(
        [Candle(ts=1710000000.0, open=500.0, high=501.0, low=499.0, close=500.5, volume=None)]
    )
    assert (b["timestamp"], b["open"], b["high"], b["low"], b["close"], b["volume"]) == (
        1710000000000,
        500.0,
        501.0,
        499.0,
        500.5,
        None,
    )
    assert b["_dt"] == datetime.fromtimestamp(1710000000.0, ET)


def _typical_price_dump(bars, tick_size=0.01):
    """Return the typical-price dump (each bar's whole volume at (H+L+C)/3).

    It is the disagreement witness: the fixtures below show the engine's distribution differs
    from it where it matters.
    """
    vol_by_price: dict = defaultdict(float)
    for b in bars:
        typical = (float(b["high"]) + float(b["low"]) + float(b["close"])) / 3.0
        vol_by_price[round(typical / tick_size) * tick_size] += float(b["volume"])
    if not vol_by_price:
        return None
    return round(max(vol_by_price, key=lambda p: vol_by_price[p]), 4)


def test_volume_profile_flat_bar_puts_all_volume_at_one_price():
    """A bar with high == low DID trade at exactly one price — distribution must not smear it."""
    bars = [{"high": 100.0, "low": 100.0, "close": 100.0, "volume": 5000.0}]
    p = volume_profile(bars)
    poc, vah, val = p.poc, p.vah, p.val
    assert poc == 100.0, f"flat bar POC moved off its only traded price: {poc}"
    assert vah == 100.0 and val == 100.0, f"flat bar produced a width: {val}..{vah}"


def test_volume_profile_distributes_a_wide_bar_across_its_range():
    """One wide bar's volume belongs across [low, high], not at (H+L+C)/3.

    With a single bar the distributed profile is FLAT, so every spanned price ties — while the
    dump puts 100% of it in one bin at the typical price.
    """
    bars = [{"high": 101.0, "low": 100.0, "close": 100.9, "volume": 10100.0}]
    p = volume_profile(bars, value_area_pct=0.70)
    vah, val = p.vah, p.val
    assert val >= 100.0 and vah <= 101.0, f"value area escaped the bar's range: {val}..{vah}"
    assert (vah - val) > 0.5, (
        f"a 70% value area over a uniformly-distributed 1.00-wide bar must span ~0.70, got "
        f"{vah - val:.2f} — the volume sits at one price, not across the bar"
    )
    dump_poc = _typical_price_dump(bars)
    assert abs(dump_poc - 100.6333) < 0.01, "witness fixture drifted"
    assert vah > dump_poc > val, (
        "the typical-price dump concentrates everything at the typical price; the distributed "
        "profile must instead spread across the range that price sits inside"
    )


def test_volume_profile_poc_is_the_price_most_bars_traded_through():
    """Hand-worked: three bars all span 100.00-100.04; a fourth spans 100.03-100.07.

    Every bar covers 100.03-100.04, so those two bins carry the most volume and the POC must
    land there. The typical-price dump cannot find it — no bar's (H+L+C)/3 lands on
    100.03/100.04.
    """
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
        "fixture does not discriminate — the typical-price dump agrees here"
    )
    assert val <= poc <= vah


def test_volume_profile_rejects_nan_and_nonpositive_volume():
    """A NaN bin key poisons every comparison after it; a zero-volume bar contributes nothing.

    Absence must read as absence rather than a fabricated level.
    """
    nan = float("nan")
    bars = [
        {"high": nan, "low": 100.0, "close": 100.0, "volume": 900.0},
        {"high": 100.0, "low": 100.0, "close": 100.0, "volume": 0.0},
        {"high": float("inf"), "low": 100.0, "close": 100.0, "volume": 900.0},
    ]
    assert volume_profile(bars) is None
    assert volume_profile([]) is None
    assert (
        volume_profile([{"high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0}], tick_size=0.0)
        is None
    )


def test_volume_profile_wide_bar_stays_bounded_and_distributed():
    """A pathological range against a 0.01 tick must not allocate unbounded bins.

    It must still SPREAD — the bound is a work cap, never a licence to dump.
    """
    bars = [{"high": 10000.0, "low": 0.01, "close": 5000.0, "volume": 1e6}]
    p = volume_profile(bars, value_area_pct=0.70)
    assert p is not None
    assert (p.vah - p.val) > 1000.0, "a 10,000-wide bar collapsed to a point — that is a dump"
    assert MAX_BINS_PER_BAR > 0


def _bar(
    d: date, hh: int, mm: int, high: float, low: float, close: float = None, volume: float = 1000.0
) -> Candle:
    """One 1m bar at an explicit ET wall-clock time."""
    ts = datetime(d.year, d.month, d.day, hh, mm, tzinfo=ET)
    return Candle(
        ts=ts.timestamp(),
        open=low,
        high=high,
        low=low,
        close=close if close is not None else high,
        volume=volume,
    )


def _overnight(bars: list, session_date: date, prior: date | None) -> dict:
    """Return the engine's overnight range as its producer gets it.

    Bars normalized once, from the close of the prior session `prior` (the date of Schwab's
    newest daily candle before the session, liquidity_value_engine.prior_session).
    """
    return get_overnight_levels(bars_from_candles(bars), session_date, prior)


def test_overnight_window_monday_reaches_back_to_friday():
    """Monday's overnight starts at FRIDAY's 16:00 close (the prior session), not at Sunday.

    Sunday has no close and no bars: Friday's post-16:00 tape is in OVERNIGHT_HIGH/LOW.
    """
    friday, monday = date(2026, 10, 2), date(2026, 10, 5)  # sessions Schwab's /markets sent
    bars = [
        _bar(friday, 10, 0, 100.0, 99.0),  # Friday RTH — establishes the prior session
        _bar(friday, 15, 59, 101.0, 100.0),  # Friday RTH, before the close
        _bar(friday, 17, 30, 108.0, 107.0),  # Friday AFTER 16:00 — inside the overnight
        _bar(monday, 4, 30, 96.0, 95.0),  # Monday pre-open — inside the overnight
        _bar(monday, 10, 0, 120.0, 90.0),  # Monday RTH — must NOT be in the overnight
    ]
    out = _overnight(bars, monday, friday)
    assert out["overnight_high"] == 108.0, (
        f"Friday's post-close high is missing from Monday's overnight: {out}"
    )
    assert out["overnight_low"] == 95.0, f"overnight low wrong: {out}"
    assert out["overnight_high"] != 96.0, "overnight collapsed to Monday's pre-open only"


def test_overnight_window_midweek_uses_the_immediately_prior_session():
    """Tuesday's overnight starts at Monday's 16:00 — and Monday's RTH body stays out of it."""
    monday, tuesday = date(2026, 10, 5), date(2026, 10, 6)
    bars = [
        _bar(monday, 10, 0, 130.0, 70.0),  # Monday RTH — wide, must be EXCLUDED
        _bar(monday, 18, 0, 104.0, 103.0),  # Monday post-close — included
        _bar(tuesday, 8, 0, 99.0, 98.0),  # Tuesday pre-open — included
        _bar(tuesday, 9, 30, 140.0, 60.0),  # Tuesday RTH open bar — must be EXCLUDED
    ]
    out = _overnight(bars, tuesday, monday)
    assert out["overnight_high"] == 104.0 and out["overnight_low"] == 98.0, (
        f"midweek overnight leaked an RTH bar: {out}"
    )


def test_overnight_window_spans_a_holiday_gap_without_inventing_a_session():
    """A closed day has no close for a range to start from.

    With Thanksgiving Thursday shut
    (Schwab's /markets: 2026-11-26 closed), Friday's overnight must reach back to WEDNESDAY's
    16:00 and include the Thursday bars in between — the interval is continuous, not two
    hand-picked calendar dates. Schwab sends no daily candle for the closed day, so the prior
    session is Wednesday's.
    """
    wed, thu, fri = date(2026, 11, 25), date(2026, 11, 26), date(2026, 11, 27)
    bars = [
        _bar(wed, 10, 0, 100.0, 99.0),  # Wednesday RTH — the real prior session
        _bar(wed, 17, 0, 106.0, 105.0),  # Wednesday post-close
        # The holiday itself: bars exist but NONE in RTH — a closed day trades no session.
        # (Placing one at 12:00 would make Thursday a real session, which is what the code
        # should conclude from that evidence; the fixture must mean what it claims.)
        _bar(thu, 3, 0, 111.0, 94.0),  # holiday extended-hours bar INSIDE the window
        _bar(fri, 8, 0, 97.0, 96.0),  # Friday pre-open
        _bar(fri, 10, 0, 200.0, 10.0),  # Friday RTH — excluded
    ]
    out = _overnight(bars, fri, wed)
    assert out["overnight_high"] == 111.0 and out["overnight_low"] == 94.0, (
        f"the holiday gap was skipped instead of spanned: {out}"
    )


def test_overnight_empty_is_empty_never_fabricated():
    """No bars in the window -> {}. Absence reads as absence."""
    tuesday = date(2026, 10, 6)
    only_rth = [_bar(date(2026, 10, 5), 11, 0, 100.0, 99.0), _bar(tuesday, 10, 0, 101.0, 98.0)]
    monday = date(2026, 10, 5)
    assert _overnight(only_rth, tuesday, monday) == {}, "an overnight range was invented"
    assert _overnight([], tuesday, monday) == {}


def test_overnight_without_a_prior_session_uses_only_this_session_premarket():
    """Fail-closed: with no prior RTH session in the buffer the interval has no start.

    So only this session's pre-open is used — never widened into a guess that sweeps older
    days.
    """
    tuesday = date(2026, 10, 6)
    bars = [
        _bar(date(2026, 10, 5), 20, 0, 300.0, 290.0),  # prior-day AFTER hours, no RTH anywhere
        _bar(tuesday, 8, 0, 99.0, 98.0),
    ]
    out = _overnight(bars, tuesday, None)  # no daily candle held for a prior session
    assert out == {"overnight_high": 99.0, "overnight_low": 98.0}, (
        f"an unbounded window swept bars from a session that was never established: {out}"
    )


# ── No liquidity-pool claim on untested extremes ─────────────────────────────────────────
_POOL_WORDS = ("liquidity", "pool", "sweep", "stop hunt", "stop-hunt", "magnet")


def _overnight_under_prior_low_bars(session_date: date) -> list:
    """Return bars that drive the taxonomy branch.

    A prior session, an overnight leg that undercuts the prior low, and an RTH open — the shape
    a pool label would claim as 'sell-side liquidity'.
    """
    prev = date.fromordinal(session_date.toordinal() - 1)
    return [
        _bar(prev, 10, 0, 105.0, 100.0, close=104.0),
        _bar(prev, 15, 0, 106.0, 101.0, close=102.0),
        _bar(prev, 17, 0, 103.0, 99.0, close=99.5),  # after the close
        _bar(session_date, 6, 0, 100.0, 95.0, close=96.0),  # overnight UNDER the prior low
        _bar(session_date, 9, 45, 101.0, 96.0, close=100.0),  # RTH
    ]


def _overnight_under_prior_low_zones(session_date: date):
    prev = date.fromordinal(session_date.toordinal() - 1)
    snap = build_price_level_snapshot(
        "SPY",
        session_date,
        bars_from_candles(_overnight_under_prior_low_bars(session_date)),
        prior=_daily_candle(prev, 106.0, 100.0, 102.0),  # the prior session's two regular bars
        bar_source="test",
    )
    return build_premarket_snapshot("SPY", PlaybookConfig(), canonical=snap).zones


def test_no_pool_language_in_rendered_zone_payload():
    """Behaviour-bound: no operator-facing field claims a pool.

    Build the snapshot for an overnight leg under the prior low and assert no operator-facing
    field claims a pool.
    """
    session = date(2026, 10, 6)  # a Tuesday: its prior session is the day before
    zones = _overnight_under_prior_low_zones(session)
    assert zones, "fixture produced no zones — the assertion would be vacuous"
    for z in zones:
        zt = z.zone_type.value
        notes = z.interpretation_notes.lower()
        assert "side_liquidity" not in zt, f"zone_type claims a pool: {zt}"
        label = ZONE_DISPLAY[z.zone_type][0].lower()
        assert "liquidity" not in label, f"the zone's name on screen claims a pool: {label}"
        for w in _POOL_WORDS:
            assert w not in notes, (
                f"interpretation_notes asserts {w!r} on an untested extreme: "
                f"{z.interpretation_notes!r} (zone_type={zt})"
            )


def test_cluster_price_levels():
    """Adjacent levels within 0.2% of the lower one merge; no reference price."""
    levels = [(500.0, "PDH"), (500.5, "PD_VAH"), (505.0, "ORB_HIGH")]
    clusters = cluster_price_levels_into_zones(levels, PlaybookConfig())
    assert [(lo, hi) for lo, hi, *_ in clusters] == [(500.0, 500.5), (505.0, 505.0)]


def test_no_lookahead_premarket():
    """Premarket snapshot does not use same-day RTH data."""
    session = date(2026, 10, 6)  # a Tuesday: its prior session is the day before
    # Only previous day bars
    prev_date = session - timedelta(days=1)
    bars = []
    for i in range(100):
        dt = datetime(prev_date.year, prev_date.month, prev_date.day, 10, 0 + i % 60, tzinfo=ET)
        bars.append(_mk_bar(dt, 500, 501, 499, 500, 1000))
    cfg = PlaybookConfig()
    snap = build_price_level_snapshot(
        "SPY",
        session,
        bars_from_candles(bars),
        prior=_daily_candle(prev_date, 501.0, 499.0, 500.0),
        bar_source="test",
        config=cfg,
    )
    out = build_premarket_snapshot("SPY", cfg, canonical=snap)
    labels = {s["label"] for z in out.zones for s in z.source_levels}
    assert labels & {"PDH", "PDL", "PDC"}
    # No today POC/VAH/VAL in the premarket zones: every poc-shaped level is the
    # previous day's PD_ form, never a same-day value.
    poc_labels = [t for t in labels if "POC" in t]
    assert poc_labels, "the premarket zones carry no POC at all"
    assert all(t.startswith("PD_") for t in poc_labels), (
        f"the premarket zones carry a same-day POC: {poc_labels}"
    )


def test_source_levels_use_actual_values():
    """source_levels stores actual level prices, not zone midpoint."""
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
    levels = [(100.0, "A"), (100.5, "B"), (101.0, "C"), (102.0, "D"), (103.0, "E")]
    cfg = PlaybookConfig(clustering_threshold_pct=0.02)
    clusters = cluster_price_levels_into_zones(levels, cfg)
    assert len(clusters) >= 1

    cfg_cap = PlaybookConfig(clustering_threshold_pct=0.02, max_zone_width=1.5)
    clusters_cap = cluster_price_levels_into_zones(levels, cfg_cap)
    for lo, hi, _, _, _ in clusters_cap:
        assert hi - lo <= 1.5 + 0.001, f"zone {lo}-{hi} exceeds max_zone_width 1.5"
    assert len(clusters_cap) >= len(clusters), "cap should produce more zones when width limited"
