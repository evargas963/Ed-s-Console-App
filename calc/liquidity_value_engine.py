"""Liquidity & Value Playbook Engine.

Deterministic institutional intraday zone mapper. Works for any ticker.
The price levels (prior day, overnight, opening range, VWAP, value area) are computed once per
bar input into the materialized PriceLevelSnapshot (build_price_level_snapshot); the zones
(build_zone_snapshot, before the open and after it) are built from that snapshot.

Data source agnostic: consumes normalized OHLCV bars (list of dicts).
All calculations derived from bars; no Schwab-specific logic.
"""

from __future__ import annotations

import hashlib
import logging
import math
import struct
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from itertools import pairwise
from typing import Any, NamedTuple

from calc.liquidity_models import (
    PlaybookConfig,
    SnapshotOutput,
    SnapshotSummary,
    SnapshotType,
    VolumeProfile,
    Zone,
    ZoneType,
    volume_profile,
)
from calc.micro_structure import Candle
from numeric_contract import float_positive_or_none
from time_et import ET, Session

log = logging.getLogger(__name__)

#: one normalized bar (bars_from_candles): timestamp (ms), _dt (its ET time), open, high, low,
#: close, volume
type Bar = dict[str, Any]
#: one cluster of levels: (zone_low, zone_high, zone_mid, source_tags, [(price, tag), ...])
type Cluster = tuple[float, float, float, list[str], list[tuple[float, str]]]
#: one point of the session VWAP series: (bar_epoch_sec, vwap)
type VwapPoint = tuple[float, float]

#: the opening range: the first this many minutes from the regular open
OPENING_RANGE_MINUTES: int = 15

#: where the prior day's high, low and close come from: Schwab sends them on its daily candle
DAILY_CANDLE_BASIS = "Schwab's daily candle (/pricehistory, frequencyType daily), as sent"


def _regular(sessions: Mapping[str, Session], d: date) -> tuple[datetime, datetime] | None:
    """`d`'s regular session (open, close) as Schwab's /markets sent it.

    `sessions` is the program's held answers by ET date (time_et.sessions). None: no regular
    session that day, or Schwab's answer for it is not held.
    """
    s = sessions.get(d.isoformat())
    if s is None or not s.regular:
        return None
    return s.regular[0][0], s.regular[-1][1]


def _in_rth(sessions: Mapping[str, Session], dt: datetime) -> bool:
    regular = _regular(sessions, dt.date())
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
    "VWAP": ("VWAP", "VWAP"),
}


def bars_from_candles(candles: list[Candle]) -> list[Bar]:
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


@dataclass(frozen=True)
class PriorDayLevels:
    """The prior session's levels: its daily candle's high, low and close as Schwab sent them.

    Its POC and value area are its volume profile's, estimated from its RTH 1-minute bars
    (`rth_bars` of them); None where those bars make no profile.
    """

    prior_date: date
    rth_bars: int
    pdh: float
    pdl: float
    pdc: float
    profile: VolumeProfile | None


@dataclass(frozen=True)
class OvernightRange:
    """The highest high and lowest low of the overnight window's bars."""

    high: float
    low: float


@dataclass(frozen=True)
class OpeningRange:
    """The highest high and lowest low of the opening minutes' bars, and their midpoint."""

    high: float
    low: float
    mid: float


def prior_session(daily: list[Candle], session_date: date) -> Candle | None:
    """Return THE prior session, for the previous-day levels and the overnight window.

    It is the newest of Schwab's daily candles (the bar writer's, state.bar_store) dated before
    `session_date`. Schwab sends a daily candle for each session that traded, so a weekend, a
    holiday or a closure has none. None: no such candle held (not received), never a guessed
    date.
    """
    before = [c for c in daily if datetime.fromtimestamp(c.ts, ET).date() < session_date]
    return max(before, key=lambda c: c.ts) if before else None


def levels_start(
    daily: list[Candle], session_date: date, sessions: Mapping[str, Session]
) -> datetime:
    """Return when the oldest bar the levels of `session_date` read can begin.

    The prior session's (prior_session) regular open as Schwab's /markets sent it: its RTH bars,
    the overnight window after its close and the session's own bars all begin there or later.
    With no prior session, or its hours not held, the levels read only the session date's bars:
    its 00:00 ET.
    """
    prior = prior_session(daily, session_date)
    regular = (
        None if prior is None else _regular(sessions, datetime.fromtimestamp(prior.ts, ET).date())
    )
    if regular is not None:
        return regular[0]
    return datetime(session_date.year, session_date.month, session_date.day, tzinfo=ET)


def get_previous_day_levels(
    bars_norm: list[Bar],
    prior: Candle,
    *,
    sessions: Mapping[str, Session],
) -> PriorDayLevels:
    """Return the prior session's levels.

    Its high, low and close as Schwab sent them on its daily candle (`prior`, prior_session),
    and its POC, VAH and VAL estimated from its RTH 1-minute bars (Schwab sends no volume
    profile), with the count of those bars.
    """
    prior_date = datetime.fromtimestamp(prior.ts, ET).date()
    prev_bars = [
        b for b in bars_norm if b["_dt"].date() == prior_date and _in_rth(sessions, b["_dt"])
    ]
    return PriorDayLevels(
        prior_date=prior_date,
        rth_bars=len(prev_bars),
        pdh=prior.high,
        pdl=prior.low,
        pdc=prior.close,
        profile=volume_profile(prev_bars),
    )


def get_overnight_levels(
    bars_norm: list[Bar],
    session_date: date,
    prev_session: date | None,
    *,
    sessions: Mapping[str, Session],
) -> OvernightRange | None:
    """Overnight range over normalized bars (bars_from_candles).

    The continuous interval from the prior session's (`prev_session`, prior_session's candle
    date) regular close to this session's regular open, as Schwab's /markets sent them -- a
    weekend's or holiday's bars included. With no prior session the interval has no start, so
    only this session's pre-open bars are used. No bars in the window, or a session's hours not
    held: None.
    """
    today = _regular(sessions, session_date)
    prev = None if prev_session is None else _regular(sessions, prev_session)
    if today is None or (prev_session is not None and prev is None):
        return None
    session_open_dt = today[0]
    prev_close_dt = None if prev is None else prev[1]

    overnight: list[Bar] = []
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
        return None
    return OvernightRange(
        high=max(b["high"] for b in overnight), low=min(b["low"] for b in overnight)
    )


# ─────────────────────────────────────────────────────────────────────────────
# OPENING RANGE
# ─────────────────────────────────────────────────────────────────────────────


def compute_opening_range(
    bars_norm: list[Bar],
    session_date: date,
    *,
    sessions: Mapping[str, Session],
) -> OpeningRange | None:
    """Return the range of the first OPENING_RANGE_MINUTES from the date's regular open (Schwab).

    From normalized bars (bars_from_candles). None when the date has no regular session, when
    Schwab's /markets answer for it is not held (the open is unknown), or when no bar falls in it.
    """
    regular = _regular(sessions, session_date)
    span = timedelta(minutes=OPENING_RANGE_MINUTES)
    orb_bars = [
        b for b in bars_norm if regular is not None and regular[0] <= b["_dt"] < regular[0] + span
    ]

    if not orb_bars:
        return None
    high, low = max(b["high"] for b in orb_bars), min(b["low"] for b in orb_bars)
    return OpeningRange(high=high, low=low, mid=(high + low) / 2.0)


# ─────────────────────────────────────────────────────────────────────────────
# VWAP
# ─────────────────────────────────────────────────────────────────────────────


def compute_session_vwap_series(
    bars_norm: list[Bar],
    session_date: date,
    *,
    sessions: Mapping[str, Session],
) -> list[VwapPoint]:
    """Return the running session VWAP after each RTH bar.

    From normalized bars (bars_from_candles). Returns [(bar_epoch_sec, vwap), ...], the standard
    cumulative VWAP_t = Σ(tp·v)/Σv.

    The one VWAP accumulation: the served VWAP level is its last point; the chart's polyline is
    this list carried to the browser.
    """
    rth_bars = _filter_rth_bars(bars_norm, session_date, sessions)
    cum_tpv = cum_vol = 0.0
    series: list[VwapPoint] = []
    for b in rth_bars:
        vol = b["volume"]  # a 0-volume minute adds nothing and keeps its VWAP point
        if vol is None:
            continue
        tp = (b["high"] + b["low"] + b["close"]) / 3.0
        cum_tpv += tp * vol
        cum_vol += vol
        if cum_vol <= 0:
            continue
        series.append((b["_dt"].timestamp(), cum_tpv / cum_vol))
    return series


def count_session_rth_positive_volume_bars(
    bars_norm: list[Bar], session_date: date, *, sessions: Mapping[str, Session]
) -> int:
    """INPUT RTH bars with positive volume on session_date — independent of the VWAP series."""
    return sum(
        1
        for b in _filter_rth_bars(bars_norm, session_date, sessions)
        if b["volume"] is not None and b["volume"] > 0
    )


def _filter_rth_bars(
    bars_norm: list[Bar], session_date: date, sessions: Mapping[str, Session]
) -> list[Bar]:
    return [b for b in bars_norm if b["_dt"].date() == session_date and _in_rth(sessions, b["_dt"])]


# ─────────────────────────────────────────────────────────────────────────────
# VOLUME PROFILE (POC, VAH, VAL)
# ─────────────────────────────────────────────────────────────────────────────


def compute_volume_profile_levels(
    bars_norm: list[Bar],
    session_date: date,
    *,
    sessions: Mapping[str, Session],
) -> VolumeProfile | None:
    """Return the current day's volume profile with its POC, VAH, VAL.

    From normalized bars (bars_from_candles). RTH only, no lookahead.
    """
    return volume_profile(_filter_rth_bars(bars_norm, session_date, sessions))


# ─────────────────────────────────────────────────────────────────────────────
# ZONE CLUSTERING
# ─────────────────────────────────────────────────────────────────────────────


def cluster_price_levels_into_zones(
    levels: list[tuple[float, str]],
    config: PlaybookConfig,
) -> list[Cluster]:
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

    def _flush_current(cur: list[float]) -> None:
        if not cur:
            return
        lo, hi = min(cur), max(cur)
        mid = (lo + hi) / 2
        tags: list[str] = []
        source_pairs: list[tuple[float, str]] = []
        for p in cur:
            for t in tag_map[p]:  # every price clustered came with its tags
                tags.append(t)
                source_pairs.append((p, t))
        clusters.append((lo, hi, mid, list(dict.fromkeys(tags)), source_pairs))

    clusters: list[Cluster] = []
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


#: every level the zones cluster, at every hour (the option levels follow them); one the snapshot
#: does not hold yet (the session's own before its open) is left out
ZONE_LEVELS = (
    "PDH",
    "PD_VAH",
    "PD_POC",
    "ORB_HIGH",
    "ORB_MID",
    "ORB_LOW",
    "TODAY_VAH",
    "VWAP",
    "TODAY_POC",
    "TODAY_VAL",
    "PD_VAL",
    "PDL",
    "PDC",
    "OVERNIGHT_HIGH",
    "OVERNIGHT_LOW",
)


def _held_levels(
    canonical: PriceLevelSnapshot, level_ids: tuple[str, ...]
) -> list[tuple[float, str]]:
    """(price, id) of each of `level_ids` the snapshot holds, in order; one not held is left out.

    Absent stays absent: never replaced by spot, zero or a neighbouring level.
    """
    return [(price, lid) for lid in level_ids if (price := canonical.price(lid)) is not None]


def _zone(cluster: Cluster, zone_type: ZoneType, notes: str) -> Zone:
    """Return the zone of one cluster (cluster_price_levels_into_zones)."""
    lo, hi, mid, tags, source_pairs = cluster
    return Zone(
        zone_type=zone_type,
        zone_low=lo,
        zone_high=hi,
        zone_mid=mid,
        source_levels=[{"label": t, "value": p} for p, t in source_pairs],
        confluence_score=len(tags),
        interpretation_notes=notes,
    )


def value_area_relation(
    val: float | None, vah: float | None, prior_val: float | None, prior_vah: float | None
) -> str | None:
    """Return where today's value area (`val` to `vah`) sits against the prior day's.

    The Market Profile comparison of the two areas themselves, with no tolerance: higher (wholly
    above), lower (wholly below), inside, outside, overlapping_higher or overlapping_lower (both
    edges moved that way), unchanged (the same edges). None, unknown, without all four edges.
    """
    if val is None or vah is None or prior_val is None or prior_vah is None:
        return None
    if (val, vah) == (prior_val, prior_vah):
        return "unchanged"
    if val > prior_vah:
        return "higher"
    if vah < prior_val:
        return "lower"
    if val >= prior_val and vah <= prior_vah:
        return "inside"
    if val <= prior_val and vah >= prior_vah:
        return "outside"
    return "overlapping_higher" if vah > prior_vah else "overlapping_lower"


def vwap_against_value(vwap: float | None, val: float | None, vah: float | None) -> str | None:
    """Return where VWAP sits against today's value area: above it, inside it or below it.

    None, unknown, without the VWAP or an edge.
    """
    if vwap is None or val is None or vah is None:
        return None
    return "above_value" if vwap > vah else "below_value" if vwap < val else "inside_value"


#: the terrain levels the zones are fused with, and the tag each carries: the one list of them
OPTION_LEVEL_TAGS = (
    ("call_wall", "GAMMA_CALL_WALL"),
    ("put_wall", "GAMMA_PUT_WALL"),
    ("call_delta_wall", "DELTA_CALL_WALL"),
    ("put_delta_wall", "DELTA_PUT_WALL"),
    ("absolute_gamma_strike", "ABS_GAMMA"),
    ("lvp", "NET_CALL_PEAK"),
    ("hvp", "NET_PUT_PEAK"),
    ("max_pain", "MAX_PAIN"),
    ("gamma_flip", "GAMMA_FLIP"),
)


def _classify_live_cluster(lo: float, hi: float, price: float | None) -> tuple[ZoneType, str]:
    """Type a live zone by its side of the live price: above it resistance, below it support.

    The definition: support is a level under the market, resistance one over it (Osler 2000,
    docs/SOURCES.md osler-2000). The price inside the zone (an edge included): pivot / value.
    With no live price the side is not known (SIDE_UNKNOWN, "-"); no level's name decides it.
    """
    if price is None:
        return ZoneType.SIDE_UNKNOWN, "No live price: the side of the price is not known"
    if lo > price:
        return ZoneType.RESISTANCE_LIQUIDITY, "Above the price"
    if hi < price:
        return ZoneType.SUPPORT_LIQUIDITY, "Below the price"
    return ZoneType.PIVOT_VALUE, "The price is inside it"


def build_zone_snapshot(
    ticker: str,
    config: PlaybookConfig,
    *,
    canonical: PriceLevelSnapshot,
    now: datetime,
    extra_levels: list[tuple[float, str]],
    price: float | None,
    sessions: Mapping[str, Session],
) -> SnapshotOutput:
    """Build the session's zones at `now` from the one price-level snapshot (``canonical``).

    The zones' one builder, at every hour: every level of ZONE_LEVELS the snapshot holds, with
    the option levels (``extra_levels``) fused in; no level helper runs here, and a level the
    snapshot does not hold is left out, never replaced by spot, zero or a neighbour. The value
    summary is built from the session's regular open (Schwab's /markets); before it, or while its
    hours are not held, there is none. Each zone is typed by its side of the live ``price``
    (_classify_live_cluster).
    """
    levels = _held_levels(canonical, ZONE_LEVELS) + [
        (float(pair[0]), str(pair[1])) for pair in extra_levels
    ]
    regular = _regular(sessions, canonical.session_date)
    if regular is None or now < regular[0]:
        kind, summary = SnapshotType.PREMARKET, None
    else:
        val, vah = canonical.price("TODAY_VAL"), canonical.price("TODAY_VAH")
        kind, summary = (
            SnapshotType.LIVE,
            SnapshotSummary(
                value_state=value_area_relation(
                    val, vah, canonical.price("PD_VAL"), canonical.price("PD_VAH")
                ),
                vwap_relation=vwap_against_value(canonical.price("VWAP"), val, vah),
            ),
        )
    zones = [
        _zone(cluster, *_classify_live_cluster(cluster[0], cluster[1], price))
        for cluster in cluster_price_levels_into_zones(levels, config)
    ]
    return SnapshotOutput(ticker=ticker, snapshot_type=kind, zones=zones, summary=summary)


# ─────────────────────────────────────────────────────────────────────────────
# The canonical materialized PriceLevelSnapshot
# ─────────────────────────────────────────────────────────────────────────────
# THE INVARIANT: exactly ONE authoritative computation and
# ONE materialized result per (ticker, level_id, semantic_scope) and bar input. Every
# API, UI, decision path, model feature, persistence write and report consumes THAT
# result unchanged. A new bar input may invoke the producer once; endpoints
# and consumers may not independently invoke or reconstruct the computation.
# The same helpers run over DIFFERENT bar inputs are a second materialization, not a
# second formula, so the MATERIALIZATION is what is single.

#: level_id -> (family, semantic_scope, evidence_tier). The registry: an id
#: in this table has exactly one canonical producer and one materialized value per
#: bar input. A checkpoint-scoped or otherwise differently-windowed metric must NOT
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
    "TODAY_POC": ("value_area", "session_rth", "derived_certified"),
    "TODAY_VAH": ("value_area", "session_rth", "derived_certified"),
    "TODAY_VAL": ("value_area", "session_rth", "derived_certified"),
}

#: The engine helpers that ARE the level computation. `build_price_level_snapshot`
#: is the only production call site.
#: This module's own name, read rather than spelled: the provenance stamp of each level.
_PRODUCER_NS: str = __name__


#: semantic_scope -> the trading-session character the levels panel
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

    @property
    def session_scope(self) -> str:
        return _SESSION_SCOPE_OF[self.semantic_scope]

    def to_contract_dict(self) -> dict[str, Any]:
        label, short = LEVEL_NAMES[self.level_id]
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
            "provenance": {
                "producer": self.producer,
                "session_scope": self.session_scope,
                "semantic_scope": self.semantic_scope,
                "window": self.window,
                "vendor_basis": self.vendor_basis,
            },
        }


class PriceLevelSnapshot:
    """The ONE materialized result for (ticker, session scope).

    state.price_level_store holds it with its input's fingerprint and builds again only when that
    changes.
    """

    __slots__ = (
        "session_date",
        "bar_source",
        "as_of_ts_utc",
        "levels",
        "vwap_series",
        "families_absent",
        "degraded",
        "bars_used",
        "volume_profile",
    )

    def __init__(
        self,
        *,
        session_date: date,
        bar_source: str,
        as_of_ts_utc: float | None,
        levels: dict[str, PriceLevelValue],
        families_absent: list[dict[str, str]],
        degraded: list[str],
        bars_used: int,
        vwap_series: list[VwapPoint],
        volume_profile: VolumeProfile | None,
    ) -> None:
        self.session_date = session_date
        self.bar_source = bar_source
        self.as_of_ts_utc = as_of_ts_utc
        self.levels = levels  # level_id -> PriceLevelValue
        self.vwap_series = vwap_series  # [(epoch_sec, vwap)]
        self.families_absent = families_absent
        self.degraded = degraded
        self.bars_used = bars_used
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


def snapshot_input_fingerprint(
    ticker: str,
    session_date: date,
    bars_norm: list[Bar],
    bar_source: str,
    prior: Candle | None,
    sessions: Mapping[str, Session],
) -> tuple[str, str, str, int, str]:
    """Identity of the INPUT. Same fingerprint ⇒ same result object.

    Bar identity, not wall-clock: re-asking with the same input must return the very
    result already materialized, or "one result per input" is prose.

    A cache key shorter than its input is a claim of equality that cannot always hold.
    Every bar enters a stable digest, so no interior edit can survive it, and the digest
    is fixed-width so the key stays cheap to compare.

    The bars are packed and hashed in one update: once a hash object has taken an update of
    2 KiB or more, CPython releases the GIL on every later update, and a bar at a time then
    waits out another thread's switch interval per bar.
    """
    present, absent = _BAR_PRESENT.pack, _BAR_ABSENT.pack
    packed = bytearray()
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
            packed += absent(ts, o, hi, lo, c, 0)
        else:
            packed += present(ts, o, hi, lo, c, float(vol), 1)
    h = hashlib.blake2b(digest_size=16)
    h.update(f"{ticker}\x1f{session_date.isoformat()}\x1f{bar_source}\x1f{len(bars_norm)}".encode())
    h.update(repr(prior).encode())  # the prior session's Schwab daily candle (a dataclass), or None
    # the regular hours Schwab's /markets sent, every held day's (the build reads this session's
    # and the prior one's): an answer that arrives later is a new input
    h.update(repr(sorted((day, s.regular) for day, s in sessions.items())).encode())
    h.update(packed)
    return (ticker, session_date.isoformat(), bar_source, len(bars_norm), h.hexdigest())


class _Family(NamedTuple):
    """One family's level prices, (level id, price), as its producer found them.

    Each is served with the family's producer, window and vendor basis.
    """

    prices: tuple[tuple[str, float], ...]
    producer: str
    window: str
    vendor_basis: str


class _Absent(NamedTuple):
    """A family with no levels, and why."""

    family: str
    reason: str


def _level_values(
    families: list[_Family | _Absent], as_of: float | None
) -> dict[str, PriceLevelValue]:
    """Return each family's (level id, price) as a served level, in order.

    Every price is a finite number: Schwab's daily candle's, checked where it came in
    (server._schwab_bar), or computed from bars checked there.
    """
    levels: dict[str, PriceLevelValue] = {}
    for f in families:
        if isinstance(f, _Absent):
            continue
        for level_id, price in f.prices:
            family, scope, tier = PHASE2A_LEVEL_IDS[level_id]
            levels[level_id] = PriceLevelValue(
                level_id=level_id,
                price=price,
                family=family,
                semantic_scope=scope,
                evidence_tier=tier,
                producer=f.producer,
                window=f.window,
                vendor_basis=f.vendor_basis,
                as_of_ts_utc=as_of,
            )
    return levels


def _prior_day_part(
    bars_norm: list[Bar],
    prior: Candle | None,
    sessions: Mapping[str, Session],
    basis: str,
) -> tuple[list[_Family | _Absent], date | None, list[str]]:
    """Return the prior session's levels, its date and what is degraded in them.

    The date is None with no prior candle held; degraded, a prior session whose RTH bars do not
    cover its regular window as Schwab's /markets sent it (a bar for each of its minutes), so its
    POC and value area are from a partial tape. A prior session
    whose RTH bars make no volume profile has its value area declared absent
    (`prior_value_area`), with why.
    """
    if prior is None:
        return [_Absent("prior_day", "no Schwab daily candle held for a prior session")], None, []
    eng = get_previous_day_levels(bars_norm, prior, sessions=sessions)
    day, p = eng.prior_date, eng.profile
    producer = f"{_PRODUCER_NS}.get_previous_day_levels"
    window = f"{day.isoformat()} RTH (most recent prior RTH session)"
    value_area: _Family | _Absent = (
        _Absent(
            "prior_value_area",
            f"no RTH bars of the prior session {day} in available bars"
            if eng.rth_bars == 0
            else f"no RTH volume in the prior session {day}'s bars for its volume profile",
        )
        if p is None
        else _Family(
            (("PD_POC", p.poc), ("PD_VAH", p.vah), ("PD_VAL", p.val)), producer, window, basis
        )
    )
    families: list[_Family | _Absent] = [
        _Family(
            (("PDH", eng.pdh), ("PDL", eng.pdl), ("PDC", eng.pdc)),
            producer,
            window,
            DAILY_CANDLE_BASIS,
        ),
        value_area,
    ]
    regular = _regular(sessions, day)
    if regular is None:  # no RTH bar is known: its value area is declared absent, none estimated
        return families, day, []
    minutes = int((regular[1] - regular[0]).total_seconds() // 60)
    if eng.rth_bars >= minutes:
        return families, day, []
    degraded = (
        f"prior_day: prior session {day} holds only {eng.rth_bars} RTH bars of its {minutes} "
        "regular-session minutes (Schwab's /markets); its POC and value area are estimated from "
        "a partial tape"
    )
    return families, day, [degraded]


def _opening_range_part(
    bars_norm: list[Bar],
    session_date: date,
    sessions: Mapping[str, Session],
    basis: str,
) -> _Family | _Absent:
    """Return the session's opening range."""
    orb = compute_opening_range(bars_norm, session_date, sessions=sessions)
    if orb is None:
        return _Absent("opening_range", "no bar in the opening minutes, or no open known")
    return _Family(
        (("ORB_HIGH", orb.high), ("ORB_LOW", orb.low), ("ORB_MID", orb.mid)),
        f"{_PRODUCER_NS}.compute_opening_range",
        f"{session_date.isoformat()} first {OPENING_RANGE_MINUTES}m RTH",
        basis,
    )


def _overnight_part(
    bars_norm: list[Bar],
    session_date: date,
    prior_date: date | None,
    sessions: Mapping[str, Session],
    basis: str,
) -> _Family | _Absent:
    """Return the overnight range before the session."""
    overnight = get_overnight_levels(bars_norm, session_date, prior_date, sessions=sessions)
    if overnight is None:
        return _Absent("overnight", "no overnight-window bars in available tape")
    return _Family(
        (("OVERNIGHT_HIGH", overnight.high), ("OVERNIGHT_LOW", overnight.low)),
        f"{_PRODUCER_NS}.get_overnight_levels",
        (
            f"{session_date.isoformat()} before the RTH open (no prior session)"
            if prior_date is None
            else f"{prior_date.isoformat()} RTH close -> {session_date.isoformat()} RTH open"
        ),
        basis,
    )


def _vwap_part(
    bars_norm: list[Bar],
    session_date: date,
    sessions: Mapping[str, Session],
    *,
    window: str,
    basis: str,
) -> tuple[_Family | _Absent, list[VwapPoint]]:
    """Return the session VWAP and its series (one accumulation for both).

    The series has a point from the first RTH bar with volume above 0 (no volume is negative,
    server._schwab_bar), so an empty one means no RTH volume.
    """
    vwap_series = compute_session_vwap_series(bars_norm, session_date, sessions=sessions)
    if not vwap_series:
        return _Absent("vwap", "no RTH volume for session VWAP in available bars"), vwap_series
    # the curve's last point IS the served level
    return _Family(
        (("VWAP", vwap_series[-1][1]),),
        f"{_PRODUCER_NS}.compute_session_vwap_series",
        window,
        basis,
    ), vwap_series


def _value_area_part(
    bars_norm: list[Bar],
    session_date: date,
    sessions: Mapping[str, Session],
    *,
    window: str,
    basis: str,
) -> tuple[_Family | _Absent, VolumeProfile | None]:
    """Return the session's value area, and its volume profile (None: none materialized).

    Bars with volume make no profile when none has a range to spread it over (high under low).
    """
    profile = compute_volume_profile_levels(bars_norm, session_date, sessions=sessions)
    if profile is None:
        rth_volume_bars = count_session_rth_positive_volume_bars(
            bars_norm, session_date, sessions=sessions
        )
        return _Absent(
            "value_area",
            "no RTH volume for the volume profile in available bars"
            if rth_volume_bars == 0
            else "RTH volume bars present but the volume profile did not materialize",
        ), None
    return _Family(
        (("TODAY_POC", profile.poc), ("TODAY_VAH", profile.vah), ("TODAY_VAL", profile.val)),
        f"{_PRODUCER_NS}.compute_volume_profile_levels",
        window,
        basis,
    ), profile


def build_price_level_snapshot(
    session_date: date,
    bars_norm: list[Bar],
    *,
    prior: Candle | None,
    bar_source: str,
    sessions: Mapping[str, Session],
) -> PriceLevelSnapshot:
    """Build the levels: THE level producer.

    From normalized bars (bars_from_candles), the prior session's Schwab daily candle
    (`prior`, prior_session; None when none is held) and Schwab's /markets answers by ET date
    (`sessions`, time_et.sessions). The only production caller of the canonical helpers.

    Absent input stays absent: a family with no bars in its window is declared in
    `families_absent` and its ids are simply not present. Nothing substitutes spot,
    zero, or a neighbouring level. A prior session whose RTH bars do not cover its regular window
    (Schwab's /markets) is disclosed in `degraded`, never filled.
    """
    as_of: float | None = max((b["_dt"].timestamp() for b in bars_norm), default=None)
    basis = f"1m bars ({bar_source}); Schwab streamed bars"
    families, prior_date, degraded = _prior_day_part(bars_norm, prior, sessions, basis)
    vwap_series: list[VwapPoint] = []
    profile: VolumeProfile | None = None
    if not bars_norm:
        families += [
            _Absent(fam, f"no bars available (source {bar_source})")
            for fam in ("vwap", "opening_range", "overnight", "value_area")
        ]
    else:
        window = f"{session_date.isoformat()} RTH (canonical snapshot over {bar_source})"
        vwap, vwap_series = _vwap_part(
            bars_norm, session_date, sessions, window=window, basis=basis
        )
        value_area, profile = _value_area_part(
            bars_norm, session_date, sessions, window=window, basis=basis
        )
        families += [
            vwap,
            _opening_range_part(bars_norm, session_date, sessions, basis),
            _overnight_part(bars_norm, session_date, prior_date, sessions, basis),
            value_area,
        ]
    return PriceLevelSnapshot(
        session_date=session_date,
        bar_source=bar_source,
        as_of_ts_utc=as_of,
        levels=_level_values(families, as_of),
        vwap_series=vwap_series,
        families_absent=[f._asdict() for f in families if isinstance(f, _Absent)],
        degraded=degraded,
        bars_used=len(bars_norm),
        volume_profile=profile,
    )


# ─────────────────────────────────────────────────────────────────────────────
# HOLD RATES (Osler 2000, Federal Reserve Bank of New York Economic Policy Review 6(2))
# ─────────────────────────────────────────────────────────────────────────────

#: the levels fixed for a whole session, measured from when each is known: the prior day's and
#: the overnight levels from the open, the opening range's once it is complete. VWAP and the
#: day's own value area move during the session and are not measured.
HOLD_LEVELS = (
    "PDH",
    "PDL",
    "PDC",
    "PD_POC",
    "PD_VAH",
    "PD_VAL",
    "OVERNIGHT_HIGH",
    "OVERNIGHT_LOW",
    "ORB_HIGH",
    "ORB_LOW",
    "ORB_MID",
)
_AFTER_OPENING_RANGE = frozenset({"ORB_HIGH", "ORB_LOW", "ORB_MID"})
#: minutes after a touch at which the close is read: Osler's 15, and her 30 as the check
HOLD_MINUTES = (15, 30)
#: the most recent completed sessions measured (Chung & Bellotti 2021: the effect decays)
HOLD_WINDOW_SESSIONS = 60
#: below this many touches the rate is not shown: its 95% interval is wider than +-10 points
HOLD_MIN_TOUCHES = 100
#: random levels per session for the baseline, evenly spaced over open +- the month's largest
#: open-to-high or open-to-low move (Osler's draw, as a grid so it reads no random generator)
HOLD_BASELINE_LEVELS = 100
_WILSON_Z = 1.959963984540054  # the two-sided 95% normal quantile


@dataclass(frozen=True)
class HoldCount:
    """Touches and holds of one level type at one horizon, and of the baseline's random levels.

    The baseline is counted over the same sessions as the level (the sessions it existed).
    """

    touches: int
    holds: int
    baseline_touches: int
    baseline_holds: int


def _touch_outcomes(rth: list[Bar], level: float, start: datetime, minutes: int) -> tuple[int, int]:
    """(touches, holds) of `level` in one session's regular-hours bars, oldest first.

    A touch: a bar from `start` on whose range reaches the level while the bar before it closed
    strictly on one side (the side it came from). One touch per approach: after a touch, the
    next counts only once a bar's whole range has been off the level (a bar touching it before
    `start` also waits for that). A hold: the close of the bar `minutes` later is strictly on the
    side it came from. A touch with no bar that many minutes later in the session is not counted.
    """
    at = {b["_dt"]: b for b in rth}
    touches = holds = 0
    armed = True
    for prev, bar in pairwise(rth):
        if not bar["low"] <= level <= bar["high"]:
            armed = True
            continue
        if bar["_dt"] < start or not armed:
            armed = False
            continue
        side = (prev["close"] > level) - (prev["close"] < level)
        if side == 0:
            continue
        armed = False
        later = at.get(bar["_dt"] + timedelta(minutes=minutes))
        if later is None:
            continue
        touches += 1
        holds += (later["close"] - level) * side > 0
    return touches, holds


def hold_counts(
    bars_norm: list[Bar],
    daily: list[Candle],
    now: datetime,
    *,
    sessions: Mapping[str, Session],
) -> dict[str, dict[int, HoldCount]]:
    """Count each level type's touches and holds over the sessions whose close is past at `now`.

    The newest HOLD_WINDOW_SESSIONS such sessions with regular-hours bars. Each session's levels are
    the one level producer's (build_price_level_snapshot) over the bars to that session's close,
    with Schwab's daily candle of the session before. The baseline: HOLD_BASELINE_LEVELS levels
    evenly spaced over the session's open +- the largest open-to-high or open-to-low move of a
    session of the same month in the window, by the same rules from the open (Osler 2000: random
    levels "hold" more than half the time, so a rate means something only beside them).
    """
    days = _closed_sessions(bars_norm, now, sessions)
    moves: dict[tuple[int, int], list[float]] = {}
    for d, (_hours, rth) in days.items():
        o = rth[0]["open"]
        moves.setdefault((d.year, d.month), []).append(
            max(max(b["high"] for b in rth) - o, o - min(b["low"] for b in rth))
        )
    swing = {month: max(m) for month, m in moves.items()}
    found = {lid: {m: [0, 0, 0, 0] for m in HOLD_MINUTES} for lid in HOLD_LEVELS}
    for d, (hours, rth) in days.items():
        snap = build_price_level_snapshot(
            d,
            [b for b in bars_norm if b["_dt"] < hours[1]],
            prior=prior_session(daily, d),
            bar_source="",
            sessions=sessions,
        )
        o, half = rth[0]["open"], swing[(d.year, d.month)]
        grid = [
            o + half * (2 * k + 1 - HOLD_BASELINE_LEVELS) / HOLD_BASELINE_LEVELS
            for k in range(HOLD_BASELINE_LEVELS)
        ]
        after_range = hours[0] + timedelta(minutes=OPENING_RANGE_MINUTES)
        opened = {
            lid: after_range if lid in _AFTER_OPENING_RANGE else hours[0] for lid in HOLD_LEVELS
        }
        for m in HOLD_MINUTES:
            base = [_touch_outcomes(rth, g, hours[0], m) for g in grid]
            base_t, base_h = sum(t for t, _h in base), sum(h for _t, h in base)
            for lid in HOLD_LEVELS:
                price = snap.price(lid)
                if price is not None:
                    t, h = _touch_outcomes(rth, price, opened[lid], m)
                    row = found[lid][m]
                    row[:] = [row[0] + t, row[1] + h, row[2] + base_t, row[3] + base_h]
    return {lid: {m: HoldCount(*found[lid][m]) for m in HOLD_MINUTES} for lid in HOLD_LEVELS}


def hold_window(bars_norm: list[Bar], now: datetime, sessions: Mapping[str, Session]) -> list[Bar]:
    """Return the bars hold_counts reads at `now`: each before a regular close at or before `now`.

    Every closed session's bars and everything before them: each bar before the newest such
    close; no bar of a session still open, and none with no session closed.
    """
    closes = [
        r[1]
        for day in sessions
        if (r := _regular(sessions, date.fromisoformat(day))) is not None and r[1] <= now
    ]
    if not closes:
        return []
    newest = max(closes)
    return [b for b in bars_norm if b["_dt"] < newest]


def _closed_sessions(
    bars_norm: list[Bar], now: datetime, sessions: Mapping[str, Session]
) -> dict[date, tuple[tuple[datetime, datetime], list[Bar]]]:
    """Return the newest HOLD_WINDOW_SESSIONS sessions closed at `now`: hours and regular bars."""
    rth_by_day: dict[date, list[Bar]] = {}
    for b in sorted(bars_norm, key=lambda b: b["_dt"]):
        if _in_rth(sessions, b["_dt"]):
            rth_by_day.setdefault(b["_dt"].date(), []).append(b)
    closed = {d: r for d in rth_by_day if (r := _regular(sessions, d)) is not None and r[1] <= now}
    return {d: (closed[d], rth_by_day[d]) for d in sorted(closed)[-HOLD_WINDOW_SESSIONS:]}


def wilson_interval(holds: int, touches: int) -> tuple[float, float]:
    """Return the Wilson score 95% interval of holds / touches (Brown, Cai & DasGupta 2001)."""
    p = holds / touches
    z2 = _WILSON_Z * _WILSON_Z
    centre = (p + z2 / (2 * touches)) / (1 + z2 / touches)
    half = (
        _WILSON_Z
        * math.sqrt(p * (1 - p) / touches + z2 / (4 * touches * touches))
        / (1 + z2 / touches)
    )
    return centre - half, centre + half
