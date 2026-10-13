"""The heatmap says which cells Schwab's stream backs now (question 2: the screen shows it
correctly): each leg live (the feed delivers it), stale (it streamed, the feed is not delivering
it), pending (the daemon holds it, no update yet) or unavailable (the daemon does not stream it),
each cell's state from its legs, and the header's chip counting the cells drawn.

End to end through the real code: the daemon's status (live_market_plane.record_feed_heartbeat),
its pushed option messages applied by the console (streaming._ingest_pushed), its price row,
the levels producer (server._publish_levels) and the heatmap route's answer at a time
(server.gamma_surface_payload).
Real data: CRWD's 2026-10-16 chain captured 2026-10-07 10:38:40 ET (tests/real_chains.py, one
expiration), valued at its capture; that day's sessions as Schwab's /markets sent them
(tests/conftest.py). STAND-INS (named): each streamed value of a CRWD contract, and the daemon's
status holding them.
"""
from __future__ import annotations

import json
from datetime import datetime

import pytest

import app.options.order_flow.state as ofls
import app.options.order_flow.streaming as ofs
import live_market_plane as lmp
import server
from tests.feed_live_helper import daemon_holds, ledger_open, no_daemon, through_the_daemons_bus
from tests.real_chains import CRWD
from time_et import ET

_SPOT = CRWD.spot
_CONTRACTS = [dict(ct) for ct in CRWD.chain]
TK = server.ticker_storage_key("CRWD")
_AT = CRWD.now                                           # RTH, at the capture
_CLOSED = datetime(2026, 10, 7, 22, 0, tzinfo=ET)        # after Schwab's 20:00 post-market end
CALLS = [c["symbol"] for c in _CONTRACTS if c["putCall"] == "CALL"]
PUTS = [c["symbol"] for c in _CONTRACTS if c["putCall"] == "PUT"]


@pytest.fixture(autouse=True)
def _clean():
    ofls.clear_all_live_state()
    no_daemon()
    yield
    ofls.clear_all_live_state()
    no_daemon()
    ofs._price_rows.pop(TK, None)
    with server._terrain_cache_lock:
        server._terrain_cache.pop(TK, None)


def _publish(held, ticked, *, at=_AT, socket_open=True):
    """The daemon holding `held` on LEVELONE_OPTIONS, Schwab having sent a GAMMA for each of
    `ticked` a second before `at`, CRWD's chain published at `at`; the route's coverage of every
    strike, and the published surface."""
    daemon_holds(at.timestamp(), {"LEVELONE_EQUITIES": [TK], "LEVELONE_OPTIONS": list(held)},
                 socket_open=socket_open)
    ofs._price_rows[TK] = {"ticker": TK, "spot": _SPOT, "trade_ts": at.timestamp()}
    bus = ledger_open(TK, _CONTRACTS, at.timestamp() - 10.0)
    for sym in ticked:
        through_the_daemons_bus(bus, sym, [{"GAMMA": 0.05}], [at.timestamp() - 1])
    server._publish_levels(TK, at.timestamp() - 10.0, now=at)
    body = server.gamma_surface_payload(TK, "all", None, 0, None, None, at)
    with server._terrain_cache_lock:
        surface = server._terrain_cache[TK]["_gamma_surface"]
    return body["view"]["coverage"], surface


def _legs(surface, sym):
    return [col[side] for cell in surface["cells"] for col, pair in zip(cell["stream"], cell["contracts"])
            for side in ("call", "put") if col and pair.get(side) == sym]


def test_a_contract_the_feed_delivers_is_live_with_its_own_age():
    sym = CALLS[0]
    cov, surface = _publish([sym], [sym])
    legs = _legs(surface, sym)
    assert legs and all(leg["state"] == "live" and leg["age_sec"] == pytest.approx(1.0) for leg in legs)
    assert cov["partial"] == 1 and cov["live"] == 0          # its put is not streamed: the cell is partial


def test_every_cell_streaming_reads_all_streaming_and_one_cell_short_never_does():
    """ALL STREAMING only when every cell drawn is live; one cell short (its put held, no update)
    is the share rounded down, never 100%, and the cell says pending."""
    every = CALLS + PUTS
    cov, _ = _publish(every, every)
    assert (cov["state"], cov["label"], cov["live"], cov["cells"]) == (
        server.COVERAGE_LIVE, "ALL STREAMING", len(CALLS), len(CALLS))
    ofls.clear_all_live_state()
    cov, surface = _publish(every, every[:-1])
    assert _legs(surface, every[-1])[0]["state"] == "pending"
    assert cov["live"] == len(CALLS) - 1 and cov["partial"] == 1
    assert cov["label"] == f"{100 * (len(CALLS) - 1) // len(CALLS)}% STREAMING" != "100% STREAMING"


def test_one_live_cell_of_many_reads_under_one_percent_never_zero():
    one = [CALLS[0], PUTS[0]]
    cov, _ = _publish(one, one)
    assert cov["live"] == 1 and cov["cells"] == len(CALLS) > 100
    assert cov["label"] == "<1% STREAMING"


def test_a_contract_that_streamed_reads_stale_while_schwabs_socket_is_closed():
    """Closed (22:00 ET), Schwab's socket closed: the values as of the close stand (the streamed
    gamma prices the cell) and its legs say they are not streaming now."""
    sym = CALLS[0]
    cov, surface = _publish([sym], [sym], at=_CLOSED, socket_open=False)
    assert [leg["state"] for leg in _legs(surface, sym)] == ["stale"]
    served = json.loads(server.get_chain(ticker=TK, expiry=None).body)["contracts"]
    assert next(ct["gamma"] for ct in served if ct["symbol"] == sym) == 0.05
    assert cov["stale"] == 1 and cov["live"] == 0


def test_a_held_contract_with_no_tick_is_pending_only_while_the_daemon_says_it_holds_it():
    """ONE-15: unknown is never confirmation. While the daemon's heartbeat is live and holds the
    contract it is pending; once the daemon stops reporting, its holding is unknown: unavailable."""
    sym = CALLS[0]
    _cov, surface = _publish([sym], [], at=_CLOSED)
    pending = [leg["state"] for leg in _legs(surface, sym)]
    lmp.record_feed_down()
    server._publish_levels(TK, _CLOSED.timestamp() - 10.0, now=_CLOSED)
    with server._terrain_cache_lock:
        down = [leg["state"] for leg in _legs(server._terrain_cache[TK]["_gamma_surface"], sym)]
    assert pending == ["pending"] and down == ["unavailable"]


def test_a_contract_the_daemon_does_not_stream_is_not_streaming():
    cov, surface = _publish([], [])
    assert all(leg["state"] == "unavailable" for sym in CALLS for leg in _legs(surface, sym))
    assert cov["unavailable"] == cov["cells"] == len(CALLS) and cov["label"] == "0% STREAMING"
