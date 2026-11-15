"""A trade at an unchanged price is a print of its own, received when its message was.

Schwab's LEVELONE stream sends only the fields that changed (Streamer API §1.5, Change), so a trade
at the last trade's price arrives with a new TRADE_TIME_MILLIS and LAST_SIZE and no LAST_PRICE. The
daemon's bus merges each message into the symbol's current record (stream_spine.MessageBus), and
the console takes that record (streaming._ingest_pushed); the tape (state.push_level_one) keeps
each new (time, price, size) as a print, stamped with the receive time of the message that made it.

Real data: SPY's LEVELONE_EQUITIES messages of 2026-11-13 10:00:00-10:02:00 ET as the daemon
recorded them (stream_capture.db stream_quotes_raw, read-only;
tests/fixtures/real_spy_levelone_2026_11_13_1000et.json), 113 messages, 4 of them trades at an
unchanged price. The expected prints are worked out here by merging the messages' fields in order.
"""

from __future__ import annotations

import json
from pathlib import Path

import app.options.order_flow.state as state
import app.options.order_flow.streaming as ofs
import l1_trade_observation as l1
from feed.connection import SERVICE_TOPIC, held_key
from stream_spine import MessageBus, quote_msg

_MSGS = json.loads(
    (Path(__file__).parent / "fixtures" / "real_spy_levelone_2026_11_13_1000et.json").read_text(
        encoding="utf-8"
    )
)["messages"]
_FIELDS = ("TRADE_TIME_MILLIS", "LAST_PRICE", "LAST_SIZE")


def _expected() -> list[tuple[float, float, float | None, int]]:
    """(receive time, price, size, trade time) of each new print, merging fields as sent."""
    held: dict[str, object] = {}
    out, last = [], None
    for m in _MSGS:
        held.update({f: m["item"][f] for f in _FIELDS if f in m["item"]})
        if "LAST_PRICE" not in held:
            continue
        triple = (held["TRADE_TIME_MILLIS"], held["LAST_PRICE"], held.get("LAST_SIZE"))
        if triple != last:
            out.append((m["ts_recv"], triple[1], triple[2], triple[0]))
            last = triple
    return out


def test_every_trade_is_a_print_received_when_its_message_was():
    state.clear_all_live_state()
    _kind, src = SERVICE_TOPIC["LEVELONE_EQUITIES"]
    bus = MessageBus()
    key = held_key("LEVELONE_EQUITIES", "SPY")
    try:
        for m in _MSGS:
            bus.publish(
                "quote.SPY",
                quote_msg(symbol="SPY", src=src, native=m["item"], ts_recv=m["ts_recv"]),
            )
            ofs._ingest_pushed("quote.SPY", bus.current[key][1])
        prints = l1.canonical_tape_prints(state.get_content_for_symbol("SPY"))
    finally:
        state.clear_all_live_state()
    want = _expected()
    got = [(p["server_received_ts"], p["price"], p["size"], p["time_millis"]) for p in prints]
    assert got == want[-state.MAX_TAPE_PRINTS :]
    unchanged = [
        m["ts_recv"]
        for m in _MSGS
        if "TRADE_TIME_MILLIS" in m["item"] and "LAST_PRICE" not in m["item"]
    ]
    assert len(unchanged) == 4
    # each trade at an unchanged price is a print, stamped with its own message's receive time
    assert set(unchanged) <= {ts for ts, _p, _s, _t in got}
