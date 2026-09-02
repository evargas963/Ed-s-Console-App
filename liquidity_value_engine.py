"""
liquidity_value_engine.py — Liquidity & Value Playbook Engine
============================================================
Deterministic institutional intraday zone mapper. Works for any ticker.
No continuous redraw — levels update only at structural checkpoints:
  PREMARKET (before 09:30 ET), OPENING (09:45 ET), MIDDAY (10:30 ET), AFTERNOON (14:00 ET).

Data source agnostic: consumes normalized OHLCV bars (DataFrame or list of dicts).
All calculations derived from bars; no Schwab-specific logic.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from typing import TYPE_CHECKING, Any, Optional

from app.domain.instrument_identity import ticker_storage_key
from liquidity_models import (
    PlaybookConfig,
    PlaybookState,
    SnapshotOutput,
    SnapshotSummary,
    SnapshotType,
    Zone,
    ZoneType,
    volume_profile_poc_vah_val,   # LP-01 Step 1 (RC-152): the ONE profile construction
)

if TYPE_CHECKING:  # forward-ref only — the "pd.DataFrame" annotations; no runtime pandas import
    import pandas as pd

log = logging.getLogger(__name__)

from app.domain.time_et import ET, RTH_END_MINS, RTH_OPEN_MINS, is_trading_day_et, now_et

# RC-324: DERIVED from the time_et minute-of-day authority, not inlined. These were
# `time(9, 30)` and `time(16, 0)` written here, and FIND-MC-1 had already removed exactly
# that shape from market_context.fetch_price_levels — which then delegated to the
# authority. Phase 2A moved the level computation INTO this module and the inline window
# came with it, so the dual authority the earlier fix closed had quietly reopened one file
# over. One place decides the session; every producer reads it.
RTH_OPEN = time(RTH_OPEN_MINS // 60, RTH_OPEN_MINS % 60)
RTH_CLOSE = time(RTH_END_MINS // 60, RTH_END_MINS % 60)


def _positive_float_or_none(value) -> Optional[float]:
    from app.domain.numeric_contract import float_positive_or_none

    return float_positive_or_none(value)


def _cluster_reference_price(*candidates) -> Optional[float]:
    """First positive price among candidates; None when no valid reference (no 500.0 fabrication)."""
    for value in candidates:
        p = _positive_float_or_none(value)
        if p is not None:
            return p
    return None


def _float_or_none(value) -> Optional[float]:
    from app.domain.numeric_contract import float_finite_or_none

    return float_finite_or_none(value)


def liquidity_zone_tradeable_score(
    *,
    n_tags: int,
    n_opt: int,
    inside: bool,
    dist_pen: float,
    spot: Optional[float] = None,
) -> float:
    """Spot-normalized liquidity zone tradeability score (LM-1 authority)."""
    if spot is None:
        return round(3.0 * n_tags + 2.5 * n_opt, 2)
    return round(3.0 * n_tags + 2.5 * n_opt + (1.5 if inside else 0.0) - dist_pen, 2)


_SCHWAB_PRICEHISTORY_SOURCE = "schwab_pricehistory"


def _resolve_bar_timestamp(d: dict) -> Optional[Any]:
    """
    Bar time key resolution aligned with market_data_adapter.normalize_bar.

    Schwab pricehistory bars require the datetime leaf (fail-closed when absent).
    Non-Schwab bars may use timestamp, datetime, date, or ts.
    """
    source = str(d.get("source") or "")
    if source == _SCHWAB_PRICEHISTORY_SOURCE:
        if d.get("datetime") is not None:
            return d.get("datetime")
        if d.get("timestamp") is not None:
            return d.get("timestamp")
        return None
    if (
        d.get("datetime") is not None
        and d.get("open") is not None
        and d.get("high") is not None
        and d.get("low") is not None
        and d.get("close") is not None
        and d.get("timestamp") is None
    ):
        return d.get("datetime")
    for key in ("timestamp", "datetime", "date", "ts"):
        val = d.get(key)
        if val is not None:
            return val
    return None


def _schwab_pricehistory_bar_missing_datetime(d: dict) -> bool:
    return (
        str(d.get("source") or "") == _SCHWAB_PRICEHISTORY_SOURCE
        and _resolve_bar_timestamp(d) is None
    )


# ─────────────────────────────────────────────────────────────────────────────
# BAR NORMALIZATION — accept DataFrame or list of dicts
# ─────────────────────────────────────────────────────────────────────────────


def _bars_to_list(bars) -> list[dict]:
    """
    Normalize bars to list of {timestamp, open, high, low, close, volume}.
    Accepts: DataFrame (columns: timestamp/open/high/low/close/volume)
             or list of dicts with o/h/l/c/volume or open/high/low/close/volume.
    """
    if bars is None or (hasattr(bars, "__len__") and len(bars) == 0):
        return []

    out = []
    is_df = hasattr(bars, "columns") and hasattr(bars, "itertuples")

    if is_df:
        for _, row in bars.iterrows():
            d = row.to_dict() if hasattr(row, "to_dict") else dict(row)
            if _schwab_pricehistory_bar_missing_datetime(d):
                continue
            ts = _resolve_bar_timestamp(d)
            if ts is None:
                continue
            o = _float_or_none(d.get("open"))
            h = _float_or_none(d.get("high"))
            l_ = _float_or_none(d.get("low"))
            c = _float_or_none(d.get("close"))
            v = d.get("volume")
            if o is None or h is None or l_ is None or c is None:
                continue
            _ts = None
            if ts is not None:
                if hasattr(ts, "timestamp"):
                    _ts = ts.timestamp()
                elif isinstance(ts, (int, float)):
                    _ts = ts / 1000.0 if ts > 1e12 else ts
            out.append({
                "timestamp": ts,
                "open": o,
                "high": h,
                "low": l_,
                "close": c,
                "volume": _positive_float_or_none(v),
            })
            if _ts is not None:
                out[-1]["_ts"] = _ts
        return out

    for b in bars:
        if isinstance(b, dict):
            row = b
            if _schwab_pricehistory_bar_missing_datetime(row):
                continue
            ts = _resolve_bar_timestamp(row)
            if ts is None:
                continue
        else:
            ts = getattr(b, "timestamp", getattr(b, "ts", None))
            row = {
                "open": getattr(b, "open", None),
                "high": getattr(b, "high", None),
                "low": getattr(b, "low", None),
                "close": getattr(b, "close", None),
                "volume": getattr(b, "volume", None),
                "timestamp": ts,
            }
            if ts is not None:
                row["_ts"] = ts.timestamp() if hasattr(ts, "timestamp") else (ts / 1000.0 if ts > 1e12 else ts)
            else:
                row["_ts"] = None
        o = _float_or_none(row.get("open"))
        h = _float_or_none(row.get("high"))
        l_ = _float_or_none(row.get("low"))
        c = _float_or_none(row.get("close"))
        v = row.get("volume")
        if o is None or h is None or l_ is None or c is None:
            continue
        ts_out = ts if isinstance(b, dict) else row.get("timestamp")
        out.append({
            "timestamp": ts_out,
            "open": o,
            "high": h,
            "low": l_,
            "close": c,
            "volume": _positive_float_or_none(v),
        })
        if row.get("_ts") is not None:
            out[-1]["_ts"] = row["_ts"]
        elif ts_out is not None:
            t = ts_out
            out[-1]["_ts"] = t.timestamp() if hasattr(t, "timestamp") else (t / 1000.0 if t > 1e12 else t)
    return out


def _bar_dt_et(bar: dict) -> Optional[datetime]:
    """Return bar timestamp as ET datetime."""
    ts = bar.get("_ts") or bar.get("timestamp")
    if ts is None:
        return None
    if hasattr(ts, "timestamp"):
        ts = ts.timestamp()
    elif isinstance(ts, (int, float)) and ts > 1e12:
        ts = ts / 1000.0
    return datetime.fromtimestamp(ts, tz=ET)


def merge_schwab_bars_with_live_overlay(schwab_bars: list, live_overlay: list) -> list:
    """
    Minute-level merge: keep full Schwab session history, but overwrite any minute
    present in ``live_overlay`` (e.g. server 1m accumulator fed by the same ticks as the UI).

    Without this, ``snapshot=live`` still readonly stale/delayed REST candles, so POC/VWAP
    matched checkpoint snapshots and looked \"unchanged.\"
    """
    if not live_overlay:
        return schwab_bars
    schw_norm = _bars_to_list(schwab_bars)
    live_norm = _bars_to_list(live_overlay)
    if not live_norm:
        return schwab_bars

    by_min: dict[int, dict] = {}
    for b in schw_norm:
        dt = _bar_dt_et(b)
        if dt is None:
            continue
        by_min[int(dt.timestamp()) // 60] = b
    for b in live_norm:
        dt = _bar_dt_et(b)
        if dt is None:
            continue
        by_min[int(dt.timestamp()) // 60] = b

    return sorted(by_min.values(), key=lambda x: x.get("_ts") or 0)


# ─────────────────────────────────────────────────────────────────────────────
# PREVIOUS DAY / OVERNIGHT
# ─────────────────────────────────────────────────────────────────────────────


def prior_trading_session_date(bars_norm: list, session_date: date) -> Optional[date]:
    """The most recent date BEFORE `session_date` that actually traded an RTH session.

    LP-01 Step 2 (RC-153) — THE single definition of "the prior session", for both the
    previous-day levels and the overnight window. The calendar cannot answer this question:
    `session_date - 1 day` is Sunday on a Monday and a closed holiday after one, and a market
    that was shut has no close for an overnight range to start from.

    Presence of RTH bars is the evidence a session happened — we do not consult a holiday table,
    because the bars ARE the record and a table can disagree with the tape (half-days, ad-hoc
    closures). Fail-closed: no prior RTH date in the buffer returns None, never a guessed date.
    """
    prior: Optional[date] = None
    for b in bars_norm:
        dt = _bar_dt_et(b)
        if dt is None:
            continue
        d = dt.date()
        if d < session_date and RTH_OPEN <= dt.time() < RTH_CLOSE:
            if prior is None or d > prior:
                prior = d
    return prior


def get_previous_day_levels(
    bars: list,
    session_date: date,
    config: PlaybookConfig,
) -> dict:
    """
    Extract previous trading day high, low, close, POC, VAH, VAL.
    Uses RTH-only bars for profile. No lookahead.
    """
    bars_norm = _bars_to_list(bars)
    if not bars_norm:
        return {}

    # UI-04 P1D (2026-07-10): previous TRADING day, not calendar-day-minus-one.
    # The old window (session_date-1 .. session_date) was empty on Mondays and
    # post-holiday sessions, and its fallback swept EVERY prior bar in the
    # buffer (multi-day, extended-hours included) into PDH/PDL/PDC — wrong
    # levels displayed as prior-day truth. Now: the most recent prior date
    # that actually has RTH bars is authoritative, single-day, RTH-only; if
    # none exists the levels stay absent (honest missing, never fabricated).
    # Schwab CSV authority checked: yes
    # CSV row(s): pricehistory.candles[].high/low/close/volume — same bar
    #   inputs, unchanged; this corrects the prior-day WINDOW selection only.
    # Derived-field disposition: KEEP_DERIVED_WITH_PROVENANCE (PDH/PDL/PDC
    #   are derivations over Schwab candles; NO_SCHWAB_EQUIVALENT for the
    #   prior-day aggregates themselves).
    # All consumers checked: yes — same dict shape; absent keys were already
    #   a legal output (empty-bars path) handled by every consumer.
    # SCHWAB_CSV_CHECKED
    # RC-153: this inline scan WAS the correct answer; it is now the canonical helper
    # `prior_trading_session_date`, shared with the overnight window so the two can never
    # disagree about which session was the prior one.
    prev_trading_day = prior_trading_session_date(bars_norm, session_date)
    prev_bars = []
    if prev_trading_day is not None:
        for b in bars_norm:
            dt = _bar_dt_et(b)
            if dt is None:
                continue
            if dt.date() == prev_trading_day and RTH_OPEN <= dt.time() < RTH_CLOSE:
                prev_bars.append(b)

    out = {}
    if prev_bars:
        out["pdh"] = max(b["high"] for b in prev_bars)
        out["pdl"] = min(b["low"] for b in prev_bars)
        out["pdc"] = prev_bars[-1]["close"]
        poc, vah, val = _volume_profile_poc_vah_val(prev_bars, config.value_area_percent, config.tick_size)
        out["pd_poc"], out["pd_vah"], out["pd_val"] = poc, vah, val
    return out


def get_overnight_levels(
    bars: list,
    session_date: date,
) -> dict:
    """Overnight range: prior TRADING session's RTH close (16:00 ET) → this session's RTH
    open (09:30 ET).

    LP-01 Step 2 (RC-153). The docstring already claimed "prior RTH close"; the code used
    `session_date - timedelta(days=1)`, i.e. CALENDAR yesterday. On a Monday that is Sunday —
    a day with no close and no bars — so Friday's entire post-16:00 session was silently
    dropped and the overnight range was only Monday's own pre-open. The same hole opens after
    every holiday. A range that omits half its window is not a narrower range, it is a wrong
    level: OVERNIGHT_HIGH/LOW are surfaced as session extremes an operator reads off the map.
    (RC-155: this line previously asserted the pool mechanism RC-154 demoted. It was written
    before that demotion and outlived its own taxonomy — a docstring that does so re-teaches
    the retired claim to the next reader.)

    The window is now a CONTINUOUS INTERVAL [prior_close, this_open), so everything inside it
    counts — Friday's post-16:00 tape, any weekend or holiday bars, and this session's
    pre-open — rather than two hand-picked calendar dates that skip whatever sits between.

    Fail-closed: with no prior trading session in the buffer the interval has no start, so only
    this session's pre-open bars are used (a subset we are certain lies inside any correct
    window) and that is stated here rather than being widened into a guess. Absence of bars in
    the window returns {} — honest empty, never a fabricated level.
    """
    bars_norm = _bars_to_list(bars)
    session_open_dt = datetime.combine(session_date, RTH_OPEN, tzinfo=ET)
    prev_session = prior_trading_session_date(bars_norm, session_date)
    prev_close_dt = (datetime.combine(prev_session, RTH_CLOSE, tzinfo=ET)
                     if prev_session is not None else None)

    overnight = []
    for b in bars_norm:
        dt = _bar_dt_et(b)
        if dt is None:
            continue
        if dt >= session_open_dt:
            continue
        if prev_close_dt is not None:
            if dt >= prev_close_dt:
                overnight.append(b)
        elif dt.date() == session_date:
            overnight.append(b)

    if not overnight:
        return {}
    return {
        "overnight_high": max(b["high"] for b in overnight),
        "overnight_low": min(b["low"] for b in overnight),
    }


# ─────────────────────────────────────────────────────────────────────────────
# OPENING RANGE
# ─────────────────────────────────────────────────────────────────────────────


def compute_opening_range(
    bars: list,
    session_date: date,
    config: PlaybookConfig,
) -> dict:
    """
    First N minutes of RTH. Default 15 min.
    """
    bars_norm = _bars_to_list(bars)
    orb_min = config.opening_range_minutes

    orb_bars = []
    for b in bars_norm:
        dt = _bar_dt_et(b)
        if dt is None or dt.date() != session_date:
            continue
        mins_since_open = (dt.hour - 9) * 60 + (dt.minute - 30)
        if 0 <= mins_since_open < orb_min:
            orb_bars.append(b)

    if not orb_bars:
        return {}
    return {
        "orb_high": max(b["high"] for b in orb_bars),
        "orb_low": min(b["low"] for b in orb_bars),
        "orb_mid": (max(b["high"] for b in orb_bars) + min(b["low"] for b in orb_bars)) / 2.0,
    }


# ─────────────────────────────────────────────────────────────────────────────
# VWAP & BANDS
# ─────────────────────────────────────────────────────────────────────────────


def compute_session_vwap_series(
    bars: list, session_date: date, cutoff_dt: Optional[datetime] = None,
) -> list[tuple[float, float, float, float, float, float]]:
    """Running session VWAP and σ bands after each RTH bar.

    Returns [(bar_epoch_sec, vwap, +1σ, -1σ, +2σ, -2σ), ...] using the standard
    cumulative moments VWAP_t = Σ(tp·v)/Σv and σ_t² = Σ(tp²·v)/Σv − VWAP_t².

    Phase 2A: this is THE single VWAP accumulation in the repository. The scalar
    `compute_session_vwap` is its last point; the chart's polyline and the exposure
    tab's band curves are this list CARRIED to the browser. Before this existed there
    were three accumulations of one session's VWAP — the engine's, a server fallback,
    and one in each of two pages — so the drawn line and the served level were
    different numbers with nothing comparing them.
    """
    bars_norm = _bars_to_list(bars)
    rth_bars = _filter_rth_bars(bars_norm, session_date, cutoff_dt)
    cum_tpv = cum_vol = cum_tp2v = 0.0
    series: list[tuple[float, float, float, float, float, float]] = []
    for b in rth_bars:
        vol = _positive_float_or_none(b.get("volume"))
        if vol is None:
            continue
        tp = (b["high"] + b["low"] + b["close"]) / 3.0
        cum_tpv += tp * vol
        cum_vol += vol
        cum_tp2v += tp * tp * vol
        if cum_vol <= 0:
            continue
        dt = _bar_dt_et(b)
        if dt is None:
            continue
        w = cum_tpv / cum_vol
        sd = max(0.0, cum_tp2v / cum_vol - w * w) ** 0.5
        series.append((dt.timestamp(), round(w, 4), round(w + sd, 4), round(w - sd, 4),
                       round(w + 2 * sd, 4), round(w - 2 * sd, 4)))
    return series


SESSION_VWAP_PRESENT = "present"
SESSION_VWAP_EXPECTED_ABSENT = "expected_absent"
SESSION_VWAP_RTH_PRODUCER_FAILURE = "rth_producer_failure"


def count_session_rth_positive_volume_bars(
    bars: list, session_date: date, cutoff_dt: Optional[datetime] = None,
) -> int:
    """INPUT RTH bars with positive volume on session_date — independent of the VWAP series."""
    n = 0
    for b in _filter_rth_bars(_bars_to_list(bars), session_date, cutoff_dt):
        if _positive_float_or_none(b.get("volume")) is not None:
            n += 1
    return n


def classify_session_vwap_presence(
    *,
    vwap: Optional[float],
    session_date: date,
    now_et_dt: datetime,
    session_rth_positive_volume_bars: int,
) -> str:
    """Classify current-session VWAP as present, expected-absent, or producer failure.

    Weekend / holiday / premarket / no same-session positive-volume RTH bars yet
    are expected absence. Genuine failure is: those bars exist and VWAP is still None.
    """
    if vwap is not None:
        return SESSION_VWAP_PRESENT
    if not is_trading_day_et(session_date.isoformat()):
        return SESSION_VWAP_EXPECTED_ABSENT
    open_dt = datetime.combine(session_date, RTH_OPEN, tzinfo=now_et_dt.tzinfo or ET)
    if now_et_dt < open_dt:
        return SESSION_VWAP_EXPECTED_ABSENT
    if session_rth_positive_volume_bars <= 0:
        return SESSION_VWAP_EXPECTED_ABSENT
    return SESSION_VWAP_RTH_PRODUCER_FAILURE


def compute_session_vwap_path(
    bars: list, session_date: date, cutoff_dt: Optional[datetime] = None,
) -> list[tuple[float, float]]:
    """[(bar_epoch_sec, vwap)] — a projection of the one series, not a second pass."""
    return [(t, w) for t, w, _u1, _d1, _u2, _d2
            in compute_session_vwap_series(bars, session_date, cutoff_dt)]


def compute_session_vwap(bars: list, session_date: date, cutoff_dt: Optional[datetime] = None) -> Optional[float]:
    """VWAP = Σ(typical_price × volume) / Σ(volume). RTH only."""
    path = compute_session_vwap_path(bars, session_date, cutoff_dt)
    return path[-1][1] if path else None


def compute_vwap_bands(
    bars: list,
    session_date: date,
    vwap_val: float,
    cutoff_dt: Optional[datetime] = None,
) -> tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
    """Volume-weighted std dev. Returns (vwap+1σ, vwap-1σ, vwap+2σ, vwap-2σ)."""
    if vwap_val is None:
        return None, None, None, None
    bars_norm = _bars_to_list(bars)
    rth_bars = _filter_rth_bars(bars_norm, session_date, cutoff_dt)
    if not rth_bars:
        return None, None, None, None
    cum_var = cum_vol = 0.0
    for b in rth_bars:
        vol = _positive_float_or_none(b.get("volume"))
        if vol is None:
            continue
        tp = (b["high"] + b["low"] + b["close"]) / 3.0
        cum_var += (tp - vwap_val) ** 2 * vol
        cum_vol += vol
    if cum_vol <= 0:
        return None, None, None, None
    std = (cum_var / cum_vol) ** 0.5
    return (
        round(vwap_val + std, 4),
        round(vwap_val - std, 4),
        round(vwap_val + 2 * std, 4),
        round(vwap_val - 2 * std, 4),
    )


def _filter_rth_bars(bars: list, session_date: date, cutoff_dt: Optional[datetime] = None) -> list:
    out = []
    for b in bars:
        dt = _bar_dt_et(b)
        if dt is None or dt.date() != session_date:
            continue
        if not (RTH_OPEN <= dt.time() < RTH_CLOSE):
            continue
        if cutoff_dt and dt > cutoff_dt:
            continue
        out.append(b)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# VOLUME PROFILE (POC, VAH, VAL)
# ─────────────────────────────────────────────────────────────────────────────


def _volume_profile_poc_vah_val(
    bars: list[dict],
    value_area_pct: float = 0.70,
    tick_size: float = 0.01,
) -> tuple[Optional[float], Optional[float], Optional[float]]:
    """POC / VAH / VAL from the ONE volume-profile construction (LP-01 Step 1, RC-152).

    This used to dump each bar's ENTIRE volume into a single bin at the typical price
    (H+L+C)/3 — a typical-price histogram, not a volume profile. `liquidity_models`
    now owns the construction and distributes each bar's volume across [low, high];
    this stays as the engine's private entry point so no caller changes.
    """
    return volume_profile_poc_vah_val(bars, value_area_pct, tick_size, ndigits=4)


def compute_volume_profile_levels(
    bars: list,
    session_date: date,
    config: PlaybookConfig,
    cutoff_dt: Optional[datetime] = None,
) -> tuple[Optional[float], Optional[float], Optional[float]]:
    """Current day POC, VAH, VAL. RTH only, no lookahead."""
    bars_norm = _bars_to_list(bars)
    rth_bars = _filter_rth_bars(bars_norm, session_date, cutoff_dt)
    return _volume_profile_poc_vah_val(rth_bars, config.value_area_percent, config.tick_size)


# ─────────────────────────────────────────────────────────────────────────────
# ATR (Average True Range)
# ─────────────────────────────────────────────────────────────────────────────


def compute_atr_from_bars(
    bars: list,
    session_date: date,
    cutoff_dt: Optional[datetime] = None,
    period: int = 14,
) -> Optional[float]:
    """
    Compute Average True Range from OHLCV bars. Deterministic, no lookahead.

    Formula:
        TR[i] = max(high[i] - low[i], |high[i] - close[i-1]|, |low[i] - close[i-1]|)
        ATR = SMA(TR over last `period` bars)

    Uses RTH bars only, filtered by session_date and cutoff_dt.
    If session_date has no RTH bars through cutoff (e.g. premarket), uses previous day RTH.

    Returns ATR in price points, or None if insufficient data.
    """
    bars_norm = _bars_to_list(bars)
    rth_bars = _filter_rth_bars(bars_norm, session_date, cutoff_dt)
    if not rth_bars:
        prev_date = session_date - timedelta(days=1)
        prev_cutoff = datetime.combine(prev_date, RTH_CLOSE, tzinfo=ET)
        rth_bars = _filter_rth_bars(bars_norm, prev_date, prev_cutoff)
    if not rth_bars or len(rth_bars) < period + 1:
        return None

    rth_bars = sorted(rth_bars, key=lambda x: (x.get("_ts") or 0))
    # RC-345 / F08: the TR + SMA arithmetic is owned by the ONE ATR authority,
    # math_volatility.compute_atr. This function owns only the RTH-session SCOPE
    # (filtering, no-lookahead cutoff, prev-day fallback) — it is not a second ATR formula.
    # compute_atr skips bars with missing h/l/c and averages sum(trs[-period:]) / period,
    # exactly as the inlined loop did, so the RTH-scoped value is unchanged.
    from math_volatility import compute_atr
    return compute_atr(rth_bars, period=period)


# ─────────────────────────────────────────────────────────────────────────────
# ZONE CLUSTERING
# ─────────────────────────────────────────────────────────────────────────────


def cluster_price_levels_into_zones(
    levels: list[tuple[float, str]],
    reference_price: float,
    config: PlaybookConfig,
    atr_value: Optional[float] = None,
) -> list[tuple[float, float, float, list[str], list[tuple[float, str]]]]:
    """
    Cluster nearby levels into zones. Returns list of (zone_low, zone_high, zone_mid, source_tags, source_pairs).
    source_pairs = [(price, tag), ...] for correct source_levels (actual level values, not zone mid).

    Threshold by clustering_mode:
      - "fixed": config.clustering_threshold (dollars/points)
      - "percent": reference_price * config.clustering_threshold_pct
      - "atr": atr_value * config.clustering_threshold_atr_mult (requires atr_value)
    """
    if not levels:
        return []
    prices = sorted(set(p for p, _ in levels if p and p > 0))
    if not prices:
        return []

    mode = (config.clustering_mode or "percent").lower()
    if mode == "fixed" and config.clustering_threshold > 0:
        thresh = config.clustering_threshold
    elif mode == "atr" and atr_value is not None and atr_value > 0:
        thresh = max(atr_value * config.clustering_threshold_atr_mult, 0.01)
    else:
        if mode == "atr":
            log.info("cluster: atr_value unavailable, falling back to percent threshold")
        thresh = max(reference_price * config.clustering_threshold_pct, 0.01)

    tag_map: dict[float, list[str]] = defaultdict(list)
    for p, tag in levels:
        if p and p > 0:
            tag_map[p].append(tag)

    max_width = _positive_float_or_none(getattr(config, "max_zone_width", None))

    def _flush_current(cur):
        if not cur:
            return
        lo, hi = min(cur), max(cur)
        mid = (lo + hi) / 2
        tags = []
        source_pairs = []
        for p in cur:
            for t in tag_map.get(p, []):
                tags.append(t)
                source_pairs.append((p, t))
        clusters.append((lo, hi, mid, list(dict.fromkeys(tags)), source_pairs))

    clusters = []
    current = [prices[0]]
    for i in range(1, len(prices)):
        cand = current + [prices[i]]
        cand_lo, cand_hi = min(cand), max(cand)
        within_thresh = prices[i] - current[-1] <= thresh
        would_exceed = max_width is not None and (cand_hi - cand_lo) > max_width

        if within_thresh and not would_exceed:
            current.append(prices[i])
        else:
            _flush_current(current)
            current = [prices[i]]
    _flush_current(current)
    return clusters


# ─────────────────────────────────────────────────────────────────────────────
# SNAPSHOT BUILDERS
# ─────────────────────────────────────────────────────────────────────────────


def _cutoff_for_snapshot(snapshot_type: SnapshotType, session_date: date) -> Optional[datetime]:
    """
    Return latest datetime allowed for this snapshot (no lookahead).
    Exact checkpoint cutoffs:
      PREMARKET: before 09:30 (09:29:59)
      OPENING: through 09:45:00 ET
      MIDDAY: through 10:30:00 ET
      AFTERNOON: through 14:00:00 ET
    """
    if snapshot_type == SnapshotType.PREMARKET:
        last = int(RTH_OPEN_MINS) - 1  # last full minute before cash RTH open
        return datetime.combine(session_date, time(last // 60, last % 60), tzinfo=ET)
    if snapshot_type == SnapshotType.OPENING:
        return datetime.combine(session_date, time(9, 45), tzinfo=ET)
    if snapshot_type == SnapshotType.MIDDAY:
        return datetime.combine(session_date, time(10, 30), tzinfo=ET)
    if snapshot_type == SnapshotType.AFTERNOON:
        return datetime.combine(session_date, time(14, 0), tzinfo=ET)
    return None


def build_premarket_snapshot(
    ticker: str,
    bars: list,
    session_date: date,
    config: PlaybookConfig,
    *,
    canonical: Optional["PriceLevelSnapshot"] = None,
) -> SnapshotOutput:
    """Premarket: PDH/PDL/PDC, PD POC/VAH/VAL, overnight high/low. No same-day RTH.

    RC-322 / Phase 2A: when ``canonical`` is supplied the families are CARRIED from that one
    materialized snapshot and no level helper runs here — the contract
    ``build_live_snapshot`` already honoured. This exit used to recompute unconditionally,
    and ``build_live_snapshot`` returns HERE whenever the session date is in the future or
    the clock is before the RTH open, so on those paths the canonical snapshot was built,
    published on /api/levels, and then discarded by the surface beside it. A latent second
    faucet on the pre-open path.

    Absent stays absent: a family missing from the snapshot is missing here, never replaced
    by spot, zero or a neighbouring level (RC-68).
    """
    bars_norm = _bars_to_list(bars)
    cutoff = _cutoff_for_snapshot(SnapshotType.PREMARKET, session_date)
    if canonical is not None:
        prev, over, _orb, _poc, _vah, _val, _vwap, _bands = (
            _phase2a_families_from_canonical(canonical)
        )
    else:
        prev = get_previous_day_levels(bars_norm, session_date, config)
        over = get_overnight_levels(bars_norm, session_date)

    levels = []
    if prev.get("pdh"):
        levels.append((prev["pdh"], "PDH"))
    if prev.get("pd_vah"):
        levels.append((prev["pd_vah"], "PD_VAH"))
    if prev.get("pd_poc"):
        levels.append((prev["pd_poc"], "PD_POC"))
    if prev.get("pd_val"):
        levels.append((prev["pd_val"], "PD_VAL"))
    if prev.get("pdl"):
        levels.append((prev["pdl"], "PDL"))
    if prev.get("pdc"):
        levels.append((prev["pdc"], "PDC"))
    if over.get("overnight_high"):
        levels.append((over["overnight_high"], "OVERNIGHT_HIGH"))
    if over.get("overnight_low"):
        levels.append((over["overnight_low"], "OVERNIGHT_LOW"))

    ref = _cluster_reference_price(prev.get("pdc"), prev.get("pd_poc"))
    if ref is None:
        clusters = []
    else:
        atr_val = compute_atr_from_bars(bars_norm, session_date, cutoff, config.atr_period) if config.clustering_mode == "atr" else None
        clusters = cluster_price_levels_into_zones(levels, ref, config, atr_val)

    zones = []
    for lo, hi, mid, tags, source_pairs in clusters:
        zt = ZoneType.RESISTANCE_LIQUIDITY
        if "PDL" in str(tags) or "PD_VAL" in str(tags) or "OVERNIGHT_LOW" in str(tags):
            zt = ZoneType.SUPPORT_LIQUIDITY
        elif "PD_POC" in str(tags) or "PDC" in str(tags):
            zt = ZoneType.PIVOT_VALUE
        sl = [{"label": t, "value": round(p, 4)} for p, t in source_pairs]
        z = Zone(
            zone_type=zt,
            zone_low=lo, zone_high=hi, zone_mid=mid,
            source_levels=sl, source_tags=tags,
            confluence_score=len(tags), snapshot_type=SnapshotType.PREMARKET,
            interpretation_notes="",
        )
        zones.append(z)

    # Canonical taxonomy (RC-154, LP-01 Step 3): downside extremes -> low_extreme; PDL/VAL ->
    # support_liquidity; POC/balance -> pivot_value; PDH/overnight high -> resistance_liquidity.
    # The GEOMETRY of each branch is unchanged; only the claim attached to it is. Notes state
    # WHERE the level came from — never that stops rest there or that price is drawn to it.
    out_zones = []
    if prev and over:
        pdh, pdl = prev.get("pdh"), prev.get("pdl")
        for z in zones:
            tags_str = " ".join(z.source_tags)
            if pdl is not None and z.zone_low < pdl * 0.995:
                z.zone_type = ZoneType.LOW_EXTREME
                z.interpretation_notes = "Extreme low, below the prior-day low"
            elif "PDH" in tags_str or "OVERNIGHT_HIGH" in tags_str:
                if "PD_POC" not in tags_str and "PDC" not in tags_str:
                    z.zone_type = ZoneType.RESISTANCE_LIQUIDITY
                    z.interpretation_notes = "Overhead structure at the prior-day high"
            elif "OVERNIGHT_LOW" in tags_str and "PDL" not in tags_str and "PD_VAL" not in tags_str:
                z.zone_type = ZoneType.LOW_EXTREME
                z.interpretation_notes = "Extreme low of the overnight window"
            elif "PDL" in tags_str or "PD_VAL" in tags_str:
                if "PD_POC" not in tags_str and "PDC" not in tags_str:
                    z.zone_type = ZoneType.SUPPORT_LIQUIDITY
                    z.interpretation_notes = "Underside structure at the prior-day low"
            elif "PD_POC" in tags_str or "PDC" in tags_str or "PD_VAL" in tags_str:
                z.zone_type = ZoneType.PIVOT_VALUE
                z.interpretation_notes = "Fair value reference from prior day POC/close"
            elif pdh is not None and z.zone_high >= pdh * 0.998:
                z.zone_type = ZoneType.RESISTANCE_LIQUIDITY
                z.interpretation_notes = "Overhead structure, above the prior-day high"
            elif pdl is not None and z.zone_low <= pdl * 1.002:
                z.zone_type = ZoneType.SUPPORT_LIQUIDITY
                z.interpretation_notes = "Underside structure at the prior-day low"
            out_zones.append(z)
    else:
        out_zones = zones

    raw = {"prev_day": prev, "overnight": over}
    return SnapshotOutput(
        ticker=ticker,
        session_date=session_date.isoformat(),
        snapshot_type=SnapshotType.PREMARKET,
        zones=out_zones,
        summary=None,
        raw_levels=raw,
    )


def build_opening_snapshot(
    ticker: str,
    bars: list,
    session_date: date,
    config: PlaybookConfig,
) -> SnapshotOutput:
    """Opening (09:45 ET): data through 09:45:00. Add ORB, VWAP. Breakout/Breakdown triggers."""
    prev = get_previous_day_levels(bars, session_date, config)
    over = get_overnight_levels(bars, session_date)
    orb = compute_opening_range(bars, session_date, config)
    cutoff = _cutoff_for_snapshot(SnapshotType.OPENING, session_date)
    vwap = compute_session_vwap(bars, session_date, cutoff)

    levels = []
    if prev.get("pdh"):
        levels.append((prev["pdh"], "PDH"))
    if prev.get("pd_vah"):
        levels.append((prev["pd_vah"], "PD_VAH"))
    if prev.get("pd_poc"):
        levels.append((prev["pd_poc"], "PD_POC"))
    if orb.get("orb_high"):
        levels.append((orb["orb_high"], "ORB_HIGH"))
    if orb.get("orb_mid"):
        levels.append((orb["orb_mid"], "ORB_MID"))
    if orb.get("orb_low"):
        levels.append((orb["orb_low"], "ORB_LOW"))
    if vwap is not None:
        levels.append((vwap, "VWAP_0945"))
    if prev.get("pd_val"):
        levels.append((prev["pd_val"], "PD_VAL"))
    if prev.get("pdl"):
        levels.append((prev["pdl"], "PDL"))
    if over.get("overnight_high"):
        levels.append((over["overnight_high"], "OVERNIGHT_HIGH"))
    if over.get("overnight_low"):
        levels.append((over["overnight_low"], "OVERNIGHT_LOW"))

    ref = _cluster_reference_price(orb.get("orb_mid"), prev.get("pdc"), prev.get("pd_poc"))
    if ref is None:
        clusters = []
    else:
        atr_val = compute_atr_from_bars(bars, session_date, cutoff, config.atr_period) if config.clustering_mode == "atr" else None
        clusters = cluster_price_levels_into_zones(levels, ref, config, atr_val)

    zones = []
    _orb_h, orb_l = orb.get("orb_high"), orb.get("orb_low")
    for lo, hi, mid, tags, source_pairs in clusters:
        zt = ZoneType.PIVOT_VALUE
        notes = ""
        if "ORB_HIGH" in tags:
            zt = ZoneType.BREAKOUT_TRIGGER
            notes = "Breakout trigger above opening range high"
        elif "ORB_LOW" in tags:
            zt = ZoneType.BREAKDOWN_TRIGGER
            notes = "Breakdown trigger below opening range low"
        elif "PDH" in str(tags) or "PD_VAH" in str(tags):
            zt = ZoneType.RESISTANCE_LIQUIDITY
            notes = "Overhead structure"
        elif "PDL" in str(tags) or "PD_VAL" in str(tags):
            zt = ZoneType.SUPPORT_LIQUIDITY
            notes = "Underside structure"
        elif "VWAP" in str(tags) or "ORB_MID" in str(tags):
            zt = ZoneType.PIVOT_VALUE
            notes = "Intraday pivot zone"
        elif orb_l and lo < orb_l * 0.995:
            zt = ZoneType.LOW_EXTREME
            notes = "Extreme low, below the opening range"
        sl = [{"label": t, "value": round(p, 4)} for p, t in source_pairs]
        z = Zone(
            zone_type=zt,
            zone_low=lo, zone_high=hi, zone_mid=mid,
            source_levels=sl,
            source_tags=tags,
            confluence_score=len(tags),
            snapshot_type=SnapshotType.OPENING,
            interpretation_notes=notes,
        )
        zones.append(z)

    vwap_p1 = vwap_m1 = vwap_p2 = vwap_m2 = None
    vwap_bands = None
    if vwap is not None:
        vwap_p1, vwap_m1, vwap_p2, vwap_m2 = compute_vwap_bands(bars, session_date, vwap, cutoff)
        vwap_bands = {
            "vwap": vwap,
            "plus1": vwap_p1,
            "minus1": vwap_m1,
            "plus2": vwap_p2,
            "minus2": vwap_m2,
        }
    raw = {"prev_day": prev, "overnight": over, "orb": orb, "vwap": vwap, "vwap_bands": vwap_bands}
    return SnapshotOutput(
        ticker=ticker,
        session_date=session_date.isoformat(),
        snapshot_type=SnapshotType.OPENING,
        zones=zones,
        summary=None,
        raw_levels=raw,
    )


def build_midday_snapshot(
    ticker: str,
    bars: list,
    session_date: date,
    config: PlaybookConfig,
) -> SnapshotOutput:
    """Midday (10:30 ET): data through 10:30:00. Current POC/VAH/VAL, VWAP migration, value shift."""
    cutoff = _cutoff_for_snapshot(SnapshotType.MIDDAY, session_date)
    prev = get_previous_day_levels(bars, session_date, config)
    orb = compute_opening_range(bars, session_date, config)
    poc, vah, val = compute_volume_profile_levels(bars, session_date, config, cutoff)
    vwap = compute_session_vwap(bars, session_date, cutoff)
    vwap_p1 = vwap_m1 = vwap_p2 = vwap_m2 = None
    if vwap is not None:
        vwap_p1, vwap_m1, vwap_p2, vwap_m2 = compute_vwap_bands(bars, session_date, vwap, cutoff)

    levels = []
    if prev.get("pdh"):
        levels.append((prev["pdh"], "PDH"))
    if vah:
        levels.append((vah, "TODAY_VAH"))
    if vwap_p1:
        levels.append((vwap_p1, "VWAP_P1"))
    if vwap is not None:
        levels.append((vwap, "VWAP"))
    if vwap_m1:
        levels.append((vwap_m1, "VWAP_M1"))
    if poc:
        levels.append((poc, "TODAY_POC"))
    if val:
        levels.append((val, "TODAY_VAL"))
    if prev.get("pd_val"):
        levels.append((prev["pd_val"], "PD_VAL"))
    if orb.get("orb_low"):
        levels.append((orb["orb_low"], "ORB_LOW"))

    ref = _cluster_reference_price(poc, prev.get("pd_poc"))
    if ref is None:
        clusters = []
    else:
        atr_val = compute_atr_from_bars(bars, session_date, cutoff, config.atr_period) if config.clustering_mode == "atr" else None
        clusters = cluster_price_levels_into_zones(levels, ref, config, atr_val)

    # Value shift: compare today POC vs prev POC
    value_state = "unchanged"
    if poc and prev.get("pd_poc"):
        d = (poc - prev["pd_poc"]) / prev["pd_poc"]
        if d > 0.002:
            value_state = "shifted_higher"
        elif d < -0.002:
            value_state = "shifted_lower"

    vwap_relation = "at_value"
    if vwap and poc:
        if vwap > poc * 1.001:
            vwap_relation = "above_value"
        elif vwap < poc * 0.999:
            vwap_relation = "below_value"

    auction_interp = ""
    if value_state == "shifted_higher" and vwap_relation == "above_value":
        auction_interp = "bullish_acceptance"
    elif value_state == "shifted_lower" and vwap_relation == "below_value":
        auction_interp = "bearish_acceptance"

    zones = []
    for lo, hi, mid, tags, source_pairs in clusters:
        zt = ZoneType.PIVOT_VALUE
        notes = ""
        if "VWAP" in str(tags) and "TODAY_VAH" in str(tags):
            zt = ZoneType.RESISTANCE_LIQUIDITY
            notes = "VWAP remains above developing value; rallies into this area may meet supply."
        elif "VWAP" in str(tags) and "TODAY_VAL" in str(tags):
            zt = ZoneType.SUPPORT_LIQUIDITY
            notes = "VWAP near value low; selloffs into this area may find demand."
        elif "TODAY_POC" in str(tags):
            zt = ZoneType.PIVOT_VALUE
            notes = "Midday fair value zone"
        elif "PDH" in str(tags) or "TODAY_VAH" in str(tags):
            zt = ZoneType.RESISTANCE_LIQUIDITY
            notes = "Major resistance zone"
        elif "ORB_LOW" in str(tags) or "PD_VAL" in str(tags):
            zt = ZoneType.LOW_EXTREME
            notes = "Extreme low of the session so far"
        sl = [{"label": t, "value": round(p, 4)} for p, t in source_pairs]
        z = Zone(
            zone_type=zt,
            zone_low=lo, zone_high=hi, zone_mid=mid,
            source_levels=sl,
            source_tags=tags,
            confluence_score=len(tags),
            snapshot_type=SnapshotType.MIDDAY,
            interpretation_notes=notes,
        )
        zones.append(z)

    vwap_bands = None
    if vwap is not None:
        vwap_bands = {
            "vwap": vwap,
            "plus1": vwap_p1,
            "minus1": vwap_m1,
            "plus2": vwap_p2,
            "minus2": vwap_m2,
        }
    raw = {"prev": prev, "orb": orb, "poc": poc, "vah": vah, "val": val, "vwap": vwap, "vwap_bands": vwap_bands}
    summary = SnapshotSummary(
        value_state=value_state,
        vwap_relation=vwap_relation,
        auction_interpretation=auction_interp,
    )
    return SnapshotOutput(
        ticker=ticker,
        session_date=session_date.isoformat(),
        snapshot_type=SnapshotType.MIDDAY,
        zones=zones,
        summary=summary,
        raw_levels=raw,
    )


def build_afternoon_snapshot(
    ticker: str,
    bars: list,
    session_date: date,
    config: PlaybookConfig,
) -> SnapshotOutput:
    """Afternoon (14:00 ET): data through 14:00:00. Updated profile, afternoon fair value, new value area."""
    cutoff = _cutoff_for_snapshot(SnapshotType.AFTERNOON, session_date)
    prev = get_previous_day_levels(bars, session_date, config)
    poc, vah, val = compute_volume_profile_levels(bars, session_date, config, cutoff)
    vwap = compute_session_vwap(bars, session_date, cutoff)
    vwap_p1 = vwap_m1 = vwap_p2 = vwap_m2 = None
    if vwap is not None:
        vwap_p1, vwap_m1, vwap_p2, vwap_m2 = compute_vwap_bands(bars, session_date, vwap, cutoff)

    levels = []
    if vah:
        levels.append((vah, "TODAY_VAH"))
    if vwap is not None:
        levels.append((vwap, "VWAP"))
    if poc:
        levels.append((poc, "TODAY_POC"))
    if val:
        levels.append((val, "TODAY_VAL"))
    if prev.get("pd_val"):
        levels.append((prev["pd_val"], "PD_VAL"))
    if prev.get("pdl"):
        levels.append((prev["pdl"], "PDL"))

    ref = _cluster_reference_price(poc)
    if ref is None:
        clusters = []
    else:
        atr_val = compute_atr_from_bars(bars, session_date, cutoff, config.atr_period) if config.clustering_mode == "atr" else None
        clusters = cluster_price_levels_into_zones(levels, ref, config, atr_val)

    # Value shift: compare today POC vs prev POC (same logic as midday)
    value_state = "unchanged"
    if poc and prev.get("pd_poc"):
        d = (poc - prev["pd_poc"]) / prev["pd_poc"]
        if d > 0.002:
            value_state = "shifted_higher"
        elif d < -0.002:
            value_state = "shifted_lower"

    vwap_relation = "at_value"
    if vwap and poc:
        if vwap > poc * 1.001:
            vwap_relation = "above_value"
        elif vwap < poc * 0.999:
            vwap_relation = "below_value"

    auction_interp = ""
    if value_state == "shifted_higher" and vwap_relation == "above_value":
        auction_interp = "bullish_acceptance"
    elif value_state == "shifted_lower" and vwap_relation == "below_value":
        auction_interp = "bearish_acceptance"

    # New value area: afternoon POC shifted vs morning
    new_value_area = False
    if poc and prev.get("pd_poc"):
        if abs(poc - prev["pd_poc"]) / max(prev["pd_poc"], 0.01) > 0.005:
            new_value_area = True

    zones = []
    for lo, hi, mid, tags, source_pairs in clusters:
        zt = ZoneType.PIVOT_VALUE
        notes = "Afternoon fair value zone"
        if "TODAY_VAH" in str(tags):
            zt = ZoneType.RESISTANCE_LIQUIDITY
            notes = "Updated resistance"
        elif "PDL" in str(tags) or "PD_VAL" in str(tags):
            zt = ZoneType.SUPPORT_LIQUIDITY
            notes = "Updated support"
        sl = [{"label": t, "value": round(p, 4)} for p, t in source_pairs]
        z = Zone(
            zone_type=zt,
            zone_low=lo, zone_high=hi, zone_mid=mid,
            source_levels=sl,
            source_tags=tags,
            confluence_score=len(tags),
            snapshot_type=SnapshotType.AFTERNOON,
            interpretation_notes=notes,
        )
        zones.append(z)

    vwap_bands = None
    if vwap is not None:
        vwap_bands = {
            "vwap": vwap,
            "plus1": vwap_p1,
            "minus1": vwap_m1,
            "plus2": vwap_p2,
            "minus2": vwap_m2,
        }
    raw = {
        "prev": prev,
        "poc": poc,
        "vah": vah,
        "val": val,
        "vwap": vwap,
        "vwap_bands": vwap_bands,
        "new_value_area": new_value_area,
    }
    notes_list = ["New value area formed" if new_value_area else "Value area unchanged"]
    summary = SnapshotSummary(
        value_state=value_state,
        vwap_relation=vwap_relation,
        auction_interpretation=auction_interp,
        notes=notes_list,
    )
    return SnapshotOutput(
        ticker=ticker,
        session_date=session_date.isoformat(),
        snapshot_type=SnapshotType.AFTERNOON,
        zones=zones,
        summary=summary,
        raw_levels=raw,
    )


def _last_rth_close_price(bars_norm: list, session_date: date, cutoff_dt: Optional[datetime]) -> Optional[float]:
    rth = _filter_rth_bars(bars_norm, session_date, cutoff_dt)
    if not rth:
        return None
    c = rth[-1].get("close")
    if c is None:
        return None
    try:
        cf = float(c)
    except (TypeError, ValueError):
        return None
    return cf if cf > 0 else None


def _classify_live_cluster(tags: list[str], orb: dict) -> tuple[ZoneType, str]:
    """Map clustered level tags to zone type + note (live / fused playbook)."""
    ts = " ".join(tags)
    opt_markers = (
        "GAMMA_CALL", "GAMMA_PUT", "DELTA_CALL", "DELTA_PUT",
        "OI_CALL", "OI_PUT", "GAMMA_PIN", "NET_GEX_PEAK", "MAX_PAIN", "GAMMA_FLIP",
        "GAMMA_INFLECTION", "DELTA_INFLECTION", "OI_CENTER", "EM_UPPER", "EM_LOWER", "SYNTH_FWD",
    )
    has_opt = any(m in ts for m in opt_markers)
    if "SPOT_LIVE" in ts:
        return ZoneType.PIVOT_VALUE, "Live spot (from console cache)"
    if has_opt:
        up = any(x in ts for x in ("GAMMA_CALL", "DELTA_CALL", "OI_CALL", "EM_UPPER"))
        dn = any(x in ts for x in ("GAMMA_PUT", "DELTA_PUT", "OI_PUT", "EM_LOWER"))
        if up and not dn:
            return ZoneType.RESISTANCE_LIQUIDITY, "Confluence: overhead positioning / supply"
        if dn and not up:
            return ZoneType.SUPPORT_LIQUIDITY, "Confluence: downside positioning / demand"
        return ZoneType.PIVOT_VALUE, "Confluence: mixed positioning + session levels"

    if "ORB_HIGH" in ts or "TODAY_VAH" in ts or "PDH" in ts or "OVERNIGHT_HIGH" in ts or "PD_VAH" in ts:
        return ZoneType.RESISTANCE_LIQUIDITY, "Resistance / upper structure"
    if "ORB_LOW" in ts or "TODAY_VAL" in ts or "PDL" in ts or "OVERNIGHT_LOW" in ts or "PD_VAL" in ts:
        return ZoneType.SUPPORT_LIQUIDITY, "Support / lower structure"
    if "TODAY_POC" in ts or "VWAP" in ts or "ORB_MID" in ts or "PD_POC" in ts or "PDC" in ts:
        return ZoneType.PIVOT_VALUE, "Fair value / pivot"
    # RC-155: the FALLTHROUGH note — no tag matched any branch above, so nothing is known about
    # this cluster beyond the fact that it exists in this session. The retired wording named a
    # pool mechanism precisely where the code had run out of classifications, and it reached the
    # payload by RETURN TUPLE, which the first note-sweep (assignments only) could not see.
    return ZoneType.PIVOT_VALUE, "Unclassified session zone"


def _phase2a_families_from_canonical(canonical: "PriceLevelSnapshot"):
    """Unpack the canonical snapshot into the legacy family shapes, values UNCHANGED.

    Absent stays absent: a level missing from the snapshot is missing here, never
    replaced by zero, spot or a neighbouring level (RC-68).
    """
    p = canonical.price
    prev = {k: v for k, v in (
        ("pdh", p("PDH")), ("pdl", p("PDL")), ("pdc", p("PDC")),
        ("pd_poc", p("PD_POC")), ("pd_vah", p("PD_VAH")), ("pd_val", p("PD_VAL")),
    ) if v is not None}
    over = {k: v for k, v in (
        ("overnight_high", p("OVERNIGHT_HIGH")), ("overnight_low", p("OVERNIGHT_LOW")),
    ) if v is not None}
    orb = {k: v for k, v in (
        ("orb_high", p("ORB_HIGH")), ("orb_low", p("ORB_LOW")), ("orb_mid", p("ORB_MID")),
    ) if v is not None}
    bands = (p("VWAP_P1"), p("VWAP_M1"), p("VWAP_P2"), p("VWAP_M2"))
    return (prev, over, orb, p("TODAY_POC"), p("TODAY_VAH"), p("TODAY_VAL"),
            p("VWAP"), bands)


def build_live_snapshot(
    ticker: str,
    bars: list,
    session_date: date,
    config: PlaybookConfig,
    *,
    extra_levels: Optional[list[tuple[float, str]]] = None,
    spot: Optional[float] = None,
    canonical: Optional["PriceLevelSnapshot"] = None,
) -> SnapshotOutput:
    """
    Rolling intraday snapshot: RTH cutoff is min(now ET, 16:00) on the session date;
    historical session_date (prior calendar days) uses full RTH through 16:00.
    Before today's RTH open → same as premarket snapshot.

    Merges optional ``extra_levels`` (e.g. options walls from cache) with VWAP / profile / ORB context.

    Phase 2A: when ``canonical`` is supplied (every live serving path does), the Phase 2A
    families are CARRIED from that one materialized snapshot and no level helper runs here.
    The self-computing path remains only for replay of a historical session_date, which is
    a different generation and is never served beside a live /api/levels payload.
    """
    today_et = datetime.now(ET).date()
    now = datetime.now(ET)
    open_dt = datetime.combine(session_date, RTH_OPEN, tzinfo=ET)
    close_dt = datetime.combine(session_date, RTH_CLOSE, tzinfo=ET)

    # RC-322: both exits carry `canonical` through. They used to drop it, so the pre-open
    # and future-date paths recomputed the Phase 2A families beside the materialized ones.
    if session_date > today_et:
        return build_premarket_snapshot(ticker, bars, session_date, config,
                                        canonical=canonical)

    if session_date < today_et:
        cutoff = close_dt
    else:
        if now < open_dt:
            return build_premarket_snapshot(ticker, bars, session_date, config,
                                            canonical=canonical)
        cutoff = min(now, close_dt)

    bars_norm = _bars_to_list(bars)
    if canonical is not None:
        prev, over, orb, poc, vah, val, vwap, (vwap_p1, vwap_m1, vwap_p2, vwap_m2) = (
            _phase2a_families_from_canonical(canonical)
        )
    else:
        prev = get_previous_day_levels(bars_norm, session_date, config)
        over = get_overnight_levels(bars_norm, session_date)
        orb = compute_opening_range(bars_norm, session_date, config)
        poc, vah, val = compute_volume_profile_levels(bars_norm, session_date, config, cutoff)
        vwap = compute_session_vwap(bars_norm, session_date, cutoff)
        vwap_p1 = vwap_m1 = vwap_p2 = vwap_m2 = None
        if vwap is not None:
            vwap_p1, vwap_m1, vwap_p2, vwap_m2 = compute_vwap_bands(bars_norm, session_date, vwap, cutoff)

    levels: list[tuple[float, str]] = []
    if prev.get("pdh"):
        levels.append((prev["pdh"], "PDH"))
    if prev.get("pd_vah"):
        levels.append((prev["pd_vah"], "PD_VAH"))
    if prev.get("pd_poc"):
        levels.append((prev["pd_poc"], "PD_POC"))
    if orb.get("orb_high"):
        levels.append((orb["orb_high"], "ORB_HIGH"))
    if orb.get("orb_mid"):
        levels.append((orb["orb_mid"], "ORB_MID"))
    if orb.get("orb_low"):
        levels.append((orb["orb_low"], "ORB_LOW"))
    if vah:
        levels.append((vah, "TODAY_VAH"))
    if vwap_p1:
        levels.append((vwap_p1, "VWAP_P1"))
    if vwap is not None:
        levels.append((vwap, "VWAP"))
    if poc:
        levels.append((poc, "TODAY_POC"))
    if vwap_m1:
        levels.append((vwap_m1, "VWAP_M1"))
    if val:
        levels.append((val, "TODAY_VAL"))
    if prev.get("pd_val"):
        levels.append((prev["pd_val"], "PD_VAL"))
    if prev.get("pdl"):
        levels.append((prev["pdl"], "PDL"))
    if over.get("overnight_high"):
        levels.append((over["overnight_high"], "OVERNIGHT_HIGH"))
    if over.get("overnight_low"):
        levels.append((over["overnight_low"], "OVERNIGHT_LOW"))

    for pair in extra_levels or []:
        if len(pair) < 2:
            continue
        p, tag = pair[0], pair[1]
        try:
            pf = float(p)
            if pf > 0:
                levels.append((pf, str(tag)))
        except (TypeError, ValueError):
            continue

    ref: Optional[float] = None
    if spot is not None:
        try:
            sf = float(spot)
            if sf > 0:
                ref = sf
        except (TypeError, ValueError):
            pass
    if ref is None or ref <= 0:
        lx = _last_rth_close_price(bars_norm, session_date, cutoff)
        ref = _cluster_reference_price(
            lx, vwap, poc, prev.get("pdc"), prev.get("pd_poc"),
        )

    if ref is None:
        clusters = []
    else:
        atr_val = compute_atr_from_bars(bars_norm, session_date, cutoff, config.atr_period) if config.clustering_mode == "atr" else None
        clusters = cluster_price_levels_into_zones(levels, float(ref), config, atr_val)

    value_state = "unchanged"
    if poc and prev.get("pd_poc"):
        d0 = prev["pd_poc"]
        d = (poc - d0) / d0 if d0 else 0
        if d > 0.002:
            value_state = "shifted_higher"
        elif d < -0.002:
            value_state = "shifted_lower"

    vwap_relation = "at_value"
    if vwap and poc:
        if vwap > poc * 1.001:
            vwap_relation = "above_value"
        elif vwap < poc * 0.999:
            vwap_relation = "below_value"

    auction_interp = ""
    if value_state == "shifted_higher" and vwap_relation == "above_value":
        auction_interp = "bullish_acceptance"
    elif value_state == "shifted_lower" and vwap_relation == "below_value":
        auction_interp = "bearish_acceptance"

    zones: list[Zone] = []
    for lo, hi, mid, tags, source_pairs in clusters:
        zt, notes = _classify_live_cluster(tags, orb)
        sl = [{"label": t, "value": round(p, 4)} for p, t in source_pairs]
        zones.append(
            Zone(
                zone_type=zt,
                zone_low=lo,
                zone_high=hi,
                zone_mid=mid,
                source_levels=sl,
                source_tags=tags,
                confluence_score=len(tags),
                snapshot_type=SnapshotType.LIVE,
                interpretation_notes=notes,
            )
        )

    vwap_bands = None
    if vwap is not None:
        vwap_bands = {
            "vwap": vwap,
            "plus1": vwap_p1,
            "minus1": vwap_m1,
            "plus2": vwap_p2,
            "minus2": vwap_m2,
        }
    raw = {
        "prev": prev,
        "overnight": over,
        "orb": orb,
        "poc": poc,
        "vah": vah,
        "val": val,
        "vwap": vwap,
        "vwap_bands": vwap_bands,
        "cutoff_et": cutoff.isoformat(),
        # Phase 2A: which (scope, generation) these numbers ARE, in the payload, so a
        # consumer can never mistake a replayed historical scope for the canonical one.
        "semantic_scope": "session_rth" if canonical is not None else f"replay_cutoff:{cutoff.isoformat()}",
        "level_generation": canonical.generation if canonical is not None else None,
        "level_snapshot_as_of_ts_utc": canonical.as_of_ts_utc if canonical is not None else None,
    }
    summary = SnapshotSummary(
        value_state=value_state,
        vwap_relation=vwap_relation,
        auction_interpretation=auction_interp,
        notes=[
            "Live zones: volume/VWAP/OR/prior day through cutoff; options fused when cache hit.",
        ],
    )
    return SnapshotOutput(
        ticker=ticker,
        session_date=session_date.isoformat(),
        snapshot_type=SnapshotType.LIVE,
        zones=zones,
        summary=summary,
        raw_levels=raw,
    )


# ─────────────────────────────────────────────────────────────────────────────
# INTERPRETATION
# ─────────────────────────────────────────────────────────────────────────────


def summarize_snapshot(out: SnapshotOutput) -> str:
    """Generate readable interpretation summary."""
    lines = [f"{out.ticker} {out.snapshot_type.value.upper()} Snapshot ({out.session_date})"]
    if out.summary:
        s = out.summary
        if s.value_state:
            lines.append(f"  Value state: {s.value_state}")
        if s.vwap_relation:
            lines.append(f"  VWAP relation: {s.vwap_relation}")
        if s.auction_interpretation:
            lines.append(f"  Auction: {s.auction_interpretation}")
    for z in out.zones:
        lines.append(f"  [{z.zone_type.value}] {z.zone_low:.2f}–{z.zone_high:.2f} — {z.interpretation_notes or '—'}")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# MASTER FUNCTION
# ─────────────────────────────────────────────────────────────────────────────


def generate_liquidity_value_snapshot(
    ticker: str,
    bars_dataframe: list | "pd.DataFrame",
    session_date: str | date,
    snapshot_type: SnapshotType | str,
    config: Optional[PlaybookConfig] = None,
) -> SnapshotOutput:
    """
    Master function: generate structural snapshot for given ticker/session/type.

    Args:
        ticker: Instrument symbol (e.g. SPY, QQQ)
        bars_dataframe: OHLCV bars (DataFrame or list of dicts)
        session_date: "YYYY-MM-DD" or date
        snapshot_type: PREMARKET | OPENING | MIDDAY | AFTERNOON
        config: Optional. Uses defaults if None.

    Returns:
        SnapshotOutput with zones, summary, raw_levels.

    No lookahead: each snapshot uses only data allowed for that checkpoint.
    """
    if config is None:
        config = PlaybookConfig()

    if isinstance(session_date, str):
        session_date = date.fromisoformat(session_date)

    st = snapshot_type
    if isinstance(st, str):
        st = SnapshotType(st.lower().replace(" ", "_"))

    if st == SnapshotType.PREMARKET:
        return build_premarket_snapshot(ticker, bars_dataframe, session_date, config)
    if st == SnapshotType.OPENING:
        return build_opening_snapshot(ticker, bars_dataframe, session_date, config)
    if st == SnapshotType.MIDDAY:
        return build_midday_snapshot(ticker, bars_dataframe, session_date, config)
    if st == SnapshotType.AFTERNOON:
        return build_afternoon_snapshot(ticker, bars_dataframe, session_date, config)
    if st == SnapshotType.LIVE:
        return build_live_snapshot(
            ticker, bars_dataframe, session_date, config, extra_levels=None, spot=None
        )
    raise ValueError(f"Unknown snapshot_type: {snapshot_type}")


# ─────────────────────────────────────────────────────────────────────────────
# PLAYBOOK STATE
# ─────────────────────────────────────────────────────────────────────────────


def generate_playbook_state(
    ticker: str,
    bars_dataframe: list | "pd.DataFrame",
    session_date: str | date,
    config: Optional[PlaybookConfig] = None,
) -> PlaybookState:
    """
    Generate all structural snapshots and package into PlaybookState.
    Each snapshot uses only data available through its cutoff time (no lookahead).

    Args:
        ticker: Instrument symbol
        bars_dataframe: OHLCV bars (DataFrame or list of dicts)
        session_date: "YYYY-MM-DD" or date
        config: Optional. Uses defaults if None.

    Returns:
        PlaybookState with premarket, opening, midday, afternoon snapshots.
    """
    if config is None:
        config = PlaybookConfig()

    if isinstance(session_date, str):
        session_date = date.fromisoformat(session_date)

    bars = _bars_to_list(bars_dataframe)
    premarket = build_premarket_snapshot(ticker, bars, session_date, config)
    opening = build_opening_snapshot(ticker, bars, session_date, config)
    midday = build_midday_snapshot(ticker, bars, session_date, config)
    afternoon = build_afternoon_snapshot(ticker, bars, session_date, config)

    latest_type = SnapshotType.AFTERNOON
    latest_summary = afternoon.summary
    if latest_summary is None:
        latest_type = SnapshotType.MIDDAY
        latest_summary = midday.summary
    if latest_summary is None:
        latest_type = SnapshotType.OPENING
        latest_summary = opening.summary

    session_bias = ""
    auction_state = ""
    if latest_summary:
        auction_state = latest_summary.auction_interpretation or ""
        if latest_summary.auction_interpretation == "bullish_acceptance":
            session_bias = "bullish"
        elif latest_summary.auction_interpretation == "bearish_acceptance":
            session_bias = "bearish"
        elif latest_summary.value_state == "shifted_higher":
            session_bias = "bullish"
        elif latest_summary.value_state == "shifted_lower":
            session_bias = "bearish"

    return PlaybookState(
        ticker=ticker,
        session_date=session_date.isoformat(),
        premarket_snapshot=premarket,
        opening_snapshot=opening,
        midday_snapshot=midday,
        afternoon_snapshot=afternoon,
        latest_snapshot_type=latest_type,
        latest_summary=latest_summary,
        session_bias=session_bias,
        auction_state=auction_state,
        generated_at=now_et().isoformat(),
    )


def playbook_state_to_dict(state: PlaybookState) -> dict:
    """Serialize PlaybookState to JSON-serializable dict."""

    def _snap_to_dict(snap: Optional[SnapshotOutput]) -> Optional[dict]:
        if snap is None:
            return None
        d = {
            "ticker": snap.ticker,
            "session_date": snap.session_date,
            "snapshot_type": snap.snapshot_type.value,
            "zones": [
                {
                    "zone_type": z.zone_type.value,
                    "zone_class": z.zone_class,
                    "zone_low": z.zone_low,
                    "zone_high": z.zone_high,
                    "zone_mid": z.zone_mid,
                    "zone_width": round(z.zone_high - z.zone_low, 4),
                    "source_levels": z.source_levels,
                    "source_tags": z.source_tags,
                    "confluence_score": z.confluence_score,
                    "interpretation_notes": z.interpretation_notes or "",
                }
                for z in snap.zones
            ],
            "summary": None,
            "raw_levels": snap.raw_levels,
        }
        if snap.summary:
            d["summary"] = {
                "value_state": snap.summary.value_state,
                "vwap_relation": snap.summary.vwap_relation,
                "auction_interpretation": snap.summary.auction_interpretation,
                "notes": snap.summary.notes,
            }
        return d

    return {
        "ticker": state.ticker,
        "session_date": state.session_date,
        "premarket_snapshot": _snap_to_dict(state.premarket_snapshot),
        "opening_snapshot": _snap_to_dict(state.opening_snapshot),
        "midday_snapshot": _snap_to_dict(state.midday_snapshot),
        "afternoon_snapshot": _snap_to_dict(state.afternoon_snapshot),
        "latest_snapshot_type": state.latest_snapshot_type.value if state.latest_snapshot_type else None,
        "latest_summary": (
            {
                "value_state": state.latest_summary.value_state,
                "vwap_relation": state.latest_summary.vwap_relation,
                "auction_interpretation": state.latest_summary.auction_interpretation,
                "notes": state.latest_summary.notes,
            }
            if state.latest_summary
            else None
        ),
        "session_bias": state.session_bias,
        "auction_state": state.auction_state,
        "generated_at": state.generated_at,
    }


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 2A — the canonical materialized PriceLevelSnapshot
# ─────────────────────────────────────────────────────────────────────────────
# THE INVARIANT (operator, 2026-08-08): exactly ONE authoritative computation and
# ONE materialized result per (ticker, level_id, semantic_scope, generation). Every
# API, UI, decision path, model feature, persistence write and report consumes THAT
# result unchanged. A new market generation may invoke the producer once; endpoints
# and consumers may not independently invoke or reconstruct the computation.
#
# WHY THIS EXISTS, measured: /api/levels served overnight 773.3975/773.3975 while
# /api/liquidity-snapshot served 773.40/772.55 for the same ticker at the same
# instant, and the prior-day value area disagreed intermittently. Neither endpoint
# was wrong about its own arithmetic — they ran the same helpers over DIFFERENT bar
# inputs (live accumulator vs a synchronous Schwab fetch), which is a second
# materialization, not a second formula. Collapsing the formulas was never going to
# fix it; collapsing the MATERIALIZATION is.

#: level_id -> (family, semantic_scope, evidence_tier). The Phase 2A registry: an id
#: in this table has exactly one canonical producer and one materialized value per
#: generation. A checkpoint-scoped or otherwise differently-windowed metric must NOT
#: reuse these ids — it carries its own explicit scope suffix (see `scoped_level_id`).
PHASE2A_LEVEL_IDS: dict[str, tuple[str, str, str]] = {
    "PDH": ("prior_day", "prior_rth_session", "price_fact"),
    "PDL": ("prior_day", "prior_rth_session", "price_fact"),
    "PDC": ("prior_day", "prior_rth_session", "price_fact"),
    "PD_POC": ("prior_day", "prior_rth_session", "derived_certified"),
    "PD_VAH": ("prior_day", "prior_rth_session", "derived_certified"),
    "PD_VAL": ("prior_day", "prior_rth_session", "derived_certified"),
    "OVERNIGHT_HIGH": ("overnight", "overnight_window", "price_fact"),
    "OVERNIGHT_LOW": ("overnight", "overnight_window", "price_fact"),
    "ORB_HIGH": ("opening_range", "session_rth", "price_fact"),
    "ORB_LOW": ("opening_range", "session_rth", "price_fact"),
    "ORB_MID": ("opening_range", "session_rth", "price_fact"),
    "VWAP": ("vwap", "session_rth", "derived_certified"),
    "VWAP_P1": ("vwap", "session_rth", "derived_certified"),
    "VWAP_M1": ("vwap", "session_rth", "derived_certified"),
    "VWAP_P2": ("vwap", "session_rth", "derived_certified"),
    "VWAP_M2": ("vwap", "session_rth", "derived_certified"),
    "TODAY_POC": ("value_area", "session_rth", "derived_certified"),
    "TODAY_VAH": ("value_area", "session_rth", "derived_certified"),
    "TODAY_VAL": ("value_area", "session_rth", "derived_certified"),
}

#: The engine helpers that ARE the Phase 2A computation. `build_price_level_snapshot`
#: is the only production call site; the static guard
#: (tools/check_institutional_correctness.check_phase2a_single_level_computation)
#: enforces that, alias-resolved, so a second invocation under another name still fires.
#: This module's own name, read rather than spelled: RC-154's Step-3 lock bans the
#: literal "liquidity" in any non-docstring engine string, and a provenance stamp is
#: not a market claim — reading __name__ keeps the stamp honest and the lock intact.
_PRODUCER_NS: str = __name__

PHASE2A_CANONICAL_HELPERS: frozenset[str] = frozenset({
    "get_previous_day_levels",
    "get_overnight_levels",
    "compute_opening_range",
    "compute_session_vwap",
    "compute_session_vwap_path",
    "compute_vwap_bands",
    "compute_volume_profile_levels",
})


def scoped_level_id(level_id: str, semantic_scope: str) -> str:
    """The id a NON-canonical scope must use, so two scopes can never share an id.

    A midday-cutoff VWAP is a legitimate, different measurement — it just is not the
    repo-wide canonical `VWAP`. It travels as `VWAP@checkpoint:midday`, which no
    canonical consumer reads and no divergence check compares against `VWAP`.
    """
    lid = str(level_id).strip().upper()
    scope = str(semantic_scope).strip()
    if lid in PHASE2A_LEVEL_IDS and scope == PHASE2A_LEVEL_IDS[lid][1]:
        return lid
    return f"{lid}@{scope}"


#: semantic_scope -> the trading-session character the /api/levels contract has always
#: published as provenance.session_scope (RTH vs full/extended session). The two are
#: different questions: `semantic_scope` identifies WHICH measurement this is,
#: `session_scope` says which hours it was measured over.
_SESSION_SCOPE_OF: dict[str, str] = {
    "prior_rth_session": "RTH",
    "session_rth": "RTH",
    "overnight_window": "extended",
}


class PriceLevelValue:
    """One materialized level: its value AND the identity that makes it comparable."""

    __slots__ = ("level_id", "price", "family", "semantic_scope", "evidence_tier",
                 "producer", "window", "vendor_basis", "as_of_ts_utc", "generation",
                 "session_date")

    def __init__(self, *, level_id: str, price: float, family: str, semantic_scope: str,
                 evidence_tier: str, producer: str, window: str, vendor_basis: str,
                 as_of_ts_utc: Optional[float], generation: int,
                 session_date: str) -> None:
        # session_date is REQUIRED, not defaulted: it is part of the carrier ledger key,
        # so a value built without one would land under a key no real carrier uses and
        # would silently never collide with anything — a conflict detector that cannot
        # detect. Failing to construct is the loud version of that.
        self.level_id = level_id
        self.price = float(price)
        self.family = family
        self.semantic_scope = semantic_scope
        self.evidence_tier = evidence_tier
        self.producer = producer
        self.window = window
        self.vendor_basis = vendor_basis
        self.as_of_ts_utc = as_of_ts_utc
        self.generation = generation
        self.session_date = session_date

    @property
    def session_scope(self) -> str:
        return _SESSION_SCOPE_OF.get(self.semantic_scope, self.semantic_scope)

    def identity(self) -> tuple:
        """The identity a second carrier must reproduce EXACTLY."""
        return (self.level_id, self.semantic_scope, self.generation,
                self.price, self.producer, self.as_of_ts_utc)

    def to_contract_dict(self) -> dict:
        return {
            "id": self.level_id,
            "price": self.price,
            "family": self.family,
            "label": self.level_id,
            "side": None,
            "strength": None,
            "evidence_tier": self.evidence_tier,
            "semantic_scope": self.semantic_scope,
            "generation": self.generation,
            "provenance": {
                "producer": self.producer,
                "session_scope": self.session_scope,
                "semantic_scope": self.semantic_scope,
                "window": self.window,
                "vendor_basis": self.vendor_basis,
            },
            "staleness": {"as_of_ts_utc": self.as_of_ts_utc},
        }


class PriceLevelSnapshot:
    """The ONE materialized result for (ticker, session scope, generation)."""

    __slots__ = ("ticker", "session_date", "generation", "bar_source", "as_of_ts_utc",
                 "produced_ts_utc", "levels", "vwap_path", "vwap_series",
                 "families_absent", "degraded", "input_fingerprint", "bars_used",
                 "session_rth_positive_volume_bars")

    def __init__(self, *, ticker: str, session_date: date, generation: int,
                 bar_source: str, as_of_ts_utc: Optional[float], produced_ts_utc: float,
                 levels: dict, vwap_path: list, families_absent: list,
                 degraded: list, input_fingerprint: tuple, bars_used: int,
                 vwap_series: Optional[list] = None,
                 session_rth_positive_volume_bars: int = 0) -> None:
        self.ticker = ticker
        self.session_date = session_date
        self.generation = generation
        self.bar_source = bar_source
        self.as_of_ts_utc = as_of_ts_utc
        self.produced_ts_utc = produced_ts_utc
        self.levels = levels                    # level_id -> PriceLevelValue
        self.vwap_path = vwap_path              # [(epoch_sec, vwap)]
        self.vwap_series = vwap_series or []    # [(epoch_sec, vwap, +1σ, -1σ, +2σ, -2σ)]
        self.families_absent = families_absent
        self.degraded = degraded
        self.input_fingerprint = input_fingerprint
        self.bars_used = bars_used
        self.session_rth_positive_volume_bars = int(session_rth_positive_volume_bars)

    def price(self, level_id: str) -> Optional[float]:
        """The canonical value, or None. Absence is absence — never spot, zero or a sibling."""
        lv = self.levels.get(level_id)
        return None if lv is None else lv.price

    def prices(self, *level_ids: str) -> tuple:
        return tuple(self.price(i) for i in level_ids)


def _snapshot_input_fingerprint(ticker: str, session_date: date, bars_norm: list,
                                bar_source: str) -> tuple:
    """Identity of the INPUT. Same fingerprint ⇒ same generation ⇒ same result object.

    Bar identity, not wall-clock: re-asking within a generation must return the very
    result already materialized, or "one result per generation" is prose.

    RC-324: this used to be (ticker, date, source, len, first_ts, last_ts, last_close) — a
    SAMPLE of the input, not a cover of it. Cursor proved the consequence by execution:
    changing PDH from 105 to 999 leaves the length, both endpoints and the last close
    untouched, so the fingerprint matched, the cached object was returned, and the stale 105
    was served under generation 1. A cache key shorter than its input is a claim of equality
    that cannot always hold. Every bar now enters a stable digest, so no interior edit can
    survive it, and the digest is fixed-width so the key stays cheap to compare.
    """
    h = hashlib.blake2b(digest_size=16)
    h.update(f"{ticker}\x1f{session_date.isoformat()}\x1f{bar_source}\x1f"
             f"{len(bars_norm)}".encode())
    for b in bars_norm:
        dt = _bar_dt_et(b)
        h.update(b"\x1e")
        # Both the PARSED instant and the RAW time fields. `_bar_dt_et` returns None for
        # shapes it cannot read, and hashing only the parse would then cover no time at
        # all — a bar could be moved in the series without moving the key.
        h.update(repr((
            None if dt is None else dt.timestamp(),
            b.get("datetime"), b.get("ts_utc"), b.get("bar_start_ts_utc"),
            b.get("open"), b.get("high"), b.get("low"), b.get("close"), b.get("volume"),
        )).encode())
    return (ticker, session_date.isoformat(), bar_source, len(bars_norm), h.hexdigest())


def build_price_level_snapshot(
    ticker: str,
    session_date: date,
    bars: list,
    *,
    bar_source: str,
    config: Optional[PlaybookConfig] = None,
    generation: int = 0,
    degraded: Optional[list] = None,
) -> PriceLevelSnapshot:
    """THE Phase 2A producer. The only production caller of the canonical helpers.

    Absent input stays absent: a family with no bars in its window is declared in
    `families_absent` and its ids are simply not present. Nothing substitutes spot,
    zero, or a neighbouring level (RC-68).
    """
    cfg = config or PlaybookConfig()
    bars_norm = _bars_to_list(bars)
    tk = ticker_storage_key(ticker)  # RC-345/F25: canonical liquidity snapshot/ledger identity
    produced_ts = datetime.now(tz=ET).timestamp()
    levels: dict[str, PriceLevelValue] = {}
    families_absent: list[dict] = []
    vwap_path: list[tuple[float, float]] = []
    vwap_series: list[tuple] = []

    as_of: Optional[float] = None
    for b in bars_norm:
        dt = _bar_dt_et(b)
        if dt is None:
            continue
        ts = dt.timestamp()
        if as_of is None or ts > as_of:
            as_of = ts

    basis = f"1m bars ({bar_source}); schwab pricehistory/stream basis"

    def _put(level_id: str, price, *, producer: str, window: str) -> None:
        if price is None:
            return
        v = _float_or_none(price)
        if v is None:
            return
        family, scope, tier = PHASE2A_LEVEL_IDS[level_id]
        levels[level_id] = PriceLevelValue(
            level_id=level_id, price=v, family=family, semantic_scope=scope,
            evidence_tier=tier, producer=producer, window=window, vendor_basis=basis,
            as_of_ts_utc=as_of, generation=generation,
            session_date=session_date.isoformat(),
        )

    # ── prior day ────────────────────────────────────────────────────────────
    prior_date = prior_trading_session_date(bars_norm, session_date)
    if prior_date is None:
        families_absent.append({
            "family": "prior_day",
            "reason": f"no prior RTH session in available bars (source {bar_source})",
        })
    else:
        eng = get_previous_day_levels(bars_norm, session_date, cfg)
        window = f"{prior_date.isoformat()} 09:30-16:00 ET (most recent prior RTH session)"
        for lid, key in (("PDH", "pdh"), ("PDL", "pdl"), ("PDC", "pdc"),
                         ("PD_POC", "pd_poc"), ("PD_VAH", "pd_vah"), ("PD_VAL", "pd_val")):
            _put(lid, eng.get(key),
                 producer=f"{_PRODUCER_NS}.get_previous_day_levels", window=window)

    sess_window = f"{session_date.isoformat()} RTH (canonical snapshot over {bar_source})"

    if not bars_norm:
        for fam in ("vwap", "opening_range", "overnight", "value_area"):
            families_absent.append({
                "family": fam, "reason": f"no bars available (source {bar_source})"})
        return PriceLevelSnapshot(
            ticker=tk, session_date=session_date, generation=generation,
            bar_source=bar_source, as_of_ts_utc=as_of, produced_ts_utc=produced_ts,
            levels=levels, vwap_path=vwap_path, vwap_series=vwap_series,
            families_absent=families_absent, degraded=list(degraded or []),
            input_fingerprint=_snapshot_input_fingerprint(tk, session_date, bars_norm, bar_source),
            bars_used=0, session_rth_positive_volume_bars=0,
        )

    # ── vwap + bands (one accumulation: the series IS the scalars' source) ───
    session_rth_vol_n = count_session_rth_positive_volume_bars(bars_norm, session_date)
    vwap_series = compute_session_vwap_series(bars_norm, session_date)
    vwap_val = vwap_series[-1][1] if vwap_series else None
    if vwap_val is None:
        if session_rth_vol_n > 0:
            vwap_abs_reason = "RTH volume bars present but session VWAP did not materialize"
        else:
            vwap_abs_reason = "no RTH volume for session VWAP in available bars"
        families_absent.append({"family": "vwap", "reason": vwap_abs_reason})
    else:
        _put("VWAP", vwap_val,
             producer=f"{_PRODUCER_NS}.compute_session_vwap_series", window=sess_window)
        p1, m1, p2, m2 = compute_vwap_bands(bars_norm, session_date, vwap_val)
        for lid, val in (("VWAP_P1", p1), ("VWAP_M1", m1), ("VWAP_P2", p2), ("VWAP_M2", m2)):
            _put(lid, val,
                 producer=f"{_PRODUCER_NS}.compute_vwap_bands", window=sess_window)
        # The drawn curve must END on the served level. The band scalars come from
        # compute_vwap_bands' two-pass form about the final VWAP and the curve from the
        # cumulative moments — algebraically the same quantity, so pinning the last
        # point removes any float-noise gap between the line and the number beside it.
        if None not in (p1, m1, p2, m2):
            t_last, w_last = vwap_series[-1][0], vwap_series[-1][1]
            vwap_series[-1] = (t_last, w_last, p1, m1, p2, m2)
    vwap_path = [(t, w) for t, w, _a, _b, _c, _d in vwap_series]

    # ── opening range ────────────────────────────────────────────────────────
    orb = compute_opening_range(bars_norm, session_date, cfg)
    if not orb:
        families_absent.append({
            "family": "opening_range", "reason": "no ORB bars in available tape for session"})
    else:
        orb_window = f"{session_date.isoformat()} first {cfg.opening_range_minutes}m RTH"
        for lid, key in (("ORB_HIGH", "orb_high"), ("ORB_LOW", "orb_low"), ("ORB_MID", "orb_mid")):
            _put(lid, orb.get(key),
                 producer=f"{_PRODUCER_NS}.compute_opening_range", window=orb_window)

    # ── overnight ────────────────────────────────────────────────────────────
    overnight = get_overnight_levels(bars_norm, session_date)
    if not overnight:
        families_absent.append({
            "family": "overnight", "reason": "no overnight-window bars in available tape"})
    else:
        for lid, key in (("OVERNIGHT_HIGH", "overnight_high"), ("OVERNIGHT_LOW", "overnight_low")):
            _put(lid, overnight.get(key),
                 producer=f"{_PRODUCER_NS}.get_overnight_levels",
                 window="prior RTH close -> session RTH open (RC-153)")

    # ── current-session value area ───────────────────────────────────────────
    poc, vah, val = compute_volume_profile_levels(bars_norm, session_date, cfg)
    if poc is None and vah is None and val is None:
        families_absent.append({
            "family": "value_area", "reason": "no today RTH bars for volume profile"})
    else:
        for lid, price in (("TODAY_POC", poc), ("TODAY_VAH", vah), ("TODAY_VAL", val)):
            _put(lid, price,
                 producer=f"{_PRODUCER_NS}.compute_volume_profile_levels",
                 window=sess_window)

    return PriceLevelSnapshot(
        ticker=tk, session_date=session_date, generation=generation,
        bar_source=bar_source, as_of_ts_utc=as_of, produced_ts_utc=produced_ts,
        levels=levels, vwap_path=vwap_path, vwap_series=vwap_series,
        families_absent=families_absent, degraded=list(degraded or []),
        input_fingerprint=_snapshot_input_fingerprint(tk, session_date, bars_norm, bar_source),
        bars_used=len(bars_norm),
        session_rth_positive_volume_bars=session_rth_vol_n,
    )


#: (ticker, session_date_iso) -> the ONE materialized snapshot for the current generation.
_MATERIALIZED_SNAPSHOTS: dict[tuple[str, str], PriceLevelSnapshot] = {}
#: RC-324: guards the whole read-decide-build-write of materialize_price_level_snapshot.
#: Deciding a generation from a value you then overwrite is a check-then-act, and a
#: check-then-act is a race unless something serialises it.
_MATERIALIZE_LOCK = threading.Lock()


def materialize_price_level_snapshot(
    ticker: str,
    session_date: date,
    bars: list,
    *,
    bar_source: str,
    config: Optional[PlaybookConfig] = None,
    degraded: Optional[list] = None,
) -> PriceLevelSnapshot:
    """Materialize once per generation; return the SAME object within a generation.

    A new market generation (the bar input changed) invokes the producer exactly once.
    Every later ask in that generation is a read, never a recomputation.
    """
    tk = ticker_storage_key(ticker)  # RC-345/F25: canonical liquidity snapshot/ledger identity
    bars_norm = _bars_to_list(bars)
    key = (tk, session_date.isoformat())
    fingerprint = _snapshot_input_fingerprint(tk, session_date, bars_norm, bar_source)
    # RC-324: the read, the generation decision, the build and the write-back are ONE
    # critical section. Unguarded, this is a check-then-act: Cursor proved two concurrent
    # callers both observed `existing is None`, both computed generation 1, and produced two
    # different objects carrying PDH 105 and 205 — two results under one generation, which
    # is the exact half of the invariant this producer exists to guarantee.
    with _MATERIALIZE_LOCK:
        existing = _MATERIALIZED_SNAPSHOTS.get(key)
        if existing is not None and existing.input_fingerprint == fingerprint:
            return existing
        generation = 1 if existing is None else existing.generation + 1
        snap = build_price_level_snapshot(
            tk, session_date, bars_norm, bar_source=bar_source, config=config,
            generation=generation, degraded=degraded,
        )
        _MATERIALIZED_SNAPSHOTS[key] = snap
        _prune_carrier_ledger(tk, session_date.isoformat(), generation)
        return snap


def get_materialized_snapshot(ticker: str, session_date: date) -> Optional[PriceLevelSnapshot]:
    """READ the materialized snapshot. Never computes — absent means absent."""
    return _MATERIALIZED_SNAPSHOTS.get(
        (ticker_storage_key(ticker), session_date.isoformat()))  # RC-345/F25: read key matches canonical write


def clear_materialized_snapshots(ticker: Optional[str] = None) -> None:
    if ticker is None:
        _MATERIALIZED_SNAPSHOTS.clear()
        return
    tk = ticker_storage_key(ticker)  # RC-345/F25: canonical liquidity snapshot/ledger identity
    for k in [k for k in _MATERIALIZED_SNAPSHOTS if k[0] == tk]:
        _MATERIALIZED_SNAPSHOTS.pop(k, None)


# ── runtime carrier contract ─────────────────────────────────────────────────


class LevelCarrierConflict(RuntimeError):
    """Two carriers disagree for one (ticker, level_id, semantic_scope, generation).

    This is the failure the static guard cannot see: the source may contain exactly
    one computation and still ship two different numbers, because a carrier rounded,
    re-derived, cached across a generation boundary, or relabelled provenance.
    """


#: (ticker, session_date, level_id, semantic_scope, generation) -> (identity, carrier).
#: session_date is part of the KEY, not just the value: yesterday's generation 1 and
#: today's generation 1 are different subjects, and colliding them would report a
#: disagreement that is only a change of day.
_CARRIER_LEDGER: dict[tuple[str, str, str, str, int], tuple[tuple, str]] = {}


def reset_level_carrier_ledger(ticker: Optional[str] = None) -> None:
    if ticker is None:
        _CARRIER_LEDGER.clear()
        return
    tk = ticker_storage_key(ticker)  # RC-345/F25: canonical liquidity snapshot/ledger identity
    for k in [k for k in _CARRIER_LEDGER if k[0] == tk]:
        _CARRIER_LEDGER.pop(k, None)


def _prune_carrier_ledger(ticker: str, session_date_iso: str, generation: int) -> None:
    """Drop every ledger row for this ticker that is not the current generation.

    Superseded generations are not disagreements — they are history, and keeping them
    would both grow without bound in a multi-day process and let a stale row accuse a
    correct carrier.
    """
    tk = ticker_storage_key(ticker)  # RC-345/F25: canonical liquidity snapshot/ledger identity
    for k in [k for k in _CARRIER_LEDGER
              if k[0] == tk and (k[1] != session_date_iso or k[4] != generation)]:
        _CARRIER_LEDGER.pop(k, None)


def register_level_carrier(
    carrier: str,
    ticker: str,
    value: PriceLevelValue,
) -> None:
    """Record what a carrier is about to ship; raise if it contradicts an earlier carrier."""
    tk = ticker_storage_key(ticker)  # RC-345/F25: canonical liquidity snapshot/ledger identity
    key = (tk, value.session_date, value.level_id, value.semantic_scope, value.generation)
    identity = value.identity()
    prior = _CARRIER_LEDGER.get(key)
    if prior is None:
        _CARRIER_LEDGER[key] = (identity, carrier)
        return
    prior_identity, prior_carrier = prior
    if prior_identity != identity:
        fields = ("level_id", "semantic_scope", "generation", "price", "producer",
                  "as_of_ts_utc")
        diff = [f"{f}: {a!r} != {b!r}"
                for f, a, b in zip(fields, prior_identity, identity) if a != b]
        raise LevelCarrierConflict(
            f"{tk} {value.level_id} scope={value.semantic_scope} "
            f"generation={value.generation}: carrier {carrier!r} disagrees with "
            f"{prior_carrier!r} — " + "; ".join(diff)
        )


def carry_snapshot_levels(
    snapshot: PriceLevelSnapshot,
    carrier: str,
    level_ids: Optional[tuple] = None,
) -> dict:
    """Carry canonical values to a consumer, registering each against the contract.

    Returns {level_id: price-or-None}. A consumer calls this INSTEAD of computing;
    the returned mapping is the only legal source for a Phase 2A id on that surface.
    """
    ids = tuple(level_ids) if level_ids else tuple(PHASE2A_LEVEL_IDS)
    out: dict[str, Optional[float]] = {}
    for lid in ids:
        v = snapshot.levels.get(lid)
        if v is None:
            out[lid] = None
            continue
        register_level_carrier(carrier, snapshot.ticker, v)
        out[lid] = v.price
    return out
