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




# ── Helpers ───────────────────────────────────────────────────────────────────















# ===========================================================================
# Price Action Levels — VWAP, PDH/PDL/PDC, ORB, Today OHLC
# ===========================================================================








