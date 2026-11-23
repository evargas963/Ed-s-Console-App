"""Schwab -> the Flow panel.

A contract's quote time and book time stay when the feed is down.

Real data: TSLA 2026-08-31 367.5 call's 12 LEVELONE_OPTIONS and 4 OPTIONS_BOOK messages as Schwab
sent them (tests/fixtures/real_options_stream_history_samples.json), applied in receive order by
the console's own intake (streaming._ingest_pushed).
"""

from __future__ import annotations

import json
from pathlib import Path

import time_et
from app.options.order_flow import state as of_state
from push import contract as push_contract
from stream_spine import book_msg, verbatim_msg
from tests.feed_live_helper import mark_feed_down, pushed

_SAMPLES = json.loads(
    (Path(__file__).parent / "fixtures" / "real_options_stream_history_samples.json").read_text(
        encoding="utf-8"
    )
)
_SYM = "TSLA  260831C00367500"


def test_a_down_feed_keeps_the_contracts_quote_time_and_book_time():
    """QUOTE_TIME_MILLIS stays on the option top, and BOOK_TIME stays on the book.

    The Flow panel still shows the last bid Schwab sent (0.58), with both times: the newest
    QUOTE_TIME_MILLIS (1788202221274) and BOOK_TIME (1788202221430), each 13:50 CT on Monday
    2026-08-31 (worked out with Python's zoneinfo, outside this code).
    """
    events = next(c for c in _SAMPLES["contracts"] if c["symbol"] == _SYM)["events"]
    of_state.clear_all_live_state()
    try:
        for e in sorted(events, key=lambda e: e["ts_recv"]):
            if e["kind"] == "book":
                msg = book_msg(
                    symbol=_SYM,
                    service="OPTIONS_BOOK",
                    content=e["content"],
                    src="schwab_book",
                    ts_recv=e["ts_recv"],
                )
                pushed(f"book.{_SYM}", msg)
            else:
                msg = verbatim_msg(
                    symbol=_SYM, content=e["content"], src="schwab_options_l1", ts_recv=e["ts_recv"]
                )
                pushed(f"optquote.{_SYM}", msg)
        mark_feed_down()
        body = push_contract.options_microstructure(_SYM, time_et.now())
    finally:
        of_state.clear_all_live_state()
    assert body["top_of_book"]["bid"] == 0.58
    assert body["top_outage"] is not None
    assert body["quote_time_ct"] == "Mon 08/31 01:50 PM CT"
    assert body["book_time_ct"] == "Mon 08/31 01:50 PM CT"
