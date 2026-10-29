"""Schwab -> the levels, the chain and every option contract: one served verdict each, judged by the
ticker's own option market (docs/DATA_FLOW.md §2 D5).

Real data: TSLA's (stock options, whose market Schwab's /markets answer closes at 16:00 ET) and SPY's
0DTE (index-close options, 16:15 ET) chains captured 2026-10-07, a date the held /markets answers
cover (tests/conftest.py), each published by the levels producer (server._publish_levels) at the
price Schwab's LEVELONE_EQUITIES quote at that capture gave (live_price_rows.price_row). STAND-IN
(named): each chain delivered at the instant a test names rather than its capture's, and the
daemon's status typed in its shape (none is captured).
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

import app.options.order_flow.streaming as ofs
import live_market_plane as lmp
import live_price_rows
import push_changes
import server
from calibration.complete_chain_capture import CAPTURE_BASIS, persist_complete_chain_capture
from tests.real_chains import SPY_0DTE, TSLA
from time_et import ET

_QUOTES = {
    q["ticker"]: q
    for q in json.loads(
        (
            Path(__file__).parent
            / "fixtures"
            / "real_spy_tsla_quotes_at_chain_capture_2026_10_07.json"
        ).read_text(encoding="utf-8")
    )["quotes"]
}


def _et(hh: int, mm: int = 0, day: str = "2026-10-07") -> datetime:
    return datetime.fromisoformat(f"{day}T{hh:02d}:{mm:02d}:00").replace(tzinfo=ET)


def _forget() -> None:
    with server._terrain_cache_lock:
        for tk in ("TSLA", "SPY"):
            server._terrain_cache.pop(tk, None)
    for tk in ("TSLA", "SPY"):
        ofs._price_rows.pop(tk, None)
        lmp._by_ticker.pop(tk, None)
        lmp._fields_by_ticker.pop(tk, None)
    lmp.record_feed_down()


def _publish(tk: str, chain, delivered: datetime) -> None:
    """`chain` published by the levels producer as delivered at `delivered`, at the price the
    daemon's price row gave from Schwab's quote at that chain's capture."""
    quote = _QUOTES[tk]
    lmp.record_from_level_one_equity(tk, quote["native"], received_ts=quote["ts_recv"])
    lmp.record_feed_heartbeat(
        {"ts": quote["ts_recv"], "schwab_socket_open": True, "held": {"LEVELONE_EQUITIES": [tk]}}
    )
    row = ofs._price_rows[tk] = live_price_rows.price_row(tk, quote["ts_recv"])
    server._publish_levels(
        tk,
        [dict(c) for c in chain.chain],
        delivered.timestamp(),
        chain_spot=(row["spot"], row["trade_ts"]),
        now=delivered,
    )


@pytest.fixture
def published():
    _forget()
    yield _publish
    _forget()


@pytest.mark.parametrize(
    "tk, chain, delivered, at, state",
    [
        ("TSLA", TSLA, _et(13, 0), _et(13, 1), "LIVE"),  # its options open, the chain current
        (
            "TSLA",
            TSLA,
            _et(13, 0),
            _et(13, 30),
            "STALE",
        ),  # its options open, no chain for 30 minutes
        ("TSLA", TSLA, _et(16, 1), _et(16, 5), "CLOSE"),  # fetched after its own 16:00 close
        ("TSLA", TSLA, _et(15, 59), _et(16, 5), "STALE"),  # its close values never fetched
        ("SPY", SPY_0DTE, _et(16, 4), _et(16, 5), "LIVE"),  # its options still open until 16:15
        ("SPY", SPY_0DTE, _et(16, 4), _et(16, 20), "STALE"),  # fetched before its own 16:15 close
        ("SPY", SPY_0DTE, _et(16, 16), _et(16, 20), "CLOSE"),
        (
            "SPY",
            SPY_0DTE,
            _et(16, 16, "2026-10-09"),
            _et(12, 0, "2026-10-10"),
            "CLOSE",
        ),  # Saturday: Friday's close
        (
            "SPY",
            SPY_0DTE,
            _et(16, 16),
            _et(12, 0, "2026-10-10"),
            "STALE",
        ),  # Saturday: Wednesday's, not Friday's
    ],
)
def test_the_levels_are_judged_by_the_tickers_own_option_market(
    published, tk, chain, delivered, at, state
):
    """The levels' one served word: LIVE while the ticker's own option market is open and its
    chain current, STALE when the chain is overdue or the close values were never fetched, CLOSE
    once its own market has closed and a chain fetched after that close stands."""
    published(tk, chain, delivered)
    body = server.terrain_answer(tk, at)
    assert body["levels_state"] == state
    assert body["levels_age_sec"] == pytest.approx(at.timestamp() - delivered.timestamp())
    assert body["levels_time_ct"] is not None


def test_levels_with_no_markets_answer_held_are_not_live(published):
    """2026-09-20: no /markets answer held for that date, so the levels are not live."""
    published("TSLA", TSLA, _et(11, 0, "2026-09-20"))
    body = server.terrain_answer("TSLA", _et(11, 1, "2026-09-20"))
    assert (body["levels_state"], body["levels_stale_reason"]) == (
        "NOT LIVE",
        "the market session is unknown",
    )


@pytest.mark.parametrize(
    "tk, at, state, why",
    [
        ("TSLA", _et(15, 59), "LIVE", None),
        (
            "TSLA",
            _et(16, 5),
            "NOT LIVE",
            "outside Schwab's option market hours",
        ),  # its stock options closed
        ("SPY", _et(16, 5), "LIVE", None),  # index-close options still open
        ("SPY", _et(16, 20), "NOT LIVE", "outside Schwab's option market hours"),
    ],
)
def test_the_flow_panel_judges_a_contract_by_the_option_market_of_the_chain_that_lists_it(
    published, tk, at, state, why
):
    """A contract of TSLA's or SPY's published chain, held on LEVELONE_OPTIONS and OPTIONS_BOOK, the
    feed up: the route (server.options_microstructure) finds its ticker by the chain that lists it
    and serves it live by that ticker's own option market."""
    chain = {"TSLA": TSLA, "SPY": SPY_0DTE}[tk]
    published(tk, chain, _et(13, 0))
    sym = chain.chain[0]["symbol"]
    lmp.record_feed_heartbeat(
        {
            "ts": at.timestamp(),
            "schwab_socket_open": True,
            "held": {"LEVELONE_OPTIONS": [sym], "OPTIONS_BOOK": [sym]},
        }
    )
    body = server.options_microstructure(sym, at.timestamp())
    assert (body["top_feed_label"], body["top_outage"]) == (state, why)
    assert body["streaming_plane"]["feed_health"]["l1"]["state"] == state


def test_a_contract_no_chain_lists_has_no_known_market(published):
    """With no chain held that lists it, a contract's market is not known: not live, and why."""
    sym = TSLA.chain[0]["symbol"]
    at = _et(13, 0)
    lmp.record_feed_heartbeat(
        {
            "ts": at.timestamp(),
            "schwab_socket_open": True,
            "held": {"LEVELONE_OPTIONS": [sym], "OPTIONS_BOOK": [sym]},
        }
    )
    body = server.options_microstructure(sym, at.timestamp())
    assert (body["top_feed_label"], body["top_outage"]) == (
        "NOT LIVE",
        "the contract's option market is not known",
    )


_SUNDAY = json.loads(
    (
        Path(__file__).parent
        / "fixtures"
        / "real_spy_2026_10_26_expiry_friday_close_and_sunday_chain.json"
    ).read_text(encoding="utf-8")
)


def test_on_a_closed_day_a_delivered_chain_keeps_the_close_counts_schwab_blanks():
    """Sunday 2026-10-25, a day Schwab's /markets answer says is closed: the daemon, restarted, fetches
    SPY's chain again (09:37 ET) and Schwab sends open interest 0 for contracts Friday's 16:16 close had
    above 0. A closed day is outside every option market's window (time_et.option_market_open), so the
    close counts stand (server._keep_last_reported, the stored close capture), as after any close.
    STAND-IN (named): the chain's price is Friday's close capture's underlying price, not Schwab's
    LAST_PRICE with its trade time."""
    friday, sunday = _SUNDAY["friday_close"], _SUNDAY["sunday"]
    close_oi = {c["symbol"]: c["openInterest"] for c in friday["chain"]}
    blanked = [
        c["symbol"] for c in sunday["chain"] if c["openInterest"] == 0 and close_oi[c["symbol"]] > 0
    ]
    at = datetime.fromtimestamp(sunday["ts_utc"], ET)
    _forget()
    try:
        persist_complete_chain_capture(
            server.get_db().db_path,
            ticker="SPY",
            expiry=_SUNDAY["expiry"],
            contracts=[dict(c) for c in friday["chain"]],
            spot=friday["spot"],
            completeness_basis=CAPTURE_BASIS,
            ts_utc=friday["ts_utc"],
        )
        server._publish_levels(
            "SPY",
            [dict(c) for c in sunday["chain"]],
            sunday["ts_utc"],
            chain_spot=(friday["spot"], friday["ts_utc"]),
            now=at,
        )
        priced = {
            c["symbol"]: c for c in server.terrain_cache_get("SPY", at.timestamp())["_priced_chain"]
        }
        same_day = server.terrain_answer("SPY", at)["same_day"]
    finally:
        _forget()
        with sqlite3.connect(
            server.get_db().db_path
        ) as db:  # the session's shared database keeps no SPY capture
            db.execute(
                "DELETE FROM complete_chain_captures WHERE ticker = 'SPY' AND ts_utc = ?",
                (friday["ts_utc"],),
            )
    assert len(blanked) == 46
    assert {s: priced[s]["openInterest"] for s in blanked} == {s: close_oi[s] for s in blanked}
    # no option market trades on Sunday, so there is no same-day close to reprice to: no 0DTE level
    # is made from the next expiry
    assert same_day and all(v is None for v in same_day.values()), same_day
    with sqlite3.connect(server.get_db().db_path) as db:
        assert db.execute(
            "SELECT COUNT(*) FROM complete_chain_captures WHERE ticker = 'SPY'"
        ).fetchone() == (0,)


def _told(tk: str, at: datetime) -> set:
    """What a page open on `tk` is told by the levels loop's minute (server.refresh_not_live_pages)."""

    async def run():
        push_changes.bind(asyncio.get_running_loop())
        page = push_changes.subscribe(tk)
        try:
            server.refresh_not_live_pages(at.timestamp())
            return await push_changes.next_changes(page, 0.3)
        finally:
            push_changes.unsubscribe(tk, page)
            push_changes.bind(None)

    return asyncio.run(run())


def test_a_page_is_told_to_read_again_only_while_its_price_or_its_levels_are_not_live(published):
    """TSLA's price live (its quote's receipt, the daemon holding it) and its chain current: the page
    is not told, each new price and chain tell it. The same chain at 16:05, after TSLA's own option
    close and fetched after it: the levels are CLOSE, so the page is told each minute and the close
    values' age keeps counting."""
    quote = _QUOTES["TSLA"]
    at = datetime.fromtimestamp(quote["ts_recv"], ET)
    published("TSLA", TSLA, at)
    assert server.terrain_answer("TSLA", at)["levels_state"] == "LIVE"
    assert _told("TSLA", at) == set()
    published("TSLA", TSLA, _et(16, 1))
    later = _et(16, 5)
    lmp.record_feed_heartbeat(
        {
            "ts": later.timestamp(),
            "schwab_socket_open": True,
            "held": {"LEVELONE_EQUITIES": ["TSLA"]},
        }
    )
    assert server.terrain_answer("TSLA", later)["levels_state"] == "CLOSE"
    assert _told("TSLA", later) == {push_changes.LEVELS}
