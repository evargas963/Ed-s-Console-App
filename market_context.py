"""
market_context.py — External market context for Ed Console.

Fetches VIX, SPY/QQQ, and top constituent quotes via the authenticated Schwab client.
Uses safe_get_quote per ticker (consistent with existing app patterns).
All results returned as a MarketContext dataclass — caller manages caching in session_state.
"""

from __future__ import annotations
import os
from dataclasses import dataclass, field
from typing import Callable, Optional


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


# ── Top SPY constituents — current weights as of Feb 2026 ────────────────────
# Source: SPDR SPY holdings. Weights updated periodically — these drive the
# weighted_push calculation which is the primary confluence signal.
SPY_TOP = [
    ("NVDA",  "Nvidia",          0.0748),
    ("AAPL",  "Apple",           0.0720),
    ("MSFT",  "Microsoft",       0.0606),
    ("AMZN",  "Amazon",          0.0385),
    ("GOOGL", "Alphabet A",      0.0317),
    ("AVGO",  "Broadcom",        0.0306),
    ("GOOG",  "Alphabet C",      0.0256),
    ("META",  "Meta",            0.0237),
    ("TSLA",  "Tesla",           0.0214),
]

# Combined weight of the 9 constituents above — used to normalise weighted_push
# so the output is interpretable as "approx % SPY move from these names alone"
SPY_TOP_WEIGHT_SUM = sum(w for _, _, w in SPY_TOP)   # ~0.279

# ── QQQ top Nasdaq-100 names (approx index weights; refresh quarterly from fund factsheet)
QQQ_TOP = [
    ("NVDA",  "Nvidia",     0.0850),
    ("AAPL",  "Apple",      0.0750),
    ("MSFT",  "Microsoft",  0.0570),
    ("AMZN",  "Amazon",     0.0450),
    ("TSLA",  "Tesla",      0.0380),
    ("META",  "Meta",       0.0360),
    ("GOOGL", "Alphabet A", 0.0340),
    ("WMT",   "Walmart",    0.0340),
    ("GOOG",  "Alphabet C", 0.0320),
    ("AVGO",  "Broadcom",   0.0290),
]
QQQ_TOP_WEIGHT_SUM = sum(w for _, _, w in QQQ_TOP)

# ── IWM top holdings (small weights each; Russell 2000 is diffuse — refresh from iShares holdings)
IWM_TOP_HOLDINGS = [
    ("BE",   "Bloom Energy",      0.0105),
    ("FN",   "Fabrinet",         0.0071),
    ("NXT",  "Nextpower",        0.0062),
    ("CDE",  "Coeur Mining",     0.0058),
    ("CRDO", "Credo Tech",       0.0055),
    ("SATS", "EchoStar",         0.0052),
    ("KTOS", "Kratos",           0.0047),
    ("STRL", "Sterling Infra",   0.0044),
    ("AEIS", "Adv Energy",       0.0041),
    ("BBIO", "BridgeBio",        0.0039),
]
IWM_HOLDINGS_WEIGHT_SUM = sum(w for _, _, w in IWM_TOP_HOLDINGS)

# ── IWM sector proxies — Russell 2000 sector coverage ────────────────────────
# These 4 ETFs cover ~63% of IWM's weight with meaningful proxies.
IWM_SECTORS = [
    ("KRE",  "Financials",   0.18),   # Regional banks — largest IWM sector
    ("XBI",  "Healthcare",   0.17),   # Biotech/small cap healthcare
    ("PSCI", "Industrials",  0.17),   # S&P SmallCap Industrials ETF
    ("XRT",  "Consumer",     0.11),   # Equal-weight retail / consumer disc
]
IWM_SECTOR_WEIGHT_SUM = sum(w for _, _, w in IWM_SECTORS)  # ~0.63

CONTEXT_TICKERS_MARKET = ["SPY", "QQQ", "IWM", "$VIX"]


def market_context_panel_symbols_excluding_core(core_upper: frozenset[str]) -> list[str]:
    """
    Equity / index symbols whose quotes are pulled every ``fetch_market_context`` cycle for the UI
    cross-instrument panel (SPY/QQQ/IWM tops, IWM sector ETFs, VIX, 10Y).

    Excludes ``core_upper`` so callers do not duplicate ``CORE_TICKERS`` rows in ``logging_universe``.
    Order is deterministic (tables top-to-bottom, then macro indices).
    """
    seen: set[str] = set()
    out: list[str] = []

    def add(sym: str) -> None:
        s = (sym or "").upper().strip()
        if not s or s in seen or s in core_upper:
            return
        seen.add(s)
        out.append(s)

    for sym, _, _ in SPY_TOP:
        add(sym)
    for sym, _, _ in QQQ_TOP:
        add(sym)
    for sym, _, _ in IWM_TOP_HOLDINGS:
        add(sym)
    for sym, _, _ in IWM_SECTORS:
        add(sym)
    add("$VIX")
    add("$TNX")
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
    bond_signal:     str             = "neutral"  # 'flight_to_safety', 'risk_on', 'neutral', 'rate_stress'

    pcr:             Optional[float] = None
    pcr_arrow:       str             = "→"
    pcr_color:       str             = "#9ca3af"
    pcr_label:       str             = ""

    # Session label — derived once from ET clock, shared across all tickers.
    # Values: "RTH" | "Pre-Market" | "After-Hours" | "Closed"
    session_label:   str             = "Closed"

    error:           str             = ""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _vix_regime(vix: float) -> tuple[str, str, str]:
    if vix < 15:
        return "Low Vol",   "#166534", "Low vol — gamma walls stickier, pinning likely"
    elif vix < 20:
        return "Normal",    "#92400e", "Normal vol — gamma exposure reliable"
    elif vix < 30:
        return "Elevated",  "#b45309", "Elevated vol — walls less sticky, widen stops"
    else:
        return "High Vol",  "#991b1b", "Vol spike — gamma unreliable, reduce size"


def _dot_color(chg_pct: Optional[float]) -> str:
    if chg_pct is None:   return "#d1d5db"
    if chg_pct >  0.5:    return "#16a34a"   # strong green
    if chg_pct >  0.0:    return "#86efac"   # light green
    if chg_pct > -0.5:    return "#fca5a5"   # light red
    return "#dc2626"                          # strong red


def _extract_quote(symbol: str, q_json: dict) -> tuple[Optional[float], Optional[float]]:
    """Return (last, chg_pct) from a single-ticker Schwab quote payload."""
    try:
        data    = q_json.get(symbol, {})
        quote   = data.get("quote", {})
        last    = quote.get("lastPrice") or quote.get("mark") or quote.get("last")
        pct_chg = quote.get("netPercentChange")
        net_chg = quote.get("netChange")
        if last:
            last = float(last)
        if pct_chg is not None:
            pct_chg = float(pct_chg)
        elif net_chg is not None and last and (last - float(net_chg)) != 0:
            pct_chg = float(net_chg) / (last - float(net_chg)) * 100.0
        return last, pct_chg
    except Exception:
        return None, None


def _build_confluence(constituents: list, weight_sum_ref: float,
                      mod_thr: float = 0.15, strong_thr: float = 0.30) -> ConfluenceRead:
    """
    Cap-weighted participation: sum(weight_i * chg_pct_i), normalised to weight_sum_ref.

    weight_sum_ref: SPY_TOP_WEIGHT_SUM, QQQ_TOP_WEIGHT_SUM, or IWM_HOLDINGS_WEIGHT_SUM.
    Thresholds (mod_thr / strong_thr) are in the same units as SPY top-9 read (~pct points).
    """
    push        = 0.0
    weight_used = 0.0
    greens      = 0
    total       = 0

    for cq in constituents:
        total += 1
        if cq.chg_pct is not None:
            contrib      = cq.weight * cq.chg_pct
            cq.contribution = contrib
            push         += contrib
            weight_used  += cq.weight
            if cq.chg_pct > 0:
                greens += 1

    if weight_used > 0 and weight_used < weight_sum_ref * 0.5:
        push = push / weight_used * weight_sum_ref

    weighted_push = round(push, 3) if weight_used > 0 else None

    if weighted_push is None:
        label, color = "No data", "#9ca3af"
    elif weighted_push >  strong_thr:
        label, color = "Strong bull confluence", "#166534"
    elif weighted_push >  mod_thr:
        label, color = "Moderate bull confluence", "#92400e"
    elif weighted_push < -strong_thr:
        label, color = "Strong bear confluence", "#991b1b"
    elif weighted_push < -mod_thr:
        label, color = "Moderate bear confluence", "#b45309"
    else:
        label, color = "Mixed — no clear directional confluence", "#6b7280"

    return ConfluenceRead(
        weighted_push=weighted_push,
        dot_count_green=greens,
        dot_count_total=total,
        label=label,
        color=color,
    )


def _build_iwm_confluence(sectors: list) -> ConfluenceRead:
    """
    Compute weighted push from IWM sector proxies.
    Same logic as _build_confluence but uses IWM_SECTOR_WEIGHT_SUM.
    """
    push        = 0.0
    weight_used = 0.0
    greens      = 0
    total       = 0

    for sq in sectors:
        total += 1
        if sq.chg_pct is not None:
            contrib       = sq.weight * sq.chg_pct
            sq.contribution = contrib
            push         += contrib
            weight_used  += sq.weight
            if sq.chg_pct > 0:
                greens += 1

    if weight_used > 0 and weight_used < IWM_SECTOR_WEIGHT_SUM * 0.5:
        push = push / weight_used * IWM_SECTOR_WEIGHT_SUM

    weighted_push = round(push, 3) if weight_used > 0 else None

    if weighted_push is None:
        label, color = "No data", "#9ca3af"
    elif weighted_push >  0.20:
        label, color = "Risk ON — sectors bullish", "#166534"
    elif weighted_push >  0.08:
        label, color = "Mild risk ON", "#92400e"
    elif weighted_push < -0.20:
        label, color = "Risk OFF — sectors bearish", "#991b1b"
    elif weighted_push < -0.08:
        label, color = "Mild risk OFF", "#b45309"
    else:
        label, color = "Neutral — mixed sectors", "#6b7280"

    return ConfluenceRead(
        weighted_push=weighted_push,
        dot_count_green=greens,
        dot_count_total=total,
        label=label,
        color=color,
    )


def iwm_blended_participation_push(ctx: MarketContext) -> Optional[float]:
    """
    Russell 2000 tape participation for the stack: blend top-holdings confluence
    with sector-proxy confluence (IWM is diffuse — ~55% weight on named holdings,
    ~45% on sector ETFs). Falls back to whichever side has data.
    """
    hcf = getattr(ctx, "iwm_holdings_confluence", None)
    scf = getattr(ctx, "iwm_confluence", None)
    h = getattr(hcf, "weighted_push", None) if hcf is not None else None
    s = getattr(scf, "weighted_push", None) if scf is not None else None
    wh, ws = 0.55, 0.45
    try:
        if h is not None and s is not None:
            return round(wh * float(h) + ws * float(s), 4)
        if h is not None:
            return round(float(h), 4)
        if s is not None:
            return round(float(s), 4)
    except (TypeError, ValueError):
        pass
    return None


def _derive_session() -> str:
    """
    Derive market session label from the ET clock.
    Returns one of: "RTH" | "Pre-Market" | "After-Hours" | "Closed"

    Boundaries (ET):
      Pre-Market:  04:00 – 09:29
      RTH:         09:30 – 15:59
      After-Hours: 16:00 – 19:59
      Closed:      20:00 – 03:59 (overnight)
    """
    from datetime import datetime
    from zoneinfo import ZoneInfo
    now = datetime.now(ZoneInfo("America/New_York"))
    mins = now.hour * 60 + now.minute
    if 570 <= mins <= 959:    # 09:30 – 15:59
        return "RTH"
    if 240 <= mins <= 569:    # 04:00 – 09:29
        return "Pre-Market"
    if 960 <= mins <= 1199:   # 16:00 – 19:59
        return "After-Hours"
    return "Closed"


def fetch_market_context(client, safe_get_quote_fn,
                         pcr: Optional[float] = None,
                         prev_pcr: Optional[float] = None,
                         stream_chg_pct_fn: Optional[Callable[[str], Optional[float]]] = None) -> MarketContext:
    """
    Fetch market context. safe_get_quote_fn is the already-imported safe_get_quote.
    stream_chg_pct_fn: when provided (e.g. get_stream_chg_pct), uses stream
        REGULAR_MARKET_CHANGE_PERCENT/CHANGE_PERCENT as primary over REST-derived chg_pct.
    Never raises — returns partial context on any error.
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

    def _chg_for(sym: str, rest_chg: Optional[float]) -> Optional[float]:
        """Stream chg_pct primary; REST derivation fallback."""
        if stream_chg_pct_fn:
            stream_chg = stream_chg_pct_fn(sym)
            if stream_chg is not None:
                return stream_chg
        return rest_chg

    # VIX
    vix_json = _fetch("$VIX")
    vix_last, _ = _extract_quote("$VIX", vix_json)
    if vix_last:
        ctx.vix = vix_last
        ctx.vix_regime, ctx.vix_color, ctx.vix_implication = _vix_regime(vix_last)

    # SPY
    spy_json = _fetch("SPY")
    ctx.spy_last, _spy_chg = _extract_quote("SPY", spy_json)
    ctx.spy_chg_pct = _chg_for("SPY", _spy_chg)

    # QQQ
    qqq_json = _fetch("QQQ")
    ctx.qqq_last, _qqq_chg = _extract_quote("QQQ", qqq_json)
    ctx.qqq_chg_pct = _chg_for("QQQ", _qqq_chg)

    # IWM
    iwm_json = _fetch("IWM")
    ctx.iwm_last, _iwm_chg = _extract_quote("IWM", iwm_json)
    ctx.iwm_chg_pct = _chg_for("IWM", _iwm_chg)

    # IWM sector proxies — KRE, XBI, PSCI, XRT
    for sym, label, weight in IWM_SECTORS:
        j = _fetch(sym)
        last, chg = _extract_quote(sym, j)
        chg = _chg_for(sym, chg)
        ctx.iwm_sectors.append(SectorQuote(
            symbol=sym, label=label, weight=weight,
            last=last, chg_pct=chg, dot_color=_dot_color(chg),
        ))
    ctx.iwm_confluence = _build_iwm_confluence(ctx.iwm_sectors)

    # TNX — 10-Year Treasury Yield
    tnx_json = _fetch("$TNX")
    tnx_last, tnx_chg = _extract_quote("$TNX", tnx_json)
    if tnx_last:
        ctx.tnx_yield = tnx_last
        ctx.tnx_chg = tnx_chg
        # Bond signal interpretation:
        # Yields falling = bonds buying = flight to safety (risk-off for equities)
        # Yields rising  = bonds selling = risk appetite OR rate stress
        # Context from VIX matters: yields falling + VIX rising = pure risk-off
        #                            yields rising + VIX low = healthy risk-on
        #                            yields rising + VIX high = rate stress
        if tnx_chg is not None:
            if tnx_chg < -0.5:  # yields dropping fast
                ctx.bond_signal = "flight_to_safety"
            elif tnx_chg < -0.15:
                ctx.bond_signal = "flight_to_safety" if (ctx.vix and ctx.vix > 20) else "neutral"
            elif tnx_chg > 0.5:  # yields spiking
                ctx.bond_signal = "rate_stress" if (ctx.vix and ctx.vix > 22) else "risk_on"
            elif tnx_chg > 0.15:
                ctx.bond_signal = "risk_on"
            else:
                ctx.bond_signal = "neutral"

    # Constituents — fetch all 9, build ConstituentQuote list
    for sym, label, weight in SPY_TOP:
        j = _fetch(sym)
        last, chg = _extract_quote(sym, j)
        chg = _chg_for(sym, chg)
        ctx.constituents.append(ConstituentQuote(
            symbol=sym, label=label, weight=weight,
            last=last, chg_pct=chg, dot_color=_dot_color(chg),
        ))

    # Weighted confluence — computed after all constituents are populated
    ctx.confluence = _build_confluence(ctx.constituents, SPY_TOP_WEIGHT_SUM)

    # QQQ — top Nasdaq-100 holdings (participation, not “3 ETFs agree”)
    for sym, label, weight in QQQ_TOP:
        j = _fetch(sym)
        last, chg = _extract_quote(sym, j)
        chg = _chg_for(sym, chg)
        ctx.qqq_constituents.append(ConstituentQuote(
            symbol=sym, label=label, weight=weight,
            last=last, chg_pct=chg, dot_color=_dot_color(chg),
        ))
    ctx.qqq_confluence = _build_confluence(ctx.qqq_constituents, QQQ_TOP_WEIGHT_SUM)

    # IWM — top individual Russell names (diffuse index; ~5–6% of fund from top 10)
    for sym, label, weight in IWM_TOP_HOLDINGS:
        j = _fetch(sym)
        last, chg = _extract_quote(sym, j)
        chg = _chg_for(sym, chg)
        ctx.iwm_holdings.append(ConstituentQuote(
            symbol=sym, label=label, weight=weight,
            last=last, chg_pct=chg, dot_color=_dot_color(chg),
        ))
    ctx.iwm_holdings_confluence = _build_confluence(
        ctx.iwm_holdings, IWM_HOLDINGS_WEIGHT_SUM, mod_thr=0.03, strong_thr=0.06,
    )

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


def proximity_alerts(spot: float, walls_rows: list, pins_rows: list,
                     threshold_pct: float = 0.005) -> list[dict]:
    """
    Return alert dicts for any wall/pin level within threshold_pct of spot.
    Works with WallRow / SummaryRow objects from math_exposure.
    """
    alerts    = []
    threshold = spot * threshold_pct

    def _check(level_obj, name_hint):
        level = None
        for attr in ("level", "strike", "strikePrice"):
            v = getattr(level_obj, attr, None)
            if v is not None:
                try:
                    level = float(v); break
                except Exception:
                    pass
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
    """
    Compute POC (Point of Control), VAH (Value Area High), VAL (Value Area Low)
    from bars with 'open','high','low','close','volume'.
    POC = price with max volume. Value area = smallest range containing
    value_area_pct of volume, centered on POC.
    Returns (poc, vah, val).
    """
    if not bars:
        return None, None, None
    from collections import defaultdict
    vol_by_price: dict[float, float] = defaultdict(float)
    for c in bars:
        o = float(c.get("open", 0) or 0)
        h = float(c.get("high", 0) or 0)
        l = float(c.get("low", 0) or 0)
        cl = float(c.get("close", 0) or 0)
        vol = float(c.get("volume", 0) or 0)
        if vol <= 0:
            continue
        typical = (h + l + cl) / 3.0
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
    lo_idx = prices_sorted.index(poc_price) if poc_price in prices_sorted else 0
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
    return round(poc_price, 2), round(best_hi, 2), round(best_lo, 2)


def _vwap_bands(bars: list, vwap_val: float) -> tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
    """Compute VWAP ±1σ and ±2σ. Returns (vwap_p1, vwap_m1, vwap_p2, vwap_m2)."""
    if not bars or vwap_val is None:
        return None, None, None, None
    cum_var = 0.0
    cum_vol = 0.0
    for c in bars:
        h = float(c.get("high", 0) or 0)
        l = float(c.get("low", 0) or 0)
        cl = float(c.get("close", 0) or 0)
        vol = float(c.get("volume", 0) or 0)
        if vol <= 0:
            continue
        typical = (h + l + cl) / 3.0
        cum_var += (typical - vwap_val) ** 2 * vol
        cum_vol += vol
    if cum_vol <= 0:
        return None, None, None, None
    std = (cum_var / cum_vol) ** 0.5
    return (
        round(vwap_val + std, 2),
        round(vwap_val - std, 2),
        round(vwap_val + 2 * std, 2),
        round(vwap_val - 2 * std, 2),
    )


@dataclass
class PriceLevels:
    """
    Intraday institutional price action levels.
    Computed from Schwab price history (1-min bars) + quote OHLC.

    Two tiers:
      - Tier 1 (always available): today open/high/low, PDC from quote{}
      - Tier 2 (needs price history): VWAP, PDH, PDL, ORB high/low

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
    pdc:          Optional[float] = None   # Previous day close

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
    error:        str             = ""


def fetch_price_levels(
    client,
    symbol: str,
    quote_raw: dict | None = None,
    orb_minutes: int = 15,
    *,
    include_extended_hours: bool = False,
) -> PriceLevels:
    """
    Fetch VWAP, PDH/PDL/PDC, ORB, POC/VAH/VAL, VWAP bands from Schwab price history + quote.
    Never raises. Returns best available data with graceful fallback.

    quote_raw: the raw quote JSON dict (from safe_get_quote response.json())
               Used for Tier 1 fallback (today open/high/low/PDC).
    include_extended_hours: if True, fetches pre-market for overnight high/low.
    """
    from datetime import datetime, date, timezone, timedelta
    from zoneinfo import ZoneInfo

    pl = PriceLevels(orb_minutes=orb_minutes)
    ET = ZoneInfo("America/New_York")
    RTH_OPEN_HOUR  = 9
    RTH_OPEN_MIN   = 30
    RTH_CLOSE_HOUR = 16

    # ── Tier 1: extract from quote{} ─────────────────────────────────────────
    if quote_raw:
        try:
            sym_node = quote_raw.get(symbol.upper()) or quote_raw.get(symbol) or {}
            q = sym_node.get("quote", {}) or sym_node.get("reference", {}) or {}
            def _sf(key):
                try: return float(q.get(key)) if q.get(key) is not None else None
                except Exception: return None
            pl.today_open = _sf("openPrice")
            pl.today_high = _sf("highPrice")
            pl.today_low  = _sf("lowPrice")
            pl.pdc        = _sf("closePrice")
        except Exception as e:
            pl.error = f"quote parse: {e}"

    # ── Tier 2: price history for VWAP + PDH/PDL + ORB ──────────────────────
    try:
        # schwab-py uses nested enums on the Client class.
        # Try enum-based call first, then fall back to raw string kwargs.
        resp = None
        try:
            import schwab as _schwab
            PH = _schwab.client.Client.PriceHistory
            resp = client.get_price_history(
                symbol,
                period_type=PH.PeriodType.DAY,
                period=PH.Period.TWO_DAYS,
                frequency_type=PH.FrequencyType.MINUTE,
                frequency=PH.Frequency.EVERY_MINUTE,
                need_extended_hours_data=include_extended_hours,
            )
        except Exception:
            try:
                resp = client.get_price_history(
                    symbol,
                    periodType="day",
                    period=2,
                    frequencyType="minute",
                    frequency=1,
                    needExtendedHoursData=include_extended_hours,
                )
            except Exception:
                resp = None

        if resp is None or resp.status_code != 200:
            raise ValueError(f"price history fetch failed (status {getattr(resp,'status_code','?')})")

        candles = resp.json().get("candles", [])
        if not candles:
            raise ValueError("empty candles")

        today_date = datetime.now(ET).date()
        today_bars = []
        prev_bars  = []
        overnight_bars = []

        for c in candles:
            dt_ms  = c.get("datetime", 0)
            dt_utc = datetime.fromtimestamp(dt_ms / 1000, tz=timezone.utc)
            dt_et  = dt_utc.astimezone(ET)
            is_rth = (
                dt_et.hour > RTH_OPEN_HOUR or
                (dt_et.hour == RTH_OPEN_HOUR and dt_et.minute >= RTH_OPEN_MIN)
            ) and dt_et.hour < RTH_CLOSE_HOUR
            if not is_rth:
                if include_extended_hours and dt_et.date() == today_date:
                    mins = dt_et.hour * 60 + dt_et.minute
                    if mins < RTH_OPEN_HOUR * 60 + RTH_OPEN_MIN:
                        overnight_bars.append((dt_et, c))
                continue
            if dt_et.date() == today_date:
                today_bars.append((dt_et, c))
            elif dt_et.date() < today_date:
                prev_bars.append((dt_et, c))

        # ── PDH / PDL / POC / VAH / VAL from previous session ────────────────
        if prev_bars:
            prev_candles = [c for _, c in prev_bars]
            pl.pdh = max(c["high"] for _, c in prev_bars)
            pl.pdl = min(c["low"] for _, c in prev_bars)
            if pl.pdc is None:
                pl.pdc = prev_bars[-1][1]["close"]
            pl.pd_poc, pl.pd_vah, pl.pd_val = _volume_profile_poc_vah_val(prev_candles)

        # ── Overnight high/low ────────────────────────────────────────────────
        if overnight_bars:
            pl.overnight_high = max(c["high"] for _, c in overnight_bars)
            pl.overnight_low  = min(c["low"] for _, c in overnight_bars)

        # ── VWAP + bands + ORB + today POC/VAH/VAL ───────────────────────────
        if today_bars:
            today_candles = [c for _, c in today_bars]
            pl.bars_today = len(today_bars)
            cum_tpv = 0.0
            cum_vol = 0.0
            orb_h, orb_l = -1e9, 1e9
            orb_bars_seen = 0

            for dt_et, c in today_bars:
                o, h, l, cl, vol = (
                    float(c.get("open",  0)),
                    float(c.get("high",  0)),
                    float(c.get("low",   0)),
                    float(c.get("close", 0)),
                    float(c.get("volume", 0)),
                )
                typical = (h + l + cl) / 3.0
                cum_tpv += typical * vol
                cum_vol += vol

                # ORB: first orb_minutes of RTH
                mins_since_open = (
                    (dt_et.hour - RTH_OPEN_HOUR) * 60 +
                    (dt_et.minute - RTH_OPEN_MIN)
                )
                if mins_since_open < orb_minutes:
                    orb_h = max(orb_h, h)
                    orb_l = min(orb_l, l)
                    orb_bars_seen += 1

            if cum_vol > 0:
                pl.vwap = cum_tpv / cum_vol
                pl.vwap_p1, pl.vwap_m1, pl.vwap_p2, pl.vwap_m2 = _vwap_bands(today_candles, pl.vwap)

            if orb_bars_seen > 0 and orb_h > -1e9:
                pl.orb_high = orb_h
                pl.orb_low  = orb_l
                pl.orb_midpoint = (orb_h + orb_l) / 2.0

            pl.today_poc, pl.today_vah, pl.today_val = _volume_profile_poc_vah_val(today_candles)

    except Exception as e:
        err_str = str(e)[:120]
        pl.error = (pl.error + f" | history: {err_str}").strip(" |")

    return pl
