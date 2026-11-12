"""The Vanna and Charm panels the page's socket sends (server.strike_bars).

Operator field-inventory audit, 2026-09-13: both wrap ALREADY-canonical, already-tested faucets --
math_exposure_core.compute_exposures_by_strike's own call_vanna/put_vanna (RC-211's exact
BS-vanna faucet) and math_levels.compute_charm_by_strike (the same function the forces panel's
charm_below/charm_above already sum) -- read off the snapshot _publish_levels last
published (the vanna_rows/charm_rows of the PublishedLevels record it holds),
zero extra vendor calls or pricing. These tests
prove the wiring, not the math (bs_vanna_array/bs_charm_array/compute_charm_by_strike are proven
elsewhere: test_charm_by_strike_v1.py, test_charm_sign_finite_difference.py).

Real data: CRWD's 2026-10-16 chain captured 2026-10-07 10:38:40 ET (tests/real_chains.py), priced
at its capture instant, and CRWD's LEVELONE_EQUITIES message the daemon received at 10:38:00 ET
(tests/fixtures/real_crwd_quote_2026_10_07.json), the live price the panels serve beside it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import live_market_plane as lmp
import server
import time_et
from math_exposure_core import bucket_metric, compute_exposures_by_strike
from math_levels import compute_charm_by_strike
from option_contract import read_chain
from tests.conftest import MARKETS_ANSWERS
from tests.feed_live_helper import mark_feed_live
from tests.real_chains import CRWD

_SPOT = CRWD.spot
_CONTRACTS = read_chain(CRWD.chain)
_QUOTE = json.loads(
    (Path(__file__).resolve().parent / "fixtures" / "real_crwd_quote_2026_10_07.json").read_text(
        encoding="utf-8"
    )
)
TK = server.ticker_storage_key("CRWD")
#: the windows a page asks: Auto and All, following the price
AUTO = {"scope": "auto", "centre": None, "shift": 0}
ALL = {**AUTO, "scope": "all"}


def _clear():
    with server._terrain_cache_lock:
        server._terrain_cache.pop(TK, None)
    lmp._by_ticker.pop(TK, None)
    lmp._fields_by_ticker.pop(TK, None)


def _put_live_chain():
    """CRWD's chain published by the one producer at its capture."""
    at = CRWD.now.timestamp()
    server._publish_levels(TK, _CONTRACTS, at, chain_spot=(_SPOT, at), now=CRWD.now)


def setup_function(_fn):
    _clear()


def teardown_function(_fn):
    _clear()


def test_vanna_by_strike_unavailable_with_no_cached_chain():
    body = server.strike_bars("vanna_rows", TK, time_et.now(), AUTO)
    assert body["available"] is False
    assert body["reason"] == "no levels published for this ticker yet"


def test_charm_by_strike_unavailable_with_no_cached_chain():
    body = server.strike_bars("charm_rows", TK, time_et.now(), AUTO)
    assert body["available"] is False
    assert body["reason"] == "no levels published for this ticker yet"


@pytest.mark.parametrize(
    ("params", "words"),
    [
        ({**AUTO, "scope": "most"}, "scope 'most' is not one of auto, wider, all"),
        ({**AUTO, "centre": "high"}, "centre 'high' is not a strike"),
        ({**AUTO, "centre": True}, "centre True is not a strike"),
        ({**AUTO, "shift": 1.5}, "shift 1.5 is not a whole number of rows"),
        ({"centre": None, "shift": 0}, "scope None is not one of auto, wider, all"),
        ({"scope": "auto", "centre": None}, "shift None is not a whole number of rows"),
    ],
)
def test_a_window_the_panel_cannot_draw_is_unavailable_with_its_words(params, words):
    """A page's parameters the route refused (422) are the panel's reason, never a default."""
    _put_live_chain()
    for rows in ("vanna_rows", "charm_rows"):
        body = server.strike_bars(rows, TK, time_et.now(), params)
        assert body == {"ticker": TK, "available": False, "reason": words}


def test_vanna_by_strike_matches_the_same_canonical_faucet_call_vanna_minus_put_vanna():
    _put_live_chain()
    # Schwab's CRWD quote in the daemon's plane, as the daemon takes it in: its price row
    lmp.record_from_level_one_equity(TK, _QUOTE["native"], received_ts=time_et.now())
    mark_feed_live(TK)

    body = server.strike_bars("vanna_rows", TK, time_et.now(), ALL)
    assert body["available"] is True
    # spot is the live price (the header's own), not the price the rows were computed at
    assert body["spot"] == _QUOTE["native"]["LAST_PRICE"] and "priced_at_spot" not in body
    rows = {r[0]: r[1] for r in body["rows"]}
    assert rows, "a real chain must yield at least one vanna row"

    # the same chain at the same instant: the published rows are the faucet's own values
    exposures, _ = compute_exposures_by_strike(_CONTRACTS, spot=_SPOT, now=CRWD.now)
    checked = 0
    for k, b in exposures.items():
        expected = bucket_metric(b, "net_vanna")
        if expected is None:  # a leg's vanna input Schwab did not send: no row
            assert float(k) not in rows
            continue
        assert rows[float(k)] == expected
        checked += 1
    assert checked > 5


def test_charm_by_strike_matches_the_same_canonical_faucet_compute_charm_by_strike():
    _put_live_chain()
    body = server.strike_bars("charm_rows", TK, time_et.now(), ALL)
    assert body["available"] is True
    rows = {r[0]: r[1] for r in body["rows"]}
    assert rows, "a real chain must yield at least one charm row"

    # the same chain at the same instant: the published rows are the faucet's own values
    per_ch = compute_charm_by_strike(_CONTRACTS, _SPOT, now=CRWD.now)
    checked = 0
    for k, b in per_ch.items():
        if b.get("net_charm") is None:
            continue
        assert rows[float(k)] == float(b["net_charm"])
        checked += 1
    assert checked > 5


#: the panels the Vanna / Charm browser test draws (tests/e2e/console-options-vanna-charm.spec.js)
E2E_PANELS = Path(__file__).resolve().parent / "e2e" / "fixtures" / "vanna_charm_panels_crwd.json"


def build_e2e_panels() -> dict:
    """Return the panels of CRWD's real chain as the page's socket sends them.

    Vanna, Charm and the per-strike rows every Gamma view reads (strikes), each in the page's
    default window (Auto, following the price), with Schwab's CRWD price as the live price:
    vanna and charm at the quote's own time, the strikes at the chain's (its verdict is of that
    instant). Regenerate the browser tests' file with write_e2e_panels.
    """
    _clear()
    try:
        _put_live_chain()
        at = _QUOTE["ts_recv"]  # when the daemon received it
        lmp.record_from_level_one_equity(TK, _QUOTE["native"], received_ts=at)
        return json.loads(
            json.dumps(
                {
                    "vanna": server.strike_bars("vanna_rows", TK, at, AUTO),
                    "charm": server.strike_bars("charm_rows", TK, at, AUTO),
                    "strikes": server.strikes(TK, CRWD.now.timestamp(), AUTO),
                }
            )
        )
    finally:
        _clear()


def write_e2e_panels() -> None:
    """Regeneration utility (never called by a test).

    Schwab's /markets answers held as the tests hold them (tests/conftest.py), then the panels
    written to the browser tests' file:
    python -c "import tests.conftest, tests.test_vanna_charm_by_strike_v1 as t;
    t.write_e2e_panels()"
    """
    for a in json.loads(MARKETS_ANSWERS.read_text(encoding="utf-8"))["answers"].values():
        if a["status"] == 200:
            time_et.record_markets(json.loads(a["body"]))
    E2E_PANELS.write_text(json.dumps(build_e2e_panels(), indent=1), encoding="utf-8")


def test_the_browser_tests_panels_are_the_producers_own():
    assert json.loads(E2E_PANELS.read_text(encoding="utf-8")) == build_e2e_panels()


def test_vanna_and_charm_rows_are_sorted_by_strike_ascending():
    _put_live_chain()
    v_rows = server.strike_bars("vanna_rows", TK, time_et.now(), AUTO)["rows"]
    c_rows = server.strike_bars("charm_rows", TK, time_et.now(), AUTO)["rows"]
    assert [r[0] for r in v_rows] == sorted(r[0] for r in v_rows)
    assert [r[0] for r in c_rows] == sorted(r[0] for r in c_rows)
