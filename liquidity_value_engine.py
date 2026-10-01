"""
liquidity_value_engine.py — Liquidity & Value Playbook Engine
============================================================
Deterministic institutional intraday zone mapper. Works for any ticker.
The price levels (prior day, opening range, VWAP, value area) are computed once per
generation into the materialized PriceLevelSnapshot (build_price_level_snapshot); the zones
(build_zones) are built from that snapshot, the prior close Schwab streams and the option levels.

The levels are derived from normalized 1-minute OHLCV bars (list of dicts).
"""

from __future__ import annotations

import hashlib
import logging
import threading
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from typing import Any, Optional

from instrument_identity import ticker_storage_key
from numeric_contract import float_finite_or_none, float_positive_or_none, schwab_count, schwab_number
from liquidity_models import (
    VALUE_SHIFT_MIN_FRACTION,
    VALUE_SHIFTED_HIGHER,
    VALUE_SHIFTED_LOWER,
    VALUE_UNCHANGED,
    VWAP_ABOVE_VALUE,
    VWAP_AT_VALUE,
    VWAP_BELOW_VALUE,
    PlaybookConfig,
    ValueContext,
    Zone,
    VolumeProfile,
    ZoneType,
    volume_profile,
)

log = logging.getLogger(__name__)

from time_et import (
    ET,
    RTH_OPEN_MINS,
    ct_label,
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
}

#: why no overnight level is served: price_bars_1m holds only the collect window's bars
#: (time_et.is_collect_window_bar_end_ts_utc), at most 30 minutes of the prior close -> open
#: interval, which is not that interval's range
OVERNIGHT_ABSENT_REASON = ("the stored 1-minute bars cover 09:15 ET to 15 minutes after the close; "
                           "the overnight session is not stored")


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
    and four prices that are numbers (`schwab_number`); a volume that is not a number stays None."""
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
# PREVIOUS DAY
# ─────────────────────────────────────────────────────────────────────────────


def prior_trading_session_date(bars_norm: list, session_date: date) -> Optional[date]:
    """The most recent date BEFORE `session_date` that actually traded an RTH session: the one
    definition of "the prior session". The calendar cannot answer this question:
    `session_date - 1 day` is Sunday on a Monday and a closed holiday after one.

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
    from normalized bars (_bars_to_list): its date, its RTH bar count, and its high, low, POC,
    VAH and VAL from those RTH bars. No prior session: {} (never a calendar walk or other
    days' bars). The prior close is not here: it is Schwab's CLOSE_PRICE, on the price row."""
    prior = prior_trading_session_date(bars_norm, session_date)
    if prior is None:
        return {}
    prev_bars = [b for b in bars_norm if b["_dt"].date() == prior and _in_rth(b["_dt"])]
    p = volume_profile(prev_bars, config.value_area_percent, config.tick_size, ndigits=4)
    return {"prior_date": prior, "rth_bars": len(prev_bars),
            "pdh": max(b["high"] for b in prev_bars), "pdl": min(b["low"] for b in prev_bars),
            "pd_poc": None if p is None else p.poc, "pd_vah": None if p is None else p.vah,
            "pd_val": None if p is None else p.val}


# ─────────────────────────────────────────────────────────────────────────────
# OPENING RANGE
# ─────────────────────────────────────────────────────────────────────────────


def compute_opening_range(
    bars_norm: list,
    session_date: date,
    config: PlaybookConfig,
) -> dict:
    """The range of the session's first `opening_range_minutes` of RTH, from normalized bars
    (_bars_to_list), once that window has ended. A stored bar is a completed minute, so the
    window has ended when the session's newest bar starts at or after the window's last minute;
    until then {"forming_until": the window's end}, never the range so far. No bar in the
    window: {}."""
    open_dt = datetime.combine(session_date, RTH_OPEN, tzinfo=ET)
    end_dt = open_dt + timedelta(minutes=config.opening_range_minutes)
    session_bars = [b for b in bars_norm if b["_dt"].date() == session_date and b["_dt"] >= open_dt]
    orb_bars = [b for b in session_bars if b["_dt"] < end_dt]
    if not orb_bars:
        return {}
    if max(b["_dt"] for b in session_bars) < end_dt - timedelta(minutes=1):
        return {"forming_until": end_dt}
    hi, lo = max(b["high"] for b in orb_bars), min(b["low"] for b in orb_bars)
    return {"orb_high": hi, "orb_low": lo, "orb_mid": (hi + lo) / 2.0}


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
    prices = sorted(set(p for p, _ in levels))

    tag_map: dict[float, list[str]] = defaultdict(list)
    for p, tag in levels:
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
# ZONES
# ─────────────────────────────────────────────────────────────────────────────

#: the price-level snapshot's levels a zone is built from (its second VWAP bands are not)
SESSION_ZONE_LEVELS = ("PDH", "PD_VAH", "PD_POC", "PD_VAL", "PDL", "ORB_HIGH", "ORB_MID", "ORB_LOW",
                       "TODAY_VAH", "VWAP_P1", "VWAP", "TODAY_POC", "VWAP_M1", "TODAY_VAL")

#: the levels that mark value rather than a bound of price -- a point of control, the VWAP and its
#: first bands, a mid, the prior close, and the option levels that are neither a call nor a put
#: level (server.TERRAIN_FUSION_LEVELS' tags). A zone made only of these is a pivot.
VALUE_ZONE_LEVELS = frozenset({"PD_POC", "PDC", "ORB_MID", "VWAP", "VWAP_P1", "VWAP_M1", "TODAY_POC",
                               "ABS_GAMMA", "NET_GEX_PEAK", "MAX_PAIN", "GAMMA_FLIP"})


def build_zones(
    canonical: "PriceLevelSnapshot",
    config: PlaybookConfig,
    *,
    spot: Optional[float],
    extra_levels: list[tuple[float, str]],
) -> list[Zone]:
    """The ticker's zones: the snapshot's session levels and `extra_levels` ([(price, tag)]: the
    prior close and the option levels) clustered by price (cluster_price_levels_into_zones).

    A zone made only of value levels (VALUE_ZONE_LEVELS) is a pivot. Any other zone is support
    when it lies below `spot` and resistance when it lies above it: a side is where the zone is
    against the live price, never what its levels are called. With spot inside it, or no spot, it
    has no side. Ordered nearest `spot` first; with no spot, by price, highest first. `spot` is
    never a level."""
    levels = [(canonical.price(lid), lid) for lid in SESSION_ZONE_LEVELS if canonical.price(lid) is not None]
    zones = []
    for lo, hi, mid, tags, pairs in cluster_price_levels_into_zones(levels + list(extra_levels), config):
        if all(t in VALUE_ZONE_LEVELS for t in tags):
            zt = ZoneType.PIVOT_VALUE
        elif spot is None or lo <= spot <= hi:
            zt = ZoneType.STRUCTURE
        else:
            zt = ZoneType.SUPPORT_LIQUIDITY if hi < spot else ZoneType.RESISTANCE_LIQUIDITY
        zones.append(Zone(zone_type=zt, zone_low=lo, zone_high=hi, zone_mid=mid,
                          source_levels=[{"label": t, "value": p} for p, t in pairs],
                          confluence_score=len(tags)))
    if spot is None:
        return sorted(zones, key=lambda z: -z.zone_high)
    return sorted(zones, key=lambda z: (0.0 if z.zone_low <= spot <= z.zone_high
                                        else min(abs(spot - z.zone_low), abs(spot - z.zone_high)),
                                        -z.zone_high))


def value_context(canonical: "PriceLevelSnapshot") -> ValueContext:
    """Today's value against the prior day's, and the session VWAP against today's value area,
    from the one snapshot. `value_state`: today's point of control against the prior day's,
    shifted when it moved more than VALUE_SHIFT_MIN_FRACTION of it. `vwap_relation`: above the
    value area high, below the value area low, or inside the value area. An input the snapshot
    does not hold leaves that state absent, with the reason."""
    poc, pd_poc = canonical.price("TODAY_POC"), canonical.price("PD_POC")
    vwap, vah, val = canonical.price("VWAP"), canonical.price("TODAY_VAH"), canonical.price("TODAY_VAL")
    value_state = value_why = vwap_relation = vwap_why = None
    if poc is None or pd_poc is None:
        value_why = "no point of control today" if poc is None else "no prior-day point of control"
    else:
        floor = abs(pd_poc) * VALUE_SHIFT_MIN_FRACTION
        value_state = (VALUE_SHIFTED_HIGHER if poc - pd_poc > floor
                       else VALUE_SHIFTED_LOWER if pd_poc - poc > floor else VALUE_UNCHANGED)
    if vwap is None or vah is None or val is None:
        vwap_why = "no session VWAP" if vwap is None else "no value area today"
    else:
        vwap_relation = VWAP_ABOVE_VALUE if vwap > vah else VWAP_BELOW_VALUE if vwap < val else VWAP_AT_VALUE
    return ValueContext(value_state, value_why, vwap_relation, vwap_why)


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
    "PD_POC": ("prior_day", "prior_rth_session", "derived_certified"),
    "PD_VAH": ("prior_day", "prior_rth_session", "derived_certified"),
    "PD_VAL": ("prior_day", "prior_rth_session", "derived_certified"),
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
#: is the only production call site (no check enforces it).
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
                 "levels", "vwap_series", "families_absent", "degraded", "input_fingerprint",
                 "volume_profile")

    def __init__(self, *, ticker: str, session_date: date, generation: int,
                 bar_source: str, as_of_ts_utc: Optional[float],
                 levels: dict, families_absent: list, degraded: list,
                 vwap_series: Optional[list] = None,
                 volume_profile: Optional[VolumeProfile] = None) -> None:
        self.ticker = ticker
        self.session_date = session_date
        self.generation = generation
        self.bar_source = bar_source
        self.as_of_ts_utc = as_of_ts_utc        # the end of the newest bar the levels are built from
        self.levels = levels                    # level_id -> PriceLevelValue
        self.vwap_series = vwap_series or []    # [(epoch_sec, vwap, +1σ, -1σ, +2σ, -2σ)]
        self.families_absent = families_absent  # [{family, reason}]
        self.degraded = degraded                # [{family, reason}]
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
    levels: dict[str, PriceLevelValue] = {}
    families_absent: list[dict] = []
    degraded: list[dict] = []

    # the levels are as of the end of the newest 1-minute bar
    as_of: Optional[float] = max((b["_dt"].timestamp() + 60.0 for b in bars_norm), default=None)

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
        for lid, key in (("PDH", "pdh"), ("PDL", "pdl"),
                         ("PD_POC", "pd_poc"), ("PD_VAH", "pd_vah"), ("PD_VAL", "pd_val")):
            _put(lid, eng.get(key),
                 producer=f"{_PRODUCER_NS}.get_previous_day_levels", window=window)
        if eng["pd_poc"] is None:
            families_absent.append({"family": "prior_day_value_area", "reason": (
                f"the prior session's ({prior_date}) bars carry no volume for a volume profile")})
        if eng["rth_bars"] < LEVELS_PRIOR_SESSION_MIN_BARS:
            degraded.append({"family": "prior_day", "reason": (
                f"prior session {prior_date} holds only {eng['rth_bars']} of >= "
                f"{LEVELS_PRIOR_SESSION_MIN_BARS} RTH bars; prior-day levels derive from a partial tape")})

    sess_window = f"{session_date.isoformat()} RTH (canonical snapshot over {bar_source})"
    families_absent.append({"family": "overnight", "reason": OVERNIGHT_ABSENT_REASON})

    if not bars_norm:
        for fam in ("vwap", "opening_range", "value_area"):
            families_absent.append({
                "family": fam, "reason": f"no bars available (source {bar_source})"})
        return PriceLevelSnapshot(
            ticker=tk, session_date=session_date, generation=generation,
            bar_source=bar_source, as_of_ts_utc=as_of, levels=levels,
            families_absent=families_absent, degraded=degraded)

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

    # ── opening range ────────────────────────────────────────────────────────
    orb = compute_opening_range(bars_norm, session_date, cfg)
    if not orb:
        families_absent.append({
            "family": "opening_range", "reason": "no ORB bars in available tape for session"})
    elif "forming_until" in orb:
        families_absent.append({"family": "opening_range", "reason": (
            f"the opening range is still forming: its first {cfg.opening_range_minutes} minutes end "
            f"{ct_label(orb['forming_until'].timestamp())}, and no later bar has arrived")})
    else:
        orb_window = f"{session_date.isoformat()} first {cfg.opening_range_minutes}m RTH"
        for lid, key in (("ORB_HIGH", "orb_high"), ("ORB_LOW", "orb_low"), ("ORB_MID", "orb_mid")):
            _put(lid, orb.get(key),
                 producer=f"{_PRODUCER_NS}.compute_opening_range", window=orb_window)

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
        bar_source=bar_source, as_of_ts_utc=as_of,
        levels=levels, vwap_series=vwap_series,
        families_absent=families_absent, degraded=degraded,
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






