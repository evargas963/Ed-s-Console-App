"""The Confluence matrix marks only the key levels, each strike with its distance in implied moves.

The operator's decision (2026-11-23, the matrix plan's "Key levels"): only the levels institutions
have a mechanical reason to trade at. From the chain, where options dealers' hedging turns and
concentrates (Gamma Flip, Gamma Call, Gamma Put, Gamma Total) and the pin of the expiry settling
that day (OI Pin), the first four's same-day copies only when the chosen expiry settles that day;
from the session, the execution desks' benchmarks (VWAP and the prior close). Each strike and
each level carries its distance from the live price in dollars and in the expiry's implied moves
(σ): ln(price / spot) over the at-the-money volatility times the square root of the time left.

Real data: the panels the server answered on SPY's and AMZN's captured 2026-11-11 and 2026-11-12
(tests/e2e/fixtures/panels_*_two_day.json, held equal to the server's own answers by
tests/test_e2e_panels_two_day_v1.py), at the front expiry and the chain's second. The expected σ is
worked out here: the time left runs from the newer capture to the expiry's expirationDate as
Schwab sent it in the captured chain (both are equity options, settled at the regular close),
over a 365-day year; the volatility is the expiry's at-the-money volatility as the terrain panel
serves it.
"""

from __future__ import annotations

import gzip
import json
import math
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from tests.shared_helpers import rail_levels

pytestmark = pytest.mark.rail

_FX = Path(__file__).resolve().parent / "fixtures"
_E2E = Path(__file__).resolve().parent / "e2e" / "fixtures"
ET = ZoneInfo("America/New_York")
KEY_OPTIONS = {"Gamma Flip", "Gamma Call", "Gamma Put", "Gamma Total", "OI Pin"}
SAME_DAY = {"0DTE Gamma Flip", "0DTE Gamma Call", "0DTE Gamma Put", "0DTE Gamma Total"}
KEY_SESSION = {"VWAP", "Prior day close"}
CASES = [
    (name, key) for name in ("spy", "amzn") for key in ("confluence", "confluence_second_expiry")
]


def _panels(name: str) -> dict:
    return json.loads((_E2E / f"panels_{name}_two_day.json").read_text(encoding="utf-8"))


def _newer_capture(name: str) -> dict:
    """Return the newer capture: the chain the panels were answered on, at its instant."""
    two = json.loads(
        gzip.decompress((_FX / f"real_{name}_two_day_captures_2026_11_12.json.gz").read_bytes())
    )
    return max(two["captures"], key=lambda c: c["ts_utc"])


def _captured_at(name: str) -> datetime:
    return datetime.fromtimestamp(_newer_capture(name)["ts_utc"], ET)


#: the option market each ticker's options close with, by Schwab's /markets product: SPY is on
#: the exchanges' list of symbols whose options trade to the index-option close
PRODUCT = {"spy": "IND", "amzn": "EQO"}


def _settles(name: str, expiry: str) -> datetime:
    """Return the expiry's settlement, as the one clock reads it from what Schwab sent.

    For a day whose /markets answer is captured, the regular close of the ticker's option market
    that day; for a later day, its contracts' one expirationDate as Schwab sent it.
    """
    answer = _FX / f"real_schwab_markets_{expiry.replace('-', '_')}.json"
    if answer.exists():
        body = json.loads(answer.read_text(encoding="utf-8"))["body"]
        hours = body["option"][PRODUCT[name]]["sessionHours"]["regularMarket"]
        return datetime.fromisoformat(hours[-1]["end"])
    sent = {
        c["expirationDate"]
        for row in _newer_capture(name)["rows"]
        if row["expiry"] == expiry
        for c in row["contracts"]
    }
    assert len(sent) == 1, sent
    return datetime.fromisoformat(sent.pop())


def _signed(x: float, digits: int) -> str:
    shown = f"{x:+.{digits}f}"
    return shown[1:] if float(shown) == 0 else shown


@pytest.mark.parametrize(("name", "key"), CASES)
def test_the_matrix_marks_only_the_key_levels(name: str, key: str) -> None:
    """Only the kept levels; the same-day copies only when the expiry settles that day."""
    body = _panels(name)[key]
    expiry_day = body["expiry"] == _captured_at(name).date().isoformat()
    titles = {lv["title"] for lv in rail_levels(body)}
    allowed = KEY_OPTIONS | KEY_SESSION | (SAME_DAY if expiry_day else set())
    assert titles <= allowed, titles - allowed
    # both benchmarks are there (the day has bars), and the dealers' gamma levels
    assert titles >= KEY_SESSION
    assert titles >= {"Gamma Flip", "Gamma Call", "Gamma Put", "Gamma Total"}
    assert bool(titles & SAME_DAY) == expiry_day
    session = {lv["title"] for lv in rail_levels(body) if lv["lane"] == "session"}
    assert session <= KEY_SESSION


@pytest.mark.parametrize("name", ["spy", "amzn"])
def test_a_key_level_past_the_shown_strikes_is_listed_past_them(name: str) -> None:
    """SPY's Gamma Call and AMZN's Gamma Flip lie past the strikes shown, listed above or below."""
    body = _panels(name)["confluence"]
    top, bottom = body["rows"][0]["strike"], body["rows"][-1]["strike"]
    assert body["levels_above"] or body["levels_below"]
    assert all(lv["price"] > top for lv in body["levels_above"])
    assert all(lv["price"] < bottom for lv in body["levels_below"])


def test_the_front_expiry_of_spy_is_that_days_own_and_amzns_is_not() -> None:
    """The cases above cover both kinds: SPY's front expiry settles on the capture's day."""
    assert _panels("spy")["confluence"]["expiry"] == "2026-11-12"
    assert _panels("amzn")["confluence"]["expiry"] == "2026-11-13"


@pytest.mark.parametrize(("name", "key"), CASES)
def test_each_strike_and_level_is_its_distance_in_points_and_in_implied_moves(
    name: str, key: str
) -> None:
    """ln(price / spot) over the expiry's at-the-money volatility × √(time left), signed.

    `spot` is the live price at that instant, the price row's (Schwab's last trade, the one
    producer the page's socket carries); the matrix serves no copy of it.
    """
    panels = _panels(name)
    body = panels[key]
    spot, expiry = panels["price_row"]["spot"], body["expiry"]
    assert "spot" not in body
    iv = panels["terrain"]["atm_iv_pct_by_expiry"][expiry] / 100.0
    years = (_settles(name, expiry) - _captured_at(name)).total_seconds() / (365 * 86400)
    assert iv > 0 and years > 0, "the case has a volatility and time left: not vacuous"
    priced = [(row["strike"], row) for row in body["rows"]]
    priced += [(lv["price"], lv) for lv in rail_levels(body)]
    for price, shown in priced:
        z = math.log(price / spot) / (iv * math.sqrt(years))
        assert shown["sigma"] == pytest.approx(z, rel=1e-9), price
        assert shown["sigma_text"] == _signed(z, 1) + "σ", price
        assert shown["distance_text"] == _signed(price - spot, 2), price
