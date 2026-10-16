"""A contract the daemon stops holding keeps Schwab's last bid on the Flow panel.

End to end through the real code: the daemon's status (live_market_plane.record_feed_heartbeat),
Schwab's LEVELONE_OPTIONS message (streaming._ingest_pushed), the release path
(streaming._drop_released_options), and the Flow panel (server.options_microstructure).
Real data: one LEVELONE_OPTIONS message received 2026-10-05 14:00 CT
(tests/fixtures/real_stream_mix_2026_10_05_1400ct.json). The daemon's status is the console's
own message, built here in its shape (no status is captured).
"""
from __future__ import annotations

import json
from pathlib import Path

import app.options.order_flow.state as ofls
import app.options.order_flow.streaming as ofs
import live_market_plane as lmp
import server
from stream_spine import options_quote_msg

_MIX = json.loads((Path(__file__).parent / "fixtures" / "real_stream_mix_2026_10_05_1400ct.json")
                  .read_text(encoding="utf-8"))["messages"]
_MSG = next(m for m in _MIX if m["service"] == "LEVELONE_OPTIONS" and "BID_PRICE" in m["item"])
_SYM = _MSG["item"]["key"]
_AT = _MSG["ts_recv"] + 1.0


def test_a_released_contract_keeps_its_last_bid_and_is_not_streamed():
    """The option rule moves off the contract during the open session: the Flow panel still
    shows Schwab's bid, marks the contract NOT STREAMED, and says the quote is OFFLINE."""
    ofls.clear_all_live_state()
    try:
        lmp.record_feed_heartbeat({"ts": _AT - 0.5, "schwab_socket_open": True,
                                   "held": {"LEVELONE_OPTIONS": [_SYM], "OPTIONS_BOOK": []}})
        ofs._ingest_pushed(f"optquote.{_SYM}", options_quote_msg(
            symbol=_SYM, content=_MSG["item"], src="schwab_options_l1", ts_recv=_MSG["ts_recv"]))
        lmp.record_feed_heartbeat({"ts": _AT - 0.5, "schwab_socket_open": True,
                                   "held": {"LEVELONE_OPTIONS": [], "OPTIONS_BOOK": []}})
        ofs._drop_released_options(_AT)
        body = server.options_microstructure(_SYM, _AT)
    finally:
        ofls.clear_all_live_state()
        lmp.record_feed_down()
    assert body["top_of_book"]["bid"] == _MSG["item"]["BID_PRICE"]
    assert body["streaming_plane"]["subscription_state"] == ofs.NOT_STREAMED
    assert body["top_outage"]
