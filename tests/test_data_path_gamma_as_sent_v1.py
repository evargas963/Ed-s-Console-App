"""Schwab -> the chain, the heatmap and the option rule: a gamma is taken as Schwab sends it.

Whatever its size (operator 2026-11-04: "we take what schwab gives and we wire it up. plain and
simple"); only Schwab's own no-value code, -999 on the Greek or on the contract's volatility, is
no value.

Real data (tests/fixtures/real_impossible_gamma_nvda_2026_10_22_and_iwm_0dte_2026_10_20.json, read
from ed_console.db and stream_capture.db): NVDA's 2026-12-18 chain captured 2026-10-22 12:30 CT,
whose 148 call came with gamma 16.42 at delta 0.92; Schwab's /markets answers for the day. NFLX's
chain of 2026-10-07 (tests/real_chains.py) carries Greeks on a volatility Schwab sent as -999.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

import server
from app.market_data.schwab.streaming.capture import by_gamma
from option_contract import read_chain
from tests.real_chains import NFLX
from time_et import ET, record_markets

_FX = json.loads(
    (
        Path(__file__).parent
        / "fixtures"
        / "real_impossible_gamma_nvda_2026_10_22_and_iwm_0dte_2026_10_20.json"
    ).read_text(encoding="utf-8")
)
NVDA = _FX["nvda"]
LARGE = "NVDA  261218C00148000"


@pytest.fixture(autouse=True)
def _sessions():
    for answer in _FX["markets"].values():
        record_markets(answer)


@pytest.fixture
def published():
    at = datetime.fromtimestamp(NVDA["ts_utc"], tz=ET)
    server._publish_levels(
        "NVDA",
        captures=[
            {
                "contracts": read_chain(NVDA["contracts"]),
                "ts_utc": NVDA["ts_utc"],
                "spot": NVDA["spot"],
                "et_date": at.date().isoformat(),
                "basis": server.CAPTURE_BASIS,
                "spot_ts": None,
                "spot_from_chain": False,
            }
        ],
        now=at,
    )
    yield
    with server._terrain_cache_lock:
        server._terrain_cache.pop("NVDA", None)


def test_the_chain_serves_every_gamma_as_schwab_sent_it(published):
    body = json.loads(bytes(server.get_chain(ticker="NVDA", expiry=NVDA["expiry"]).body))
    served = {c["symbol"]: c["gamma"] for c in body["contracts"]}
    sent = {k["symbol"]: k["gamma"] for k in NVDA["contracts"]}
    assert served[LARGE] == sent[LARGE] > 16
    assert served == sent


def test_the_heatmap_cell_of_a_large_gamma_has_its_gex(published):
    body = json.loads(
        bytes(
            server.get_options_gamma_surface(
                ticker="NVDA", scope="all", centre=None, shift=0, cols=None, expiry=None
            ).body
        )
    )
    cell = next(r for r in body["cells"] if r["strike"] == 148.0)
    assert cell["gex"][0] is not None
    assert all(r["gex"][0] is not None for r in body["cells"])


def test_the_option_rule_ranks_the_largest_gamma_schwab_sent_first():
    ranked = by_gamma(read_chain(NVDA["contracts"]), NVDA["spot"], NVDA["ts_utc"])
    assert ranked[0] == LARGE


def test_the_chain_shows_greeks_on_a_no_value_volatility_as_missing():
    tk, expiry = "NFLX", "2027-12-17"
    server._publish_levels(
        tk,
        captures=[
            {
                "contracts": read_chain(NFLX.chain),
                "ts_utc": NFLX.now.timestamp(),
                "spot": NFLX.spot,
                "et_date": NFLX.now.date().isoformat(),
                "basis": server.CAPTURE_BASIS,
                "spot_ts": None,
                "spot_from_chain": False,
            }
        ],
        now=NFLX.now,
    )
    try:
        body = json.loads(bytes(server.get_chain(ticker=tk, expiry=expiry).body))
    finally:
        with server._terrain_cache_lock:
            server._terrain_cache.pop(tk, None)
    no_value = {
        c["symbol"]
        for c in NFLX.chain
        if c["expirationDate"].startswith(expiry) and c["volatility"] == -999
    }
    served = {c["symbol"]: c for c in body["contracts"]}
    assert no_value
    for s in no_value:
        assert (served[s]["volatility"], served[s]["gamma"], served[s]["delta"]) == (
            None,
            None,
            None,
        )
