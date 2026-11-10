"""A /quotes answer reaches the levels: its values, and its receive time as the levels' time.

Schwab streams part of a ticker's contracts. The others get their bid, ask, volume and Greeks from
/quotes, and the daemon sends the console each answer the moment it arrives (topic `optquotes`,
`ts_recv` the time the answer was received). The console lays an answer over the chain it holds
only when the answer was received after that chain began: an earlier answer is older than the
chain's own values.

Through the real code: the console's feed (streaming._ingest_pushed), its tick and the pricing
thread (server._on_stream_tick), the one producer of the levels (server._publish_levels). Real
data: SPY's 2026-11-20 chain captured 2026-09-30 15:31:57 ET and Schwab's two /quotes answers for
its 442 contracts (tests/schwab_rest_standin.SPY), and the LEVELONE_OPTIONS messages Schwab pushed
for SPY 260904C00772000 (fixtures/real_options_stream_history_samples.json).
STAND-INS (named): each answer's receive time (Schwab's answers were captured 2026-10-01 04:52 ET,
with the market closed, when nothing is laid over a chain); the chain as /chains sent it, without
the quotes the sweep puts on a chain it delivers (the one capture of them is the answers under
test); the held contract's stream record, those messages keyed as SPY 261120C00875000 at one
receive time (no captured stream of a 2026-11-20 contract carries its Greeks); the daemon's status.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime

import pytest

import app.options.order_flow.state as ofls
import app.options.order_flow.streaming as ofs
import live_market_plane as lmp
import server
from option_contract import read_chain
from stream_spine import verbatim_msg
from terrain_engine import compute_terrain
from tests.feed_live_helper import daemon_status
from tests.schwab_rest_standin import FX, SPY
from time_et import ET

TK = server.ticker_storage_key("SPY")
#: the chain as the console reads it, once (option_contract.read_chain)
_CHAIN = read_chain(SPY["chain"])
#: the chain began at its capture, 2026-09-30 15:31:57 ET
_BEGUN = SPY["capture_ts_utc"]
_SPOT = SPY["spot"]
#: Schwab's two /quotes answers, each contract's `quote` as sent: 300 contracts, then the other 142
_FIRST, _SECOND = ({s: e["quote"] for s, e in q["reply"].items()} for q in SPY["quotes"])
#: STAND-IN times: an answer received 30 s after the chain began, a push 10 s after it
_RECEIVED = _BEGUN + 30.0
_PUSHED = _BEGUN + 10.0
#: the contract the stream holds, and every LEVELONE_OPTIONS message it is given, oldest first
HELD = "SPY   261120C00875000"
_L1 = [
    e["content"]
    for c in json.loads(
        (FX / "real_options_stream_history_samples.json").read_text(encoding="utf-8")
    )["contracts"]
    if c["symbol"] == "SPY   260904C00772000"
    for e in c["events"]
    if e["kind"] == "l1"
]
_GREEKS = ("gamma", "delta", "theta", "vega", "rho", "volatility")


def _reset() -> None:
    ofls.clear_all_live_state()
    with ofls._rest_lock:
        ofls._REST_QUOTES.clear()
    lmp.record_feed_down()
    lmp._by_ticker.pop(TK, None)
    lmp._fields_by_ticker.pop(TK, None)
    with server._terrain_cache_lock:
        server._terrain_cache.pop(TK, None)
    with server._chains_waiting_lock:
        server._chains_delivered.discard(TK)


@pytest.fixture(autouse=True)
def _clean():
    """Reset to this test's state only."""
    _reset()
    yield
    _reset()


def _daemon(at: float, held=()) -> None:
    """The daemon's status at `at`: Schwab's stream up, holding `held` of SPY's contracts."""
    lmp.record_feed_heartbeat(
        daemon_status(
            at,
            schwab_socket_open=True,
            held={"LEVELONE_EQUITIES": [TK], "LEVELONE_OPTIONS": list(held)},
        )
    )


def _put_chain() -> None:
    """The chain reaches the console, priced at its capture's spot as of when it began."""
    server._publish_levels(
        TK, _CHAIN, _BEGUN, chain_spot=(_SPOT, _BEGUN), now=datetime.fromtimestamp(_BEGUN, ET)
    )


def _answered(answer: dict, received: float) -> None:
    """Take the daemon's message of one /quotes answer (ChainSweep.send_quotes publishes it)."""
    ofs._ingest_pushed("optquotes", {"src": "schwab_quotes", "ts_recv": received, "answer": answer})


def _cached() -> server.PublishedLevels:
    return server.published_levels(TK)


def _repriced(answer: dict, received: float) -> server.PublishedLevels:
    """Return the levels once the pricing thread has priced the ticks of `answer`."""
    ofs._on_tick_callback = server._on_stream_tick  # as start_order_flow_stream sets it
    try:
        _answered(answer, received)
        while True:
            server._chain_pricing.submit(lambda: None).result(timeout=60)
            with server._chains_waiting_lock:
                if not server._chains_waiting:
                    break
    finally:
        ofs._on_tick_callback = None
    return _cached()


def _quoted_chain(answer: dict) -> list:
    """The chain, each contract of `answer` with its quote's values as sent, the others its own."""
    return [
        replace(
            ct,
            bid=answer[ct.symbol]["bidPrice"],
            ask=answer[ct.symbol]["askPrice"],
            volume=answer[ct.symbol]["totalVolume"],
            **{g: answer[ct.symbol][g] for g in _GREEKS},
        )
        if ct.symbol in answer
        else ct
        for ct in _CHAIN
    ]


def _levels_of(chain: list, at: float) -> list:
    """Each strike's row of `chain` priced at the capture's spot as of `at`."""
    return compute_terrain(TK, chain, _SPOT, now=datetime.fromtimestamp(at, ET)).per_strike


def test_an_answer_received_after_the_chain_began_prices_the_levels_at_its_receive_time():
    """Schwab answered /quotes for 300 of SPY's contracts 30 s after the chain began.

    Each of them carries the answer's bid, ask, volume and Greeks as sent, the 142 not answered
    keep the chain's own, the levels are priced with both as of the answer's receive time, and the
    levels' time is that receive time; the chain's time stays the chain's.
    """
    _daemon(_BEGUN)
    _put_chain()
    before = _cached()
    _daemon(_RECEIVED)
    c = _repriced(_FIRST, _RECEIVED)
    for got, want in zip(c.priced_chain, _quoted_chain(_FIRST), strict=True):
        assert got == want, want.symbol
    assert c.snap.per_strike == _levels_of(_quoted_chain(_FIRST), _RECEIVED)
    assert c.snap.per_strike != before.snap.per_strike
    assert (c.levels_ts_utc, c.computed_ts_utc) == (_RECEIVED, _BEGUN)


def test_a_later_answer_moves_the_levels_time_to_its_own_receive_time():
    """Schwab's second answer, for the other 142 contracts, arrives 5 s after the first.

    Every contract then carries its quote's values, and the levels' time is the second answer's
    receive time: the newest of Schwab's option values in them.
    """
    _daemon(_BEGUN)
    _put_chain()
    _daemon(_RECEIVED)
    _repriced(_FIRST, _RECEIVED)
    _daemon(_RECEIVED + 5.0)
    c = _repriced(_SECOND, _RECEIVED + 5.0)
    for got, want in zip(c.priced_chain, _quoted_chain({**_FIRST, **_SECOND}), strict=True):
        assert got == want, want.symbol
    assert (c.levels_ts_utc, c.computed_ts_utc) == (_RECEIVED + 5.0, _BEGUN)


def test_an_answer_received_before_the_chain_began_is_not_laid_over_it():
    """The console holds a /quotes answer received a minute before SPY's newest chain began.

    The chain's values are the newer ones: every contract keeps them, the levels are priced with
    them, and the levels' time is the chain's.
    """
    _answered(_FIRST, _BEGUN - 60.0)
    _daemon(_BEGUN)
    _put_chain()
    c = _cached()
    for got, ct in zip(c.priced_chain, _CHAIN, strict=True):
        assert got == ct, ct.symbol
    assert c.snap.per_strike == _levels_of(_CHAIN, _BEGUN)
    assert c.levels_ts_utc == c.computed_ts_utc == _BEGUN


def test_a_contract_the_stream_holds_takes_the_streams_values_and_time_not_the_answers():
    """Schwab streams one contract, and a /quotes answer for it arrives after its pushes.

    The stream is that contract's one producer: its Greeks and volume are the pushed ones, its bid
    and ask none (the stream sent neither), and the levels' time is the push's, not the answer's.
    """
    _daemon(_BEGUN, held=[HELD])
    _put_chain()
    _daemon(_PUSHED, held=[HELD])
    for content in _L1:
        ofs._ingest_pushed(
            f"optquote.{HELD}",
            verbatim_msg(
                symbol=HELD,
                content={**content, "key": HELD},
                src="schwab_options_l1",
                ts_recv=_PUSHED,
            ),
        )
    _daemon(_RECEIVED, held=[HELD])
    c = _repriced({HELD: _FIRST[HELD]}, _RECEIVED)
    newest = {field: value for content in _L1 for field, value in content.items()}
    got = next(ct for ct in c.priced_chain if ct.symbol == HELD)
    assert {g: getattr(got, g) for g in _GREEKS} == {g: newest[g.upper()] for g in _GREEKS}
    assert (got.volume, got.bid, got.ask) == (newest["TOTAL_VOLUME"], None, None)
    assert c.levels_ts_utc == _PUSHED
