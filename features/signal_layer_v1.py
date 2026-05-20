"""
Canonical 1m signal layer (v1) — bar-only features for directional structure.

All features use completed 1m bars with bar_end_ts_utc <= decision_ts_utc (no lookahead).
VWAP/session fields from SignalInput are aligned to decision time (same clock as refresh_ts_utc).

Categories: price structure, VWAP/value, volatility/compression, candle/imbalance,
multi-timeframe (derived from stacked 1m), participation.
"""

from __future__ import annotations

import logging
import math
from typing import Any, Mapping, Optional, Sequence

from numeric_contract import float_finite_or_none

log = logging.getLogger(__name__)

EPS = 1e-12
DEFAULT_MAX_BARS = 256

# Rolling windows (1m bars)
W_SLOPE_SHORT = 20
W_SLOPE_MED = 40
W_SWING = 50
W_ATR = 14
W_ATR_LONG = 60
W_VWAP_STATS = 20
W_VWAP_ROLL = 60
W_VOL_PART = 20
W_RANGE = 20
W_RV = 30
W_MTF5 = 30   # 30×1m ≈ 30m for 5m-like aggregation
W_MTF15 = 45  # 15×1m bars aggregated as 15m proxy


def _f(x: Any) -> Optional[float]:
    return float_finite_or_none(x)


def meta_n_bars_int(layer: Mapping[str, Any]) -> int:
    """Parse ``meta.n_bars`` without raising on corrupt bundle strings."""
    raw = layer.get("meta.n_bars")
    if raw is None or raw == "":
        return 0
    try:
        n = int(raw)
    except (TypeError, ValueError):
        log.debug("meta_n_bars_int: unparseable meta.n_bars=%r", raw)
        return 0
    return n if n > 0 else 0


def _clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _safe_div(a: float, b: float) -> Optional[float]:
    if abs(b) < EPS:
        return None
    return a / b


def _tr(bar: Mapping[str, Any]) -> float:
    h = _f(bar.get("high"))
    l_ = _f(bar.get("low"))
    if h is None or l_ is None:
        c = _f(bar.get("close"))
        if c is None:
            return EPS
        h = c if h is None else h
        l_ = c if l_ is None else l_
    pc = _f(bar.get("_prev_close"))
    if pc is None:
        return max(h - l_, EPS)
    return max(h - l_, abs(h - pc), abs(l_ - pc), EPS)


def _atr(bars: Sequence[Mapping[str, Any]], period: int) -> Optional[float]:
    if len(bars) < period + 1:
        return None
    trs: list[float] = []
    for i in range(len(bars) - period, len(bars)):
        b = dict(bars[i])
        if i > 0:
            b["_prev_close"] = _f(bars[i - 1].get("close"))
        trs.append(_tr(b))
    return sum(trs) / float(len(trs))


def _percentile_rank_window(values: Sequence[float], x: float) -> Optional[float]:
    if not values:
        return None
    lo = sum(1 for v in values if v < x)
    eq = sum(1 for v in values if v == x)
    n = float(len(values))
    return _clip((lo + 0.5 * eq) / n, 0.0, 1.0)


def _ols_slope_yx(y: Sequence[float]) -> Optional[float]:
    n = len(y)
    if n < 3:
        return None
    xs = list(range(n))
    mx = sum(xs) / n
    my = sum(y) / n
    num = sum((xs[i] - mx) * (y[i] - my) for i in range(n))
    den = sum((xi - mx) ** 2 for xi in xs)
    if abs(den) < EPS:
        return None
    return num / den


def _ols_log_slope_close(closes: Sequence[float]) -> Optional[float]:
    if len(closes) < 3:
        return None
    log_c = [math.log(max(c, EPS)) for c in closes]
    # slope per bar index of log price
    return _ols_slope_yx(log_c)


def _fractal_swings(
    bars: Sequence[Mapping[str, Any]], lookback: int
) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
    """Return swing highs and lows as (index, price) in global bar indices (relative to bars)."""
    n = len(bars)
    if n < 5:
        return [], []
    lo = max(1, n - lookback)
    highs: list[tuple[int, float]] = []
    lows: list[tuple[int, float]] = []
    # Pivots need neighbors on both sides → i in [1, n-2]
    for i in range(lo, n - 1):
        h = _f(bars[i].get("high"))
        l_ = _f(bars[i].get("low"))
        if h is None or l_ is None:
            continue
        hp = _f(bars[i - 1].get("high"))
        hn = _f(bars[i + 1].get("high"))
        lp = _f(bars[i - 1].get("low"))
        ln = _f(bars[i + 1].get("low"))
        if hp is not None and hn is not None and h > hp and h > hn:
            highs.append((i, h))
        if lp is not None and ln is not None and l_ < lp and l_ < ln:
            lows.append((i, l_))
    return highs, lows


def _aggregate_bars(bars: Sequence[Mapping[str, Any]], group: int) -> list[dict[str, Any]]:
    """Aggregate consecutive 1m bars into synthetic 'group'-minute OHLC."""
    out: list[dict[str, Any]] = []
    chunk: list[Mapping[str, Any]] = []
    for b in bars:
        chunk.append(b)
        if len(chunk) == group:
            o = _f(chunk[0].get("open"))
            c = _f(chunk[-1].get("close"))
            highs = [_f(x.get("high")) for x in chunk]
            lows = [_f(x.get("low")) for x in chunk]
            volumes = [_f(x.get("volume")) for x in chunk]
            vol = sum(v for v in volumes if v is not None) if all(v is not None for v in volumes) else None
            if o is not None and c is not None and all(h is not None for h in highs) and all(l is not None for l in lows):
                out.append(
                    {
                        "open": o,
                        "high": max(float(h) for h in highs if h is not None),
                        "low": min(float(l) for l in lows if l is not None),
                        "close": c,
                        "volume": vol,
                    }
                )
            chunk = []
    return out


def _sign_trend(slope: Optional[float], eps: float = 1e-8) -> float:
    if slope is None:
        return 0.0
    if slope > eps:
        return 1.0
    if slope < -eps:
        return -1.0
    return 0.0


def _volume_profile_proxy(
    bars: Sequence[Mapping[str, Any]], n: int
) -> tuple[Optional[float], Optional[float], Optional[float]]:
    """Return (poc, val, vah) price levels from last n bars (volume-weighted histogram)."""
    sl = bars[-n:] if len(bars) >= n else bars
    if len(sl) < 5:
        return None, None, None
    prices: list[float] = []
    vols: list[float] = []
    for b in sl:
        c = _f(b.get("close"))
        v = _f(b.get("volume"))
        if c is None or v is None:
            continue
        prices.append(c)
        vols.append(v)
    if len(prices) < 5:
        return None, None, None
    pmin, pmax = min(prices), max(prices)
    if abs(pmax - pmin) < EPS:
        return pmin, pmin, pmax
    nbin = min(12, len(prices))
    width = (pmax - pmin) / nbin
    bins = [0.0] * nbin
    for p, v in zip(prices, vols):
        idx = int((p - pmin) / (width + EPS))
        idx = _clip(idx, 0, nbin - 1)
        bins[idx] += v
    imax = max(range(nbin), key=lambda i: bins[i])
    poc = pmin + (imax + 0.5) * width
    total_v = sum(bins)
    target = 0.70 * total_v
    cum = 0.0
    lo_i, hi_i = imax, imax
    while cum < target and (lo_i > 0 or hi_i < nbin - 1):
        left = bins[lo_i - 1] if lo_i > 0 else 0.0
        right = bins[hi_i + 1] if hi_i < nbin - 1 else 0.0
        if right >= left and hi_i < nbin - 1:
            cum += right
            hi_i += 1
        elif lo_i > 0:
            cum += left
            lo_i -= 1
        else:
            break
    val = pmin + lo_i * width
    vah = pmin + (hi_i + 1) * width
    return poc, val, vah


def load_bars_before_decision(
    conn: Any,
    ticker: str,
    decision_ts_utc: float,
    *,
    max_bars: int = DEFAULT_MAX_BARS,
) -> list[dict[str, Any]]:
    """
    Load completed 1m bars with bar_end_ts_utc <= decision_ts_utc, oldest first.
    """
    from instrument_identity import ticker_storage_key

    tkey = ticker_storage_key(ticker)
    cur = conn.execute(
        """
        SELECT bar_start_ts_utc, bar_end_ts_utc, open, high, low, close, volume
        FROM price_bars_1m
        WHERE ticker = ? AND bar_end_ts_utc <= ?
        ORDER BY bar_end_ts_utc DESC
        LIMIT ?
        """,
        (tkey, float(decision_ts_utc), int(max_bars)),
    )
    desc = [c[0] for c in (cur.description or ())]
    rows = [dict(zip(desc, tup)) for tup in cur.fetchall()]
    rows.reverse()
    return rows


def compute_signal_layer_v1(
    bars: Sequence[Mapping[str, Any]],
    *,
    decision_ts_utc: float,
    inp: Any | None = None,
) -> dict[str, Any]:
    """
    Compute full v1 feature dict. Missing history yields None for unstable features.

    Leakage rule: only bars with bar_end_ts_utc <= decision_ts_utc; inp fields are
    contemporaneous with the decision tick (not future outcomes).
    """
    out: dict[str, Any] = {
        "meta.decision_ts_utc": float(decision_ts_utc),
        "meta.n_bars": int(len(bars)),
    }
    if not bars:
        out["meta.bar_end_last"] = None
        return out

    last = bars[-1]
    be_last = _f(last.get("bar_end_ts_utc"))
    out["meta.bar_end_last"] = be_last
    out["meta.bar_start_first"] = _f(bars[0].get("bar_start_ts_utc"))

    closes = [_f(b.get("close")) for b in bars]
    if not closes or closes[-1] is None:
        out["meta.error"] = "missing_last_close"
        return out

    # ── A. Price structure ─────────────────────────────────────────────────
    c_now = closes[-1]
    assert c_now is not None
    atr14 = _atr(bars, W_ATR)
    atr5 = _atr(bars, 5) if len(bars) >= 6 else None
    atr20 = _atr(bars, 20) if len(bars) >= 21 else atr14

    w = min(W_SLOPE_SHORT, len(closes))
    cw = [c for c in closes[-w:] if c is not None]
    sl = _ols_log_slope_close(cw) if len(cw) >= 3 else None
    out["ps.rolling_trend_slope_log20"] = sl

    wm = min(W_SLOPE_MED, len(closes))
    cwm = [c for c in closes[-wm:] if c is not None]
    out["ps.rolling_trend_slope_log40"] = _ols_log_slope_close(cwm) if len(cwm) >= 3 else None

    sh, sls = _fractal_swings(bars, W_SWING)
    swing_high = sh[-1][1] if sh else None
    swing_low = sls[-1][1] if sls else None
    prev_sh = sh[-2][1] if len(sh) >= 2 else None
    prev_sl = sls[-2][1] if len(sls) >= 2 else None

    struct = 0.0
    if swing_high is not None and prev_sh is not None and swing_low is not None and prev_sl is not None:
        hh = swing_high > prev_sh
        hl = swing_low > prev_sl
        lh = swing_high < prev_sh
        ll = swing_low < prev_sl
        if hh and hl:
            struct = 1.0
        elif lh and ll:
            struct = -1.0
        else:
            struct = 0.5 if (hh or hl) else -0.5 if (lh or ll) else 0.0
    out["ps.hh_hl_lh_ll_state"] = struct

    bos_up = 0.0
    bos_dn = 0.0
    if swing_high is not None and c_now > swing_high:
        bos_up = 1.0
    if swing_low is not None and c_now < swing_low:
        bos_dn = 1.0
    out["ps.break_of_structure_up"] = bos_up
    out["ps.break_of_structure_down"] = bos_dn

    if swing_high is not None and atr14:
        out["ps.dist_to_swing_high_atr"] = _safe_div(swing_high - c_now, atr14)
    else:
        out["ps.dist_to_swing_high_atr"] = None
    if swing_low is not None and atr14:
        out["ps.dist_to_swing_low_atr"] = _safe_div(c_now - swing_low, atr14)
    else:
        out["ps.dist_to_swing_low_atr"] = None

    rn = min(W_RANGE, len(bars))
    seg = bars[-rn:]
    highs = [_f(b.get("high")) or _f(b.get("close")) for b in seg]
    lows = [_f(b.get("low")) or _f(b.get("close")) for b in seg]
    if all(h is not None for h in highs) and all(l is not None for l in lows):
        rh = max(highs)  # type: ignore[arg-type]
        rl = min(lows)  # type: ignore[arg-type]
        out["ps.range_position_n20"] = _safe_div(c_now - rl, rh - rl + EPS)
    else:
        out["ps.range_position_n20"] = None

    # ── B. VWAP / value ────────────────────────────────────────────────────
    typ_vol_sum = 0.0
    vol_sum = 0.0
    sl_v = bars[-W_VWAP_ROLL:] if len(bars) >= 5 else bars
    for b in sl_v:
        h = _f(b.get("high"))
        l_ = _f(b.get("low"))
        c = _f(b.get("close"))
        v = _f(b.get("volume"))
        if h and l_ and c and v is not None:
            tp = (h + l_ + c) / 3.0
            typ_vol_sum += tp * v
            vol_sum += v
    vwap_roll = _safe_div(typ_vol_sum, vol_sum) if vol_sum > EPS else None

    vwap_inp = _f(getattr(inp, "vwap", None)) if inp is not None else None
    if vwap_inp is not None:
        vwap_use = vwap_inp
        out["meta.vwap_source"] = "inp"
    else:
        vwap_use = vwap_roll
        out["meta.vwap_source"] = "roll" if vwap_roll is not None else None

    if vwap_use is not None:
        out["vl.price_vs_vwap_pct"] = _safe_div(c_now - vwap_use, c_now) * 100.0
        out["vl.vwap_distance_pts"] = c_now - vwap_use
    else:
        out["vl.price_vs_vwap_pct"] = None
        out["vl.vwap_distance_pts"] = None

    resid: list[float] = []
    for b in bars[-W_VWAP_STATS:]:
        c = _f(b.get("close"))
        if c is None or vwap_use is None:
            continue
        resid.append(c - vwap_use)
    if len(resid) >= 5:
        m = sum(resid) / len(resid)
        var = sum((x - m) ** 2 for x in resid) / max(len(resid) - 1, 1)
        std = math.sqrt(max(var, EPS))
        out["vl.vwap_zscore"] = _safe_div(resid[-1], std)
    else:
        out["vl.vwap_zscore"] = None

    if vwap_use is not None and len(resid) >= 5:
        m = sum(resid) / len(resid)
        var = sum((x - m) ** 2 for x in resid) / max(len(resid) - 1, 1)
        std = math.sqrt(max(var, EPS))
        upper = vwap_use + 2.0 * std
        lower = vwap_use - 2.0 * std
        out["vl.dist_to_vwap_band_upper_pts"] = upper - c_now
        out["vl.dist_to_vwap_band_lower_pts"] = c_now - lower
    else:
        out["vl.dist_to_vwap_band_upper_pts"] = None
        out["vl.dist_to_vwap_band_lower_pts"] = None

    poc, val, vah = _volume_profile_proxy(bars, W_RANGE)
    if poc is not None and atr14:
        out["vl.dist_to_poc_atr"] = _safe_div(c_now - poc, atr14)
        if val is not None:
            out["vl.dist_to_val_atr"] = _safe_div(c_now - val, atr14)
        else:
            out["vl.dist_to_val_atr"] = None
        if vah is not None:
            out["vl.dist_to_vah_atr"] = _safe_div(c_now - vah, atr14)
        else:
            out["vl.dist_to_vah_atr"] = None
    else:
        out["vl.dist_to_poc_atr"] = None
        out["vl.dist_to_val_atr"] = None
        out["vl.dist_to_vah_atr"] = None

    # ── C. Volatility / compression ────────────────────────────────────────
    atr_hist: list[float] = []
    for end in range(W_ATR + 1, len(bars) + 1):
        sub = bars[:end]
        a = _atr(sub, W_ATR)
        if a is not None:
            atr_hist.append(a)
    if atr14 and atr_hist:
        hist = atr_hist[-W_ATR_LONG:]
        out["vol.atr_percentile_60"] = _percentile_rank_window(hist, atr14)
    else:
        out["vol.atr_percentile_60"] = None

    if atr5 and atr20 and atr20 > EPS:
        out["vol.atr_expansion_ratio_5_20"] = atr5 / atr20
    else:
        out["vol.atr_expansion_ratio_5_20"] = None

    last_bar = bars[-1]
    h0 = _f(last_bar.get("high"))
    l0 = _f(last_bar.get("low"))
    if h0 and l0 and atr14:
        rng = h0 - l0
        out["vol.range_compression_last"] = _safe_div(rng, atr14)
    else:
        out["vol.range_compression_last"] = None

    rets: list[float] = []
    for i in range(1, min(W_RV + 1, len(closes))):
        a, b = closes[-i], closes[-i - 1]
        if a is not None and b is not None and b > EPS and a > EPS:
            rets.append(math.log(a / b))
    if len(rets) >= 10:
        mu = sum(rets) / len(rets)
        var = sum((r - mu) ** 2 for r in rets) / max(len(rets) - 1, 1)
        rv = math.sqrt(max(var, EPS)) * math.sqrt(252.0 * 390.0)  # rough annualization for 1m bars
        # rolling window of rv estimates — simplified: percentile of |ret|
        abs_rets = [abs(r) for r in rets]
        out["vol.realized_vol_pctile_last30"] = _percentile_rank_window(abs_rets, abs_rets[-1])
        out["vol.realized_vol_annualized_proxy"] = rv
    else:
        out["vol.realized_vol_pctile_last30"] = None
        out["vol.realized_vol_annualized_proxy"] = None

    comp_window = 10
    if len(bars) > comp_window + 2 and atr14 and h0 and l0:
        narrow: list[float] = []
        for j in range(comp_window, len(bars)):
            segj = bars[j - comp_window : j]
            hs = [_f(x.get("high")) for x in segj]
            ls = [_f(x.get("low")) for x in segj]
            if not (all(h is not None for h in hs) and all(l is not None for l in ls)):
                continue
            atr_j = _atr(bars[: j + 1], W_ATR)
            if atr_j and atr_j > EPS:
                span = max(hs) - min(ls)  # type: ignore[operator]
                r = _safe_div(span, atr_j)
                if r is not None:
                    narrow.append(r)
        was_tight = bool(narrow) and min(narrow) < 0.9
        last_rng = h0 - l0
        out["vol.breakout_from_compression_flag"] = (
            1.0 if (was_tight and last_rng > 1.2 * atr14) else 0.0
        )
    else:
        out["vol.breakout_from_compression_flag"] = None

    # ── D. Candle / imbalance ────────────────────────────────────────────────
    o0 = _f(last_bar.get("open"))
    if o0 is None:
        o0 = _f(bars[-2].get("close")) if len(bars) > 1 else c_now
    if h0 and l0 and abs(h0 - l0) > EPS:
        body = abs(c_now - o0)
        out["cnd.body_range_ratio"] = body / (h0 - l0)
        uw = h0 - max(o0, c_now)
        lw = min(o0, c_now) - l0
        out["cnd.wick_asymmetry"] = _safe_div(uw - lw, h0 - l0)
        out["cnd.close_location_in_bar"] = _safe_div(c_now - l0, h0 - l0)
    else:
        out["cnd.body_range_ratio"] = None
        out["cnd.wick_asymmetry"] = None
        out["cnd.close_location_in_bar"] = None

    impulse = 0
    dir_sign: float | None = None
    for i in range(len(bars) - 1, 0, -1):
        c = closes[i]
        p = closes[i - 1]
        if c is None or p is None:
            break
        d = 1.0 if c > p else (-1.0 if c < p else 0.0)
        if d == 0.0:
            break
        if dir_sign is None:
            dir_sign = d
            impulse = 1
        elif d == dir_sign:
            impulse += 1
        else:
            break
    out["cnd.consecutive_impulse_count"] = float(min(impulse, 20))

    if len(bars) >= 2:
        prev_c = _f(bars[-2].get("close"))
        if prev_c and o0:
            gap = o0 - prev_c
            out["cnd.gap_open_vs_prev_close_pts"] = gap
            out["cnd.gap_flag"] = 1.0 if abs(gap) > (atr14 or 0.05) * 0.25 else 0.0
        else:
            out["cnd.gap_open_vs_prev_close_pts"] = None
            out["cnd.gap_flag"] = None
    else:
        out["cnd.gap_open_vs_prev_close_pts"] = None
        out["cnd.gap_flag"] = None

    br = out.get("cnd.body_range_ratio")
    ic = float(out.get("cnd.consecutive_impulse_count") or 0.0)
    out["cnd.drive_flag"] = 1.0 if (isinstance(br, float) and br > 0.65) else 0.0
    out["cnd.stall_flag"] = 1.0 if (isinstance(br, float) and br < 0.25 and ic >= 3.0) else 0.0

    # ── E. Multi-timeframe (from 1m only) ─────────────────────────────────
    out["mtf.trend_1m_sign"] = _sign_trend(sl)
    tail5 = bars[-(5 * 14) :] if len(bars) >= 5 * 6 else bars
    agg5 = _aggregate_bars(tail5, 5)
    if len(agg5) >= 4:
        c5 = [float(x["close"]) for x in agg5[-6:]]
        s5 = _ols_log_slope_close(c5)
        out["mtf.trend_5m_from_1m_sign"] = _sign_trend(s5)
    else:
        out["mtf.trend_5m_from_1m_sign"] = None

    tail15 = bars[-(15 * 8) :] if len(bars) >= 15 * 4 else bars
    agg15 = _aggregate_bars(tail15, 15)
    if len(agg15) >= 3:
        c15 = [float(x["close"]) for x in agg15[-4:]]
        s15 = _ols_log_slope_close(c15)
        out["mtf.bias_15m_from_1m_sign"] = _sign_trend(s15)
    else:
        out["mtf.bias_15m_from_1m_sign"] = None

    s1 = out["mtf.trend_1m_sign"]
    s5 = out["mtf.trend_5m_from_1m_sign"]
    s15 = out["mtf.bias_15m_from_1m_sign"]
    if s1 is None or s5 is None or s15 is None:
        out["mtf.alignment_state"] = None
    elif s1 == s5 == s15 and s1 != 0.0:
        out["mtf.alignment_state"] = 1.0
    elif s1 != 0.0 and s5 != 0.0 and (s1 * s5 < 0 or s1 * s15 < 0):
        out["mtf.alignment_state"] = -1.0
    else:
        out["mtf.alignment_state"] = 0.0

    # ── F. Participation ─────────────────────────────────────────────────
    vols = [_f(b.get("volume")) for b in bars[-W_VOL_PART:]]
    vols = [v for v in vols if v is not None]
    v_last = _f(last_bar.get("volume"))
    if vols and v_last is not None:
        vm = sum(vols) / len(vols)
        out["part.relative_volume"] = _safe_div(v_last, vm) if vm > EPS else None
        out["part.volume_spike_pctile"] = _percentile_rank_window(vols, v_last)
    else:
        out["part.relative_volume"] = None
        out["part.volume_spike_pctile"] = None

    tr_sum = 0.0
    for i in range(max(1, len(bars) - 5), len(bars)):
        bd = dict(bars[i])
        if i > 0:
            bd["_prev_close"] = _f(bars[i - 1].get("close"))
        tr_sum += _tr(bd)
    body_sum = abs(c_now - o0) if o0 else 0.0
    if tr_sum > EPS:
        out["part.move_efficiency_last_vs_tr5"] = body_sum / tr_sum
    else:
        out["part.move_efficiency_last_vs_tr5"] = None

    return out


def compute_signal_layer_v1_from_db(
    conn: Any,
    ticker: str,
    decision_ts_utc: float,
    inp: Any | None = None,
    *,
    max_bars: int = DEFAULT_MAX_BARS,
) -> dict[str, Any]:
    """Convenience: load bars then compute layer."""
    bars = load_bars_before_decision(conn, ticker, decision_ts_utc, max_bars=max_bars)
    return compute_signal_layer_v1(bars, decision_ts_utc=decision_ts_utc, inp=inp)


def _sqlite_conn_from_db(db: Any) -> Any:
    """Resolve a sqlite connection from EdDB or a raw connection."""
    if db is None:
        return None
    fn = getattr(db, "_connect", None)
    if callable(fn):
        return fn()
    return db if hasattr(db, "execute") else None


def compute_signal_layer_v1_for_calibration(
    db: Any,
    ticker: str,
    decision_ts_utc: float,
    inp: Any | None = None,
) -> dict[str, Any]:
    """Load 1m bars from EdDB (or sqlite-like) and compute the v1 layer; read-only."""
    conn = _sqlite_conn_from_db(db)
    if conn is None:
        return {"meta.error": "no_db_connection", "meta.decision_ts_utc": float(decision_ts_utc)}
    try:
        return compute_signal_layer_v1_from_db(conn, ticker, decision_ts_utc, inp)
    finally:
        try:
            close = getattr(conn, "close", None)
            if callable(close):
                close()
        except Exception:
            log.debug("signal_layer_v1: connection close failed", exc_info=True)


def layer_direction_policy(layer: Mapping[str, Any], *, thresh: float = 0.85) -> str:
    """
    Simple interpretable policy from the v1 layer (not the fusion model).
    Returns long | short | wait from composite score (roughly in [-4,4]).
    """
    s = 0.0
    v1 = layer.get("ps.rolling_trend_slope_log20")
    if isinstance(v1, (int, float)):
        s += _clip(float(v1) * 120.0, -1.25, 1.25)
    vz = layer.get("vl.vwap_zscore")
    if isinstance(vz, (int, float)):
        s += _clip(float(vz) / 2.5, -1.25, 1.25)
    for k in ("mtf.trend_1m_sign", "mtf.trend_5m_from_1m_sign", "mtf.bias_15m_from_1m_sign"):
        v = layer.get(k)
        if v is None:
            continue
        if isinstance(v, (int, float)):
            s += float(v)
    if s > thresh:
        return "long"
    if s < -thresh:
        return "short"
    return "wait"


def signal_layer_v1_to_direction_probs(
    layer: Mapping[str, Any],
) -> Optional[tuple[float, float, float]]:
    """
    Map numeric v1 layer to a calibrated (up, down, flat) triple for fusion blending.
    Uses directional score → softmax; flat mass rises when |score| is small.
    Returns None when bar history is insufficient (no uniform 1/3 placeholder).
    """
    fn = flatten_numeric_features(layer)
    if meta_n_bars_int(layer) < 25:
        return None

    score = 0.0
    s = fn.get("ps.rolling_trend_slope_log20")
    if s is not None:
        score += float(s) * 45.0
    vz = fn.get("vl.vwap_zscore")
    if vz is not None:
        score += float(vz) * 0.18
    for k, w in (
        ("mtf.trend_1m_sign", 0.42),
        ("mtf.trend_5m_from_1m_sign", 0.38),
        ("mtf.bias_15m_from_1m_sign", 0.28),
    ):
        v = layer.get(k)
        if v is None:
            continue
        if isinstance(v, (int, float)):
            score += float(v) * w

    score = max(-3.0, min(3.0, score))

    eu = math.exp(score)
    ed = math.exp(-score)
    flat_boost = max(0.15, 0.95 - 0.22 * abs(score))
    ef = math.exp(flat_boost)
    t = eu + ed + ef
    return float(eu / t), float(ed / t), float(ef / t)


def flatten_numeric_features(layer: Mapping[str, Any]) -> dict[str, float]:
    """Strip meta.* keys; keep only numeric features for correlation matrices."""
    out: dict[str, float] = {}
    for k, v in layer.items():
        if k.startswith("meta."):
            continue
        if isinstance(v, bool):
            out[k] = 1.0 if v else 0.0
        elif isinstance(v, (int, float)) and not isinstance(v, bool):
            fv = float(v)
            if not (math.isnan(fv) or math.isinf(fv)):
                out[k] = fv
    return out
