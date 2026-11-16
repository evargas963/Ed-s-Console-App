"""A ticker's forces between its two newest market days' captures: the record the levels hold.

The change in open interest, the dealer delta in dollars and the dealer charm, each side of the
price, each with its text as the screen shows it; None where not known. Built by
server._forces_from_captures, held with the levels (state.level_store), served by push.forces.
A Calculator's record lives with the Calculators, so State and Push import it and no
Calculator imports either (docs/ARCHITECTURE.md §1).
"""

from __future__ import annotations

from typing import NotRequired, TypedDict


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


def forces_absent(tk: str) -> Forces:
    """Return `tk`'s forces before two market days of captures exist: each number None.

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
