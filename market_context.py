"""
market_context.py — External market context for Ed Console.

Fetches VIX (vol regime), optional native vol indices, TNX yield, and
env-configured index futures. Uses safe_get_quote per ticker.
All results returned as a MarketContext dataclass — caller manages caching.

The SPY/QQQ/IWM constituent-weight "index confluence" subsystem (hardcoded
fund tables, weighted pushes, IWM blend, bond_signal, T-08..T-15) is retired.
A missing value stays missing.
"""

from __future__ import annotations
import functools
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Callable, Optional, Any
import logging

log = logging.getLogger(__name__)


def _positive_float_or_none(value) -> Optional[float]:
    from numeric_contract import float_positive_or_none

    return float_positive_or_none(value)


def _float_or_none(value) -> Optional[float]:
    from numeric_contract import float_finite_or_none

    return float_finite_or_none(value)


def configured_index_futures_symbols() -> dict[str, str]:
    """
    Front-month CME index futures for Schwab REST/stream (contract-specific).
    Set env vars to full symbols, e.g. ED_FUTURES_ES=/ESH25 ED_FUTURES_NQ=/NQH25 ED_FUTURES_RTY=/RTYH25
    Empty / unset = skip fetch (no error).
    """
    out: dict[str, str] = {}
    for leg, env in (
        ("ES", "ED_FUTURES_ES"),
        ("NQ", "ED_FUTURES_NQ"),
        ("RTY", "ED_FUTURES_RTY"),
    ):
        v = (os.environ.get(env) or "").strip()
        if v:
            out[leg] = v
    return out


INDEX_CONFLUENCE_RETIRED_REASON = "index_confluence_retired"


def market_context_panel_symbols_excluding_core(core_upper: frozenset[str]) -> list[str]:
    """
    Symbols quoted every ``fetch_market_context`` cycle for snapshot enrollment.

    The retired index-confluence roster is gone. Only ``$VIX`` remains (vol regime).
    Excludes ``core_upper`` so callers do not duplicate ``CORE_TICKERS`` rows.
    ``$TNX`` stays unenrolled: it has no options chain (RC-495).
    """
    seen: set[str] = set()
    out: list[str] = []

    def add(sym: str) -> None:
        s = (sym or "").upper().strip()
        if not s or s in seen or s in core_upper:
            return
        seen.add(s)
        out.append(s)

    add("$VIX")
    return out


# CME index futures (Schwab: root + month/year, e.g. /ESH25, /NQH25, /RTYH25 — not generic /ES in all APIs).
# Streamer docs use level_one_futures; REST quotes may require full contract symbol from chains.
# Wire separately when account + symbol validation is confirmed (overnight session % vs cash ETF).


@dataclass
class ConstituentQuote:
    symbol:     str
    label:      str
    weight:     float              # actual SPY index weight (e.g. 0.0748)
    last:       Optional[float] = None
    chg_pct:    Optional[float] = None
    dot_color:  str             = "#d1d5db"
    contribution: Optional[float] = None   # weight * chg_pct — weighted push contribution


@dataclass
class SectorQuote:
    """One IWM sector proxy quote."""
    symbol:       str
    label:        str
    weight:       float
    last:         Optional[float] = None
    chg_pct:      Optional[float] = None
    dot_color:    str             = "#d1d5db"
    contribution: Optional[float] = None


@dataclass
class ConfluenceRead:
    """
    Primary confluence signal: weighted push + label.

    weighted_push: sum(weight_i * chg_pct_i) across all constituents with data.
        Interpretable as approximate % contribution to SPY from these names.
        e.g. +0.28 means top names are pushing SPY ~+0.28% on net.

    dot_count_green / dot_count_total: raw dot count for reference display.
    label / color: human-readable directional read driven by weighted_push.
    """
    weighted_push:      Optional[float] = None
    dot_count_green:    int             = 0
    dot_count_total:    int             = 0
    label:              str             = "—"
    color:              str             = "#6b7280"


@dataclass
class MarketContext:
    vix:             Optional[float] = None
    vix_regime:      str             = "—"
    vix_color:       str             = "#9ca3af"
    vix_implication: str             = ""

    # Vol-index lane V1 — additive fetch-only; not routed to SignalInput/ms_dict until V3/V5.
    vxn:             Optional[float] = None   # $VXN — Nasdaq-100 native vol (QQQ confluence)
    rvx:             Optional[float] = None   # $RVX — Russell 2000 native vol (IWM confluence)

    spy_last:        Optional[float] = None
    spy_chg_pct:     Optional[float] = None
    qqq_last:        Optional[float] = None
    qqq_chg_pct:     Optional[float] = None

    constituents:    list            = field(default_factory=list)  # list[ConstituentQuote]
    confluence:      ConfluenceRead  = field(default_factory=ConfluenceRead)

    # QQQ — cap-weighted top N names (same machinery as SPY constituents)
    qqq_constituents:  list            = field(default_factory=list)
    qqq_confluence:    ConfluenceRead  = field(default_factory=ConfluenceRead)

    # IWM — top individual holdings + existing sector proxies
    iwm_holdings:      list            = field(default_factory=list)  # ConstituentQuote
    iwm_holdings_confluence: ConfluenceRead = field(default_factory=ConfluenceRead)

    # IWM
    iwm_last:        Optional[float] = None
    iwm_chg_pct:     Optional[float] = None
    iwm_sectors:     list            = field(default_factory=list)   # list[SectorQuote]
    iwm_confluence:  ConfluenceRead  = field(default_factory=ConfluenceRead)

    # CME index futures (optional — symbols from ED_FUTURES_* env; Schwab contract format e.g. /ESH25)
    fut_es_symbol:     str             = ""
    fut_es_last:       Optional[float] = None
    fut_es_chg_pct:    Optional[float] = None
    fut_nq_symbol:     str             = ""
    fut_nq_last:       Optional[float] = None
    fut_nq_chg_pct:    Optional[float] = None
    fut_rty_symbol:    str             = ""
    fut_rty_last:      Optional[float] = None
    fut_rty_chg_pct:   Optional[float] = None

    # Bond yields
    tnx_yield:       Optional[float] = None   # 10Y Treasury yield (e.g. 4.25)
    tnx_chg:         Optional[float] = None   # change today (basis points concept: 4.25 → 4.30 = +0.05)
    bond_signal:     Optional[str]   = None  # set when TNX move is known; 'flight_to_safety', 'risk_on', 'neutral', 'rate_stress'

    pcr:             Optional[float] = None
    pcr_arrow:       str             = "→"
    pcr_color:       str             = "#9ca3af"
    pcr_label:       str             = ""

    # Session label — derived once from ET clock, shared across all tickers.
    # Values: "RTH" | "Pre-Market" | "After-Hours" | "Closed" (None until _derive_session runs)
    session_label:   Optional[str]   = None

    error:           str             = ""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _vix_regime(vix: float) -> tuple[str, str, str]:
    # The 15/20/30 cuts are the single-source authority (math_volatility.vix_tier_token);
    # this function owns ONLY the display mapping (label/color/implication), so the
    # thresholds can never drift from vix_bucket / the L1 adaptive-materiality engine.
    from math_volatility import vix_tier_token
    return {
        "low":      ("Low Vol",  "#166534", "Low vol — gamma walls stickier, pinning likely"),
        "normal":   ("Normal",   "#92400e", "Normal vol — gamma exposure reliable"),
        "elevated": ("Elevated", "#b45309", "Elevated vol — walls less sticky, widen stops"),
        "high":     ("High Vol", "#991b1b", "Vol spike — gamma unreliable, reduce size"),
    }.get(vix_tier_token(vix), ("Normal", "#92400e", "Normal vol — gamma exposure reliable"))


def _last_traded_price(quote: dict, ext: dict, reg: dict) -> Optional[float]:
    """``quotes.quote.lastPrice`` only. Missing stays missing (T-11).

    SPOT SEMANTICS (RC-16, 2026-07-19). A last may only be an actual trade.
    ``quote.mark`` and ``regularMarketLastPrice`` are the regular close, not last.
    ``extended.lastPrice`` is a different book — substituting it was T-11.
    ``or`` chaining treated a legitimate 0.0 as absent; 0.0 is not a trade.
    """
    _ = ext
    _ = reg
    candidate = (quote or {}).get("lastPrice")
    if candidate is not None and float(candidate) > 0:
        return candidate
    return None


def extract_pct_change(quote: dict, regular: dict, last: Optional[float]) -> Optional[float]:
    """
    ONE parser: ``quotes.quote.netPercentChange`` only (T-09). Missing stays missing.

    Shared by ``_extract_quote`` and ``server._parse_quote_node_session_fields``.
    ``regular`` / ``last`` stay in the signature so callers do not grow a second parser.
    """
    from numeric_contract import float_finite_or_none as _fin
    _ = regular
    _ = last
    return _fin((quote or {}).get("netPercentChange"))


def _extract_quote(symbol: str, q_json: dict) -> tuple[Optional[float], Optional[float]]:
    """Return (last, chg_pct) from a single-ticker Schwab quote payload."""
    try:
        data = q_json.get(symbol, {})
        quote = data.get("quote", {}) or {}
        ext = data.get("extended", {}) or {}
        reg = data.get("regular", {}) or {}
        last = _last_traded_price(quote, ext, reg)
        from numeric_contract import float_finite_or_none as _fin
        if last:
            last = _fin(last)
        pct_chg = extract_pct_change(quote, reg, last)
        return last, pct_chg
    except Exception:
        return None, None


def weighted_pushes_from_snapshot_row(
    row: Mapping[str, Any],
    *,
    extra_chg: Mapping[str, Optional[float]] | None = None,
) -> dict[str, Optional[float]]:
    """Retired: never recompute a weighted push from partial or aged constituent chg (T-15)."""
    _ = row
    _ = extra_chg
    return {
        "spy_weighted_push": None,
        "qqq_weighted_push": None,
        "iwm_weighted_push": None,
    }


def iwm_blended_participation_push(ctx: MarketContext) -> Optional[float]:
    """Retired (T-13). One side standing in for the other is a fallback."""
    _ = ctx
    return None


def _derive_session() -> str:
    """Market session label from the ET clock — HOLIDAY / early-close aware via the one
    time_et calendar authority. Returns "RTH" | "Pre-Market" | "After-Hours" | "Closed".

    No local RTH constants and no holiday blindness: the RTH close comes from
    session_close_mins_for_et_date (960 normal, 780 early-close), and weekends / full
    holidays / uncovered-calendar-years fail closed to "Closed" instead of falsely
    reporting "RTH" (the served session_label used to say "RTH" on a full holiday).
    """
    from time_et import now_et, session_close_mins_for_et_date, RTH_START_MINS

    now = now_et()
    if now.weekday() >= 5:                              # Sat / Sun
        return "Closed"
    close = session_close_mins_for_et_date(now.strftime("%Y-%m-%d"))
    if close is None:                                  # full holiday / uncovered year
        return "Closed"
    mins = now.hour * 60 + now.minute
    if mins < 240:            # before 04:00
        return "Closed"
    if mins < RTH_START_MINS:  # 04:00 – 09:29
        return "Pre-Market"
    if mins < close:           # 09:30 – close (960 normal, 780 early-close)
        return "RTH"
    if mins < 1200:            # close – 19:59
        return "After-Hours"
    return "Closed"


def resolve_chg_pct(ticker: str, rest_chg_pct: Optional[float], *,
                     stream_chg_pct_fn: Optional[Callable[[str], Optional[float]]] = None) -> Optional[float]:
    """
    Stream percent-change or None (T-10). REST is not a substitute.

    ``rest_chg_pct`` stays in the signature so callers do not grow a second parser.
    stream_chg_pct_fn defaults to app.options.order_flow.state.get_stream_chg_pct.
    """
    _ = rest_chg_pct
    fn = stream_chg_pct_fn
    if fn is None:
        try:
            from app.options.order_flow.state import get_stream_chg_pct as fn
        except Exception:
            fn = None
    if fn is not None:
        try:
            stream_chg = fn(ticker)
            if stream_chg is not None:
                return stream_chg
        except Exception as e:
            log.debug("resolve_chg_pct: stream_chg_pct_fn failed for %s: %s", ticker, e)
    return None


def fetch_market_context(client, safe_get_quote_fn,
                         pcr: Optional[float] = None,
                         prev_pcr: Optional[float] = None,
                         stream_chg_pct_fn: Optional[Callable[[str], Optional[float]]] = None) -> MarketContext:
    """
    Fetch VIX, optional vol indices, TNX yield, and env-configured futures.
    Index-confluence roster fetches are retired. Never raises — partial on error.
    """
    ctx    = MarketContext(pcr=pcr)
    errors = []

    def _fetch(sym):
        try:
            resp = safe_get_quote_fn(client, sym)
            if resp and resp.status_code == 200:
                return resp.json()
        except Exception as e:
            errors.append(f"{sym}: {e}")
        return {}

    _chg_for = functools.partial(resolve_chg_pct, stream_chg_pct_fn=stream_chg_pct_fn)

    # VIX — macro fear gauge; legacy ctx.vix semantics frozen (DUAL_GAUGE_HYBRID macro arm).
    vix_json = _fetch("$VIX")
    vix_last, _ = _extract_quote("$VIX", vix_json)
    if vix_last:
        ctx.vix = vix_last
        ctx.vix_regime, ctx.vix_color, ctx.vix_implication = _vix_regime(vix_last)

    # VXN / RVX — native vol indices (fetch-only; no consumer routing in V1 lane).
    # Schwab CSV authority checked: yes
    # CSV row(s): quotes.quote.lastPrice ($VXN); quotes.quote.lastPrice ($RVX)
    # Derived-field disposition: REPLACE_WITH_SCHWAB via _extract_quote wire-first chain
    # All consumers checked: no — V1 fetch-only; SignalInput/ms_dict routing is V3/V5 lane scope
    # REGISTER_ROW: f71114faa5593111d243, c03a3d4963e22eded241
    vxn_json = _fetch("$VXN")
    vxn_last, _ = _extract_quote("$VXN", vxn_json)
    if vxn_last:
        ctx.vxn = vxn_last

    rvx_json = _fetch("$RVX")
    rvx_last, _ = _extract_quote("$RVX", rvx_json)
    if rvx_last:
        ctx.rvx = rvx_last

    # TNX — 10-Year Treasury Yield. bond_signal is retired (T-08): never guessed.
    tnx_json = _fetch("$TNX")
    tnx_last, tnx_chg = _extract_quote("$TNX", tnx_json)
    if tnx_last:
        ctx.tnx_yield = tnx_last
        ctx.tnx_chg = tnx_chg

    # Index futures (ES / NQ / RTY) — same quote path as equities; symbol must be explicit contract.
    for leg, sym in configured_index_futures_symbols().items():
        j = _fetch(sym)
        last, chg = _extract_quote(sym, j)
        chg = _chg_for(sym, chg)
        if leg == "ES":
            ctx.fut_es_symbol, ctx.fut_es_last, ctx.fut_es_chg_pct = sym, last, chg
        elif leg == "NQ":
            ctx.fut_nq_symbol, ctx.fut_nq_last, ctx.fut_nq_chg_pct = sym, last, chg
        elif leg == "RTY":
            ctx.fut_rty_symbol, ctx.fut_rty_last, ctx.fut_rty_chg_pct = sym, last, chg

    if errors:
        ctx.error = "; ".join(errors[:3])

    # PCR trend
    if pcr is not None:
        if prev_pcr is None:
            ctx.pcr_arrow, ctx.pcr_color, ctx.pcr_label = "→", "#9ca3af", "baseline"
        elif pcr > prev_pcr + 0.05:
            ctx.pcr_arrow, ctx.pcr_color, ctx.pcr_label = "↑", "#991b1b", "put pressure building"
        elif pcr < prev_pcr - 0.05:
            ctx.pcr_arrow, ctx.pcr_color, ctx.pcr_label = "↓", "#166534", "hedges unwinding"
        else:
            ctx.pcr_arrow, ctx.pcr_color, ctx.pcr_label = "→", "#92400e", "flat"

    # Session label — derived from ET clock, shared across all tickers
    ctx.session_label = _derive_session()

    return ctx


def proximity_alerts(
    spot: Optional[float],
    walls_rows: list,
    pins_rows: list,
    threshold_pct: float = 0.005,
) -> list[dict]:
    """
    Return alert dicts for any wall/pin level within threshold_pct of spot.
    Works with WallRow / SummaryRow objects from math_exposure.
    """
    if spot is None or spot <= 0:
        return []
    alerts    = []
    threshold = float(spot) * threshold_pct

    def _check(level_obj, name_hint):
        level = None
        for attr in ("level", "strike", "strikePrice"):
            v = getattr(level_obj, attr, None)
            if v is not None:
                try:
                    level = float(v); break
                except Exception as e:
                    log.debug("strike level parse: %s", e, exc_info=True)
        if level is None:
            return
        dist = level - spot
        if abs(dist) > threshold:
            return
        role  = getattr(level_obj, "role", "") or getattr(level_obj, "type_label", "") or ""
        label = getattr(level_obj, "label", "") or getattr(level_obj, "row_label", "") or name_hint
        side  = "above" if dist >= 0 else "below"
        if "Magnet" in role or "Wall" in role:
            color   = "#dc2626" if side == "above" else "#2563eb"
            meaning = "Gamma wall — may accelerate through or reverse sharply"
        elif "Pin" in role:
            color   = "#b45309"
            meaning = "OI Pin — dealers defending, expect stall or reversal"
        else:
            color   = "#6b7280"
            meaning = "Key level"
        alerts.append(dict(level=level, name=label, dist=abs(dist),
                           side=side, color=color, meaning=meaning))

    for w in (walls_rows or []):
        _check(w, "Wall")
    for p in (pins_rows or []):
        _check(p, "Pin")

    return sorted(alerts, key=lambda a: a["dist"])


# ===========================================================================
# Price Action Levels — VWAP, PDH/PDL/PDC, ORB, Today OHLC
# ===========================================================================

def _volume_profile_poc_vah_val(bars: list, value_area_pct: float = 0.70,
                                 tick_size: float = 0.01) -> tuple[Optional[float], Optional[float], Optional[float]]:
    """POC / VAH / VAL from the ONE volume-profile construction (LP-01 Step 1, RC-152).

    This was a SECOND, independent copy of the same typical-price dump — it binned each bar's
    entire volume at (H+L+C)/3, and its output feeds `pd_poc/pd_vah/pd_val` and
    `today_poc/today_vah/today_val`. Two copies of a wrong construction is two wrong answers
    that can also disagree with each other; `liquidity_models` now owns the one implementation
    and distributes volume across [low, high]. Kept as a thin entry point so no caller changes,
    and `ndigits=2` preserves this module's original rounding.
    """
    from liquidity_models import volume_profile_poc_vah_val
    return volume_profile_poc_vah_val(bars, value_area_pct, tick_size, ndigits=2)


@dataclass
class PriceLevels:
    """
    Intraday institutional price action levels.
    Computed from Schwab price history (1-min bars) + quote OHLC.

    Two tiers:
      - Tier 1 (quote{}): today open/high/low. Not PDC — quote closePrice is a
        different book from the Phase 2A prior-session RTH close (RC-213/RC-415).
      - Tier 2 (canonical snapshot): VWAP, PDH, PDL, PDC, ORB high/low

    Extended (volume profile + bands):
      - pd_poc, pd_vah, pd_val: previous day POC/VAH/VAL
      - today_poc, today_vah, today_val: current day (same session)
      - vwap_p1, vwap_m1, vwap_p2, vwap_m2: VWAP standard deviation bands
      - overnight_high, overnight_low: pre-market range (when extended hours enabled)
      - orb_midpoint: (orb_high + orb_low) / 2
    """
    # Tier 1 — from quote{}
    today_open:   Optional[float] = None   # RTH open
    today_high:   Optional[float] = None   # RTH running high
    today_low:    Optional[float] = None   # RTH running low
    # PDC is the canonical snapshot's prior RTH session close, never quote closePrice.
    pdc:          Optional[float] = None

    # Tier 2 — from price history
    vwap:         Optional[float] = None   # Today intraday VWAP (RTH)
    pdh:          Optional[float] = None   # Previous day high
    pdl:          Optional[float] = None   # Previous day low
    orb_high:     Optional[float] = None   # Opening range high (first 30min)
    orb_low:      Optional[float] = None   # Opening range low (first 30min)
    orb_minutes:  int             = 15     # ORB window used

    # Volume profile — previous day
    pd_poc:       Optional[float] = None   # Previous day Point of Control
    pd_vah:       Optional[float] = None   # Previous day Value Area High
    pd_val:       Optional[float] = None   # Previous day Value Area Low

    # Volume profile — current day
    today_poc:    Optional[float] = None
    today_vah:    Optional[float] = None
    today_val:    Optional[float] = None

    # VWAP bands (standard deviations)
    vwap_p1:      Optional[float] = None   # VWAP + 1σ
    vwap_m1:      Optional[float] = None   # VWAP - 1σ
    vwap_p2:      Optional[float] = None   # VWAP + 2σ
    vwap_m2:      Optional[float] = None   # VWAP - 2σ

    # Overnight (pre-market) — requires need_extended_hours_data=True
    overnight_high: Optional[float] = None
    overnight_low:  Optional[float] = None

    # Derived
    orb_midpoint: Optional[float] = None   # (orb_high + orb_low) / 2

    # Meta
    bars_today:   int             = 0      # Number of 1-min bars for today
    session_rth_positive_volume_bars: int = 0  # same-session RTH bars with volume (VWAP input)
    error:        str             = ""

    # Phase 2A carriage identity — WHICH canonical snapshot these values came out of.
    # Carried, never recomputed; a consumer comparing two surfaces compares generations
    # too, so agreement-by-coincidence is distinguishable from agreement-by-identity.
    level_generation:     Optional[int]   = None
    level_semantic_scope: Optional[str]   = None
    level_as_of_ts_utc:   Optional[float] = None


def fetch_price_levels(
    client,
    symbol: str,
    quote_raw: dict | None = None,
    orb_minutes: int = 15,
    *,
    include_extended_hours: bool = False,
    level_snapshot=None,
) -> PriceLevels:
    """
    Tier 1 (today open/high/low) from the quote; every Phase 2A level CARRIED from the
    one canonical PriceLevelSnapshot. Never raises.

    Phase 2A (operator 2026-08-08): this function used to fetch its OWN Schwab
    TWO_DAYS minute history and run the level helpers over it. That was a second
    materialization of the same concepts — the same helpers, a different tape — and it
    is what put a different PDC/VWAP in the console header from the one /api/levels
    served. The vendor fetch is DELETED, not kept as a fallback: a fallback is exactly
    the second answer this invariant forbids.

    quote_raw: the raw quote JSON dict (from safe_get_quote response.json()).
    level_snapshot: the canonical snapshot. When absent, the materialized store is READ;
        when that is empty too, the Phase 2A fields stay absent (never substituted).
    ``client``, ``orb_minutes`` and ``include_extended_hours`` are retained for call-site
    compatibility; the canonical producer owns the bar input and the ORB window now.
    """
    from liquidity_value_engine import LevelCarrierConflict
    from time_et import now_et

    pl = PriceLevels(orb_minutes=orb_minutes)

    # ── Tier 1: extract from quote{} ─────────────────────────────────────────
    if quote_raw:
        try:
            sym_node = quote_raw.get(symbol.upper()) or quote_raw.get(symbol) or {}
            q = sym_node.get("quote", {}) or {}
            def _sf(key):
                # single source: canonical finite reader. Raw float() admitted NaN/inf
                # straight into today_open/high/low, and from there into the levels; the
                # finite reader rejects them and needs no try/except (it never raises).
                from numeric_contract import float_finite_or_none as _fin
                return _fin(q.get(key))
            pl.today_open = _sf("openPrice")
            pl.today_high = _sf("highPrice")
            pl.today_low  = _sf("lowPrice")
            # RC-415: do not seed pdc from quote closePrice. That field is the vendor
            # quote last close (can be extended-hours / a different session). PDC is
            # the last RTH 1m close of the prior session from the one snapshot.
            # Seeding here and overwriting only when carried PDC exists left closePrice
            # painted as PDC whenever the snapshot family was absent.
        except Exception as e:
            pl.error = f"quote parse: {e}"

    # ── Tier 2: CARRIED from the canonical PriceLevelSnapshot ────────────────
    try:
        from liquidity_value_engine import carry_snapshot_levels, get_materialized_snapshot

        snap = level_snapshot
        if snap is None:
            snap = get_materialized_snapshot(symbol, now_et().date())
        if snap is None:
            # Absence reads as absence (RC-68). There is deliberately no local
            # recomputation here — that fallback WAS the second faucet.
            pl.error = (pl.error + " | levels: no canonical snapshot materialized "
                                   "for this ticker/session yet").strip(" |")
            return pl

        carried = carry_snapshot_levels(snap, "market_context.fetch_price_levels")
        pl.pdh = carried["PDH"]
        pl.pdl = carried["PDL"]
        # RC-213 / RC-415: PDC is the last RTH 1m close of the single prior session
        # from the one snapshot. Assign even when None — absence withholds. Quote
        # closePrice is not a fallback (that WAS the second authority).
        pl.pdc = carried["PDC"]
        pl.pd_poc, pl.pd_vah, pl.pd_val = (
            carried["PD_POC"], carried["PD_VAH"], carried["PD_VAL"])
        pl.overnight_high, pl.overnight_low = (
            carried["OVERNIGHT_HIGH"], carried["OVERNIGHT_LOW"])
        pl.orb_high, pl.orb_low = carried["ORB_HIGH"], carried["ORB_LOW"]
        pl.orb_midpoint = carried["ORB_MID"]
        pl.vwap = carried["VWAP"]
        pl.vwap_p1, pl.vwap_m1, pl.vwap_p2, pl.vwap_m2 = (
            carried["VWAP_P1"], carried["VWAP_M1"], carried["VWAP_P2"], carried["VWAP_M2"])
        pl.today_poc, pl.today_vah, pl.today_val = (
            carried["TODAY_POC"], carried["TODAY_VAH"], carried["TODAY_VAL"])
        pl.bars_today = snap.bars_used
        pl.session_rth_positive_volume_bars = int(
            getattr(snap, "session_rth_positive_volume_bars", 0) or 0
        )
        pl.level_generation = snap.generation
        pl.level_semantic_scope = "session_rth"
        pl.level_as_of_ts_utc = snap.as_of_ts_utc

    except LevelCarrierConflict:
        # NEVER swallowed: two carriers disagreeing for one (ticker, level_id, scope,
        # generation) is the exact failure this architecture exists to make impossible.
        # Degrading it to a string in `error` would restore the silent divergence.
        raise
    except Exception as e:
        err_str = str(e)[:120]
        pl.error = (pl.error + f" | levels: {err_str}").strip(" |")

    return pl


def missing_confluence_weighted_pushes(ctx: MarketContext) -> list[str]:
    """Retired: no weighted-push field is required, so nothing is "missing"."""
    _ = ctx
    return []


def stamp_confluence_display_fields(mkt_ctx: "MarketContext | None") -> dict[str, object]:
    """ONE /api/state faucet for retired index-confluence keys (F39). Always withheld."""
    _ = mkt_ctx
    return {
        "cf_weighted_push": None,
        "cf_label": "—",
        "cf_color": "#9ca3af",
        "cf_unavailable_reason": INDEX_CONFLUENCE_RETIRED_REASON,
        "qqq_cf_weighted_push": None,
        "qqq_cf_label": "—",
        "qqq_cf_color": "#9ca3af",
        "iwm_holdings_cf_push": None,
        "iwm_holdings_cf_label": "—",
        "iwm_holdings_cf_color": "#9ca3af",
        "iwm_cf_push": None,
        "iwm_cf_label": "—",
        "iwm_cf_color": "#9ca3af",
        "iwm_participation_push": None,
        "cf_dot_green": None,
        "cf_dot_total": None,
    }


def confluence_quote_rows_from_context(
    ctx: MarketContext,
    *,
    ts_utc: float,
    ts_et: str,
) -> list[dict[str, Any]]:
    """Thin quote rows for remaining context symbols (VIX; TNX when quoted)."""
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(sym: str, last: Optional[float], chg: Optional[float]) -> None:
        s = (sym or "").upper().strip()
        if not s or s in seen:
            return
        seen.add(s)
        rows.append(
            {
                "ticker": s,
                "ts_utc": ts_utc,
                "ts_et": ts_et,
                "last_price": last,
                "chg_pct": chg,
            }
        )

    add("$VIX", ctx.vix, None)
    if ctx.tnx_yield is not None:
        add("$TNX", ctx.tnx_yield, ctx.tnx_chg)
    return rows

