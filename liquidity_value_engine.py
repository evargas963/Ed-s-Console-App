"""liquidity_value_engine.py — Liquidity & Value Playbook Engine.

Deterministic institutional intraday zone mapper. Works for any ticker.
The price levels (prior day, overnight, opening range, VWAP, value area) are computed once per
generation into the materialized PriceLevelSnapshot (build_price_level_snapshot); the zones
(build_live_snapshot, build_premarket_snapshot before the open) are built from that snapshot.

Data source agnostic: consumes normalized OHLCV bars (list of dicts).
All calculations derived from bars; no Schwab-specific logic.
"""

from __future__ import annotations

import functools
import hashlib
import logging
import struct
import threading
from collections import defaultdict
from datetime import date, datetime, timedelta

from instrument_identity import ticker_storage_key
from liquidity_models import (
    PlaybookConfig,
    SnapshotOutput,
    SnapshotSummary,
    SnapshotType,
    VolumeProfile,
    Zone,
    ZoneType,
    volume_profile,
)
from numeric_contract import float_finite_or_none, float_positive_or_none
from time_et import ET, session

log = logging.getLogger(__name__)

#: a prior session with fewer 1-minute RTH bars than this (of ~390) is disclosed as partial on the
#: price levels built from it
LEVELS_PRIOR_SESSION_MIN_BARS: int = 300

#: where the prior day's high, low and close come from: Schwab sends them on its daily candle
DAILY_CANDLE_BASIS = "Schwab's daily candle (/pricehistory, frequencyType daily), as sent"


def _regular(d: date) -> tuple[datetime, datetime] | None:
    """`d`'s regular session (open, close) as Schwab's /markets sent it (time_et.session).

    None: no regular session that day, or Schwab's answer for it is not held.
    """
    s = session(d.isoformat())
    if s is None or not s.regular:
        return None
    return s.regular[0][0], s.regular[-1][1]


def _in_rth(dt: datetime) -> bool:
    regular = _regular(dt.date())
    return regular is not None and regular[0] <= dt < regular[1]


#: each price level's name, spelled out and as the chart's short tag -- the one home for both.
#: POC and value area come from the estimated profile (each 1-minute bar's volume spread evenly
#: over its range, not trades at a price): their names say so.
LEVEL_NAMES = {
    "TODAY_VAH": ("Value area high (est. from 1-min bars)", "VAH est"),
    "TODAY_VAL": ("Value area low (est. from 1-min bars)", "VAL est"),
    "TODAY_POC": ("Point of control (est. from 1-min bars)", "POC est"),
    "PDH": ("Prior day high", "PDH"),
    "PDL": ("Prior day low", "PDL"),
    "PDC": ("Prior day close", "PDC"),
    "PD_POC": ("Prior day POC (est. from 1-min bars)", "pPOC est"),
    "PD_VAH": ("Prior day VAH (est. from 1-min bars)", "pVAH est"),
    "PD_VAL": ("Prior day VAL (est. from 1-min bars)", "pVAL est"),
    "ORB_HIGH": ("Opening range high", "ORH"),
    "ORB_LOW": ("Opening range low", "ORL"),
    "ORB_MID": ("Opening range mid", "ORM"),
    "OVERNIGHT_HIGH": ("Overnight high", "ONH"),
    "OVERNIGHT_LOW": ("Overnight low", "ONL"),
}


def bars_from_candles(candles) -> list[dict]:
    """Return the bars every level function takes, from the bar writer's Candles.

    Each field is already checked once as Schwab sent it, where it came in (server._schwab_bar):
    {timestamp (ms), _dt (its ET time), open, high, low, close, volume}.
    """
    return [
        {
            "timestamp": int(c.ts * 1000),
            "_dt": datetime.fromtimestamp(c.ts, tz=ET),
            "open": c.open,
            "high": c.high,
            "low": c.low,
            "close": c.close,
            "volume": c.volume,
        }
        for c in candles
    ]


# ─────────────────────────────────────────────────────────────────────────────
# PREVIOUS DAY / OVERNIGHT
# ─────────────────────────────────────────────────────────────────────────────


def prior_session(daily: list, session_date: date):
    """Return THE prior session, for the previous-day levels and the overnight window.

    It is the newest of Schwab's daily candles (the bar writer's, server._series) dated before
    `session_date`. Schwab sends a daily candle for each session that traded, so a weekend, a
    holiday or a closure has none. None: no such candle held (not received), never a guessed
    date.
    """
    before = [c for c in daily if datetime.fromtimestamp(c.ts, ET).date() < session_date]
    return max(before, key=lambda c: c.ts) if before else None


def get_previous_day_levels(bars_norm: list, prior, config: PlaybookConfig) -> dict:
    """Return the prior session's levels.

    Its high, low and close as Schwab sent them on its daily candle (`prior`, prior_session),
    and its POC, VAH and VAL estimated from its RTH 1-minute bars (Schwab sends no volume
    profile), with the count of those bars. No prior session: {}.
    """
    if prior is None:
        return {}
    prior_date = datetime.fromtimestamp(prior.ts, ET).date()
    prev_bars = [b for b in bars_norm if b["_dt"].date() == prior_date and _in_rth(b["_dt"])]
    p = volume_profile(prev_bars, config.value_area_percent, config.tick_size, ndigits=4)
    return {
        "prior_date": prior_date,
        "rth_bars": len(prev_bars),
        "pdh": prior.high,
        "pdl": prior.low,
        "pdc": prior.close,
        "pd_poc": None if p is None else p.poc,
        "pd_vah": None if p is None else p.vah,
        "pd_val": None if p is None else p.val,
    }


def get_overnight_levels(
    bars_norm: list,
    session_date: date,
    prev_session: date | None,
) -> dict:
    """Overnight range over normalized bars (bars_from_candles).

    The continuous interval from the prior session's (`prev_session`, prior_session's candle
    date) regular close to this session's regular open, as Schwab's /markets sent them -- a
    weekend's or holiday's bars included. With no prior session the interval has no start, so
    only this session's pre-open bars are used. No bars in the window, or a session's hours not
    held: {}.
    """
    today = _regular(session_date)
    prev = None if prev_session is None else _regular(prev_session)
    if today is None or (prev_session is not None and prev is None):
        return {}
    session_open_dt = today[0]
    prev_close_dt = None if prev is None else prev[1]

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
    """The bars of the first N minutes (default 15) from the regular open Schwab sent for the date.

    From normalized bars (bars_from_candles). {} when the date has no regular session, when
    Schwab's /markets answer for it is not held (the open is unknown), or when no bar falls in it.
    """
    regular = _regular(session_date)
    span = timedelta(minutes=config.opening_range_minutes)
    orb_bars = [
        b for b in bars_norm if regular is not None and regular[0] <= b["_dt"] < regular[0] + span
    ]

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
    bars_norm: list,
    session_date: date,
) -> list[tuple[float, float, float, float, float, float]]:
    """Return running session VWAP and σ bands after each RTH bar.

    From normalized bars (bars_from_candles). Returns
    [(bar_epoch_sec, vwap, +1σ, -1σ, +2σ, -2σ), ...] using the standard
    cumulative moments VWAP_t = Σ(tp·v)/Σv and σ_t² = Σ(tp²·v)/Σv − VWAP_t².

    The one VWAP accumulation: the served VWAP level and bands are its last point; the chart's
    polyline is this list carried to the browser.
    """
    rth_bars = _filter_rth_bars(bars_norm, session_date)
    cum_tpv = cum_vol = cum_tp2v = 0.0
    series: list[tuple[float, float, float, float, float, float]] = []
    for b in rth_bars:
        vol = b["volume"]  # a 0-volume minute adds nothing and keeps its VWAP point
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
        series.append((b["_dt"].timestamp(), w, w + sd, w - sd, w + 2 * sd, w - 2 * sd))
    return series


def count_session_rth_positive_volume_bars(bars_norm: list, session_date: date) -> int:
    """INPUT RTH bars with positive volume on session_date — independent of the VWAP series."""
    return sum(
        1
        for b in _filter_rth_bars(bars_norm, session_date)
        if b["volume"] is not None and b["volume"] > 0
    )


def _filter_rth_bars(bars_norm: list, session_date: date) -> list:
    return [b for b in bars_norm if b["_dt"].date() == session_date and _in_rth(b["_dt"])]


# ─────────────────────────────────────────────────────────────────────────────
# VOLUME PROFILE (POC, VAH, VAL)
# ─────────────────────────────────────────────────────────────────────────────


def compute_volume_profile_levels(
    bars_norm: list,
    session_date: date,
    config: PlaybookConfig,
) -> VolumeProfile | None:
    """Return the current day's volume profile with its POC, VAH, VAL.

    From normalized bars (bars_from_candles). RTH only, no lookahead.
    """
    return volume_profile(
        _filter_rth_bars(bars_norm, session_date),
        config.value_area_percent,
        config.tick_size,
        ndigits=4,
    )


# ─────────────────────────────────────────────────────────────────────────────
# ZONE CLUSTERING
# ─────────────────────────────────────────────────────────────────────────────


def cluster_price_levels_into_zones(
    levels: list[tuple[float, str]],
    config: PlaybookConfig,
) -> list[tuple[float, float, float, list[str], list[tuple[float, str]]]]:
    """Cluster nearby levels into zones.

    Returns list of (zone_low, zone_high, zone_mid, source_tags, source_pairs). source_pairs =
    [(price, tag), ...] for correct source_levels (actual level values, not zone mid).

    Adjacent levels merge while the gap is within config.clustering_threshold_pct of the lower one.
    """
    if not levels:
        return []
    prices = sorted(set(p for p, _ in levels))

    tag_map: dict[float, list[str]] = defaultdict(list)
    for p, tag in levels:
        tag_map[p].append(tag)

    max_width = float_positive_or_none(config.max_zone_width)

    def _flush_current(cur):
        if not cur:
            return
        lo, hi = min(cur), max(cur)
        mid = (lo + hi) / 2
        tags = []
        source_pairs = []
        for p in cur:
            for t in tag_map[p]:  # every price clustered came with its tags
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
    canonical: PriceLevelSnapshot,
) -> SnapshotOutput:
    """Premarket: PDH/PDL/PDC, PD POC/VAH/VAL, overnight high/low. No same-day RTH.

    The families are CARRIED from the one materialized snapshot (``canonical``); no level
    helper runs here. Absent stays absent: a family missing from the snapshot is missing here,
    never replaced by spot, zero or a neighbouring level.
    """
    levels = _held_levels(canonical, PREMARKET_LEVELS)
    families = {PHASE2A_LEVEL_IDS[lid][0] for _price, lid in levels}
    pdh, pdl = canonical.price("PDH"), canonical.price("PDL")
    zones = []
    for cluster in cluster_price_levels_into_zones(levels, config):
        lo, hi, _mid, tags, _source_pairs = cluster
        if {"prior_day", "overnight"} <= families:
            zone_type, notes = _place_premarket_cluster(tags, lo, hi, pdh, pdl)
        else:
            zone_type, notes = _premarket_type_by_tags(tags), ""
        zones.append(_zone(cluster, zone_type, notes, SnapshotType.PREMARKET))
    return SnapshotOutput(
        ticker=ticker,
        session_date=session_date.isoformat(),
        snapshot_type=SnapshotType.PREMARKET,
        zones=zones,
        summary=None,
    )


#: the levels a premarket snapshot clusters, in order
PREMARKET_LEVELS = (
    "PDH",
    "PD_VAH",
    "PD_POC",
    "PD_VAL",
    "PDL",
    "PDC",
    "OVERNIGHT_HIGH",
    "OVERNIGHT_LOW",
)
#: the levels a live snapshot clusters, in order (the option levels and spot follow them)
LIVE_LEVELS = (
    "PDH",
    "PD_VAH",
    "PD_POC",
    "ORB_HIGH",
    "ORB_MID",
    "ORB_LOW",
    "TODAY_VAH",
    "VWAP_P1",
    "VWAP",
    "TODAY_POC",
    "VWAP_M1",
    "TODAY_VAL",
    "PD_VAL",
    "PDL",
    "OVERNIGHT_HIGH",
    "OVERNIGHT_LOW",
)


def _held_levels(canonical: PriceLevelSnapshot, level_ids: tuple) -> list[tuple[float, str]]:
    """(price, id) of each of `level_ids` the snapshot holds, in order; one not held is left out.

    Absent stays absent: never replaced by spot, zero or a neighbouring level.
    """
    return [(price, lid) for lid in level_ids if (price := canonical.price(lid)) is not None]


def _zone(cluster: tuple, zone_type: ZoneType, notes: str, snapshot_type: SnapshotType) -> Zone:
    """Return the zone of one cluster (cluster_price_levels_into_zones)."""
    lo, hi, mid, tags, source_pairs = cluster
    return Zone(
        zone_type=zone_type,
        zone_low=lo,
        zone_high=hi,
        zone_mid=mid,
        source_levels=[{"label": t, "value": p} for p, t in source_pairs],
        source_tags=tags,
        confluence_score=len(tags),
        snapshot_type=snapshot_type,
        interpretation_notes=notes,
    )


def _premarket_type_by_tags(tags: list[str]) -> ZoneType:
    """Return the zone type a premarket cluster's tags alone give."""
    if "PDL" in tags or "PD_VAL" in tags or "OVERNIGHT_LOW" in tags:
        return ZoneType.SUPPORT_LIQUIDITY
    if "PD_POC" in tags or "PDC" in tags:
        return ZoneType.PIVOT_VALUE
    return ZoneType.RESISTANCE_LIQUIDITY


def _place_premarket_cluster(
    tags: list[str], zone_low: float, zone_high: float, pdh: float | None, pdl: float | None
) -> tuple[ZoneType, str]:
    """Return a premarket cluster's zone type and note, placed against the prior day's range.

    Canonical taxonomy: downside extremes -> low_extreme; PDL/VAL -> support_liquidity;
    POC/balance -> pivot_value; PDH/overnight high -> resistance_liquidity. Notes state WHERE the
    level came from -- never that stops rest there or that price is drawn to it.
    """
    high = "PDH" in tags or "OVERNIGHT_HIGH" in tags
    low = "PDL" in tags or "PD_VAL" in tags
    value = "PD_POC" in tags or "PDC" in tags
    if pdl is not None and zone_low < pdl * 0.995:
        return ZoneType.LOW_EXTREME, "Extreme low, below the prior-day low"
    if value and (high or low):  # a prior-day POC or close keeps the type its tags give
        return _premarket_type_by_tags(tags), ""
    if high:
        return ZoneType.RESISTANCE_LIQUIDITY, "Overhead structure at the prior-day high"
    if "OVERNIGHT_LOW" in tags and not low:
        return ZoneType.LOW_EXTREME, "Extreme low of the overnight window"
    if low:
        return ZoneType.SUPPORT_LIQUIDITY, "Underside structure at the prior-day low"
    if value:
        return ZoneType.PIVOT_VALUE, "Fair value reference from prior day POC/close"
    if pdh is not None and zone_high >= pdh * 0.998:
        return ZoneType.RESISTANCE_LIQUIDITY, "Overhead structure, above the prior-day high"
    if pdl is not None and zone_low <= pdl * 1.002:
        return ZoneType.SUPPORT_LIQUIDITY, "Underside structure at the prior-day low"
    return _premarket_type_by_tags(tags), ""


def _classify_value_state_and_vwap_relation(
    poc: float | None,
    prev_pd_poc: float | None,
    vwap: float | None,
) -> tuple[str, str, str]:
    """Value-area shift + VWAP-vs-value relation + auction interpretation."""
    value_state = "unchanged"
    if poc is not None and prev_pd_poc is not None:
        if poc > prev_pd_poc * 1.002:
            value_state = "shifted_higher"
        elif poc < prev_pd_poc * 0.998:
            value_state = "shifted_lower"

    vwap_relation = "at_value"
    if vwap is not None and poc is not None:
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


def _classify_live_cluster(tags: list[str]) -> tuple[ZoneType, str]:
    """Map clustered level tags to zone type + note (live / fused playbook)."""
    ts = " ".join(tags)
    opt_markers = (
        "GAMMA_CALL",
        "GAMMA_PUT",
        "DELTA_CALL",
        "DELTA_PUT",
        "OI_CALL",
        "OI_PUT",
        "GAMMA_PIN",
        "NET_GEX_PEAK",
        "MAX_PAIN",
        "GAMMA_FLIP",
        "GAMMA_INFLECTION",
        "DELTA_INFLECTION",
        "OI_CENTER",
        "EM_UPPER",
        "EM_LOWER",
        "SYNTH_FWD",
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

    if (
        "ORB_HIGH" in ts
        or "TODAY_VAH" in ts
        or "PDH" in ts
        or "OVERNIGHT_HIGH" in ts
        or "PD_VAH" in ts
    ):
        return ZoneType.RESISTANCE_LIQUIDITY, "Resistance / upper structure"
    if (
        "ORB_LOW" in ts
        or "TODAY_VAL" in ts
        or "PDL" in ts
        or "OVERNIGHT_LOW" in ts
        or "PD_VAL" in ts
    ):
        return ZoneType.SUPPORT_LIQUIDITY, "Support / lower structure"
    if "TODAY_POC" in ts or "VWAP" in ts or "ORB_MID" in ts or "PD_POC" in ts or "PDC" in ts:
        return ZoneType.PIVOT_VALUE, "Fair value / pivot"
    # The FALLTHROUGH note — no tag matched any branch above, so nothing is known about
    # this cluster beyond the fact that it exists in this session.
    return ZoneType.PIVOT_VALUE, "Unclassified session zone"


def build_live_snapshot(
    ticker: str,
    config: PlaybookConfig,
    *,
    canonical: PriceLevelSnapshot,
    now: datetime,
    extra_levels: list[tuple[float, str]],
) -> SnapshotOutput:
    """Build the session's zones from the one materialized price-level snapshot (``canonical``).

    Optional ``extra_levels`` (the option levels and spot) are fused in; no level helper runs
    here. Before the session's regular open it is the premarket shape, as it is while the session's
    hours are not held: the regular session Schwab's /markets sent.
    """
    session_date = canonical.session_date
    regular = _regular(session_date)
    if regular is None or now < regular[0]:
        return build_premarket_snapshot(ticker, session_date, config, canonical=canonical)
    levels = _held_levels(canonical, LIVE_LEVELS) + [
        (float(pair[0]), str(pair[1])) for pair in extra_levels
    ]
    zones = [
        _zone(cluster, *_classify_live_cluster(cluster[3]), SnapshotType.LIVE)
        for cluster in cluster_price_levels_into_zones(levels, config)
    ]
    value_state, vwap_relation, auction_interp = _classify_value_state_and_vwap_relation(
        canonical.price("TODAY_POC"), canonical.price("PD_POC"), canonical.price("VWAP")
    )
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
    )


# ─────────────────────────────────────────────────────────────────────────────
# The canonical materialized PriceLevelSnapshot
# ─────────────────────────────────────────────────────────────────────────────
# THE INVARIANT: exactly ONE authoritative computation and
# ONE materialized result per (ticker, level_id, semantic_scope, generation). Every
# API, UI, decision path, model feature, persistence write and report consumes THAT
# result unchanged. A new market generation may invoke the producer once; endpoints
# and consumers may not independently invoke or reconstruct the computation.
# The same helpers run over DIFFERENT bar inputs are a second materialization, not a
# second formula, so the MATERIALIZATION is what is single.

#: level_id -> (family, semantic_scope, evidence_tier). The registry: an id
#: in this table has exactly one canonical producer and one materialized value per
#: generation. A checkpoint-scoped or otherwise differently-windowed metric must NOT
#: reuse these ids — it carries its own explicit scope suffix.
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

#: The engine helpers that ARE the level computation. `build_price_level_snapshot`
#: is the only production call site.
#: This module's own name, read rather than spelled: the provenance stamp of each level.
_PRODUCER_NS: str = __name__


#: semantic_scope -> the trading-session character the /api/levels contract
#: publishes as provenance.session_scope (RTH vs full/extended session). The two are
#: different questions: `semantic_scope` identifies WHICH measurement this is,
#: `session_scope` says which hours it was measured over.
_SESSION_SCOPE_OF: dict[str, str] = {
    "prior_rth_session": "RTH",
    "session_rth": "RTH",
    "overnight_window": "extended",
}


class PriceLevelValue:
    """One materialized level: its value AND the identity that makes it comparable."""

    __slots__ = (
        "level_id",
        "price",
        "family",
        "semantic_scope",
        "evidence_tier",
        "producer",
        "window",
        "vendor_basis",
        "as_of_ts_utc",
        "generation",
    )

    def __init__(
        self,
        *,
        level_id: str,
        price: float,
        family: str,
        semantic_scope: str,
        evidence_tier: str,
        producer: str,
        window: str,
        vendor_basis: str,
        as_of_ts_utc: float | None,
        generation: int,
    ) -> None:
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
    """The ONE materialized result for (ticker, session scope, generation).

    `input_fingerprint` is set by materialize_price_level_snapshot, which decides the generation
    from it.
    """

    __slots__ = (
        "ticker",
        "session_date",
        "generation",
        "bar_source",
        "as_of_ts_utc",
        "levels",
        "vwap_path",
        "vwap_series",
        "families_absent",
        "degraded",
        "input_fingerprint",
        "bars_used",
        "session_rth_positive_volume_bars",
        "volume_profile",
    )

    def __init__(
        self,
        *,
        ticker: str,
        session_date: date,
        generation: int,
        bar_source: str,
        as_of_ts_utc: float | None,
        levels: dict,
        vwap_path: list,
        families_absent: list,
        degraded: list,
        bars_used: int,
        vwap_series: list,
        session_rth_positive_volume_bars: int = 0,
        volume_profile: VolumeProfile | None = None,
    ) -> None:
        self.ticker = ticker
        self.session_date = session_date
        self.generation = generation
        self.bar_source = bar_source
        self.as_of_ts_utc = as_of_ts_utc
        self.levels = levels  # level_id -> PriceLevelValue
        self.vwap_path = vwap_path  # [(epoch_sec, vwap)]
        self.vwap_series = vwap_series  # [(epoch_sec, vwap, +1σ, -1σ, +2σ, -2σ)]
        self.families_absent = families_absent
        self.degraded = degraded
        self.bars_used = bars_used
        self.session_rth_positive_volume_bars = int(session_rth_positive_volume_bars)
        self.volume_profile = volume_profile  # the session's profile the value area is read from

    def price(self, level_id: str) -> float | None:
        """Return the canonical value, or None.

        Absence is absence — never spot, zero or a sibling.
        """
        lv = self.levels.get(level_id)
        return None if lv is None else lv.price


# A reported volume and a missing one are different inputs (a reported 0 is 0). They are
# packed with different layouts so the digest cannot treat an absent volume as zero.
_BAR_PRESENT = struct.Struct("<qdddddB")
_BAR_ABSENT = struct.Struct("<qddddB")


def _snapshot_input_fingerprint(
    ticker: str, session_date: date, bars_norm: list, bar_source: str, prior
) -> tuple:
    """Identity of the INPUT. Same fingerprint ⇒ same generation ⇒ same result object.

    Bar identity, not wall-clock: re-asking within a generation must return the very
    result already materialized, or "one result per generation" is prose.

    A cache key shorter than its input is a claim of equality that cannot always hold.
    Every bar enters a stable digest, so no interior edit can survive it, and the digest
    is fixed-width so the key stays cheap to compare.
    """
    h = hashlib.blake2b(digest_size=16)
    h.update(f"{ticker}\x1f{session_date.isoformat()}\x1f{bar_source}\x1f{len(bars_norm)}".encode())
    h.update(repr(prior).encode())  # the prior session's Schwab daily candle (a dataclass), or None
    present, absent = _BAR_PRESENT.pack, _BAR_ABSENT.pack
    for b in bars_norm:
        ts, o, hi, lo, c = (
            int(b["timestamp"]),
            float(b["open"]),
            float(b["high"]),
            float(b["low"]),
            float(b["close"]),
        )
        vol = b["volume"]
        if vol is None:
            h.update(absent(ts, o, hi, lo, c, 0))
        else:
            h.update(present(ts, o, hi, lo, c, float(vol), 1))
    return (ticker, session_date.isoformat(), bar_source, len(bars_norm), h.hexdigest())


def _put_levels(
    levels: dict[str, PriceLevelValue],
    prices,
    *,
    producer: str,
    window: str,
    vendor_basis: str,
    as_of: float | None,
    generation: int,
) -> None:
    """Materialize each (level id, price) of `prices` into `levels`.

    A price that is not a finite number is left out: absent stays absent.
    """
    for level_id, price in prices:
        v = float_finite_or_none(price)
        if v is None:
            continue
        family, scope, tier = PHASE2A_LEVEL_IDS[level_id]
        levels[level_id] = PriceLevelValue(
            level_id=level_id,
            price=v,
            family=family,
            semantic_scope=scope,
            evidence_tier=tier,
            producer=producer,
            window=window,
            vendor_basis=vendor_basis,
            as_of_ts_utc=as_of,
            generation=generation,
        )


def build_price_level_snapshot(
    ticker: str,
    session_date: date,
    bars_norm: list,
    *,
    prior,
    bar_source: str,
    config: PlaybookConfig | None = None,
    generation: int = 0,
) -> PriceLevelSnapshot:
    """Build the levels: THE level producer.

    From normalized bars (bars_from_candles) and the prior session's Schwab daily candle
    (`prior`, prior_session; None when none is held). The only production caller of the
    canonical helpers.

    Absent input stays absent: a family with no bars in its window is declared in
    `families_absent` and its ids are simply not present. Nothing substitutes spot,
    zero, or a neighbouring level. A prior session with fewer than
    LEVELS_PRIOR_SESSION_MIN_BARS RTH bars is disclosed in `degraded`, never filled.
    """
    cfg = config or PlaybookConfig()
    tk = ticker_storage_key(ticker)  # canonical liquidity snapshot/ledger identity
    levels: dict[str, PriceLevelValue] = {}
    families_absent: list[dict] = []
    degraded: list[dict] = []
    vwap_path: list[tuple[float, float]] = []
    vwap_series: list[tuple] = []

    as_of: float | None = max((b["_dt"].timestamp() for b in bars_norm), default=None)

    put = functools.partial(
        _put_levels,
        levels,
        vendor_basis=f"1m bars ({bar_source}); Schwab streamed bars",
        as_of=as_of,
        generation=generation,
    )

    # ── prior day ────────────────────────────────────────────────────────────
    eng = get_previous_day_levels(bars_norm, prior, cfg)
    prior_date = eng.get("prior_date")
    if prior_date is None:
        families_absent.append(
            {"family": "prior_day", "reason": "no Schwab daily candle held for a prior session"}
        )
    else:
        producer = f"{_PRODUCER_NS}.get_previous_day_levels"
        window = f"{prior_date.isoformat()} RTH (most recent prior RTH session)"
        put(
            (("PDH", eng["pdh"]), ("PDL", eng["pdl"]), ("PDC", eng["pdc"])),
            producer=producer,
            window=window,
            vendor_basis=DAILY_CANDLE_BASIS,
        )
        put(
            (("PD_POC", eng["pd_poc"]), ("PD_VAH", eng["pd_vah"]), ("PD_VAL", eng["pd_val"])),
            producer=producer,
            window=window,
        )
        if eng["rth_bars"] < LEVELS_PRIOR_SESSION_MIN_BARS:
            degraded.append(
                {
                    "family": "prior_day",
                    "last_good_ts_utc": None,
                    "reason": (
                        f"prior session {prior_date} holds only {eng['rth_bars']} of >= "
                        f"{LEVELS_PRIOR_SESSION_MIN_BARS} RTH bars; its POC and value area are "
                        "estimated from a partial tape"
                    ),
                }
            )

    sess_window = f"{session_date.isoformat()} RTH (canonical snapshot over {bar_source})"

    if not bars_norm:
        families_absent.extend(
            {"family": fam, "reason": f"no bars available (source {bar_source})"}
            for fam in ("vwap", "opening_range", "overnight", "value_area")
        )
        return PriceLevelSnapshot(
            ticker=tk,
            session_date=session_date,
            generation=generation,
            bar_source=bar_source,
            as_of_ts_utc=as_of,
            levels=levels,
            vwap_path=vwap_path,
            vwap_series=vwap_series,
            families_absent=families_absent,
            degraded=degraded,
            bars_used=0,
            session_rth_positive_volume_bars=0,
        )

    # ── vwap + bands (one accumulation: the series IS the scalars' source) ───
    session_rth_vol_n = count_session_rth_positive_volume_bars(bars_norm, session_date)
    vwap_series = compute_session_vwap_series(bars_norm, session_date)
    if not vwap_series:
        families_absent.append(
            {
                "family": "vwap",
                "reason": (
                    "RTH volume bars present but session VWAP did not materialize"
                    if session_rth_vol_n > 0
                    else "no RTH volume for session VWAP in available bars"
                ),
            }
        )
    else:
        # the curve's last point IS the served level and band
        _t, vwap, p1, m1, p2, m2 = vwap_series[-1]
        put(
            (("VWAP", vwap), ("VWAP_P1", p1), ("VWAP_M1", m1), ("VWAP_P2", p2), ("VWAP_M2", m2)),
            producer=f"{_PRODUCER_NS}.compute_session_vwap_series",
            window=sess_window,
        )
    vwap_path = [(t, w) for t, w, _a, _b, _c, _d in vwap_series]

    # ── opening range ────────────────────────────────────────────────────────
    orb = compute_opening_range(bars_norm, session_date, cfg)
    if not orb:
        families_absent.append(
            {"family": "opening_range", "reason": "no bar in the opening minutes, or no open known"}
        )
    else:
        put(
            (
                ("ORB_HIGH", orb["orb_high"]),
                ("ORB_LOW", orb["orb_low"]),
                ("ORB_MID", orb["orb_mid"]),
            ),
            producer=f"{_PRODUCER_NS}.compute_opening_range",
            window=f"{session_date.isoformat()} first {cfg.opening_range_minutes}m RTH",
        )

    # ── overnight ────────────────────────────────────────────────────────────
    overnight = get_overnight_levels(bars_norm, session_date, prior_date)
    if not overnight:
        families_absent.append(
            {"family": "overnight", "reason": "no overnight-window bars in available tape"}
        )
    else:
        put(
            (
                ("OVERNIGHT_HIGH", overnight["overnight_high"]),
                ("OVERNIGHT_LOW", overnight["overnight_low"]),
            ),
            producer=f"{_PRODUCER_NS}.get_overnight_levels",
            window=(
                f"{session_date.isoformat()} before the RTH open (no prior session)"
                if prior_date is None
                else f"{prior_date.isoformat()} RTH close -> {session_date.isoformat()} RTH open"
            ),
        )

    # ── current-session value area ───────────────────────────────────────────
    profile = compute_volume_profile_levels(bars_norm, session_date, cfg)
    if profile is None:
        families_absent.append(
            {
                "family": "value_area",
                "reason": (
                    "no RTH volume for the volume profile in available bars"
                    if session_rth_vol_n == 0
                    else "RTH volume bars present but the volume profile did not materialize"
                ),
            }
        )
    else:
        put(
            (("TODAY_POC", profile.poc), ("TODAY_VAH", profile.vah), ("TODAY_VAL", profile.val)),
            producer=f"{_PRODUCER_NS}.compute_volume_profile_levels",
            window=sess_window,
        )

    return PriceLevelSnapshot(
        ticker=tk,
        session_date=session_date,
        generation=generation,
        bar_source=bar_source,
        as_of_ts_utc=as_of,
        levels=levels,
        vwap_path=vwap_path,
        vwap_series=vwap_series,
        families_absent=families_absent,
        degraded=degraded,
        bars_used=len(bars_norm),
        session_rth_positive_volume_bars=session_rth_vol_n,
        volume_profile=profile,
    )


#: (ticker, session_date_iso) -> the ONE materialized snapshot for the current generation.
_MATERIALIZED_SNAPSHOTS: dict[tuple[str, str], PriceLevelSnapshot] = {}
#: Guards the whole read-decide-build-write of materialize_price_level_snapshot.
#: Deciding a generation from a value you then overwrite is a check-then-act, and a
#: check-then-act is a race unless something serialises it.
_MATERIALIZE_LOCK = threading.Lock()


def materialize_price_level_snapshot(
    ticker: str,
    session_date: date,
    bars_norm: list,
    *,
    daily: list,
    bar_source: str,
    config: PlaybookConfig | None = None,
) -> PriceLevelSnapshot:
    """Materialize once per generation; return the SAME object within a generation.

    Built from normalized bars (bars_from_candles) and Schwab's daily candles (`daily`,
    server._series).

    A new market generation (the bar input or the prior session's candle changed) invokes the
    producer exactly once. Every later ask in that generation is a read, never a recomputation.
    """
    tk = ticker_storage_key(ticker)  # canonical liquidity snapshot/ledger identity
    key = (tk, session_date.isoformat())
    prior = prior_session(daily, session_date)
    fingerprint = _snapshot_input_fingerprint(tk, session_date, bars_norm, bar_source, prior)
    # The read, the generation decision, the build and the write-back are ONE
    # critical section. Unguarded, two concurrent callers can both see `existing is None`,
    # both compute generation 1 and produce two results under one generation.
    with _MATERIALIZE_LOCK:
        existing = _MATERIALIZED_SNAPSHOTS.get(key)
        if existing is not None and existing.input_fingerprint == fingerprint:
            return existing
        generation = 1 if existing is None else existing.generation + 1
        snap = build_price_level_snapshot(
            tk,
            session_date,
            bars_norm,
            prior=prior,
            bar_source=bar_source,
            config=config,
            generation=generation,
        )
        snap.input_fingerprint = fingerprint
        _MATERIALIZED_SNAPSHOTS[key] = snap
        return snap
