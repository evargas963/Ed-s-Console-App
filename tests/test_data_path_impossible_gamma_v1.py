"""Schwab -> the heatmap and the chain. A gamma more than twice the largest any option can have at its
own volatility, price and time left is not a value: the chain shows "-" and the strike's GEX is
unknown (operator 2026-10-23). Real data (tests/fixtures/real_impossible_gamma_nvda_2026_10_22_and_iwm_0dte_2026_10_20.json,
read from ed_console.db): NVDA's 2026-12-18 chain captured 2026-10-22 12:30 CT, whose 148 call came
with gamma 16.42 at delta 0.92; IWM's same-day 276 call and put at 15:02 CT on their expiry day,
real gammas of 1.83 and 1.80 near the close."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

import server
from math_exposure_core import greek_reported, largest_gamma
from time_et import ET

_FX = json.loads((Path(__file__).parent / "fixtures" / "real_impossible_gamma_nvda_2026_10_22_and_iwm_0dte_2026_10_20.json")
                 .read_text(encoding="utf-8"))
NVDA, IWM = _FX["nvda"], _FX["iwm"]
BAD = "NVDA  261218C00148000"


def _contract(cap, symbol):
    return next(k for k in cap["contracts"] if k["symbol"] == symbol)


def test_a_gamma_past_twice_the_largest_possible_is_not_a_value_and_a_real_one_is():
    bad = _contract(NVDA, BAD)
    largest = largest_gamma(bad, NVDA["spot"])
    assert bad["gamma"] > 2 * largest
    assert not greek_reported(bad["gamma"], iv=bad["volatility"], largest=largest)
    for k in IWM["contracts"]:
        assert k["gamma"] > 1.7
        assert greek_reported(k["gamma"], iv=k["volatility"], largest=largest_gamma(k, IWM["spot"]))
    unstamped = {key: v for key, v in bad.items() if key != "greeksTime"}
    assert largest_gamma(unstamped, NVDA["spot"]) is None
    assert largest_gamma(bad, None) is None


@pytest.fixture
def published():
    at = datetime.fromtimestamp(NVDA["ts_utc"], tz=ET)
    server._publish_levels("NVDA", captures=[{"contracts": [dict(c) for c in NVDA["contracts"]], "ts_utc": NVDA["ts_utc"],
                                              "spot": NVDA["spot"], "et_date": at.date().isoformat(),
                                              "basis": server.CAPTURE_BASIS}], now=at)
    yield
    with server._terrain_cache_lock:
        server._terrain_cache.pop("NVDA", None)


def test_the_chain_shows_the_impossible_gamma_as_missing_and_the_rest_as_sent(published):
    body = json.loads(bytes(server.get_chain(ticker="NVDA", expiry=NVDA["expiry"]).body))
    served = {c["symbol"]: c for c in body["contracts"]}
    assert served[BAD]["gamma"] is None
    assert served[BAD]["delta"] == _contract(NVDA, BAD)["delta"]
    sent = {k["symbol"]: k["gamma"] for k in NVDA["contracts"]}
    assert [s for s, c in served.items() if c["gamma"] != sent[s]] == [BAD]


def test_the_heatmap_cell_of_the_impossible_gamma_is_unknown(published):
    body = json.loads(bytes(server.get_options_gamma_surface(ticker="NVDA", scope="all", centre=None, shift=0,
                                                             cols=None, expiry=None).body))
    cell = next(r for r in body["cells"] if r["strike"] == 148.0)
    assert cell["gex"] == [None]
    assert sum(r["gex"][0] is None for r in body["cells"]) == 1
