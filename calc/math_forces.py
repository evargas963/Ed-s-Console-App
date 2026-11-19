"""A ticker's forces: its chain now against the prior day's close, the record the levels hold.

The change in open interest since the prior day's close, the dealer delta in dollars and the
dealer charm, each side of the price, each with its text as the screen shows it; None where not
known. Computed with every publication of the levels (server._publish_levels: live), held with
them (state.level_store), served by push.forces. A Calculator's record lives with the
Calculators, so State and Push import it and no Calculator imports either
(docs/ARCHITECTURE.md §1).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import NotRequired, TypedDict

from calc.math_exposure_core import (
    Bucket,
    ExposureDiagnostics,
    bucket_metric,
    merge_exposure_books,
    strike_total_oi,
)
from calc.math_levels import CharmBucket
from calc.terrain_engine import side_total
from numeric_contract import compact_text, count_text, dollars_text


class Forces(TypedDict):
    """A ticker's forces, each side of the price of the newer capture."""

    ticker: str
    available: bool
    doi_below: float | None
    doi_above: float | None
    doi_below_text: str | None
    doi_above_text: str | None
    dex_below_dollars: float | None
    dex_above_dollars: float | None
    dex_below_text: str | None
    dex_above_text: str | None
    charm_below: float | None
    charm_above: float | None
    charm_below_text: str | None
    charm_above_text: str | None
    #: the older of the two days, and how each number is made; only when available
    older_et_date: NotRequired[str]
    method: NotRequired[str]


type Books = Iterable[tuple[dict[float, Bucket], ExposureDiagnostics]]


def forces(
    tk: str,
    spot: float,
    books: Books,
    charm_by_strike: dict[float, CharmBucket],
    prior_books: Books,
    prior_et_date: str,
) -> Forces:
    """Return `tk`'s forces: its chain now (`books`, `charm_by_strike`) against the prior close.

    Each side of `spot`, the chain's own price: the open interest of each side less the prior
    market day's close capture's (`prior_books`, of `prior_et_date`), both sides split at the
    same price, so a moving price never reads as a change in open interest; the dealer DEX
    (net_dex_dollars) and the dealer-signed net charm (call charm - put charm) of the chain now.
    A strike the prior day did not list held no contracts then (each capture is the whole chain).
    """
    now, before = merge_exposure_books(books)[0], merge_exposure_books(prior_books)[0]

    def below(k: float) -> bool:
        return k < spot

    def above(k: float) -> bool:
        return k > spot

    def oi_change(in_side: Callable[[float], bool]) -> float | None:
        newer, older = (
            side_total([strike_total_oi(b) for k, b in book.items() if in_side(k)])
            for book in (now, before)
        )
        return None if newer is None or older is None else newer - older

    def dex(in_side: Callable[[float], bool]) -> float | None:
        return side_total(
            [bucket_metric(b, "net_dex_dollars") for k, b in now.items() if in_side(k)]
        )

    def charm(in_side: Callable[[float], bool]) -> float | None:
        return side_total([v["net_charm"] for k, v in charm_by_strike.items() if in_side(k)])

    doi_below, doi_above = oi_change(below), oi_change(above)
    dex_below, dex_above = dex(below), dex(above)
    charm_below, charm_above = charm(below), charm(above)
    return {
        "ticker": tk,
        "available": True,
        "doi_below": doi_below,
        "doi_above": doi_above,
        "doi_below_text": count_text(doi_below),
        "doi_above_text": count_text(doi_above),
        "dex_below_dollars": dex_below,
        "dex_above_dollars": dex_above,
        "dex_below_text": dollars_text(dex_below),
        "dex_above_text": dollars_text(dex_above),
        "charm_below": charm_below,
        "charm_above": charm_above,
        "charm_below_text": compact_text(charm_below),
        "charm_above_text": compact_text(charm_above),
        "older_et_date": prior_et_date,
        "method": (
            "OI side totals of the chain now less the prior day's close capture, both split at "
            "the chain's price; DEX = net_dex_dollars side sums on the chain now; "
            "CHARM = dealer-signed net_charm side sums on the chain now"
        ),
    }


def forces_absent(tk: str) -> Forces:
    """Return `tk`'s forces with no prior day's close captured: each number None.

    Nothing stands in for a number not known.
    """
    return {
        "ticker": tk,
        "available": False,
        "doi_below": None,
        "doi_above": None,
        "doi_below_text": None,
        "doi_above_text": None,
        "dex_below_dollars": None,
        "dex_above_dollars": None,
        "dex_below_text": None,
        "dex_above_text": None,
        "charm_below": None,
        "charm_above": None,
        "charm_below_text": None,
        "charm_above_text": None,
    }
