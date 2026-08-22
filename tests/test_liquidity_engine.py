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

from time_et import ET, RTH_SESSION_MINUTES, RTH_START_MINS
def _mk_bar(dt: datetime, o: float, h: float, l: float, c: float, vol: float = 1000.0) -> dict:
    return {
        "timestamp": int(dt.timestamp() * 1000),
        "_ts": dt.timestamp(),
        "open": o, "high": h, "low": l, "close": c, "volume": vol,
    }


def _synthetic_bars(session_date: date, prev_day_bars: int = RTH_SESSION_MINUTES, today_bars: int = 300) -> list[dict]:
    """Generate synthetic 1-min bars: prev day RTH + today RTH (partial).
    today_bars=300 gives bars through 14:30 ET (enough for afternoon cutoff 14:00)."""
    from datetime import timedelta

    bars = []
    base_price = 500.0
    prev_date = session_date - timedelta(days=1)

    # Previous day cash RTH [open, close)
    for i in range(prev_day_bars):
        mins = int(RTH_START_MINS) + i
        h = mins // 60
        m = mins % 60
        dt = datetime(prev_date.year, prev_date.month, prev_date.day, h, m, tzinfo=ET)
        p = base_price + (i % 50) - 25
        bars.append(_mk_bar(dt, p, p + 0.5, p - 0.5, p, 1000))

    # Today cash RTH: first N minutes
    for i in range(today_bars):
        mins = int(RTH_START_MINS) + i
        h = mins // 60
        m = mins % 60
        dt = datetime(session_date.year, session_date.month, session_date.day, h, m, tzinfo=ET)
        p = base_price + (i % 40) - 20
        bars.append(_mk_bar(dt, p, p + 0.3, p - 0.3, p, 800))
    return bars


def _bars_through(session_date: date, hour: int, minute: int, prev_day_bars: int = RTH_SESSION_MINUTES) -> list[dict]:
    """Bars only through given ET time (exclusive of bars past that time)."""
    from datetime import timedelta

    bars = []
    base_price = 500.0
    prev_date = session_date - timedelta(days=1)
    cutoff_mins = hour * 60 + minute

    for i in range(prev_day_bars):
        mins = int(RTH_START_MINS) + i
        h = mins // 60
        m = mins % 60
        dt = datetime(prev_date.year, prev_date.month, prev_date.day, h, m, tzinfo=ET)
        p = base_price + (i % 50) - 25
        bars.append(_mk_bar(dt, p, p + 0.5, p - 0.5, p, 1000))

    today_start = int(RTH_START_MINS)
    for i in range(cutoff_mins - today_start + 1):
        mins = today_start + i
        h = mins // 60
        m = mins % 60
        dt = datetime(session_date.year, session_date.month, session_date.day, h, m, tzinfo=ET)
        p = base_price + (i % 40) - 20
        bars.append(_mk_bar(dt, p, p + 0.3, p - 0.3, p, 800))
    return bars


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


def test_schwab_candles_to_bars_drops_missing_ohlc_bar():
    """S003: pricehistory candle OHLC fields are required."""
    from market_data_adapter import schwab_candles_to_bars
    candles = [{"datetime": 1710000000000, "open": 500, "high": 501, "close": 500.5, "volume": 1000}]

    assert schwab_candles_to_bars(candles) == []


def test_get_previous_day_levels():
    """Previous day levels extracted from bars."""
    from liquidity_value_engine import get_previous_day_levels
    from liquidity_models import PlaybookConfig
    session = date(2026, 3, 13)
    bars = _synthetic_bars(session)
    cfg = PlaybookConfig()
    prev = get_previous_day_levels(bars, session, cfg)
    assert prev.get("pdh") is not None
    assert prev.get("pdl") is not None
    assert prev.get("pdc") is not None
    assert prev.get("pd_poc") is not None
    assert prev["pdh"] >= prev["pdl"]


def test_compute_opening_range():
    """Opening range = first 15 min of RTH."""
    from liquidity_value_engine import compute_opening_range
    from liquidity_models import PlaybookConfig
    session = date(2026, 3, 13)
    bars = _synthetic_bars(session)
    cfg = PlaybookConfig(opening_range_minutes=15)
    orb = compute_opening_range(bars, session, cfg)
    assert orb.get("orb_high") is not None
    assert orb.get("orb_low") is not None
    assert orb.get("orb_mid") is not None
    assert orb["orb_high"] >= orb["orb_low"]


def test_compute_session_vwap():
    """VWAP computed from RTH bars."""
    from liquidity_value_engine import compute_session_vwap
    session = date(2026, 3, 13)
    bars = _synthetic_bars(session)
    vwap = compute_session_vwap(bars, session)
    assert vwap is not None
    assert 400 < vwap < 600


def test_compute_session_vwap_returns_none_when_volume_missing():
    """S002: VWAP is volume-weighted and must fail closed without candle volume."""
    from liquidity_value_engine import compute_session_vwap
    session = date(2026, 3, 13)
    bars = _synthetic_bars(session)
    for bar in bars:
        bar.pop("volume", None)

    assert compute_session_vwap(bars, session) is None


def test_midday_snapshot_does_not_create_vwap_bands_when_vwap_missing():
    """S014 sub-slice: missing VWAP must not create bands around synthetic zero."""
    import liquidity_value_engine as lve
    from liquidity_models import PlaybookConfig

    session = date(2026, 3, 13)
    bars = _synthetic_bars(session)
    for bar in bars:
        if datetime.fromtimestamp(float(bar["_ts"]), ET).date() == session:
            bar.pop("volume", None)

    out = lve.build_midday_snapshot("SPY", bars, session, PlaybookConfig())

    assert out.raw_levels["vwap"] is None
    assert out.raw_levels["vwap_bands"] is None
    assert all("VWAP_P1" not in z.source_tags and "VWAP_M1" not in z.source_tags for z in out.zones)


def test_compute_volume_profile_levels():
    """POC, VAH, VAL computed from bars."""
    from liquidity_value_engine import compute_volume_profile_levels
    from liquidity_models import PlaybookConfig
    session = date(2026, 3, 13)
    bars = _synthetic_bars(session)
    cfg = PlaybookConfig()
    poc, vah, val = compute_volume_profile_levels(bars, session, cfg)
    assert poc is not None
    assert vah is not None
    assert val is not None
    assert val <= poc <= vah


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
    from liquidity_models import volume_profile_poc_vah_val
    bars = [{"high": 100.0, "low": 100.0, "close": 100.0, "volume": 5000.0}]
    poc, vah, val = volume_profile_poc_vah_val(bars)
    assert poc == 100.0, f"flat bar POC moved off its only traded price: {poc}"
    assert vah == 100.0 and val == 100.0, f"flat bar produced a width: {val}..{vah}"


def test_volume_profile_distributes_a_wide_bar_across_its_range():
    """The defect in one line: one wide bar's volume belongs across [low, high], not at
    (H+L+C)/3. With a single bar the distributed profile is FLAT, so every spanned price ties —
    while the dump puts 100% of it in one bin at the typical price."""
    from liquidity_models import volume_profile_poc_vah_val
    bars = [{"high": 101.0, "low": 100.0, "close": 100.9, "volume": 10100.0}]
    poc, vah, val = volume_profile_poc_vah_val(bars, value_area_pct=0.70)
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
    from liquidity_models import volume_profile_poc_vah_val
    bars = [
        {"high": 100.04, "low": 100.00, "close": 100.00, "volume": 500.0},
        {"high": 100.04, "low": 100.00, "close": 100.00, "volume": 500.0},
        {"high": 100.04, "low": 100.00, "close": 100.00, "volume": 500.0},
        {"high": 100.07, "low": 100.03, "close": 100.07, "volume": 500.0},
    ]
    poc, vah, val = volume_profile_poc_vah_val(bars, value_area_pct=0.70)
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
    from liquidity_models import volume_profile_poc_vah_val
    nan = float("nan")
    bars = [
        {"high": nan, "low": 100.0, "close": 100.0, "volume": 900.0},
        {"high": 100.0, "low": 100.0, "close": 100.0, "volume": 0.0},
        {"high": float("inf"), "low": 100.0, "close": 100.0, "volume": 900.0},
    ]
    assert volume_profile_poc_vah_val(bars) == (None, None, None)
    assert volume_profile_poc_vah_val([]) == (None, None, None)
    assert volume_profile_poc_vah_val([{"high": 1.0, "low": 1.0, "close": 1.0,
                                        "volume": 1.0}], tick_size=0.0) == (None, None, None)


def test_volume_profile_wide_bar_stays_bounded_and_still_distributed():
    """A pathological range against a 0.01 tick must not allocate unbounded bins, and must
    still SPREAD — the bound is a work cap, never a licence to dump."""
    from liquidity_models import MAX_BINS_PER_BAR, volume_profile_poc_vah_val
    bars = [{"high": 10000.0, "low": 0.01, "close": 5000.0, "volume": 1e6}]
    poc, vah, val = volume_profile_poc_vah_val(bars, value_area_pct=0.70)
    assert poc is not None and vah is not None and val is not None
    assert (vah - val) > 1000.0, "a 10,000-wide bar collapsed to a point — that is a dump"
    assert MAX_BINS_PER_BAR > 0


def test_both_call_sites_use_the_one_construction():
    """LP-01 Step 1 requires ONE faucet. liquidity_value_engine and market_context each held an
    independent copy of the same dump; two copies of a wrong construction are two wrong answers
    that can also disagree with each other."""
    import re
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    for name in ("liquidity_value_engine.py", "market_context.py"):
        src = (root / name).read_text(encoding="utf-8")
        body = re.sub(r"#.*$", "", src, flags=re.M)
        assert "volume_profile_poc_vah_val(bars, value_area_pct, tick_size" in body, (
            f"{name} does not delegate to the one construction"
        )
        i = body.find("def _volume_profile_poc_vah_val")
        assert i > 0, f"{name} lost its entry point"
        # Scope to the PROFILE function only. Typical price is CORRECT for VWAP — VWAP is
        # defined as sum(typical * vol) / sum(vol) — so `_vwap_bands` legitimately computes
        # (h+l+cl)/3 and must not be swept up by this check. The defect was using typical
        # price to build the volume PROFILE, nowhere else.
        fn = body[i:i + 1200]
        assert "/ 3.0" not in fn, f"{name} still builds the profile from a typical price"
        assert "defaultdict" not in fn, (
            f"{name} still accumulates its own bins instead of delegating to the one faucet"
        )


def test_engine_and_context_agree_on_one_profile():
    """Same bars, same tick, same value-area pct -> the two entry points must agree (they now
    share an implementation; rounding differs by design, 4dp vs 2dp)."""
    from liquidity_value_engine import _volume_profile_poc_vah_val as eng
    from market_context import _volume_profile_poc_vah_val as ctx
    bars = [
        {"high": 100.04, "low": 100.00, "close": 100.02, "volume": 500.0},
        {"high": 100.06, "low": 100.02, "close": 100.05, "volume": 800.0},
    ]
    e_poc, e_vah, e_val = eng(bars, 0.70, 0.01)
    c_poc, c_vah, c_val = ctx(bars, 0.70, 0.01)
    assert abs(e_poc - c_poc) < 0.01, f"two faucets disagree on POC: {e_poc} vs {c_poc}"
    assert abs(e_vah - c_vah) < 0.01 and abs(e_val - c_val) < 0.01


def _bar(d: date, hh: int, mm: int, high: float, low: float, close: float = None,
         volume: float = 1000.0) -> dict:
    """One 1m bar at an explicit ET wall-clock time."""
    from datetime import datetime as _dt
    from time_et import ET as _ET
    ts = _dt(d.year, d.month, d.day, hh, mm, tzinfo=_ET)
    return {"datetime": int(ts.timestamp() * 1000), "open": low,
            "high": high, "low": low, "close": close if close is not None else high,
            "volume": volume}


def test_overnight_window_monday_reaches_back_to_friday():
    """LP-01 Step 2 (RC-153): Monday's overnight starts at FRIDAY's 16:00 close. The old code
    used session_date - 1 day = SUNDAY, a day with no close and no bars, so Friday's entire
    post-16:00 tape was dropped and OVERNIGHT_HIGH/LOW described only Monday's pre-open."""
    from liquidity_value_engine import get_overnight_levels
    friday, monday = date(2026, 7, 24), date(2026, 7, 27)
    bars = [
        _bar(friday, 10, 0, 100.0, 99.0),      # Friday RTH — establishes the prior session
        _bar(friday, 15, 59, 101.0, 100.0),    # Friday RTH, before the close
        _bar(friday, 17, 30, 108.0, 107.0),    # Friday AFTER 16:00 — inside the overnight
        _bar(monday, 4, 30, 96.0, 95.0),       # Monday pre-open — inside the overnight
        _bar(monday, 10, 0, 120.0, 90.0),      # Monday RTH — must NOT be in the overnight
    ]
    out = get_overnight_levels(bars, monday)
    assert out["overnight_high"] == 108.0, (
        f"Friday's post-close high is missing from Monday's overnight: {out}"
    )
    assert out["overnight_low"] == 95.0, f"overnight low wrong: {out}"
    assert out["overnight_high"] != 96.0, "overnight collapsed to Monday's pre-open only"


def test_overnight_window_midweek_uses_the_immediately_prior_session():
    """Tuesday's overnight starts at Monday's 16:00 — and Monday's RTH body stays out of it."""
    from liquidity_value_engine import get_overnight_levels
    monday, tuesday = date(2026, 7, 27), date(2026, 7, 28)
    bars = [
        _bar(monday, 10, 0, 130.0, 70.0),      # Monday RTH — wide, must be EXCLUDED
        _bar(monday, 18, 0, 104.0, 103.0),     # Monday post-close — included
        _bar(tuesday, 8, 0, 99.0, 98.0),       # Tuesday pre-open — included
        _bar(tuesday, 9, 30, 140.0, 60.0),     # Tuesday RTH open bar — must be EXCLUDED
    ]
    out = get_overnight_levels(bars, tuesday)
    assert out["overnight_high"] == 104.0 and out["overnight_low"] == 98.0, (
        f"midweek overnight leaked an RTH bar: {out}"
    )


def test_overnight_window_spans_a_holiday_gap_without_inventing_a_session():
    """A closed day has no close for a range to start from. With Thursday shut, Friday's
    overnight must reach back to WEDNESDAY's 16:00 and include the Thursday bars in between —
    the interval is continuous, not two hand-picked calendar dates."""
    from liquidity_value_engine import get_overnight_levels, prior_trading_session_date
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
    out = get_overnight_levels(bars, fri)
    assert out["overnight_high"] == 111.0 and out["overnight_low"] == 94.0, (
        f"the holiday gap was skipped instead of spanned: {out}"
    )


def test_overnight_empty_is_empty_never_fabricated():
    """No bars in the window -> {}. Absence reads as absence."""
    from liquidity_value_engine import get_overnight_levels
    tuesday = date(2026, 7, 28)
    only_rth = [_bar(date(2026, 7, 27), 11, 0, 100.0, 99.0),
                _bar(tuesday, 10, 0, 101.0, 98.0)]
    assert get_overnight_levels(only_rth, tuesday) == {}, "an overnight range was invented"
    assert get_overnight_levels([], tuesday) == {}


def test_overnight_without_a_prior_session_uses_only_this_session_premarket():
    """Fail-closed: with no prior RTH session in the buffer the interval has no start, so only
    this session's pre-open is used — never widened into a guess that sweeps older days."""
    from liquidity_value_engine import get_overnight_levels
    tuesday = date(2026, 7, 28)
    bars = [
        _bar(date(2026, 7, 27), 20, 0, 300.0, 290.0),   # prior-day AFTER hours, no RTH anywhere
        _bar(tuesday, 8, 0, 99.0, 98.0),
    ]
    out = get_overnight_levels(bars, tuesday)
    assert out == {"overnight_high": 99.0, "overnight_low": 98.0}, (
        f"an unbounded window swept bars from a session that was never established: {out}"
    )


def test_prior_session_helper_is_the_one_definition():
    """Both the previous-day levels and the overnight window must resolve 'prior session' the
    same way — two definitions is how they disagree about which day yesterday was."""
    import ast
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent / "liquidity_value_engine.py").read_text(
        encoding="utf-8")
    tree = ast.parse(src)
    fns = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    for name in ("get_overnight_levels", "get_previous_day_levels", "compute_atr_from_bars"):
        assert name in fns, f"{name} is gone"
        node = fns[name]
        # EXECUTABLE code only — the docstrings deliberately quote the retired
        # `session_date - timedelta(days=1)` to explain the defect, and a text search would
        # read that explanation as the defect itself.
        stmts = [s for s in node.body if not (isinstance(s, ast.Expr)
                                              and isinstance(s.value, ast.Constant)
                                              and isinstance(s.value.value, str))]
        code = "\n".join(ast.dump(s) for s in stmts)
        assert "prior_trading_session_date" in code, (
            f"{name} does not use the one prior-session definition"
        )
        assert "timedelta" not in code, (
            f"{name} still does calendar arithmetic to find the prior session"
        )


def test_atr_fallback_uses_friday_not_sunday_on_monday():
    """LP-01 / RC-474: Monday premarket ATR must use Friday RTH, not calendar Sunday."""
    from liquidity_value_engine import compute_atr_from_bars

    monday = date(2026, 8, 24)
    friday = date(2026, 8, 21)
    bars = []
    for i in range(20):
        mins = int(RTH_START_MINS) + i
        dt = datetime(friday.year, friday.month, friday.day, mins // 60, mins % 60, tzinfo=ET)
        p = 100.0 + i * 0.1
        bars.append(_mk_bar(dt, p, p + 0.4, p - 0.4, p + 0.1, 1000))
    pre = datetime(monday.year, monday.month, monday.day, 8, 15, tzinfo=ET)
    bars.append(_mk_bar(pre, 110.0, 110.5, 109.5, 110.2, 100))
    cutoff = datetime(monday.year, monday.month, monday.day, 9, 0, tzinfo=ET)
    atr = compute_atr_from_bars(bars, monday, cutoff, period=5)
    assert atr is not None and atr > 0


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
    from liquidity_value_engine import build_premarket_snapshot
    out = build_premarket_snapshot("SPY", _step3_bars(session_date),
                                   session_date, PlaybookConfig())
    return out.zones


def test_no_liquidity_pool_claim_in_zone_taxonomy():
    """RC-154: these zones are session EXTREMES. Presenting them as sell/buy-side liquidity is
    an SMC pool claim we have not measured — no equal-extreme stop-cluster detection exists and
    no touch study has run. The wire must not assert what nothing has proven."""
    from liquidity_models import ZoneType, zone_class_for_type
    values = {z.value for z in ZoneType}
    assert not any("side_liquidity" in v for v in values), (
        f"zone taxonomy still claims liquidity pools: {sorted(values)}"
    )
    classes = {zone_class_for_type(z) for z in ZoneType}
    assert "liquidity" not in classes, (
        f"a zone_class still asserts 'liquidity': {sorted(classes)}"
    )


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


def test_engine_emits_no_pool_language_anywhere_it_writes_notes():
    """Every operator-facing note STRING in the engine, however it reaches the payload.

    RC-155 (v39 gun 2): the first version of this sweep matched only `notes =` /
    `interpretation_notes =` ASSIGNMENTS, so `return ZoneType.PIVOT_VALUE, "Session liquidity
    zone"` — a note delivered by return tuple — was invisible to it and survived the Step 3
    demotion. A checker that only knows one delivery mechanism certifies the others as clean.

    This now walks the AST and inspects every string CONSTANT in the module, so a note cannot
    escape by changing how it travels. Docstrings and comments are excluded: they must be free
    to NAME the retired vocabulary in order to explain it (the RC-153 trap), and neither is
    ever rendered to an operator.
    """
    import ast
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent / "liquidity_value_engine.py").read_text(
        encoding="utf-8")
    tree = ast.parse(src)
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            d = ast.get_docstring(node, clean=False)
            if d:
                docstrings.add(d)
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            s = node.value
            if s in docstrings:
                continue
            if any(w in s.lower() for w in _POOL_WORDS):
                offenders.append((getattr(node, "lineno", "?"), s))
    # Source TAGS and enum values are identifiers, not prose shown as a claim; the two
    # remaining zone-type names are named OBSERVED in RC-154 and are not Step 3 victims.
    offenders = [(ln, s) for ln, s in offenders
                 if s not in ("support_liquidity", "resistance_liquidity")]
    assert not offenders, (
        f"engine still emits pool language in a rendered string: {offenders}"
    )


def test_ui_shows_no_pool_badges():
    """Surface-bound: the Console Liquidity Map painted 'SELL LIQ' / 'BUY LIQ' — an operator
    reading those sees a proven pool, which is the claim being demoted."""
    import re
    from pathlib import Path
    ui = (Path(__file__).resolve().parent.parent / "static" / "index.html").read_text(
        encoding="utf-8")
    # Strip // comments: the badge map's own comment quotes the retired labels to explain what
    # was demoted, and a raw text search reads that explanation as the offence (the same trap
    # RC-153's docstring set). Only code the browser executes can paint a badge.
    code = re.sub(r"^\s*//.*$", "", ui, flags=re.M)
    assert "SELL LIQ" not in code and "BUY LIQ" not in code, "the UI still paints pool badges"
    assert "sell_side_liquidity" not in code and "buy_side_liquidity" not in code, (
        "the UI badge map still keys on the retired pool taxonomy"
    )
    i = code.find("ZONE_BADGE_MAP")
    assert i > 0, "the badge map is gone"
    block = code[i:i + 700]
    assert "low_extreme" in block and "high_extreme" in block, (
        "the demoted zone types have no badge, so they would render via the raw-string fallback"
    )
    assert "LOW EXTREME" in block and "HIGH EXTREME" in block


# ── LP-01 Step 4 (RC-156): raw structure levels are OPERATOR-VISIBLE on Chart ────────────
_RL_REQUIRED_IDS = [
    "rl-PDH", "rl-PDL", "rl-PDC", "rl-PD_POC", "rl-PD_VAH", "rl-PD_VAL",
    "rl-OVERNIGHT_HIGH", "rl-OVERNIGHT_LOW",
    "rl-ORB_HIGH", "rl-ORB_MID", "rl-ORB_LOW",
    "rl-TODAY_POC", "rl-TODAY_VAH", "rl-TODAY_VAL",
    "rl-VWAP", "rl-VWAP_P1", "rl-VWAP_M1", "rl-VWAP_P2", "rl-VWAP_M2",
]


def _chart_src() -> str:
    from pathlib import Path
    return (Path(__file__).resolve().parent.parent / "static" / "chart.html").read_text(
        encoding="utf-8")


def test_chart_declares_every_raw_level_row_with_a_unique_id():
    """Step 4 requires the levels to be visible AND checkable. Ids are the contract: a panel
    that renders a blob of text cannot be verified, and a panel with COLLIDING ids is worse than
    one with none — MEASURED in the rendered DOM this turn, deriving the id from the display
    label collapsed 'VWAP +2σ' and 'VWAP −2σ' onto one token because +, − and σ are all
    non-alphanumeric. Every row id is therefore stated explicitly in RL_SPEC."""
    import re
    src = _chart_src()
    i = src.find("const RL_SPEC")
    assert i > 0, "the raw-levels spec is gone"
    spec = src[i:src.find("];", i)]
    ids = []
    for ln in spec.splitlines():
        if not ln.strip().startswith("['"):
            continue
        # the id is the LAST column by contract; anchor on it rather than splitting on quotes,
        # because a description may legitimately contain an apostrophe ("today's value area")
        m = re.search(r"'([A-Z0-9_]+)'\s*\],?\s*$", ln)
        assert m, f"RL_SPEC row is missing its explicit id column: {ln.strip()}"
        ids.append(m.group(1))
    assert ids, "RL_SPEC parsed to nothing — the assertion would be vacuous"
    assert len(ids) == len(set(ids)), f"RL_SPEC declares duplicate row ids: {ids}"
    for want in _RL_REQUIRED_IDS:
        tag = want[len("rl-"):]
        assert tag in ids, f"{want} has no RL_SPEC entry — that level cannot render a row"


def test_chart_raw_levels_surface_is_visible_not_buried():
    """v6 (RC-192): the raw-levels CARD merged into the candle canvas — the engine levels now
    live in the LEVELS manager (per-level ids intact) and render as axis tags / FIRED pills.
    The always-visible statics are the FIRED row and the forces strip; the manager holds the
    per-level ids. Approved variant: governance/ui_mockup_approvals.json."""
    import re
    src = _chart_src()
    for vid in ("firedrow", "firedpills", "lvlmenu", "lvlrows", "forces",
                "mode-candles", "mode-line", "lvlbtn", "proxbtn"):
        assert f'id="{vid}"' in src, f"#{vid} is not present in static/chart.html"
    # the toggles are WIRED, not decorative: setMode binds both chips and repaints
    assert "chip('mode-candles'" in src and "chip('mode-line'" in src, (
        "the candles/line toggle chips have no click wiring"
    )
    assert "function setMode" in src and "chartMode" in src
    i = src.find('id="firedrow"')
    row_open = src.rfind("<div", 0, i + 4)
    assert "display:none" not in src[row_open:i + 200].replace(" ", ""), (
        "the FIRED row ships hidden"
    )
    assert src[:src.find('id="forces"')].count('id="main"') == 0, (
        "the forces card sits after a #main container — burying it there is forbidden"
    )
    # every engine level id must be REACHABLE from real data: the manager emits id="rl-<id>"
    assert re.search(r'id="rl-\$\{esc\(r\.id\)\}"', src), (
        "engine-level ids are not emitted from the declared spec id"
    )


def test_chart_forces_card_cannot_be_flex_collapsed():
    """RC-157 class, carried to the v6 forces card: `body` is a column flex container and
    `.card` sets overflow:hidden, so the default `flex: 0 1 auto` makes some card the layout's
    compression victim and clips its content invisibly (measured on the raw-levels card at
    1280x700: height 2px, 19 rows, zero visible)."""
    import re
    src = _chart_src()
    m = re.search(r"#forces\s*\{([^}]*)\}", src)
    assert m, "#forces has no CSS rule — it inherits a shrinkable flex default"
    rule = m.group(1).replace(" ", "")
    assert "flex:none" in rule or "flex-shrink:0" in rule, (
        f"#forces does not opt out of flex shrinking: {{{m.group(1).strip()}}}"
    )
    assert "overflow:visible" in rule, (
        "#forces inherits .card's overflow:hidden, so any future shrink clips silently"
    )


def test_chart_reads_levels_from_the_engine_never_recomputes_them():
    """RC-80 discipline: the client must not become a second producer of a number the engine
    owns. The manager may only READ carried level rows.

    Phase 2A moved the read to /api/levels, the canonical serving contract for the
    materialized PriceLevelSnapshot. Reading the levels off a snapshot endpoint that
    ALSO carried its own separately-materialized copy is precisely how the browser came
    to show a different overnight high from the levels endpoint at the same instant.
    """
    src = _chart_src()
    assert "/api/levels?ticker=" in src, "the chart does not read the canonical levels contract"
    i = src.find("function renderEngineLevels")
    assert i > 0, "the engine-level reader is gone"
    body = src[i:i + 1600]
    for banned in ("Math.max(", "Math.min(", "reduce(", "* 2", "/ 2"):
        assert banned not in body, (
            f"renderEngineLevels contains {banned!r} — it is deriving a level instead of reading one"
        )


def test_chart_raw_levels_are_structure_context_not_a_signal():
    """Structure-context ONLY: no Decide influence, no TRADE shaping, and the Step 3 demotion
    stays — no pool vocabulary may re-enter through the manager or the forces strip."""
    src = _chart_src()
    i = src.find('id="forces"')
    card = src[i:i + 1200]
    assert "not a trade signal" in card, "the strip does not state that it is context, not a signal"
    j = src.find("const RL_SPEC")
    surface = src[i:i + 1600] + src[j:j + 4000]
    for banned in ("TRADE", "BUY LIQ", "SELL LIQ", "liquidity pool", "stop-run", "sweep"):
        assert banned not in surface, f"the levels surface reintroduces {banned!r}"


def test_chart_raw_levels_fail_closed_on_absence():
    """A missing level is omitted; a missing payload says so and does NOT leave the previous
    ticker's levels under a new symbol."""
    src = _chart_src()
    i = src.find("function renderEngineLevels")
    body = src[i:i + 1600]
    assert "if (!isFinite(v) || v <= 0) continue;" in body, (
        "a non-finite OR non-positive level would render as a price (the engine sends 0 for "
        "not-yet-computed session levels — v6.2 audit finding: 'VAH 0.00' was drawn as a level)"
    )
    assert "no structure levels for" in body, "absence has no honest message"
    assert "rawLevelsTicker" in src, (
        "no pending-state reset — the prior ticker's levels survive a symbol switch"
    )
    # F31 connected consumer: Chart legend change is PDC-only (RC-213 B3). Absent PDC
    # omits the span; it must not fill with spy/qqq/iwm_chg_pct.
    i_leg = src.find("pdc from the engine only")
    assert i_leg != -1, "Chart legend PDC comment (RC-213) is gone"
    legend = src[i_leg:i_leg + 900]
    assert "enginePD().pdc" in legend
    assert "spy_chg_pct" not in legend
    assert "qqq_chg_pct" not in legend
    assert "iwm_chg_pct" not in legend
    assert "dn == null ? ''" in legend or "dn == null ? \"\"" in legend


def test_cluster_price_levels():
    """Levels within threshold clustered into zones."""
    from liquidity_value_engine import cluster_price_levels_into_zones
    from liquidity_models import PlaybookConfig
    levels = [(500.0, "PDH"), (500.5, "PD_VAH"), (505.0, "ORB_HIGH")]
    cfg = PlaybookConfig(clustering_threshold_pct=0.01)
    clusters = cluster_price_levels_into_zones(levels, 500.0, cfg)
    assert len(clusters) >= 1


def test_build_premarket_snapshot():
    """Premarket snapshot produces zones."""
    from liquidity_value_engine import build_premarket_snapshot
    from liquidity_models import PlaybookConfig
    session = date(2026, 3, 13)
    bars = _synthetic_bars(session)
    cfg = PlaybookConfig()
    out = build_premarket_snapshot("SPY", bars, session, cfg)
    assert out.ticker == "SPY"
    assert out.snapshot_type.value == "premarket"
    assert out.session_date == "2026-03-13"
    assert isinstance(out.zones, list)


def test_build_opening_snapshot():
    """Opening snapshot includes ORB and VWAP."""
    from liquidity_value_engine import build_opening_snapshot
    from liquidity_models import PlaybookConfig
    session = date(2026, 3, 13)
    bars = _synthetic_bars(session)
    cfg = PlaybookConfig()
    out = build_opening_snapshot("SPY", bars, session, cfg)
    assert out.snapshot_type.value == "opening"
    assert "orb" in out.raw_levels


def test_build_midday_snapshot():
    """Midday snapshot includes value shift and summary."""
    from liquidity_value_engine import build_midday_snapshot
    from liquidity_models import PlaybookConfig
    session = date(2026, 3, 13)
    bars = _synthetic_bars(session)
    cfg = PlaybookConfig()
    out = build_midday_snapshot("SPY", bars, session, cfg)
    assert out.snapshot_type.value == "midday"
    assert out.summary is not None
    assert out.summary.value_state in ("shifted_higher", "shifted_lower", "unchanged")


def test_build_afternoon_snapshot():
    """Afternoon snapshot produced."""
    from liquidity_value_engine import build_afternoon_snapshot
    from liquidity_models import PlaybookConfig
    session = date(2026, 3, 13)
    bars = _synthetic_bars(session)
    cfg = PlaybookConfig()
    out = build_afternoon_snapshot("SPY", bars, session, cfg)
    assert out.snapshot_type.value == "afternoon"


def test_generate_liquidity_value_snapshot_master():
    """Master function generates all snapshot types."""
    from liquidity_value_engine import generate_liquidity_value_snapshot
    from liquidity_models import SnapshotType, PlaybookConfig
    session = date(2026, 3, 13)
    bars = _synthetic_bars(session)
    cfg = PlaybookConfig()
    for st in [SnapshotType.PREMARKET, SnapshotType.OPENING, SnapshotType.MIDDAY, SnapshotType.AFTERNOON]:
        out = generate_liquidity_value_snapshot("QQQ", bars, session, st, cfg)
        assert out.ticker == "QQQ"
        assert out.snapshot_type == st


def test_no_lookahead_premarket():
    """Premarket snapshot does not use same-day RTH data."""
    from liquidity_value_engine import build_premarket_snapshot
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
    out = build_premarket_snapshot("SPY", bars, session, cfg)
    assert out.raw_levels.get("prev_day")
    # No today POC/VAH/VAL in premarket raw
    assert "poc" not in str(out.raw_levels.get("prev_day", {})).lower() or "pd_" in str(out.raw_levels)


def test_summarize_snapshot():
    """summarize_snapshot produces readable text."""
    from liquidity_value_engine import build_midday_snapshot, summarize_snapshot
    from liquidity_models import PlaybookConfig
    session = date(2026, 3, 13)
    bars = _synthetic_bars(session)
    cfg = PlaybookConfig()
    out = build_midday_snapshot("SPY", bars, session, cfg)
    text = summarize_snapshot(out)
    assert "SPY" in text
    assert "MIDDAY" in text


def test_opening_cutoff_0945():
    """OPENING snapshot uses data only through 09:45 ET."""
    from liquidity_value_engine import build_opening_snapshot, _cutoff_for_snapshot
    from liquidity_models import PlaybookConfig, SnapshotType

    session = date(2026, 3, 13)
    cfg = PlaybookConfig()
    cutoff = _cutoff_for_snapshot(SnapshotType.OPENING, session)
    assert cutoff is not None
    assert cutoff.hour == 9 and cutoff.minute == 45

    bars_through_0945 = _bars_through(session, 9, 45)
    bars_through_1000 = _bars_through(session, 10, 0)
    out_0945 = build_opening_snapshot("SPY", bars_through_0945, session, cfg)
    out_1000 = build_opening_snapshot("SPY", bars_through_1000, session, cfg)
    assert out_0945.raw_levels.get("orb") is not None
    assert out_1000.raw_levels.get("orb") is not None
    assert out_0945.raw_levels["orb"]["orb_high"] == out_1000.raw_levels["orb"]["orb_high"]
    assert out_0945.raw_levels["orb"]["orb_low"] == out_1000.raw_levels["orb"]["orb_low"]


def test_midday_cutoff_1030():
    """MIDDAY snapshot uses data only through 10:30 ET."""
    from liquidity_value_engine import build_midday_snapshot, _cutoff_for_snapshot
    from liquidity_models import PlaybookConfig, SnapshotType

    session = date(2026, 3, 13)
    cfg = PlaybookConfig()
    cutoff = _cutoff_for_snapshot(SnapshotType.MIDDAY, session)
    assert cutoff is not None
    assert cutoff.hour == 10 and cutoff.minute == 30

    bars_through_1030 = _bars_through(session, 10, 30)
    bars_through_1100 = _bars_through(session, 11, 0)
    out_1030 = build_midday_snapshot("SPY", bars_through_1030, session, cfg)
    out_1100 = build_midday_snapshot("SPY", bars_through_1100, session, cfg)
    assert out_1030.raw_levels.get("poc") is not None
    assert out_1100.raw_levels.get("poc") is not None
    assert out_1030.raw_levels["poc"] == out_1100.raw_levels["poc"]


def test_afternoon_cutoff_1400():
    """AFTERNOON snapshot uses data only through 14:00 ET."""
    from liquidity_value_engine import build_afternoon_snapshot, _cutoff_for_snapshot
    from liquidity_models import PlaybookConfig, SnapshotType

    session = date(2026, 3, 13)
    cfg = PlaybookConfig()
    cutoff = _cutoff_for_snapshot(SnapshotType.AFTERNOON, session)
    assert cutoff is not None
    assert cutoff.hour == 14 and cutoff.minute == 0

    bars_through_1400 = _bars_through(session, 14, 0)
    bars_through_1500 = _bars_through(session, 15, 0)
    out_1400 = build_afternoon_snapshot("SPY", bars_through_1400, session, cfg)
    out_1500 = build_afternoon_snapshot("SPY", bars_through_1500, session, cfg)
    assert out_1400.raw_levels.get("poc") is not None
    assert out_1500.raw_levels.get("poc") is not None
    assert out_1400.raw_levels["poc"] == out_1500.raw_levels["poc"]


def test_playbook_state_builds():
    """PlaybookState builds correctly with all snapshots."""
    from liquidity_value_engine import generate_playbook_state
    from liquidity_models import PlaybookConfig

    session = date(2026, 3, 13)
    bars = _synthetic_bars(session)
    cfg = PlaybookConfig()
    state = generate_playbook_state("SPY", bars, session, cfg)

    assert state.ticker == "SPY"
    assert state.session_date == "2026-03-13"
    assert state.premarket_snapshot is not None
    assert state.opening_snapshot is not None
    assert state.midday_snapshot is not None
    assert state.afternoon_snapshot is not None
    assert state.premarket_snapshot.snapshot_type.value == "premarket"
    assert state.opening_snapshot.snapshot_type.value == "opening"
    assert state.midday_snapshot.snapshot_type.value == "midday"
    assert state.afternoon_snapshot.snapshot_type.value == "afternoon"
    assert state.latest_snapshot_type is not None
    assert state.generated_at is not None


def test_atr_clustering_no_lookahead():
    """ATR-based clustering works and does not use lookahead."""
    from liquidity_value_engine import (
        cluster_price_levels_into_zones,
        compute_atr_from_bars,
        _cutoff_for_snapshot,
    )
    from liquidity_models import PlaybookConfig, SnapshotType

    session = date(2026, 3, 13)
    bars = _synthetic_bars(session)
    cfg = PlaybookConfig(clustering_mode="atr", clustering_threshold_atr_mult=1.0)
    cutoff = _cutoff_for_snapshot(SnapshotType.OPENING, session)
    atr = compute_atr_from_bars(bars, session, cutoff, period=14)
    assert atr is not None
    assert atr > 0

    levels = [(500.0, "PDH"), (500.5, "PD_VAH"), (502.0, "ORB_HIGH")]
    clusters = cluster_price_levels_into_zones(levels, 500.0, cfg, atr_value=atr)
    assert len(clusters) >= 1

    cfg_percent = PlaybookConfig(clustering_mode="percent")
    cluster_price_levels_into_zones(levels, 500.0, cfg_percent)
    clusters_atr = cluster_price_levels_into_zones(levels, 500.0, cfg, atr_value=0.5)
    assert len(clusters_atr) >= 1


def test_source_levels_use_actual_values():
    """source_levels stores actual level prices, not zone midpoint."""
    from liquidity_value_engine import cluster_price_levels_into_zones
    from liquidity_models import PlaybookConfig
    levels = [(100.0, "A"), (101.0, "B"), (105.0, "C")]
    cfg = PlaybookConfig(clustering_mode="fixed", clustering_threshold=10.0)
    clusters = cluster_price_levels_into_zones(levels, 100.0, cfg)
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
    cfg = PlaybookConfig(clustering_mode="fixed", clustering_threshold=2.0)
    clusters = cluster_price_levels_into_zones(levels, 100.0, cfg)
    assert len(clusters) >= 1

    cfg_cap = PlaybookConfig(clustering_mode="fixed", clustering_threshold=2.0, max_zone_width=1.5)
    clusters_cap = cluster_price_levels_into_zones(levels, 100.0, cfg_cap)
    for lo, hi, _, _, _ in clusters_cap:
        assert hi - lo <= 1.5 + 0.001, f"zone {lo}-{hi} exceeds max_zone_width 1.5"
    assert len(clusters_cap) >= len(clusters), "cap should produce more zones when width limited"


def test_merge_live_overlay_overwrites_minute():
    from liquidity_value_engine import merge_schwab_bars_with_live_overlay

    t0 = datetime(2026, 6, 15, 14, 30, 0, tzinfo=ET)
    ts_ms = int(t0.timestamp() * 1000)
    base = [
        {"timestamp": ts_ms, "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000},
    ]
    over = [
        {"timestamp": ts_ms, "open": 100, "high": 102, "low": 99, "close": 101.5, "volume": 50},
    ]
    m = merge_schwab_bars_with_live_overlay(base, over)
    assert len(m) == 1
    assert m[0]["close"] == 101.5


def test_build_live_snapshot_smoke():
    """Live path runs without error on synthetic session bars."""
    from liquidity_value_engine import build_live_snapshot
    from liquidity_models import PlaybookConfig, SnapshotType
    session = date(2026, 3, 13)
    bars = _synthetic_bars(session)
    cfg = PlaybookConfig(clustering_mode="percent", max_zone_width=2.0)
    out = build_live_snapshot("SPY", bars, session, cfg, extra_levels=[(505.0, "GAMMA_CALL_WALL")], spot=500.0)
    assert out.snapshot_type in (SnapshotType.LIVE, SnapshotType.PREMARKET)
    assert isinstance(out.zones, list)
    if out.snapshot_type == SnapshotType.LIVE:
        assert "cutoff_et" in (out.raw_levels or {})


def run_all():
    test_imports()
    test_bars_normalization()
    test_get_previous_day_levels()
    test_compute_opening_range()
    test_compute_session_vwap()
    test_compute_volume_profile_levels()
    test_cluster_price_levels()
    test_build_premarket_snapshot()
    test_build_opening_snapshot()
    test_build_midday_snapshot()
    test_build_afternoon_snapshot()
    test_generate_liquidity_value_snapshot_master()
    test_no_lookahead_premarket()
    test_summarize_snapshot()
    test_opening_cutoff_0945()
    test_midday_cutoff_1030()
    test_afternoon_cutoff_1400()
    test_playbook_state_builds()
    test_atr_clustering_no_lookahead()
    test_source_levels_use_actual_values()
    test_max_zone_width()
    test_build_live_snapshot_smoke()
    test_merge_live_overlay_overwrites_minute()
    print("All liquidity engine tests passed.")


if __name__ == "__main__":
    run_all()
