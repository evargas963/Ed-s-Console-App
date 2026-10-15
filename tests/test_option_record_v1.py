"""The console keeps each option contract's LEVELONE_OPTIONS record as the daemon pushes it: every
field Schwab has sent, the last of each, and when the newest arrived; the next push replaces it
(the daemon's record is already merged: Schwab sends changes only); clearing the contract or the
session drops it.

Through the real code: the daemon's bus merges the messages (stream_spine.MessageBus), the console
takes the pushed record (app.options.order_flow.streaming._ingest_pushed). Real data: SPY
261016C00766000's four LEVELONE_OPTIONS messages in the 2026-10-05 14:00 CT stream mix
(tests/real_option_record.py).
"""
from __future__ import annotations

import pytest

import app.options.order_flow.state as ofls
import app.options.order_flow.streaming as ofs
from tests.real_option_record import bus_records

SYM = "SPY   261016C00766000"


@pytest.fixture(autouse=True)
def _clean():
    ofls.clear_all_live_state()
    yield
    ofls.clear_all_live_state()


def _push_each_as_the_daemon_does() -> dict:
    """Each message's current record pushed to the console as the daemon pushes it; the last."""
    for topic, record in bus_records(SYM):
        ofs._ingest_pushed(topic, record)
    return record


def test_the_console_holds_the_daemons_record_whole_with_its_newest_receive_time():
    assert len(list(bus_records(SYM))) > 1, "the contract sent more than one message"
    record = _push_each_as_the_daemon_does()
    assert ofls.option_records([SYM]) == {SYM: (record["content"], record["ts_recv"])}
    assert record["ts_recv"] == max(stamp[1] for stamp in record["field_ts"].values())


def test_clearing_the_contract_or_the_session_drops_its_record():
    _push_each_as_the_daemon_does()
    ofls.clear_symbol(SYM)
    assert ofls.option_records([SYM]) == {SYM: None}
    _push_each_as_the_daemon_does()
    ofls.clear_all_live_state()
    assert ofls.option_records([SYM]) == {SYM: None}
