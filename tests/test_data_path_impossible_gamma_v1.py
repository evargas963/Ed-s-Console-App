"""Schwab -> the heatmap, the chain and the option rule. A gamma more than twice the largest any option
can have at its own volatility, price and time left is not a value: the chain shows "-", the strike's
GEX is unknown, the daemon ranks the contract last, and after the close it keeps the last gamma
Schwab reported, as a -999 does (operator 2026-10-23).

Real data (tests/fixtures/real_impossible_gamma_nvda_2026_10_22_and_iwm_0dte_2026_10_20.json, read
from ed_console.db and stream_capture.db): NVDA's 2026-12-18 chain captured 2026-10-22 12:30 CT,
whose 148 call came with gamma 16.42 at delta 0.92, and that call's 12:02 reading; IWM's same-day
276 call and put stamped 16:02 ET (gamma 1.83, 1.80) and at the 16:15 ET close (2.95, 2.56);
Schwab's /markets answers for both days. NFLX's chain of 2026-10-07 (tests/real_chains.py) carries
Greeks on a volatility Schwab sent as -999."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

import server
from app.market_data.schwab.streaming.capture import by_gamma
from math_exposure_core import gamma_reported, largest_gamma
from tests.real_chains import NFLX
from time_et import ET, option_close_product, record_markets

_FX = json.loads((Path(__file__).parent / "fixtures" / "real_impossible_gamma_nvda_2026_10_22_and_iwm_0dte_2026_10_20.json")
                 .read_text(encoding="utf-8"))
NVDA, IWM, IWM_CLOSE, NVDA_BEFORE = _FX["nvda"], _FX["iwm"], _FX["iwm_last_minutes"], _FX["nvda_before"]
BAD = "NVDA  261218C00148000"


@pytest.fixture(autouse=True)
def _sessions():
    for answer in _FX["markets"].values():
        record_markets(answer)


def _contract(cap, symbol):
    return next(k for k in cap["contracts"] if k["symbol"] == symbol)


def test_a_gamma_past_twice_the_largest_possible_is_not_a_value_and_real_ones_are():
    bad = _contract(NVDA, BAD)
    assert bad["gamma"] > 2 * largest_gamma(bad, NVDA["spot"])
    assert not gamma_reported(bad, NVDA["spot"])
    product = option_close_product("IWM")
    for k in IWM["contracts"]:          # 13 minutes before IWM's 16:15 ET close
        largest = largest_gamma(k, IWM["spot"], product=product)
        assert largest is not None and 1.7 < k["gamma"] <= 2 * largest
        assert gamma_reported(k, IWM["spot"], product=product)
    for k in IWM_CLOSE["contracts"]:    # stamped at the close: no time left to judge it by
        assert k["gamma"] > 2.5 and largest_gamma(k, IWM_CLOSE["spot"], product=product) is None
        assert gamma_reported(k, IWM_CLOSE["spot"], product=product)
    unstamped = {key: v for key, v in bad.items() if key != "greeksTime"}
    assert largest_gamma(unstamped, NVDA["spot"]) is None and largest_gamma(bad, None) is None


def test_the_option_rule_ranks_the_impossible_gamma_last():
    ranked = by_gamma(NVDA["contracts"], NVDA["spot"], NVDA["ts_utc"], option_close_product("NVDA"))
    valid = [k for k in NVDA["contracts"] if gamma_reported(k, NVDA["spot"])]
    assert ranked.index(BAD) >= len(valid)
    assert max(valid, key=lambda k: k["gamma"])["symbol"] == ranked[0] != BAD


def test_after_the_close_an_impossible_gamma_keeps_the_last_one_reported():
    after_close = datetime(2026, 10, 22, 18, 0, tzinfo=ET)
    (kept,) = server._keep_last_reported([_contract(NVDA, BAD)], NVDA_BEFORE["contracts"], after_close,
                                         option_close_product("NVDA"), NVDA["spot"])
    assert (kept["gamma"], kept["delta"]) == (0.0, 1.0)
    assert kept["greeksTime"] == NVDA_BEFORE["contracts"][0]["greeksTime"]


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


def test_the_chain_shows_greeks_on_a_no_value_volatility_as_missing():
    tk, expiry = "NFLX", "2027-12-17"
    server._publish_levels(tk, captures=[{"contracts": [dict(c) for c in NFLX.chain], "ts_utc": NFLX.now.timestamp(),
                                          "spot": NFLX.spot, "et_date": NFLX.now.date().isoformat(),
                                          "basis": server.CAPTURE_BASIS}], now=NFLX.now)
    try:
        body = json.loads(bytes(server.get_chain(ticker=tk, expiry=expiry).body))
    finally:
        with server._terrain_cache_lock:
            server._terrain_cache.pop(tk, None)
    no_value = {c["symbol"] for c in NFLX.chain if c["expirationDate"].startswith(expiry) and c["volatility"] == -999}
    served = {c["symbol"]: c for c in body["contracts"]}
    assert no_value
    for s in no_value:
        assert (served[s]["volatility"], served[s]["gamma"], served[s]["delta"]) == (None, None, None)
