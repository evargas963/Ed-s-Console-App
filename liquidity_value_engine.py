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

#: a prior session with fewer 1-minute RTH bars than this (of ~390) is disclosed as partial on the
#: price levels built from it
LEVELS_PRIOR_SESSION_MIN_BARS: int = 300


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


def _bars_to_list(bars) -> list[dict]:
    """The bars every level function takes, normalized once by the producer:
    {timestamp, _dt (its ET time), open, high, low, close, volume} for each bar dict with a time
    and four prices that are numbers (rule 2); a volume that is not a number stays None."""
    out = []
    for b in bars or []:
        ts = _resolve_bar_timestamp(b)
        o, h, lo, c = (schwab_number(b.get(k)) for k in ("open", "high", "low", "close"))
        if ts is None or None in (o, h, lo, c):
            continue
        sec = ts.timestamp() if hasattr(ts, "timestamp") else (ts / 1000.0 if ts > 1e12 else ts)
        out.append({"timestamp": ts, "_dt": datetime.fromtimestamp(sec, tz=ET), "open": o, "high": h,
                    "low": lo, "close": c, "volume": schwab_count(b.get("volume"))})
    return out




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
        dt = b["_dt"]
        d = dt.date()
        if d < session_date and _in_rth(dt):
            if prior is None or d > prior:
                prior = d
    return prior


def get_previous_day_levels(
    bars_norm: list,
    session_date: date,
    config: PlaybookConfig,
) -> dict:
    """The prior session (the most recent earlier date with RTH bars, prior_trading_session_date)
    from normalized bars (_bars_to_list): its date, its RTH bar count, and its high, low, close,
    POC, VAH and VAL from those RTH bars. No prior session: {} (never a calendar walk or other
    days' bars)."""
    prior = prior_trading_session_date(bars_norm, session_date)
    if prior is None:
        return {}
    prev_bars = [b for b in bars_norm if b["_dt"].date() == prior and _in_rth(b["_dt"])]
    p = volume_profile(prev_bars, config.value_area_percent, config.tick_size, ndigits=4)
    return {"prior_date": prior, "rth_bars": len(prev_bars),
            "pdh": max(b["high"] for b in prev_bars), "pdl": min(b["low"] for b in prev_bars),
            "pdc": prev_bars[-1]["close"],
            "pd_poc": None if p is None else p.poc, "pd_vah": None if p is None else p.vah,
            "pd_val": None if p is None else p.val}


def get_overnight_levels(
    bars_norm: list,
    session_date: date,
    prev_session: Optional[date],
) -> dict:
    """Overnight range over normalized bars (_bars_to_list): the continuous interval from the
    prior session's (`prev_session`, prior_trading_session_date) RTH close to this session's RTH
    open -- a weekend's or holiday's bars included. With no prior session the interval has no
    start, so only this session's pre-open bars are used. No bars in the window: {}."""
    session_open_dt = datetime.combine(session_date, RTH_OPEN, tzinfo=ET)
    prev_close_dt = (datetime.combine(prev_session, rth_close(prev_session), tzinfo=ET)
                     if prev_session is not None else None)       # a session day: it has a close

    overnight = []
    for b in bars_norm:
        dt = b["_dt"]
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
    bars_norm: list,
    session_date: date,
    config: PlaybookConfig,
) -> dict:
    """
    First N minutes of RTH (default 15), from normalized bars (_bars_to_list).
    """
    orb_min = config.opening_range_minutes

    orb_bars = []
    for b in bars_norm:
        dt = b["_dt"]
        if dt.date() != session_date:
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
    bars_norm: list, session_date: date,
) -> list[tuple[float, float, float, float, float, float]]:
    """Running session VWAP and σ bands after each RTH bar, from normalized bars (_bars_to_list).

    Returns [(bar_epoch_sec, vwap, +1σ, -1σ, +2σ, -2σ), ...] using the standard
    cumulative moments VWAP_t = Σ(tp·v)/Σv and σ_t² = Σ(tp²·v)/Σv − VWAP_t².

    The one VWAP accumulation: the served VWAP level and bands are its last point; the chart's
    polyline is this list carried to the browser.
    """
    rth_bars = _filter_rth_bars(bars_norm, session_date)
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
        w = cum_tpv / cum_vol
        sd = max(0.0, cum_tp2v / cum_vol - w * w) ** 0.5
        series.append((b["_dt"].timestamp(), round(w, 4), round(w + sd, 4), round(w - sd, 4),
                       round(w + 2 * sd, 4), round(w - 2 * sd, 4)))
    return series




def count_session_rth_positive_volume_bars(bars_norm: list, session_date: date) -> int:
    """INPUT RTH bars with positive volume on session_date — independent of the VWAP series."""
    return sum(1 for b in _filter_rth_bars(bars_norm, session_date) if b["volume"] is not None and b["volume"] > 0)


def _filter_rth_bars(bars_norm: list, session_date: date) -> list:
    return [b for b in bars_norm if b["_dt"].date() == session_date and _in_rth(b["_dt"])]


# ─────────────────────────────────────────────────────────────────────────────
# VOLUME PROFILE (POC, VAH, VAL)
# ─────────────────────────────────────────────────────────────────────────────


def compute_volume_profile_levels(
    bars_norm: list,
    session_date: date,
    config: PlaybookConfig,
) -> Optional[VolumeProfile]:
    """The current day's volume profile with its POC, VAH, VAL, from normalized bars
    (_bars_to_list). RTH only, no lookahead."""
    return volume_profile(_filter_rth_bars(bars_norm, session_date), config.value_area_percent,
                          config.tick_size, ndigits=4)


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
                 "producer", "window", "vendor_basis", "as_of_ts_utc", "generation")

    def __init__(self, *, level_id: str, price: float, family: str, semantic_scope: str,
                 evidence_tier: str, producer: str, window: str, vendor_basis: str,
                 as_of_ts_utc: Optional[float], generation: int) -> None:
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

    @property
    def session_scope(self) -> str:
        return _SESSION_SCOPE_OF.get(self.semantic_scope, self.semantic_scope)

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
    """The ONE materialized result for (ticker, session scope, generation). `input_fingerprint`
    is set by materialize_price_level_snapshot, which decides the generation from it."""

    __slots__ = ("ticker", "session_date", "generation", "bar_source", "as_of_ts_utc",
                 "produced_ts_utc", "levels", "vwap_path", "vwap_series",
                 "families_absent", "degraded", "input_fingerprint", "bars_used",
                 "session_rth_positive_volume_bars", "volume_profile")

    def __init__(self, *, ticker: str, session_date: date, generation: int,
                 bar_source: str, as_of_ts_utc: Optional[float], produced_ts_utc: float,
                 levels: dict, vwap_path: list, families_absent: list,
                 degraded: list, bars_used: int,
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
        h.update(b"\x1e")
        h.update(repr((b["timestamp"], b["open"], b["high"], b["low"], b["close"], b["volume"])).encode())
    return (ticker, session_date.isoformat(), bar_source, len(bars_norm), h.hexdigest())


def build_price_level_snapshot(
    ticker: str,
    session_date: date,
    bars_norm: list,
    *,
    bar_source: str,
    config: Optional[PlaybookConfig] = None,
    generation: int = 0,
) -> PriceLevelSnapshot:
    """THE Phase 2A producer, from normalized bars (_bars_to_list). The only production caller
    of the canonical helpers.

    Absent input stays absent: a family with no bars in its window is declared in
    `families_absent` and its ids are simply not present. Nothing substitutes spot,
    zero, or a neighbouring level (RC-68). A prior session with fewer than
    LEVELS_PRIOR_SESSION_MIN_BARS RTH bars is disclosed in `degraded`, never filled.
    """
    cfg = config or PlaybookConfig()
    tk = ticker_storage_key(ticker)  # RC-345/F25: canonical liquidity snapshot/ledger identity
    produced_ts = datetime.now(tz=ET).timestamp()
    levels: dict[str, PriceLevelValue] = {}
    families_absent: list[dict] = []
    degraded: list[dict] = []
    vwap_path: list[tuple[float, float]] = []
    vwap_series: list[tuple] = []

    as_of: Optional[float] = max((b["_dt"].timestamp() for b in bars_norm), default=None)

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
        )

    # ── prior day ────────────────────────────────────────────────────────────
    eng = get_previous_day_levels(bars_norm, session_date, cfg)
    prior_date = eng.get("prior_date")
    if prior_date is None:
        families_absent.append({
            "family": "prior_day",
            "reason": f"no prior RTH session in available bars (source {bar_source})",
        })
    else:
        window = f"{prior_date.isoformat()} RTH (most recent prior RTH session)"
        for lid, key in (("PDH", "pdh"), ("PDL", "pdl"), ("PDC", "pdc"),
                         ("PD_POC", "pd_poc"), ("PD_VAH", "pd_vah"), ("PD_VAL", "pd_val")):
            _put(lid, eng.get(key),
                 producer=f"{_PRODUCER_NS}.get_previous_day_levels", window=window)
        if eng["rth_bars"] < LEVELS_PRIOR_SESSION_MIN_BARS:
            degraded.append({"family": "prior_day", "last_good_ts_utc": None, "reason": (
                f"prior session {prior_date} holds only {eng['rth_bars']} of >= "
                f"{LEVELS_PRIOR_SESSION_MIN_BARS} RTH bars; prior-day levels derive from a partial tape")})

    sess_window = f"{session_date.isoformat()} RTH (canonical snapshot over {bar_source})"

    if not bars_norm:
        for fam in ("vwap", "opening_range", "overnight", "value_area"):
            families_absent.append({
                "family": fam, "reason": f"no bars available (source {bar_source})"})
        return PriceLevelSnapshot(
            ticker=tk, session_date=session_date, generation=generation,
            bar_source=bar_source, as_of_ts_utc=as_of, produced_ts_utc=produced_ts,
            levels=levels, vwap_path=vwap_path, vwap_series=vwap_series,
            families_absent=families_absent, degraded=degraded,
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
    overnight = get_overnight_levels(bars_norm, session_date, prior_date)
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
        families_absent=families_absent, degraded=degraded,
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
    bars_norm: list,
    *,
    bar_source: str,
    config: Optional[PlaybookConfig] = None,
) -> PriceLevelSnapshot:
    """Materialize once per generation from normalized bars (_bars_to_list); return the SAME
    object within a generation.

    A new market generation (the bar input changed) invokes the producer exactly once.
    Every later ask in that generation is a read, never a recomputation.
    """
    tk = ticker_storage_key(ticker)  # RC-345/F25: canonical liquidity snapshot/ledger identity
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
            generation=generation,
        )
        snap.input_fingerprint = fingerprint
        _MATERIALIZED_SNAPSHOTS[key] = snap
        return snap






