"""The strike views follow the one expiry the page chooses.

GEX by Strike, the Gamma chart's profiles, Right Now's migration and the Desk map read the
`strikes` panel at the page's expiry choice (`expiry`): a listed expiry's rows are that expiry's
contracts alone, as Schwab sent them; All Expirations (None) every expiry's; an expiry the chain
does not list is said, never answered with another expiry's rows. The migration compares the same
expiry on the prior day, and shows no change where that day did not list it.

Real data: two days of Schwab's PCG chain (tests/fixtures, captured 2026-09-24 and 2026-09-25,
six expiries each), each priced by the one producer at its capture. Expected values are worked
out here from the raw chain: net GEX per 1% at a strike = the calls' gamma x open interest x
multiplier x spot^2 x 1% less the puts', with Schwab's gamma as sent.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest

import server
import time_et
from calc.math_exposure_core import bucket_metric, merge_exposure_books
from calc.terrain_engine import compute_terrain
from option_contract import read_chain
from push import strike_bars as push_strike_bars
from push import strikes as push_strikes
from state import level_store
from tests.real_chains import number

TK = "PCG"
_FX = json.loads(
    (Path(__file__).resolve().parent / "fixtures" / "real_pcg_two_day_chain.json").read_text(
        encoding="utf-8"
    )
)
THURSDAY, FRIDAY = _FX["days"]
#: every strike, so every row of the book is served whatever the price
EVERY = {"scope": "all", "centre": None, "shift": 0}
#: an expiry both days list, and a date neither lists (a Saturday)
CHOSEN = "2026-10-16"
NOT_LISTED = "2026-10-17"


def _at(day: dict) -> datetime:
    return datetime.fromtimestamp(day["ts_utc"], time_et.ET)


def _snap(contracts: list[dict], day: dict):
    return compute_terrain(
        TK, read_chain(contracts), day["spot"], now=_at(day), sessions=time_et.sessions()
    )


@pytest.fixture
def published():
    """Friday's chain published by the one producer, Thursday's levels as its prior day."""
    at = FRIDAY["ts_utc"]
    server._publish_levels(
        TK, read_chain(FRIDAY["contracts"]), at, chain_spot=(FRIDAY["spot"], at), now=_at(FRIDAY)
    )
    levels = level_store.published_levels(TK)
    level_store.publish(TK, replace(levels, prior_day=_snap(THURSDAY["contracts"], THURSDAY)))
    try:
        yield level_store.published_levels(TK)
    finally:
        with level_store._lock:
            level_store._levels.pop(TK, None)


def _strikes(expiry: str | None) -> dict:
    return push_strikes.strikes(TK, FRIDAY["ts_utc"], {**EVERY, "expiry": expiry})


def _net_gex(contracts: list[dict], spot: float) -> dict[float, float | None]:
    """Each strike's net GEX per 1% over `contracts`, worked out from the raw chain.

    None at a strike where a contract's open interest, or the gamma of one with open interest,
    is no number: a sum missing a part is not known.
    """
    out: dict[float, float | None] = {}
    for c in contracts:
        k = float(c["strikePrice"])
        oi, gamma = number(c.get("openInterest")), number(c.get("gamma"))
        if k in out and out[k] is None:
            continue
        if oi is None or (oi > 0 and gamma is None):
            out[k] = None
            continue
        sign = 1.0 if c["putCall"] == "CALL" else -1.0
        part = 0.0 if oi == 0 else sign * gamma * oi * c["multiplier"] * spot * spot * 0.01
        out[k] = out.get(k, 0) + part  # a running total: the sum of nothing is 0
    return out


def _of(contracts: list[dict], expiry: str) -> list[dict]:
    return [c for c in contracts if c["expirationDate"][:10] == expiry]


def _served(rows: list[dict]) -> dict[float, float | None]:
    return {r["strike"]: r["value"] for r in rows}


def test_a_chosen_expirys_gex_by_strike_is_its_own_contracts_alone(published):
    spot = published.snap.spot
    listed = sorted({c["expirationDate"][:10] for c in FRIDAY["contracts"]})
    assert len(listed) == 6
    for expiry in listed:
        body = _strikes(expiry)
        assert (body["expiry"], body["expiry_text"]) == (
            expiry,
            f"{expiry[5:7]}/{expiry[8:10]}/{expiry[:4]}",
        )
        want = _net_gex(_of(FRIDAY["contracts"], expiry), spot)
        got = _served(body["today"])
        assert set(got) == set(want), expiry
        for k, v in want.items():
            assert got[k] == (None if v is None else pytest.approx(v, rel=1e-9)), (expiry, k)
    # one expiry is not every expiry: the front one's 0.0 at a strike is not the book's sum there
    front, every = _served(_strikes(listed[0])["today"]), _served(_strikes(None)["today"])
    assert any(front[k] != every[k] for k in front)


def test_all_expirations_is_every_expirys_contracts(published):
    body = _strikes(None)
    assert (body["expiry"], body["expiry_text"]) == (None, "All Expirations")
    want = _net_gex(FRIDAY["contracts"], published.snap.spot)
    got = _served(body["today"])
    assert set(got) == set(want)
    for k, v in want.items():
        assert got[k] == (None if v is None else pytest.approx(v, rel=1e-9)), k
    # the largest row is of the same rows
    top = max((r for r in body["today"] if r["value"] is not None), key=lambda r: abs(r["value"]))
    assert body["max_abs_row"]["strike"] == top["strike"]


@pytest.mark.usefixtures("published")
def test_an_expiry_the_chain_does_not_list_is_said_never_another():
    body = _strikes(NOT_LISTED)
    assert body["available"] is False
    assert body["reason"] == f"the chain lists no contracts for {NOT_LISTED}"
    assert "today" not in body and "migration" not in body
    assert body["levels_state"]  # the levels' verdict stands beside the reason


def test_an_expiry_that_is_not_a_date_or_none_is_said():
    body = push_strikes.strikes(TK, FRIDAY["ts_utc"], {**EVERY, "expiry": 20261016})
    assert body == {
        "ticker": TK,
        "available": False,
        "reason": "expiry 20261016 is not an expiry date or null",
    }
    assert push_strikes.strikes(TK, FRIDAY["ts_utc"], EVERY)["available"] is False


def test_the_migration_compares_the_same_expiry_on_the_prior_day(published):
    spot_then = published.prior_day.spot
    body = _strikes(CHOSEN)
    m = body["migration"]
    prior_want = _net_gex(_of(THURSDAY["contracts"], CHOSEN), spot_then)
    compared = 0
    for r in m["rows"]:
        was = prior_want.get(r["strike"])
        assert r["prior"] == (None if was is None else pytest.approx(was, rel=1e-9)), r["strike"]
        if r["value"] is not None and was is not None:
            assert r["change"] == pytest.approx(r["value"] - was, rel=1e-9, abs=1e-6)
            compared += 1
        else:
            assert r["change"] is None and r["change_text"] is None
    assert m["compared"] and compared > 10 and m["note"] is None
    # like with like: the prior day's whole book is not what this expiry is compared with
    whole = _net_gex(THURSDAY["contracts"], spot_then)
    assert any(r["prior"] != whole.get(r["strike"]) for r in m["rows"] if r["prior"] is not None)


def test_an_expiry_the_prior_day_did_not_list_shows_no_change(published):
    """INDUCED: Thursday's chain without its 2026-10-30 expiry, as a day before it was listed."""
    thursday = [c for c in THURSDAY["contracts"] if c["expirationDate"][:10] != "2026-10-30"]
    level_store.publish(TK, replace(published, prior_day=_snap(thursday, THURSDAY)))
    body = _strikes("2026-10-30")
    m = body["migration"]
    assert body["today"] and m["rows"]
    assert all(r["prior"] is None and r["change"] is None for r in m["rows"])
    assert all(r["change_text"] is None for r in m["rows"])
    assert not m["compared"] and m["grew"] == [] and m["shrank"] == []
    assert m["note"] == "The prior day's chain lists no contracts for 2026-10-30."
    # the expiry the prior day did list is still compared
    assert _strikes(CHOSEN)["migration"]["compared"]


def test_with_no_prior_day_the_migration_says_so(published):
    level_store.publish(TK, replace(published, prior_day=None))
    m = _strikes(CHOSEN)["migration"]
    assert not m["compared"] and m["note"] == push_strikes.NO_PRIOR_DAY


def test_a_prior_day_with_no_value_known_at_any_strike_says_so(published):
    """INDUCED: Thursday's chain with no open interest sent.

    The prior day lists the expiry and no strike's net GEX is known that day, so nothing is
    compared, and the migration says that reason: not that no prior day is held, nor that the
    prior day's chain does not list the expiry.
    """
    thursday = [{k: v for k, v in c.items() if k != "openInterest"} for c in THURSDAY["contracts"]]
    level_store.publish(TK, replace(published, prior_day=_snap(thursday, THURSDAY)))
    m = _strikes(CHOSEN)["migration"]
    assert len(m["rows"]) > 10
    assert all(r["prior"] is None and r["change"] is None for r in m["rows"])
    assert not m["compared"] and (m["grew"], m["shrank"]) == ([], [])
    assert m["note"] == "No strike has a net GEX on both days."


def test_each_level_is_served_against_the_prior_days_own_with_its_texts(published):
    """PCG's call wall moved from 13 to 12 between the two captures and its put wall stood.

    Neither day has a gamma flip. Each level is served with both days' strikes and the move as
    the screen shows them: a move down signed, none as "unchanged", an unknown level as nothing.
    """
    today, prior = published.snap, published.prior_day
    assert (prior.call_wall, today.call_wall) == (13.0, 12.0)
    assert (prior.put_wall, today.put_wall) == (13.0, 13.0)
    assert prior.gamma_flip is None and today.gamma_flip is None
    for expiry in (None, CHOSEN):  # the levels are the book's, whichever expiry is shown
        assert _strikes(expiry)["level_moves"] == [
            {
                "level": "call_wall",
                "prior": 13.0,
                "today": 12.0,
                "change": -1.0,
                "prior_text": "13",
                "today_text": "12",
                "change_text": "-1",
            },
            {
                "level": "put_wall",
                "prior": 13.0,
                "today": 13.0,
                "change": 0.0,
                "prior_text": "13",
                "today_text": "13",
                "change_text": "unchanged",
            },
            {
                "level": "gamma_flip",
                "prior": None,
                "today": None,
                "change": None,
                "prior_text": None,
                "today_text": None,
                "change_text": None,
            },
        ]


def _bars(key: str, expiry: str | None) -> dict[float, float]:
    body = push_strike_bars.strike_bars(key, TK, FRIDAY["ts_utc"], {**EVERY, "expiry": expiry})
    assert body["expiry"] == expiry
    return {r["strike"]: r["value"] for r in body["rows"]}


def test_vanna_and_charm_by_strike_are_the_chosen_expirys_alone(published):
    """Each expiry's vanna is the net vanna of its own priced contracts, its charm its own map's.

    The producer priced each expiry once (snap.books by (expiry, DTE), snap.charm_by_expiry):
    the chosen expiry's rows are those of its contracts alone; All Expirations the whole book's.
    """
    snap = published.snap
    for expiry in sorted({c["expirationDate"][:10] for c in FRIDAY["contracts"]}):
        own, _ = merge_exposure_books(b for (e, _d), b in snap.books.items() if e == expiry)
        want = {k: v for k, b in own.items() if (v := bucket_metric(b, "net_vanna")) is not None}
        assert _bars("vanna", expiry) == want, expiry
        charm = snap.charm_by_expiry[expiry]
        want = {k: b["net_charm"] for k, b in charm.items() if b["net_charm"] is not None}
        assert _bars("charm", expiry) == want, expiry
    whole = {
        k: b["net_charm"] for k, b in snap.charm_by_strike.items() if b["net_charm"] is not None
    }
    assert _bars("charm", None) == whole
    assert _bars("charm", CHOSEN) != whole  # one expiry is not every one
    assert (
        push_strike_bars.strike_bars(
            "vanna", TK, FRIDAY["ts_utc"], {**EVERY, "expiry": NOT_LISTED}
        )["reason"]
        == f"the chain lists no contracts for {NOT_LISTED}"
    )


def test_an_expiry_with_no_value_known_has_no_bar_and_says_so():
    """INDUCED: Friday's chain with the 2026-10-30 expiry's open interest not sent.

    No vanna or charm of that expiry is known: each bar panel has no row and says so, while the
    expiry beside it is answered as before; the GEX rows of that expiry stand with no value,
    never 0, and its DEX and open interest profiles have no row.
    """
    blank = "2026-10-30"
    chain = [
        {k: v for k, v in c.items() if k != "openInterest" or c["expirationDate"][:10] != blank}
        for c in FRIDAY["contracts"]
    ]
    at = FRIDAY["ts_utc"]
    server._publish_levels(
        TK, read_chain(chain), at, chain_spot=(FRIDAY["spot"], at), now=_at(FRIDAY)
    )
    try:
        for key, method in push_strike_bars.STRIKE_BAR_METHODS.items():
            body = push_strike_bars.strike_bars(key, TK, at, {**EVERY, "expiry": blank})
            assert body == {
                "ticker": TK,
                "available": False,
                "expiry": blank,
                "rows": [],
                "view": {"centre": None, "centre_text": None, "note": None, "max_abs": None},
                "scope": "all",
                "reason": "no usable strikes for this chain",
                "method": method,
            }, key
            beside = push_strike_bars.strike_bars(key, TK, at, {**EVERY, "expiry": CHOSEN})
            assert beside["available"] and beside["reason"] is None, key
            assert beside["rows"] and all(
                set(r) == {"strike", "value", "strike_text", "text", "marks"}
                for r in beside["rows"]
            ), key
        gex = push_strikes.strikes(TK, at, {**EVERY, "expiry": blank})
        assert len(gex["today"]) > 10
        assert all(r["value"] is None and r["text"] is None for r in gex["today"])
        assert gex["max_abs_row"] is None and gex["view"]["max_abs"] is None
        assert all(w["rows"] == [] and w["max_abs_row"] is None for w in gex["measures"].values())
    finally:
        with level_store._lock:
            level_store._levels.pop(TK, None)
