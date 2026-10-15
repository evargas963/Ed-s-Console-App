"""The daemon's status is current at a time when it was stamped within the live limit of it,
before or after (live_market_plane.daemon_status): the console prices a chain and serves the
heatmap at the time it began, and the daemon's next status, sent while it worked, is the one it
holds. Production 2026-10-15 RTH: pricing a large chain took longer than the status's one-second
interval, that status was refused as not current, and every streamed heatmap cell of SPY, QQQ,
IWM, META, TSLA and SPCX read stale.

End to end through the real code: the daemon's status (record_feed_heartbeat), a pushed option
message (streaming._ingest_pushed), the levels producer (server._publish_levels) and the
heatmap route (server.gamma_surface_payload).
Real data: CRWD's 2026-10-16 chain captured 2026-10-07 10:38:40 ET (tests/real_chains.py),
valued at its capture. STAND-INS (named): the streamed GAMMA of one CRWD contract, and the
daemon's status holding it.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

import app.options.order_flow.state as ofls
import app.options.order_flow.streaming as ofs
import live_market_plane as lmp
import server
from stream_spine import options_quote_msg
from tests.real_chains import CRWD

_CONTRACTS = [dict(ct) for ct in CRWD.chain]
TK = server.ticker_storage_key("CRWD")
_AT = CRWD.now
SYM = next(c["symbol"] for c in _CONTRACTS if c["putCall"] == "CALL")


@pytest.fixture(autouse=True)
def _clean():
    ofls.clear_all_live_state()
    lmp.record_feed_down()
    yield
    ofls.clear_all_live_state()
    lmp.record_feed_down()
    ofs._price_rows.pop(TK, None)
    with server._terrain_cache_lock:
        server._terrain_cache.pop(TK, None)


def _states_when_the_status_was_sent(after: float) -> list[str]:
    """CRWD's chain priced and its heatmap served at `_AT`, the daemon's status it holds stamped
    `after` seconds later: the states of SYM's heatmap legs."""
    lmp.record_feed_heartbeat({"ts": (_AT + timedelta(seconds=after)).timestamp(), "schwab_socket_open": True,
                               "held": {"LEVELONE_EQUITIES": [TK], "LEVELONE_OPTIONS": [SYM]}})
    ofs._price_rows[TK] = {"ticker": TK, "spot": CRWD.spot, "trade_ts": _AT.timestamp()}
    ofs._ingest_pushed(f"optquote.{SYM}", options_quote_msg(
        symbol=SYM, content={"key": SYM, "GAMMA": 0.05}, src="schwab_options_l1", ts_recv=_AT.timestamp() - 1))
    server._publish_levels(TK, _CONTRACTS, _AT.timestamp() - 10.0, now=_AT)
    body = server.gamma_surface_payload(TK, "all", None, 0, None, None, _AT)
    return [col[side]["state"] for cell in body["cells"] for col, pair in zip(cell["stream"], cell["contracts"])
            for side in ("call", "put") if col and pair.get(side) == SYM]


@pytest.mark.parametrize("after", [0.001, 0.5, 2.9])
def test_a_status_sent_while_the_chain_was_priced_keeps_the_streamed_cell_live(after):
    assert _states_when_the_status_was_sent(after) == ["live"]


def test_a_status_sent_past_the_live_limit_is_not_current():
    assert lmp.daemon_status(_AT.timestamp() - lmp.FEED_HEARTBEAT_MAX_AGE_SEC) is None
    lmp.record_feed_heartbeat({"ts": _AT.timestamp() + lmp.FEED_HEARTBEAT_MAX_AGE_SEC, "schwab_socket_open": True,
                               "held": {"LEVELONE_OPTIONS": [SYM]}})
    assert lmp.daemon_status(_AT.timestamp()) is None and not lmp.feed_live_for(SYM, "LEVELONE_OPTIONS", _AT.timestamp())
    assert lmp.feed_live_for(SYM, "LEVELONE_OPTIONS", _AT.timestamp() + 1.0)
