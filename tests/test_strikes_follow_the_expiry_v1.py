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
import math
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest

import server
import time_et
from calc.terrain_engine import compute_terrain
from option_contract import read_chain
from push import strikes as push_strikes
from state import level_store

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


def _number(x) -> float | None:
    """A value Schwab sent as a number, else None (absent, -999, not finite)."""
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    return None if not math.isfinite(x) or x == -999 else float(x)


def _net_gex(contracts: list[dict], spot: float) -> dict[float, float | None]:
    """Each strike's net GEX per 1% over `contracts`, worked out from the raw chain.

    None at a strike where a contract's open interest, or the gamma of one with open interest,
    is no number: a sum missing a part is not known.
    """
    out: dict[float, float | None] = {}
    for c in contracts:
        k = float(c["strikePrice"])
        oi, gamma = _number(c.get("openInterest")), _number(c.get("gamma"))
        if k in out and out[k] is None:
            continue
        if oi is None or (oi > 0 and gamma is None):
            out[k] = None
            continue
        sign = 1.0 if c["putCall"] == "CALL" else -1.0
        part = 0.0 if oi == 0 else sign * gamma * oi * c["multiplier"] * spot * spot * 0.01
        out[k] = (out.get(k) or 0.0) + part
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


def test_an_expiry_the_chain_does_not_list_is_said_never_another(published):
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
