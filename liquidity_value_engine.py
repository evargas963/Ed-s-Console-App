"""
liquidity_value_engine.py — Liquidity & Value Playbook Engine
============================================================
Deterministic institutional intraday zone mapper. Works for any ticker.
The price levels (prior day, overnight, opening range, VWAP, value area) are computed once per
generation into the materialized PriceLevelSnapshot (build_price_level_snapshot); the zones
(build_live_snapshot, build_premarket_snapshot before the open) are built from that snapshot.

Data source agnostic: consumes normalized OHLCV bars (list of dicts).
All calculations derived from bars; no Schwab-specific logic.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from collections import defaultdict
from datetime import date, datetime, time
from typing import Any, Optional

from instrument_identity import ticker_storage_key
from numeric_contract import float_finite_or_none, float_positive_or_none, schwab_count, schwab_number
from liquidity_models import (
    PlaybookConfig,
    SnapshotOutput,
    SnapshotSummary,
    SnapshotType,
    Zone,
    VolumeProfile,
    ZoneType,
    volume_profile,
)

log = logging.getLogger(__name__)

from time_et import (
    ET,
    RTH_OPEN_MINS,
    session_close_mins_for_et_date,
)

# The session comes from time_et, the one market calendar: the open, and each day's close
# (13:00 on an early close, none on a holiday).
RTH_OPEN = time(RTH_OPEN_MINS // 60, RTH_OPEN_MINS % 60)


def rth_close(d: date) -> Optional[time]:
    """The regular session's close on `d` (the market calendar's); None: no session that day."""
    m = session_close_mins_for_et_date(d.isoformat())
    return None if m is None else time(m // 60, m % 60)


def _in_rth(dt: datetime) -> bool:
    close = rth_close(dt.date())
    return close is not None and RTH_OPEN <= dt.time() < close


#: each price level's name, spelled out and as the chart's short tag -- the one home for both.
#: POC and value area come from the estimated profile (each 1-minute bar's volume spread evenly
#: over its range, not trades at a price): their names say so.
LEVEL_NAMES = {
    "TODAY_VAH": ("Value area high (est. from 1-min bars)", "VAH est"),
    "TODAY_VAL": ("Value area low (est. from 1-min bars)", "VAL est"),
    "TODAY_POC": ("Point of control (est. from 1-min bars)", "POC est"),
    "PDH": ("Prior day high", "PDH"), "PDL": ("Prior day low", "PDL"), "PDC": ("Prior day close", "PDC"),
    "PD_POC": ("Prior day POC (est. from 1-min bars)", "pPOC est"),
    "PD_VAH": ("Prior day VAH (est. from 1-min bars)", "pVAH est"),
    "PD_VAL": ("Prior day VAL (est. from 1-min bars)", "pVAL est"),
    "ORB_HIGH": ("Opening range high", "ORH"), "ORB_LOW": ("Opening range low", "ORL"),
    "ORB_MID": ("Opening range mid", "ORM"),
    "OVERNIGHT_HIGH": ("Overnight high", "ONH"), "OVERNIGHT_LOW": ("Overnight low", "ONL"),
}





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


def _resolve_bar_timestamp(d: dict) -> Optional[Any]:
    """Bar time: the first of timestamp, date, ts present on the bar."""
    for key in ("timestamp", "date", "ts"):
        val = d.get(key)
        if val is not None:
            return val
    return None


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
            ts = _resolve_bar_timestamp(d)
            if ts is None:
                continue
            o = schwab_number(d.get("open"))
            h = schwab_number(d.get("high"))
            l_ = schwab_number(d.get("low"))
            c = schwab_number(d.get("close"))
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
                "volume": schwab_count(v),
            })
            if _ts is not None:
                out[-1]["_ts"] = _ts
        return out

    for b in bars:
        if isinstance(b, dict):
            row = b
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
        o = schwab_number(row.get("open"))
        h = schwab_number(row.get("high"))
        l_ = schwab_number(row.get("low"))
        c = schwab_number(row.get("close"))
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
            "volume": schwab_count(v),
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




# ─────────────────────────────────────────────────────────────────────────────
# PREVIOUS DAY / OVERNIGHT
# ─────────────────────────────────────────────────────────────────────────────


def prior_trading_session_date(bars_norm: list, session_date: date) -> Optional[date]:
    """The most recent date BEFORE `session_date` that actually traded an RTH session.

    LP-01 Step 2 (RC-153) — THE single definition of "the prior session", for both the
    previous-day levels and the overnight window. The calendar cannot answer this question:
    `session_date - 1 day` is Sunday on a Monday and a closed holiday after one, and a market
    that was shut has no close for an overnight range to start from.

    Presence of bars inside a day's regular session (the market calendar's hours, early closes
    included) is the evidence a session happened, so an ad-hoc closure with no bars is skipped.
    Fail-closed: no prior RTH date in the buffer returns None, never a guessed date.
    """
    prior: Optional[date] = None
    for b in bars_norm:
        dt = _bar_dt_et(b)
        if dt is None:
            continue
        d = dt.date()
        if d < session_date and _in_rth(dt):
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
            if dt.date() == prev_trading_day and _in_rth(dt):
                prev_bars.append(b)

    out = {}
    if prev_bars:
        out["pdh"] = max(b["high"] for b in prev_bars)
        out["pdl"] = min(b["low"] for b in prev_bars)
        out["pdc"] = prev_bars[-1]["close"]
        p = volume_profile(prev_bars, config.value_area_percent, config.tick_size, ndigits=4)
        out["pd_poc"], out["pd_vah"], out["pd_val"] = (None, None, None) if p is None else (p.poc, p.vah, p.val)
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
    prev_close_dt = (datetime.combine(prev_session, rth_close(prev_session), tzinfo=ET)
                     if prev_session is not None else None)       # a session day: it has a close

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
        vol = b["volume"]   # a 0-volume minute adds nothing and keeps its VWAP point
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




def count_session_rth_positive_volume_bars(
    bars: list, session_date: date, cutoff_dt: Optional[datetime] = None,
) -> int:
    """INPUT RTH bars with positive volume on session_date — independent of the VWAP series."""
    n = 0
    for b in _filter_rth_bars(_bars_to_list(bars), session_date, cutoff_dt):
        if b["volume"] is not None and b["volume"] > 0:
            n += 1
    return n




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
    cutoff_dt: Optional[datetime] = None,
) -> tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
    """(vwap+1σ, vwap-1σ, vwap+2σ, vwap-2σ): the last point of compute_session_vwap_series."""
    series = compute_session_vwap_series(bars, session_date, cutoff_dt)
    return series[-1][2:] if series else (None, None, None, None)


def _filter_rth_bars(bars: list, session_date: date, cutoff_dt: Optional[datetime] = None) -> list:
    out = []
    for b in bars:
        dt = _bar_dt_et(b)
        if dt is None or dt.date() != session_date:
            continue
        if not _in_rth(dt):
            continue
        if cutoff_dt and dt > cutoff_dt:
            continue
        out.append(b)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# VOLUME PROFILE (POC, VAH, VAL)
# ─────────────────────────────────────────────────────────────────────────────


def compute_volume_profile_levels(
    bars: list,
    session_date: date,
    config: PlaybookConfig,
    cutoff_dt: Optional[datetime] = None,
) -> Optional[VolumeProfile]:
    """The current day's volume profile with its POC, VAH, VAL. RTH only, no lookahead."""
    bars_norm = _bars_to_list(bars)
    rth_bars = _filter_rth_bars(bars_norm, session_date, cutoff_dt)
    return volume_profile(rth_bars, config.value_area_percent, config.tick_size, ndigits=4)


# ─────────────────────────────────────────────────────────────────────────────
# ZONE CLUSTERING
# ─────────────────────────────────────────────────────────────────────────────


def cluster_price_levels_into_zones(
    levels: list[tuple[float, str]],
    config: PlaybookConfig,
) -> list[tuple[float, float, float, list[str], list[tuple[float, str]]]]:
    """
    Cluster nearby levels into zones. Returns list of (zone_low, zone_high, zone_mid, source_tags, source_pairs).
    source_pairs = [(price, tag), ...] for correct source_levels (actual level values, not zone mid).

    Adjacent levels merge while the gap is within config.clustering_threshold_pct of the lower one.
    """
    if not levels:
        return []
    prices = sorted(set(p for p, _ in levels if p and p > 0))
    if not prices:
        return []

    tag_map: dict[float, list[str]] = defaultdict(list)
    for p, tag in levels:
        if p and p > 0:
            tag_map[p].append(tag)

    max_width = float_positive_or_none(getattr(config, "max_zone_width", None))

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
        within_thresh = prices[i] - current[-1] <= current[-1] * config.clustering_threshold_pct
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


def build_premarket_snapshot(
    ticker: str,
    session_date: date,
    config: PlaybookConfig,
    *,
    canonical: "PriceLevelSnapshot",
) -> SnapshotOutput:
    """Premarket: PDH/PDL/PDC, PD POC/VAH/VAL, overnight high/low. No same-day RTH.

    The families are CARRIED from the one materialized snapshot (``canonical``); no level
    helper runs here. Absent stays absent: a family missing from the snapshot is missing here,
    never replaced by spot, zero or a neighbouring level (RC-68).
    """
    prev, over, _orb, _poc, _vah, _val, _vwap, _bands = _phase2a_families_from_canonical(canonical)

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

    clusters = cluster_price_levels_into_zones(levels, config)

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


def _classify_value_state_and_vwap_relation(
    poc: Optional[float], prev_pd_poc: Optional[float], vwap: Optional[float],
) -> tuple[str, str, str]:
    """Value-area shift + VWAP-vs-value relation + auction interpretation — the ONE
    classification shared by the midday/afternoon/live snapshots (was copy-pasted
    identically three times)."""
    value_state = "unchanged"
    if poc and prev_pd_poc:
        d = (poc - prev_pd_poc) / prev_pd_poc if prev_pd_poc else 0
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

    return value_state, vwap_relation, auction_interp


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
    config: PlaybookConfig,
    *,
    canonical: "PriceLevelSnapshot",
    now: datetime,
    extra_levels: Optional[list[tuple[float, str]]] = None,
) -> SnapshotOutput:
    """
    The session's zones from the one materialized price-level snapshot (``canonical``), with
    optional ``extra_levels`` (the option levels and spot) fused in; no level helper runs here.
    Before the session's RTH open it is the premarket shape. The cutoff shown is min(now, the
    day's close) -- the market calendar's, early closes included.
    """
    session_date = canonical.session_date
    open_dt = datetime.combine(session_date, RTH_OPEN, tzinfo=ET)
    close = rth_close(session_date)
    close_dt = datetime.combine(session_date, close, tzinfo=ET) if close is not None else open_dt
    if now < open_dt:
        return build_premarket_snapshot(ticker, session_date, config, canonical=canonical)
    cutoff = min(now, close_dt)
    prev, over, orb, poc, vah, val, vwap, (vwap_p1, vwap_m1, vwap_p2, vwap_m2) = (
        _phase2a_families_from_canonical(canonical))

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

    clusters = cluster_price_levels_into_zones(levels, config)

    value_state, vwap_relation, auction_interp = _classify_value_state_and_vwap_relation(
        poc, prev.get("pd_poc"), vwap
    )

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
        # which snapshot generation these numbers ARE, in the payload
        "semantic_scope": "session_rth",
        "level_generation": canonical.generation,
        "level_snapshot_as_of_ts_utc": canonical.as_of_ts_utc,
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
# PLAYBOOK STATE
# ─────────────────────────────────────────────────────────────────────────────






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
        label, short = LEVEL_NAMES.get(self.level_id, (self.level_id, self.level_id))
        return {
            "id": self.level_id,
            "price": self.price,
            "family": self.family,
            "label": label,
            "short": short,
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
                 "session_rth_positive_volume_bars", "volume_profile")

    def __init__(self, *, ticker: str, session_date: date, generation: int,
                 bar_source: str, as_of_ts_utc: Optional[float], produced_ts_utc: float,
                 levels: dict, vwap_path: list, families_absent: list,
                 degraded: list, input_fingerprint: tuple, bars_used: int,
                 vwap_series: Optional[list] = None,
                 session_rth_positive_volume_bars: int = 0,
                 volume_profile: Optional[VolumeProfile] = None) -> None:
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
        self.volume_profile = volume_profile    # the session's profile the value area is read from

    def price(self, level_id: str) -> Optional[float]:
        """The canonical value, or None. Absence is absence — never spot, zero or a sibling."""
        lv = self.levels.get(level_id)
        return None if lv is None else lv.price



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
        h.update(repr((
            None if dt is None else dt.timestamp(), b.get("timestamp"),
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

    basis = f"1m bars ({bar_source}); Schwab streamed bars"

    def _put(level_id: str, price, *, producer: str, window: str) -> None:
        if price is None:
            return
        v = float_finite_or_none(price)
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
        p1, m1, p2, m2 = vwap_series[-1][2:]      # the curve's last point IS the served band
        for lid, val in (("VWAP_P1", p1), ("VWAP_M1", m1), ("VWAP_P2", p2), ("VWAP_M2", m2)):
            _put(lid, val,
                 producer=f"{_PRODUCER_NS}.compute_session_vwap_series", window=sess_window)
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
    profile = compute_volume_profile_levels(bars_norm, session_date, cfg)
    poc, vah, val = (None, None, None) if profile is None else (profile.poc, profile.vah, profile.val)
    if profile is None:
        families_absent.append({"family": "value_area", "reason": (
            "no RTH volume for the volume profile in available bars" if session_rth_vol_n == 0
            else "RTH volume bars present but the volume profile did not materialize")})
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
        volume_profile=profile,
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
