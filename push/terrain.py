"""The `terrain` panel: a ticker's published levels at the live price, with its ATRs and mark.

Read from State: the published levels (state.level_store), the live price, and the daily, weekly
and monthly candles the bar writer holds (state.bar_store, push.bars.daily_candles).
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any, TypedDict

import live_market_plane as lmp
from app.options.order_flow.streaming import price_state
from calc.terrain_atr import Atr, compute_atrs
from calc.terrain_engine import compute_terrain, price_relations
from calc.terrain_read import REGIME_NAME, REGIME_TEXT
from instrument_identity import ticker_storage_key
from numeric_contract import price_text
from push.bars import daily_candles
from push.spot import price_mark, resolve_spot
from push.verdict import terrain_cache_get
from state import bar_store, level_store
from time_et import ET, sessions


class LevelsMark(TypedDict):
    """The one word the Key Levels line shows, and why (levels_mark)."""

    levels_mark: str
    levels_mark_reason: str | None


def levels_mark(levels: Mapping[str, Any], ticker: str, now: float) -> LevelsMark:
    """Return the one word the Key Levels line shows, from the levels' verdict and their price's.

    From terrain_staleness and price_state: the levels' state while it is not LIVE, else the
    price's state (the walls stand and are LIVE only while the price they are measured from is
    live), with why.
    """
    if levels["levels_state"] != lmp.LIVE:
        return {
            "levels_mark": levels["levels_state"],
            "levels_mark_reason": levels["levels_stale_reason"],
        }
    label, outage = price_state(ticker, now)
    return {"levels_mark": label, "levels_mark_reason": outage}


def atr(ticker: str, now: datetime) -> Atr:
    """Return the ticker's daily, weekly and monthly ATR at `now`, each from Schwab's candles.

    The daily from push.bars.daily_candles, the daily chart's own; the weekly and monthly from
    Schwab's own weekly and monthly /pricehistory series as the bar writer holds them
    (state.bar_store). Too few reads as None.
    """
    tk = ticker_storage_key(ticker)
    return compute_atrs(
        daily_candles(tk, now), bar_store.series(tk, "1w"), bar_store.series(tk, "1mo")
    )


def _atr_fields(tk: str, now: datetime) -> dict[str, float | str | None]:
    """atr_daily / atr_weekly / atr_monthly at `now`, each with its text.

    A horizon that cannot be computed is None.
    """
    a = atr(tk, now)
    atrs = {"atr_daily": a.daily, "atr_weekly": a.weekly, "atr_monthly": a.monthly}
    return atrs | {f"{name}_text": price_text(value) for name, value in atrs.items()}


def _regime_words(regime: str) -> dict[str, str]:
    """Return a regime as the screen says it: in short, and its name in words (terrain_read)."""
    return {"regime_text": REGIME_TEXT[regime], "regime_name": REGIME_NAME[regime]}


def terrain(tk: str, now: float) -> dict[str, Any]:
    """Return `tk`'s published levels at `now`, at the live price (the `terrain` panel).

    `tk` is the levels' own key ($SPX). The page's socket sends
    them to Key Levels, the Gamma chart, the Trade Desk's Right Now and its map (live_ui,
    PAGE_PANELS), at once and each time the levels change (server._levels_changed).
    """
    at = datetime.fromtimestamp(now, ET)
    cached, staleness = terrain_cache_get(tk, now)
    if cached is not None:
        # the levels as the producer published them; `spot` is the live price, and every relation
        # of the price to the levels is at it (price_relations); internal fields (the kept chain,
        # the heatmap grid, per-strike rows) are their own panels
        out = cached.served() | staleness
        out["spot"], out["spot_source"], out["spot_as_of_ts_utc"] = resolve_spot(tk, now=now)
        out.update(price_relations(out, out["spot"]).to_dict())
        out.update(_atr_fields(tk, at))  # live: today's candle from the bars held now
        out.update(_regime_words(cached.snap.regime))
        # the chain's verdict is levels_state, above. The live price the relations are computed from
        # is a separate fact: the numbers stay, marked with whether that price is live
        out.update(price_mark(tk, out["spot_as_of_ts_utc"], now))
        return out | levels_mark(out, tk, now)
    spot, spot_source, spot_ts = resolve_spot(tk, now=now)
    _why = level_store.chain_failure(tk)
    empty = compute_terrain(tk, None, spot, now=at, sessions=sessions()).to_dict()
    mark = price_mark(tk, spot_ts, now)
    return (
        empty
        | price_relations(empty, spot).to_dict()
        | mark
        | levels_mark(staleness, tk, now)
        | {
            "spot_source": spot_source,
            "spot_as_of_ts_utc": spot_ts,
            **_atr_fields(tk, at),  # from the candles and bars, which do not wait for a chain
            **_regime_words(empty["regime"]),
            # not ready, with the producer's reason when it has one, and the levels' verdict
            "error": (
                "terrain_not_ready: no chain from the daemon yet for this ticker"
                + (f" (last chain error: {_why})" if _why else "")
            ),
            **staleness,
        }
    )
