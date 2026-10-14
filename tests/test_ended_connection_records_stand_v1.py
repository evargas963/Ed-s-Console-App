"""When Schwab's connection ends, the records it held stand with their last values, not live, and
the next connection's first message replaces each whole (operator 2026-10-13: "On disconnect keep
the last values, marked not live; reconnect's opening replaces them"). Before, the daemon forgot
them: a console that connected meanwhile had no last value to show.

Real data: SPY's first two LEVELONE_EQUITIES messages received 2026-10-05 14:00 CT
(tests/fixtures/real_stream_mix_2026_10_05_1400ct.json), each through the daemon's real Schwab
handler (capture._publisher) onto its bus. The second stands for the next connection's first
message (STAND-IN, named: no reconnect was captured; it carries a different set of fields, so a
merge and a replacement differ)."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from app.market_data.schwab.streaming import capture
from stream_spine import HealthRegistry, MessageBus

_SPY = [m for m in json.loads((Path(__file__).parent / "fixtures" / "real_stream_mix_2026_10_05_1400ct.json")
                              .read_text(encoding="utf-8"))["messages"]
        if m["service"] == "LEVELONE_EQUITIES" and m["item"]["key"] == "SPY"][:2]
_KEY = capture._current_key("LEVELONE_EQUITIES", "SPY")


def _sent(handler, m: dict) -> None:
    handler({"service": "LEVELONE_EQUITIES", "timestamp": m["schwab_ts"], "content": [m["item"]]})


def test_an_ended_connections_records_stand_not_live_and_the_next_ones_first_message_replaces_them():
    first, opening = _SPY
    assert set(first["item"]) - set(opening["item"]) == {"LAST_SIZE", "REGULAR_MARKET_LAST_SIZE"}
    daemon = capture.Daemon(MessageBus(), HealthRegistry(), ["SPY"])
    handler = capture._publisher("LEVELONE_EQUITIES", daemon.bus, daemon.health)
    daemon.held["LEVELONE_EQUITIES"] = frozenset({"SPY"})
    _sent(handler, first)
    asyncio.run(daemon.disconnect())
    # the last values stand; nothing is held, which the heartbeat reports: not live
    assert daemon.bus.current[_KEY][1]["native"] == first["item"]
    assert daemon.status()["held"]["LEVELONE_EQUITIES"] == []
    # a reader that starts now (the console reconnecting) is handed them
    reader = daemon.bus.subscribe("quote.")
    assert _KEY in reader.changed
    # the next connection's first message is the whole record: no field of the ended one stays
    daemon.held["LEVELONE_EQUITIES"] = frozenset({"SPY"})
    _sent(handler, opening)
    assert daemon.bus.current[_KEY][1]["native"] == opening["item"]
    assert set(daemon.bus.current[_KEY][1]["field_ts"]) == set(opening["item"])


_OPEN = json.loads((Path(__file__).parent / "fixtures" / "real_spy_0dte_open_stream_and_chain_2026_10_13.json")
                   .read_text(encoding="utf-8"))["messages"]


def test_the_console_keeps_an_ended_connections_option_prints_until_the_rule_drops_the_contract():
    """A held SPY 0DTE contract's first LEVELONE_OPTIONS message of the 2026-10-13 open (its trade
    in the console's one tape), through the daemon's bus. The connection ends, and a new one
    begins with nothing held yet: its print stands, the daemon's rule still picking it. Only when
    the rule stops picking it -- here while Schwab is down, so no connection ever holds it again
    -- is it forgotten. Before, the first status after the connection ended released every
    contract: the Flow tape and the option books emptied."""
    import time

    import option_ledger
    from app.options.order_flow import history
    from app.options.order_flow import state as ofls
    from app.options.order_flow import streaming as ofs
    from stream_spine import current_key
    from tests.feed_live_helper import CONNECTED_AT, daemon_holds, no_daemon

    m = next(x for x in _OPEN if "LAST_PRICE" in x["content"] and "TRADE_TIME_MILLIS" in x["content"])
    sym, held = m["symbol"], {"LEVELONE_OPTIONS": [m["symbol"]]}
    bus = MessageBus()
    topic, msg = option_ledger.posting(sym, option_ledger.from_stream(m["content"], m["schwab_ts"]),
                                       m["schwab_ts"], m["ts_recv"])
    bus.publish(topic, msg)
    now, again = time.time(), CONNECTED_AT + 1.0
    try:
        daemon_holds(now, held)
        ofs._ingest_pushed(topic, bus.current[current_key(topic, msg)][1])
        printed = history.TAPE.prints(sym)
        assert printed
        daemon_holds(now + 1, {}, socket_open=False, picks=held)        # the connection ended
        daemon_holds(now + 2, {}, connected_at=again, picks=held)       # a new one, nothing held yet
        assert history.TAPE.prints(sym) == printed, "the last values stand"
        daemon_holds(now + 3, {}, socket_open=False, picks={})          # the rule moved off it, Schwab down
        assert history.TAPE.prints(sym) == []
    finally:
        ofls.clear_symbol(sym)
        no_daemon()


def test_the_consoles_price_record_takes_the_new_connections_opening_whole():
    """SPY's two messages on the console's price record (live_market_plane, which the price row
    reads), a new Schwab connection begun between them: the second, the new connection's first,
    is the whole record. Before, the ended connection's LAST_SIZE stayed, shown as current once
    the feed was held again."""
    import live_market_plane as lmp
    import live_price_rows
    from tests.feed_live_helper import daemon_holds, forget_price, no_daemon

    first, opening = _SPY
    began = (first["ts_recv"] + opening["ts_recv"]) / 2
    assert first["ts_recv"] < began < opening["ts_recv"]
    held = {"LEVELONE_EQUITIES": ["SPY"]}

    def row(at):
        return live_price_rows.price_row("SPY", at, lmp.get_quote("SPY"))

    for status_first in (True, False):           # the new connection's status before its opening, or after
        forget_price("SPY")
        try:
            daemon_holds(first["ts_recv"], held)                                # the first connection
            lmp.record_from_level_one_equity("SPY", first["item"], received_ts=first["ts_recv"])
            assert row(first["ts_recv"])["last_size"] is not None and row(first["ts_recv"])["feed_live"]
            if status_first:
                daemon_holds(opening["ts_recv"], held, connected_at=began)
                # the ended connection's values stand, not live, until the new one posts
                assert row(opening["ts_recv"])["spot"] == first["item"]["LAST_PRICE"]
                assert row(opening["ts_recv"])["feed_live"] is False
            lmp.record_from_level_one_equity("SPY", opening["item"], received_ts=opening["ts_recv"])
            if not status_first:
                daemon_holds(opening["ts_recv"], held, connected_at=began)
            served = row(opening["ts_recv"])
            assert served["last_size"] is None and served["spot"] == opening["item"]["LAST_PRICE"], status_first
            assert served["feed_live"] is True
        finally:
            forget_price("SPY")
            no_daemon()
