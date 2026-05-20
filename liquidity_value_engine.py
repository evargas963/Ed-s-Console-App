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

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

from liquidity_models import (
    PlaybookConfig,
    PlaybookState,
    PriceLevel,
    SnapshotOutput,
    SnapshotSummary,
    SnapshotType,
    Zone,
    ZoneType,
)

log = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")
RTH_OPEN = time(9, 30)
RTH_CLOSE = time(16, 0)


def _positive_float_or_none(value) -> Optional[float]:
    from numeric_contract import float_positive_or_none

    return float_positive_or_none(value)


def _cluster_reference_price(*candidates) -> Optional[float]:
    """First positive price among candidates; None when no valid reference (no 500.0 fabrication)."""
    for value in candidates:
        p = _positive_float_or_none(value)
        if p is not None:
            return p
    return None


def _float_or_none(value) -> Optional[float]:
    from numeric_contract import float_finite_or_none

    return float_finite_or_none(value)


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

    session_dt = datetime.combine(session_date, RTH_OPEN, tzinfo=ET)
    prev_rth_start = session_dt - timedelta(days=1)
    prev_rth_end = datetime.combine(session_date - timedelta(days=1), RTH_CLOSE, tzinfo=ET)

    prev_bars = []
    for b in bars_norm:
        dt = _bar_dt_et(b)
        if dt is None:
            continue
        if prev_rth_end.date() <= dt.date() < session_date:
            if RTH_OPEN <= dt.time() < RTH_CLOSE:
                prev_bars.append(b)
    if not prev_bars:
        for b in bars_norm:
            dt = _bar_dt_et(b)
            if dt and dt.date() < session_date:
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
    """
    Overnight range: prior RTH close (16:00) → current RTH open (09:30).
    """
    bars_norm = _bars_to_list(bars)
    session_dt = datetime.combine(session_date, RTH_OPEN, tzinfo=ET)
    prev_close_dt = datetime.combine(session_date - timedelta(days=1), RTH_CLOSE, tzinfo=ET)

    overnight = []
    for b in bars_norm:
        dt = _bar_dt_et(b)
        if dt is None:
            continue
        if dt.date() == session_date:
            mins = dt.hour * 60 + dt.minute
            if mins < 9 * 60 + 30:
                overnight.append(b)
        elif dt.date() == session_date - timedelta(days=1):
            mins = dt.hour * 60 + dt.minute
            if mins >= 16 * 60:
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


def compute_session_vwap(bars: list, session_date: date, cutoff_dt: Optional[datetime] = None) -> Optional[float]:
    """VWAP = Σ(typical_price × volume) / Σ(volume). RTH only."""
    bars_norm = _bars_to_list(bars)
    rth_bars = _filter_rth_bars(bars_norm, session_date, cutoff_dt)
    if not rth_bars:
        return None
    cum_tpv = cum_vol = 0.0
    for b in rth_bars:
        vol = _positive_float_or_none(b.get("volume"))
        if vol is None:
            continue
        tp = (b["high"] + b["low"] + b["close"]) / 3.0
        cum_tpv += tp * vol
        cum_vol += vol
    if cum_vol <= 0:
        return None
    return round(cum_tpv / cum_vol, 4)


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
    """
    POC = price with max volume.
    Value area = smallest range containing value_area_pct of volume, centered on POC.
    Approximation: uses typical_price (H+L+C)/3 per bar, binned by tick_size.
    """
    if not bars:
        return None, None, None
    vol_by_price: dict[float, float] = defaultdict(float)
    for b in bars:
        vol = _positive_float_or_none(b.get("volume"))
        if vol is None:
            continue
        h, l_, c = b["high"], b["low"], b["close"]
        typical = (h + l_ + c) / 3.0
        price_bin = round(typical / tick_size) * tick_size
        vol_by_price[price_bin] += vol
    if not vol_by_price:
        return None, None, None
    total_vol = sum(vol_by_price.values())
    if total_vol <= 0:
        return None, None, None
    poc_price = max(vol_by_price.keys(), key=lambda p: vol_by_price[p])
    target_vol = total_vol * value_area_pct
    prices_sorted = sorted(vol_by_price.keys())
    best_lo, best_hi = poc_price, poc_price
    best_vol = vol_by_price[poc_price]
    try:
        lo_idx = prices_sorted.index(poc_price)
    except ValueError:
        lo_idx = 0
    hi_idx = lo_idx
    while best_vol < target_vol and (lo_idx > 0 or hi_idx < len(prices_sorted) - 1):
        v_lo = vol_by_price.get(prices_sorted[lo_idx - 1], 0) if lo_idx > 0 else 0
        v_hi = vol_by_price.get(prices_sorted[hi_idx + 1], 0) if hi_idx < len(prices_sorted) - 1 else 0
        if v_lo >= v_hi and lo_idx > 0:
            lo_idx -= 1
            best_vol += v_lo
            best_lo = prices_sorted[lo_idx]
        elif hi_idx < len(prices_sorted) - 1:
            hi_idx += 1
            best_vol += v_hi
            best_hi = prices_sorted[hi_idx]
        else:
            break
    return round(poc_price, 4), round(best_hi, 4), round(best_lo, 4)


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
    trs = []
    prev_close = None
    for b in sorted(rth_bars, key=lambda x: x.get("_ts") or 0):
        h = _float_or_none(b.get("high"))
        l_ = _float_or_none(b.get("low"))
        c = _float_or_none(b.get("close"))
        if h is None or l_ is None or c is None:
            prev_close = c if c is not None else prev_close
            continue
        if prev_close is not None:
            tr = max(
                h - l_,
                abs(h - prev_close),
                abs(l_ - prev_close),
            )
            trs.append(tr)
        prev_close = c

    if len(trs) < period:
        return None
    atr = sum(trs[-period:]) / period
    return round(atr, 4)


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
        return datetime.combine(session_date, time(9, 29), tzinfo=ET)
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
) -> SnapshotOutput:
    """Premarket: PDH/PDL/PDC, PD POC/VAH/VAL, overnight high/low. No same-day RTH."""
    bars_norm = _bars_to_list(bars)
    cutoff = _cutoff_for_snapshot(SnapshotType.PREMARKET, session_date)
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

    # Canonical taxonomy: overnight low / extreme downside -> sell_side_liquidity;
    # PDL/VAL/support -> support_liquidity; POC/balance -> pivot_value; PDH/overnight high -> resistance_liquidity
    out_zones = []
    if prev and over:
        pdh, pdl = prev.get("pdh"), prev.get("pdl")
        for z in zones:
            tags_str = " ".join(z.source_tags)
            if pdl is not None and z.zone_low < pdl * 0.995:
                z.zone_type = ZoneType.SELL_SIDE_LIQUIDITY
                z.interpretation_notes = "Sell-side liquidity below prior day low"
            elif "PDH" in tags_str or "OVERNIGHT_HIGH" in tags_str:
                if "PD_POC" not in tags_str and "PDC" not in tags_str:
                    z.zone_type = ZoneType.RESISTANCE_LIQUIDITY
                    z.interpretation_notes = "Resistance liquidity near prior day high"
            elif "OVERNIGHT_LOW" in tags_str and "PDL" not in tags_str and "PD_VAL" not in tags_str:
                z.zone_type = ZoneType.SELL_SIDE_LIQUIDITY
                z.interpretation_notes = "Sell-side liquidity at overnight low"
            elif "PDL" in tags_str or "PD_VAL" in tags_str:
                if "PD_POC" not in tags_str and "PDC" not in tags_str:
                    z.zone_type = ZoneType.SUPPORT_LIQUIDITY
                    z.interpretation_notes = "Support liquidity near prior day low"
            elif "PD_POC" in tags_str or "PDC" in tags_str or "PD_VAL" in tags_str:
                z.zone_type = ZoneType.PIVOT_VALUE
                z.interpretation_notes = "Fair value reference from prior day POC/close"
            elif pdh is not None and z.zone_high >= pdh * 0.998:
                z.zone_type = ZoneType.RESISTANCE_LIQUIDITY
                z.interpretation_notes = "Resistance liquidity above prior day high"
            elif pdl is not None and z.zone_low <= pdl * 1.002:
                z.zone_type = ZoneType.SUPPORT_LIQUIDITY
                z.interpretation_notes = "Support liquidity near prior day low"
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
    orb_h, orb_l = orb.get("orb_high"), orb.get("orb_low")
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
            notes = "Resistance liquidity"
        elif "PDL" in str(tags) or "PD_VAL" in str(tags):
            zt = ZoneType.SUPPORT_LIQUIDITY
            notes = "Support liquidity"
        elif "VWAP" in str(tags) or "ORB_MID" in str(tags):
            zt = ZoneType.PIVOT_VALUE
            notes = "Intraday pivot zone"
        elif orb_l and lo < orb_l * 0.995:
            zt = ZoneType.SELL_SIDE_LIQUIDITY
            notes = "Sell-side liquidity below ORB"
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
            zt = ZoneType.SELL_SIDE_LIQUIDITY
            notes = "Liquidity sweep zone"
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
        "OI_CALL", "OI_PUT", "GAMMA_PIN", "HVL", "MAX_PAIN", "GAMMA_FLIP",
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
    return ZoneType.PIVOT_VALUE, "Session liquidity zone"


def build_live_snapshot(
    ticker: str,
    bars: list,
    session_date: date,
    config: PlaybookConfig,
    *,
    extra_levels: Optional[list[tuple[float, str]]] = None,
    spot: Optional[float] = None,
) -> SnapshotOutput:
    """
    Rolling intraday snapshot: RTH cutoff is min(now ET, 16:00) on the session date;
    historical session_date (prior calendar days) uses full RTH through 16:00.
    Before today's RTH open → same as premarket snapshot.

    Merges optional ``extra_levels`` (e.g. options walls from cache) with VWAP / profile / ORB context.
    """
    today_et = datetime.now(ET).date()
    now = datetime.now(ET)
    open_dt = datetime.combine(session_date, RTH_OPEN, tzinfo=ET)
    close_dt = datetime.combine(session_date, RTH_CLOSE, tzinfo=ET)

    if session_date > today_et:
        return build_premarket_snapshot(ticker, bars, session_date, config)

    if session_date < today_et:
        cutoff = close_dt
    else:
        if now < open_dt:
            return build_premarket_snapshot(ticker, bars, session_date, config)
        cutoff = min(now, close_dt)

    bars_norm = _bars_to_list(bars)
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
        generated_at=datetime.now(ET).isoformat(),
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
