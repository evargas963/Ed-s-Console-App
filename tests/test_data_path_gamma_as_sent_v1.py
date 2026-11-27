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
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.market_data.schwab.streaming.capture import shown_first
from option_contract import read_chain
from push import chain as push_chain
from push import surface as push_surface
from state import level_store
from tests.feed_live_helper import publish_capture
from tests.real_chains import NFLX
from time_et import ET, option_close_product, record_markets, sessions

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
    publish_capture(
        "NVDA", NVDA["contracts"], NVDA["ts_utc"], NVDA["spot"], at.date().isoformat(), at
    )
    yield
    with level_store._lock:
        level_store._levels.pop("NVDA", None)


def _on_ladder(body):
    """Each contract the chain panel serves, once, in its ladder row."""
    return [c for r in body["ladder"] for c in (r["call"], r["put"]) if c]


@pytest.mark.usefixtures("published")
def test_the_chain_serves_every_gamma_as_schwab_sent_it():
    body = push_chain.chain("NVDA", NVDA["ts_utc"], {"expiry": NVDA["expiry"]})
    served = {c["symbol"]: c["gamma"] for c in _on_ladder(body)}
    sent = {k["symbol"]: k["gamma"] for k in NVDA["contracts"]}
    assert served[LARGE] == sent[LARGE] > 16
    assert served == sent


@pytest.mark.usefixtures("published")
def test_the_chain_serves_each_last_trading_day_as_its_date_in_et():
    body = push_chain.chain("NVDA", NVDA["ts_utc"], {"expiry": NVDA["expiry"]})
    sent = {
        k["symbol"]: k["lastTradingDay"]
        for k in NVDA["contracts"]
        if k["expirationDate"].startswith(NVDA["expiry"])
    }
    # Schwab's instant is 20:00 ET of the last trading day: the next day already in UTC
    assert {
        datetime.fromtimestamp(ms / 1000, tz=UTC).date().isoformat() for ms in sent.values()
    } == {"2026-12-19"}
    assert NVDA["expiry"] == "2026-12-18"
    on_ladder = {c["symbol"] for c in _on_ladder(body)}
    assert on_ladder == set(sent)
    assert {r["series"]["last_trading_day_et"] for r in body["ladder"]} == {"2026-12-18"}


@pytest.mark.usefixtures("published")
def test_the_heatmap_cell_of_a_large_gamma_has_its_gex():
    window = {"scope": "all", "centre": None, "shift": 0, "cols": None, "expiry": None}
    body = push_surface.gamma_surface("NVDA", NVDA["ts_utc"], window, requested=False)
    cell = next(r for r in body["cells"] if r["strike"] == 148.0)
    assert cell["gex"][0] is not None
    assert all(r["gex"][0] is not None for r in body["cells"])


def test_the_option_rule_ranks_the_largest_gamma_schwab_sent_first_of_those_equally_near():
    """The chain is one expiration, so a contract's distance is its strike's count from the price.

    The four contracts that far (a call and a put each side) are ordered by gamma as sent: the
    large one first, taken as it is.
    """
    ranked = shown_first(
        read_chain(NVDA["contracts"]),
        NVDA["spot"],
        NVDA["ts_utc"],
        option_close_product("NVDA"),
        sessions(),
    )
    strikes = sorted({c["strikePrice"] for c in NVDA["contracts"]})
    centre = strikes.index(min(strikes, key=lambda k: (abs(k - NVDA["spot"]), k)))
    far = abs(strikes.index(148.0) - centre)
    as_near = [
        c["symbol"]
        for c in NVDA["contracts"]
        if abs(strikes.index(c["strikePrice"]) - centre) == far
    ]
    assert len(as_near) == 4
    assert min(as_near, key=ranked.index) == LARGE
    assert set(ranked[:2]) == {"NVDA  261218P00213000", "NVDA  261218C00213000"}, "at the price"


def test_the_chain_shows_greeks_on_a_no_value_volatility_as_missing():
    tk, expiry = "NFLX", "2027-12-17"
    publish_capture(
        tk, NFLX.chain, NFLX.now.timestamp(), NFLX.spot, NFLX.now.date().isoformat(), NFLX.now
    )
    try:
        body = push_chain.chain(tk, NFLX.now.timestamp(), {"expiry": expiry})
    finally:
        with level_store._lock:
            level_store._levels.pop(tk, None)
    no_value = {
        c["symbol"]
        for c in NFLX.chain
        if c["expirationDate"].startswith(expiry) and c["volatility"] == -999
    }
    served = {c["symbol"]: c for c in _on_ladder(body)}
    assert no_value
    for s in no_value:
        assert (served[s]["iv_text"], served[s]["gamma"], served[s]["delta"]) == (
            None,
            None,
            None,
        )
