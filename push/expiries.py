"""The `expiries` panel: each listed expiry with its dropdown texts, or why there are none."""

from __future__ import annotations

from typing import TypedDict

from push.verdict import terrain_cache_get


class Expiries(TypedDict):
    """The expiries panel: each listed expiry with its dropdown texts, or why there are none."""

    expiries: list[str] | None
    dte: dict[str, float | None] | None
    labels: dict[str, str] | None
    dte_text: dict[str, str | None] | None
    reason: str | None


def expiries(ticker: str, now: float) -> Expiries:
    """Return the ticker's listed expiries at `now`, each with its dropdown texts.

    `ticker` is the levels' own key ($SPX). Each expiry's label is its date, MM/DD/YYYY, and its
    `dte_text` Schwab's daysToExpiration as sent (18DTE), None when Schwab sent none. Before the
    ticker's first chain is priced the list is unknown (None), with the levels' own reason; a
    chain listing none is an empty list with its reason. The page's socket sends it (live_ui,
    server.PAGE_PANELS) when the page subscribes on the ticker and on each new chain.
    """
    levels, verdict = terrain_cache_get(ticker, now)
    exps = dte = labels = dte_text = None
    reason = verdict["levels_stale_reason"]
    if levels is not None:
        exps, dte = levels.snap.expiries, levels.snap.expiry_dte
        labels = {e: f"{e[5:7]}/{e[8:10]}/{e[:4]}" for e in exps}
        dte_text = {e: None if dte[e] is None else f"{dte[e]:g}DTE" for e in exps}
        reason = None if exps else "no expiry listed in the published chain"
    return {
        "expiries": exps,
        "dte": dte,
        "labels": labels,
        "dte_text": dte_text,
        "reason": reason,
    }
