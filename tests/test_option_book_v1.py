"""The Options Book: each contract's resting book and volume, their summary and the options lean.

Real data, read-only from production data/ed.db on 2026-11-20
(tests/fixtures/real_spy_option_book_2026_11_19.json.gz, its source named in the file): SPY's
/chains answer for the 2026-11-19 expiry received 10:00:50 ET; at 10:01:50 ET, each contract's
newest OPTIONS_BOOK message of the 120 s before and newest LEVELONE_OPTIONS message carrying
TOTAL_VOLUME of the 600 s before, SPY's newest LEVELONE_EQUITIES message with LAST_PRICE and
Schwab's /markets answer of the day. The chain is published by the one levels producer, each message
goes through the console's own intake, and the panel is read at 10:01:50 ET. STAND-IN (named): the
daemon's status, holding SPY, each contract a message was stored for, on its service.

Every expected value is worked out here from the raw messages: each contract's resting bid and
ask (every level's TOTAL_VOLUME summed) and its volume, the summary's totals and shares, the three
readings, their average and its zone.

Regenerate the browser tests' file (tests/e2e/fixtures/option_book_spy.json):
  python -c "import tests.conftest, tests.test_option_book_v1 as t; t.write_option_book_panels()"
"""

from __future__ import annotations

import gzip
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import pytest

import app.options.order_flow.state as ofls
import live_market_plane as lmp
import server
import time_et
from calc.option_book import ZONES, lean, split
from feed.schwab_client import flatten_chain_contracts
from option_contract import read_chain
from push import option_book as push_option_book
from state import level_store
from stream_spine import book_msg, verbatim_msg
from tests.feed_live_helper import ROUND_SEC, daemon_status, pushed
from tests.test_order_flow_book_payload_v1 import _same

_FX = Path(__file__).resolve().parent / "fixtures" / "real_spy_option_book_2026_11_19.json.gz"
_E2E = Path(__file__).resolve().parent / "e2e" / "fixtures" / "option_book_spy.json"
REAL = json.loads(gzip.decompress(_FX.read_bytes()))
TK = REAL["ticker"]
AT = REAL["at"]
#: the windows the page asks: Auto and Wider, following the price, at the front expiry
AUTO = {"scope": "auto", "centre": None, "shift": 0, "expiry": None}
WIDER = {**AUTO, "scope": "wider"}
#: each contract's newest stored book and option quote, as Schwab sent them
BOOKS = {b["symbol"]: b["item"] for b in REAL["books"]}
QUOTES = {q["symbol"]: q["item"] for q in REAL["option_quotes"]}
#: the chain's contracts as Schwab listed them
LISTED = flatten_chain_contracts(REAL["chain"]["answer"])


def _clear() -> None:
    with level_store._lock:
        level_store._levels.pop(TK, None)
    server._gamma_surface_seq.pop(TK, None)
    lmp._by_ticker.pop(TK, None)
    lmp._fields_by_ticker.pop(TK, None)
    lmp.record_feed_down()
    ofls.clear_all_live_state()


@contextmanager
def held(*, books_held: bool = True) -> Iterator[None]:
    """SPY's chain published and its messages taken in, as the console holds them at AT.

    `books_held` False: the daemon's status holds no contract on OPTIONS_BOOK (the books stand,
    not live).
    """
    sessions = time_et.HELD.sessions
    time_et.HELD.sessions = {}  # the day's own answer, whatever else a test run holds
    _clear()
    try:
        time_et.record_markets(REAL["markets"]["body"])
        lmp.record_from_level_one_equity(
            TK, REAL["equity"]["item"], received_ts=REAL["equity"]["ts_recv"]
        )
        lmp.record_feed_heartbeat(
            daemon_status(
                AT,
                schwab_socket_open=True,
                held={
                    "LEVELONE_EQUITIES": [TK],
                    "LEVELONE_OPTIONS": sorted(QUOTES),
                    "OPTIONS_BOOK": sorted(BOOKS) if books_held else [],
                },
                chain_round_sec=ROUND_SEC,
            )
        )
        for b in REAL["books"]:
            pushed(
                f"book.{b['symbol']}",
                book_msg(
                    symbol=b["symbol"],
                    service="OPTIONS_BOOK",
                    content=b["item"],
                    src="schwab_book",
                    ts_recv=b["ts_recv"],
                ),
            )
        for q in REAL["option_quotes"]:
            pushed(
                f"optquote.{q['symbol']}",
                verbatim_msg(
                    symbol=q["symbol"],
                    content=q["item"],
                    src="schwab_options_l1",
                    ts_recv=q["ts_recv"],
                ),
            )
        # the chain as the sweep delivers it, with Schwab's underlyingPrice in its answer
        chain = REAL["chain"]
        server._publish_levels(
            TK,
            read_chain(LISTED),
            chain["ts_recv"],
            chain_spot=(chain["answer"]["underlyingPrice"], chain["ts_recv"]),
            now=datetime.fromtimestamp(AT, time_et.ET),
        )
        yield
    finally:
        _clear()
        time_et.HELD.sessions = sessions


def build_option_book_panels() -> dict:
    """Return the `option_book` panel at AT in the Auto and the Wider window, as sent on the socket.

    The Options Book subview and the Trade Desk card ask it at the front expiry.
    """
    with held():
        return json.loads(
            json.dumps(
                {
                    "auto": push_option_book.option_book(TK, AT, AUTO),
                    "wider": push_option_book.option_book(TK, AT, WIDER),
                }
            )
        )


def write_option_book_panels() -> None:
    """Regeneration utility (never called by a test)."""
    _E2E.write_text(
        json.dumps(build_option_book_panels(), indent=2) + "\n",  # as Prettier
        encoding="utf-8",
    )


def _resting(symbol: str, side: str) -> float:
    """A contract's resting size on `side` ("BIDS", "ASKS"): its book's levels' TOTAL_VOLUME."""
    return float(sum(level["TOTAL_VOLUME"] for level in BOOKS[symbol][side]))


def _volume(symbol: str) -> float:
    """A contract's volume today: its newest streamed TOTAL_VOLUME, else its chain's."""
    if symbol in QUOTES:
        return float(QUOTES[symbol]["TOTAL_VOLUME"])
    return float(next(c["totalVolume"] for c in LISTED if c["symbol"] == symbol))


def _tilt(a: float, b: float) -> float:
    return (a - b) / (a + b)


def test_the_browser_tests_option_book_is_the_producers_own():
    fixture = json.loads(_E2E.read_text(encoding="utf-8"))
    assert _same(fixture, build_option_book_panels()), (
        "the browser tests' file drifted from the server; regenerate with "
        "write_option_book_panels()"
    )


def test_each_contract_shows_its_book_summed_and_its_volume_as_sent():
    """Every contract shown: resting bid and ask, each its book's levels summed; volume as sent."""
    panel = build_option_book_panels()["wider"]
    shown = [x for r in panel["rows"] for x in (r["call"], r["put"]) if x is not None]
    booked = [x for x in shown if x["symbol"] in BOOKS]
    assert len(booked) == 24  # every contract Schwab streamed a book for: 731 to 742, both sides
    for x in booked:
        assert (x["bid"], x["ask"]) == (
            _resting(x["symbol"], "BIDS"),
            _resting(x["symbol"], "ASKS"),
        )
        assert x["bid_text"] == f"{x['bid']:,.0f}" and x["book_live"] is True
    for x in shown:
        assert x["volume"] == _volume(x["symbol"])
        assert x["volume_text"] == f"{_volume(x['symbol']):,.0f}"


def test_a_contract_with_no_book_streamed_is_unknown_never_zero():
    """Wider's 23 strikes: those outside the books Schwab streamed show '-' and are not summed."""
    panel = build_option_book_panels()["wider"]
    unbooked = [r for r in panel["rows"] if r["call"]["symbol"] not in BOOKS]
    assert len(panel["rows"]) == 23 and unbooked
    for r in unbooked:
        assert r["summed"] is False
        assert (r["call"]["bid"], r["call"]["bid_text"], r["call"]["book_live"]) == (
            None,
            None,
            None,
        )
        assert r["call"]["volume"] is not None  # the volume is still Schwab's
    assert panel["summary"]["left_out_text"] == (
        f"{len(unbooked)} rows shown without a Schwab book on both sides: not summed"
    )


def test_the_summary_and_the_lean_are_the_books_worked_out_from_the_raw_messages():
    panel = build_option_book_panels()["auto"]
    rows = panel["rows"]
    # Auto: 11 strikes around 737, the listed strike nearest SPY's 736.695, marked; high to low
    assert [r["strike"] for r in rows] == [float(k) for k in range(742, 731, -1)]
    assert [r["strike"] for r in rows if r["marks"]] == [737.0]
    calls = [r["call"]["symbol"] for r in rows]
    puts = [r["put"]["symbol"] for r in rows]
    call_bid = sum(_resting(s, "BIDS") for s in calls)
    call_ask = sum(_resting(s, "ASKS") for s in calls)
    put_bid = sum(_resting(s, "BIDS") for s in puts)
    put_ask = sum(_resting(s, "ASKS") for s in puts)
    call_vol = sum(_volume(s) for s in calls)
    put_vol = sum(_volume(s) for s in puts)
    s = panel["summary"]
    assert (s["calls"]["left"], s["calls"]["right"]) == (call_bid, call_ask)
    assert (s["puts"]["left"], s["puts"]["right"]) == (put_bid, put_ask)
    assert (s["volume"]["left"], s["volume"]["right"]) == (call_vol, put_vol)
    assert s["calls"]["left_share"] == pytest.approx(call_bid / (call_bid + call_ask))
    assert s["calls"]["left_share_text"] == f"{call_bid / (call_bid + call_ask):.0%}"
    assert (
        s["summed_text"] == "11 strikes 732–742: those whose call and put both have a Schwab book"
    )
    assert s["left_out_text"] is None
    c, p, v = _tilt(call_bid, call_ask), -_tilt(put_bid, put_ask), _tilt(call_vol, put_vol)
    got = panel["lean"]
    assert (got["calls"], got["puts"], got["volume"]) == pytest.approx((c, p, v))
    value = (c + p + v) / 3
    assert got["value"] == pytest.approx(value)
    assert got["value_text"] == f"{value:+.2f}"
    zone = next(i for i, top in enumerate((-0.6, -0.2, 0.2, 0.6, 1.0)) if value < top or i == 4)
    assert (got["zone_index"], got["zone"]) == (zone, ZONES[zone])
    assert got["needle_deg"] == pytest.approx(value * 90)
    assert panel["book_state"] == lmp.LIVE and panel["zones"] == list(ZONES)


def test_books_that_stopped_stand_marked_not_live():
    """The daemon holds no contract on OPTIONS_BOOK: the last books stand, NOT LIVE, with why."""
    with held(books_held=False):
        panel = push_option_book.option_book(TK, AT, AUTO)
    legs = [x for r in panel["rows"] for x in (r["call"], r["put"])]
    assert all(x["bid"] is not None and x["book_live"] is False for x in legs)
    assert panel["book_state"] == lmp.NOT_LIVE
    assert panel["book_outage"] in {
        f"{x['symbol']} is not streamed on Schwab OPTIONS_BOOK" for x in legs
    }
    assert panel["book_oldest_text"].startswith("oldest book ")


def test_with_no_chain_held_the_panel_says_why():
    panel = push_option_book.option_book("ZZNOCHAIN", AT, AUTO)
    assert panel["available"] is False and panel["reason"]


@pytest.mark.parametrize(
    ("lean_value", "zone"),
    [
        (-1.0, "Defensive"),
        (-0.8, "Defensive"),
        (-0.4, "Leaning defensive"),
        (0.0, "Neutral"),
        (0.4, "Leaning constructive"),
        (0.8, "Constructive"),
        (1.0, "Constructive"),
    ],
)
def test_the_zones_are_five_equal_fifths(lean_value, zone):
    """INDUCED: three equal readings, each `lean_value`, so their average is `lean_value`."""
    a, b = 1.0 + lean_value, 1.0 - lean_value
    got = lean(split(a, b), split(b, a), split(a, b))
    assert got.value == pytest.approx(lean_value) and got.zone == zone


def test_a_reading_with_nothing_on_either_side_leaves_the_lean_unknown():
    """INDUCED: no put volume and no call volume traded: no volume reading, so no lean."""
    got = lean(split(10.0, 5.0), split(5.0, 10.0), split(0.0, 0.0))
    assert got.volume is None and got.value is None and got.zone is None
    assert got.calls == pytest.approx(1 / 3) and got.puts == pytest.approx(1 / 3)


def test_each_quote_and_book_of_a_contract_sends_the_option_book_again():
    """The panel is live: an option's quote or book (server.flow_changed) and new levels send it."""
    assert "option_book" in server.OPTION_PANELS
    assert "option_book" in server.FLOW_PANELS
    assert "option_book" in server.LEVELS_PANELS
