"""The daemon's status is current at a time when it was stamped within the live limit of it,
before or after (live_market_plane.daemon_status): the console prices a chain and serves the
heatmap at the time it began, and the daemon's next status, sent while it worked, is the one it
holds. Production 2026-10-15 RTH: pricing a large chain took longer than the status's one-second
interval, that status was refused as not current, and every streamed heatmap cell of SPY, QQQ,
IWM, META, TSLA and SPCX read stale.

End to end through the real code: the daemon's status (record_feed_heartbeat), the pushed option
message (streaming._ingest_pushed), the levels producer (server._publish_levels) and the
heatmap route (server.gamma_surface_payload).
Real data: SPY's 2026-11-20 chain captured 2026-09-30 15:31:57 ET
(tests/fixtures/real_spy_2026_11_20_chain_and_quotes.json) and Schwab's LEVELONE_OPTIONS message
for one of its contracts received 2026-10-05 14:00 CT (tests/fixtures/real_stream_mix_2026_10_05_1400ct.json),
priced at that message's receive time with its UNDERLYING_PRICE. The daemon's status and price row
are the console's own messages, built here in their shape.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

import app.options.order_flow.state as ofls
import app.options.order_flow.streaming as ofs
import live_market_plane as lmp
import server
from stream_spine import options_quote_msg
from time_et import ET

_FX = Path(__file__).resolve().parent / "fixtures"
_CHAIN = json.loads((_FX / "real_spy_2026_11_20_chain_and_quotes.json").read_text(encoding="utf-8"))["chain"]
_LISTED = {c["symbol"] for c in _CHAIN}
_MSG = next(m for m in json.loads((_FX / "real_stream_mix_2026_10_05_1400ct.json").read_text(encoding="utf-8"))["messages"]
            if m["service"] == "LEVELONE_OPTIONS" and m["item"]["key"] in _LISTED
            and {"GAMMA", "DELTA", "OPEN_INTEREST", "TOTAL_VOLUME"} & set(m["item"]))
SYM = _MSG["item"]["key"]
TK = server.ticker_storage_key("SPY")
_AT = _MSG["ts_recv"] + 1.0                       # the chain priced a second after Schwab's message


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


def _beat(ts: float) -> None:
    lmp.record_feed_heartbeat({"ts": ts, "schwab_socket_open": True,
                               "held": {"LEVELONE_EQUITIES": [TK], "LEVELONE_OPTIONS": [SYM]}})


def _states_when_the_status_was_sent(after: float) -> list[str]:
    """SPY's chain priced and its heatmap served at `_AT`, the daemon's status it holds stamped
    `after` seconds later: the states of SYM's heatmap legs."""
    _beat(_AT + after)
    ofs._price_rows[TK] = {"ticker": TK, "spot": _MSG["item"]["UNDERLYING_PRICE"], "trade_ts": _AT}
    ofs._ingest_pushed(f"optquote.{SYM}", options_quote_msg(
        symbol=SYM, content=_MSG["item"], src="schwab_options_l1", ts_recv=_MSG["ts_recv"]))
    at = datetime.fromtimestamp(_AT, ET)
    server._publish_levels(TK, [dict(c) for c in _CHAIN], _AT - 10.0, now=at)
    body = server.gamma_surface_payload(TK, "all", None, 0, None, None, at)
    return [col[side]["state"] for cell in body["cells"] for col, pair in zip(cell["stream"], cell["contracts"])
            for side in ("call", "put") if col and pair.get(side) == SYM]


@pytest.mark.parametrize("after", [0.001, 0.5, 2.9])
def test_a_status_sent_while_the_chain_was_priced_keeps_the_streamed_cell_live(after):
    assert _states_when_the_status_was_sent(after) == ["live"]


def test_a_status_sent_past_the_live_limit_is_not_current():
    _beat(_AT + lmp.FEED_HEARTBEAT_MAX_AGE_SEC)
    assert lmp.daemon_status(_AT) is None and not lmp.feed_live_for(SYM, "LEVELONE_OPTIONS", _AT)
    assert lmp.feed_live_for(SYM, "LEVELONE_OPTIONS", _AT + 1.0)
