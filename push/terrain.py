"""The `terrain` panel: a ticker's published levels at the live price, with its ATRs and mark.

Read from State: the published levels (state.level_store), the live price, and the daily, weekly
and monthly candles the bar writer holds (state.bar_store, push.bars.daily_candles).
"""

from __future__ import annotations

from datetime import datetime
from typing import TypedDict

import live_market_plane as lmp
from app.options.order_flow.streaming import price_state
from calc.terrain_atr import Atr, compute_atrs
from calc.terrain_engine import RelationFields, TerrainFields, compute_terrain, price_relations
from calc.terrain_read import REGIME_TEXT
from instrument_identity import ticker_storage_key
from numeric_contract import price_text
from push.bars import daily_candles
from push.spot import PriceMark, price_mark, resolve_spot
from push.verdict import LevelsVerdict, terrain_cache_get
from state import bar_store, level_store
from state.level_store import ServedLevels, SpotStamp
from time_et import ET, sessions


class LevelsMark(TypedDict):
    """The one word the Key Levels line shows, and why (levels_mark)."""

    levels_mark: str
    levels_mark_reason: str | None


class AtrFields(TypedDict):
    """The ticker's daily, weekly and monthly ATR, each with its text; None with too few candles."""

    atr_daily: float | None
    atr_weekly: float | None
    atr_monthly: float | None
    atr_daily_text: str | None
    atr_weekly_text: str | None
    atr_monthly_text: str | None


class BesideTheLevels(LevelsVerdict, RelationFields, AtrFields, PriceMark, LevelsMark):
    """What the terrain panel carries beside the levels' own fields, published or not.

    The levels' verdict, the live price's relations to them and its mark, the ATRs, the regime as
    the screen says it (terrain_read) and the Key Levels line's word.
    """

    regime_text: str


class TerrainPanel(ServedLevels, BesideTheLevels):
    """The `terrain` panel: a ticker's published levels at the live price (terrain)."""


class TerrainNotReady(TerrainFields, SpotStamp, BesideTheLevels):
    """The `terrain` panel before a ticker's first levels: each level unknown, and why (`error`)."""


def levels_mark(levels: LevelsVerdict, ticker: str, now: float) -> LevelsMark:
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


def _atr_fields(tk: str, now: datetime) -> AtrFields:
    """atr_daily / atr_weekly / atr_monthly at `now`, each with its text.

    A horizon that cannot be computed is None.
    """
    a = atr(tk, now)
    return {
        "atr_daily": a.daily,
        "atr_weekly": a.weekly,
        "atr_monthly": a.monthly,
        "atr_daily_text": price_text(a.daily),
        "atr_weekly_text": price_text(a.weekly),
        "atr_monthly_text": price_text(a.monthly),
    }


def terrain(tk: str, now: float) -> TerrainPanel | TerrainNotReady:
    """Return `tk`'s published levels at `now`, at the live price (the `terrain` panel).

    `tk` is the levels' own key ($SPX). The page's socket sends
    them to Key Levels, the Gamma chart, the Trade Desk's Right Now and its map (live_ui,
    PAGE_PANELS), at once and each time the levels change (server._levels_changed).
    """
    at = datetime.fromtimestamp(now, ET)
    cached, staleness = terrain_cache_get(tk, now)
    spot, spot_source, spot_ts = resolve_spot(tk, now=now)
    if cached is not None:
        served = cached.served()
        # the levels as the producer published them; `spot` is the live price, and every relation
        # of the price to the levels is at it (price_relations); internal fields (the kept chain,
        # the heatmap grid, per-strike rows) are their own panels
        return {
            **served,
            **staleness,
            "spot": spot,
            "spot_source": spot_source,
            "spot_as_of_ts_utc": spot_ts,
            **price_relations(served, spot).to_dict(),
            **_atr_fields(tk, at),  # live: today's candle from the bars held now
            "regime_text": REGIME_TEXT[cached.snap.regime],
            # the chain's verdict is levels_state, above. The live price the relations are computed
            # from is a separate fact: the numbers stay, marked with whether that price is live
            **price_mark(tk, spot_ts, now),
            **levels_mark(staleness, tk, now),
        }
    _why = level_store.chain_failure(tk)
    empty = compute_terrain(tk, None, spot, now=at, sessions=sessions()).to_dict()
    return {
        **empty,
        **price_relations(empty, spot).to_dict(),
        **price_mark(tk, spot_ts, now),
        **levels_mark(staleness, tk, now),
        "spot_source": spot_source,
        "spot_as_of_ts_utc": spot_ts,
        **_atr_fields(tk, at),  # from the candles and bars, which do not wait for a chain
        "regime_text": REGIME_TEXT[empty["regime"]],
        # not ready, with the producer's reason when it has one, and the levels' verdict
        "error": (
            "terrain_not_ready: no chain from the daemon yet for this ticker"
            + (f" (last chain error: {_why})" if _why else "")
        ),
        **staleness,
    }
