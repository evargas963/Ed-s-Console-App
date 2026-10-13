"""The console keeps each option contract's LEVELONE_OPTIONS record as the daemon pushes it: every
field Schwab has sent, the last of each, with each field's receive time; the next push replaces it
(the daemon's record is already merged: Schwab sends changes only); clearing the contract or the
session drops it.

Through the real code: the daemon's bus merges the messages (stream_spine.MessageBus), the console
takes the pushed record (app.options.order_flow.streaming._ingest_pushed). Real data: SPY
261016C00766000's four LEVELONE_OPTIONS messages in the 2026-10-05 14:00 CT stream mix
(tests/fixtures/real_stream_mix_2026_10_05_1400ct.json).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import app.options.order_flow.state as ofls
import app.options.order_flow.streaming as ofs
from app.market_data.schwab.streaming import capture
from stream_spine import MessageBus

SYM = "SPY   261016C00766000"
_MIX = [m for m in json.loads((Path(__file__).parent / "fixtures" / "real_stream_mix_2026_10_05_1400ct.json")
                              .read_text(encoding="utf-8"))["messages"] if m["item"]["key"] == SYM]


@pytest.fixture(autouse=True)
def _clean():
    ofls.clear_all_live_state()
    yield
    ofls.clear_all_live_state()


def _push_each_as_the_daemon_does() -> dict:
    """Each message merged on the daemon's bus, its current record pushed to the console; the last."""
    bus = MessageBus()
    for m in _MIX:
        kind, msg = capture._message(m["service"], SYM, m["item"], m["schwab_ts"])
        topic = f"{kind}.{SYM}"
        bus.publish(topic, {**msg, "ts_recv": m["ts_recv"]})
        record = next(iter(bus.current.values()))[1]
        ofs._ingest_pushed(topic, record)
    return record


def test_the_console_holds_the_daemons_record_whole_with_each_fields_receive_time():
    assert len(_MIX) > 1, "the contract sent more than one message"
    record = _push_each_as_the_daemon_does()
    content, received = ofls.option_record(SYM)
    assert content == record["content"]
    assert received == {f: stamp[1] for f, stamp in record["field_ts"].items()}


def test_clearing_the_contract_or_the_session_drops_its_record():
    _push_each_as_the_daemon_does()
    ofls.clear_symbol(SYM)
    assert ofls.option_record(SYM) is None
    _push_each_as_the_daemon_does()
    ofls.clear_all_live_state()
    assert ofls.option_record(SYM) is None
