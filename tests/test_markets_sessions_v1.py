"""The market's sessions are Schwab's GET /markets answers (operator 2026-10-07): the daemon asks
for equity and option once per date per ET day -- today, the 7 days before it Schwab answers, and
each expiry date of the chains, whatever the number of tickers -- records every answer as sent, and
the console takes each 200 as that date's sessions. The session label only labels: what Schwab
streams is shown whatever it says.

Real data: Schwab's /markets answers for every date it answered on 2026-10-07, with its 400 on each
side (tests/fixtures/real_schwab_markets_2026_10_07.json, held by tests/conftest.py and served by
the stand-in host, tests/schwab_rest_standin.py), and CRWD's LEVELONE_EQUITIES message of
2026-10-07 10:38 ET (tests/fixtures/real_crwd_quote_2026_10_07.json).
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path

import live_market_plane as lmp
import server
import time_et
from app.market_data.schwab.streaming import capture
from app.options.order_flow import streaming as ofs
from stream_spine import LOG, CaptureWriter, HealthRegistry, MessageBus
from tests.feed_live_helper import mark_feed_live, publish_daemon_rows
from tests.schwab_rest_standin import CHAINS, MARKETS, MARKETS_ANSWERS, LocalSchwab
from time_et import ET

FX = Path(__file__).resolve().parent / "fixtures"


def _et(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=ET)


# ── question 1: we get what we asked Schwab for, exactly as sent ─────────────────────────────

def test_the_daemon_asks_each_date_once_and_records_every_answer_as_sent(tmp_path):
    """The real sweep on the daemon's thread (capture.run_chains, the wall clock), SPY and TSLA on
    the watchlist: each of today and the 7 days before it, and each expiry date the chains list,
    asked once -- not once per ticker -- each answer published and written by the one writer into
    stream_markets_raw exactly as Schwab sent it, with its status."""
    db = tmp_path / "stream_capture.db"
    schwab = LocalSchwab()
    client = schwab.client(tmp_path)
    today = datetime.now(ET).date()
    wanted = {(today - timedelta(days=n)).isoformat() for n in range(8)} | {e for e, _c, _s in CHAINS.values()}

    def rows():
        if not db.exists():
            return []
        con = sqlite3.connect(db)
        try:
            if not con.execute("SELECT 1 FROM sqlite_master WHERE name='stream_markets_raw'").fetchone():
                return []
            return con.execute("SELECT date, status, native_json, src FROM stream_markets_raw ORDER BY rowid").fetchall()
        finally:
            con.close()

    async def go():
        bus, health, stop = MessageBus(), HealthRegistry(), asyncio.Event()
        daemon = capture.Daemon(bus, health, ["SPY", "TSLA"])
        writer = CaptureWriter(db, batch_rows=1, batch_sec=0.01)
        written = asyncio.create_task(writer.run(bus.subscribe("", policy=LOG), stop=stop))
        sweep = asyncio.create_task(capture.run_chains(daemon, tmp_path / "ed_console.db", lambda: client, stop,
                                                       failures=writer))
        deadline = asyncio.get_running_loop().time() + 30
        while {r[0] for r in rows()} < wanted and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.1)
        await asyncio.sleep(1.0)
        stop.set()
        await asyncio.gather(written, sweep)
    try:
        asyncio.run(go())
    finally:
        schwab.close()
    asked = [q["date"] for q in schwab.asked(MARKETS)]
    assert sorted(asked) == sorted(wanted), "each date once, whatever the number of tickers"
    assert all(q["markets"] == "equity,option" for q in schwab.asked(MARKETS))
    recorded = rows()
    assert sorted(r[0] for r in recorded) == sorted(wanted)
    for day, status, native, src in recorded:
        sent = MARKETS_ANSWERS[day] if day in MARKETS_ANSWERS else None
        assert src == "schwab_markets"
        if sent is not None:
            assert (status, json.loads(native)) == (sent["status"], json.loads(sent["body"])), day


def test_the_console_holds_each_200_answer_and_never_a_400():
    """The console's intake (streaming._ingest_pushed) takes a 200 as that date's sessions, as the
    daemon publishes it; Schwab's 400 (more than 7 days back) is no session: the date stays
    unknown."""
    from calibration.complete_chain_capture import markets_message
    for day in ("2026-09-29", "2026-10-07"):
        a = MARKETS_ANSWERS[day]
        _topic, msg = markets_message(day, a["status"], json.loads(a["body"]), time.time())
        ofs._ingest_pushed(f"markets.{day}", json.loads(msg["frame"])["msg"])
    assert time_et.session("2026-09-29") is None
    s = time_et.session("2026-10-07")
    assert s.is_open and s.regular == ((_et("2026-10-07 09:30"), _et("2026-10-07 16:00")),)


# ── question 3: each session reading is correct against Schwab's answer ──────────────────────

def test_the_sessions_are_the_windows_schwab_sent_on_a_normal_day_a_holiday_and_an_early_close():
    normal, holiday, early = (time_et.session(d) for d in ("2026-10-07", "2026-11-26", "2026-11-27"))
    assert (normal.pre, normal.post) == (((_et("2026-10-07 07:00"), _et("2026-10-07 09:30")),),
                                         ((_et("2026-10-07 16:00"), _et("2026-10-07 20:00")),))
    assert normal.option_windows("EQO") == ((_et("2026-10-07 09:30"), _et("2026-10-07 16:00")),)
    assert normal.option_windows("IND") == ((_et("2026-10-07 09:30"), _et("2026-10-07 16:15")),)
    assert holiday.is_open is False and holiday.regular == () and holiday.option_windows("EQO") == ()
    assert early.regular == ((_et("2026-11-27 09:30"), _et("2026-11-27 13:00")),)
    assert early.post == ((_et("2026-11-27 13:00"), _et("2026-11-27 17:00")),)
    assert early.option_windows("IND") == ((_et("2026-11-27 09:30"), _et("2026-11-27 13:15")),)


def test_the_label_follows_schwabs_windows():
    label = time_et.session_label
    assert label(_et("2026-10-07 06:59")) == time_et.CLOSED          # Schwab's pre-market opens 07:00
    assert label(_et("2026-10-07 07:00")) == time_et.PRE_MARKET
    assert label(_et("2026-10-07 09:30")) == time_et.RTH
    assert label(_et("2026-10-07 16:00")) == time_et.AFTER_HOURS
    assert label(_et("2026-10-07 20:00")) == time_et.CLOSED
    assert label(_et("2026-11-27 13:00")) == time_et.AFTER_HOURS     # the early close
    assert label(_et("2026-11-27 17:00")) == time_et.CLOSED
    assert label(_et("2026-11-26 12:00")) == time_et.CLOSED          # Thanksgiving
    assert label(_et("2027-10-09 12:00")) == time_et.UNKNOWN         # beyond what Schwab answers
    assert time_et.closed_since(_et("2026-10-10 12:00")) == _et("2026-10-09 20:00")


def test_option_markets_open_and_close_by_their_own_windows():
    assert time_et.options_open(_et("2026-10-07 16:05"), "EQO") is False
    assert time_et.options_open(_et("2026-10-07 16:05"), "IND") is True
    assert time_et.options_closed_at(_et("2026-10-07 16:05"), "EQO") == _et("2026-10-07 16:00")
    assert time_et.options_closed_at(_et("2026-10-10 12:00"), "IND") == _et("2026-10-09 16:15")
    assert time_et.options_open(_et("2027-10-09 12:00"), "EQO") is None


def test_time_to_expiry_runs_to_schwabs_close_of_the_expiry_date():
    """Schwab's expirationDate is not the settlement (an AM-settled $SPX monthly carries 16:00 ET
    of its date): T runs to the EQO regular close Schwab's /markets sent for the expiry date --
    13:00 on the 2026-11-27 early close -- or its 09:30 open for settlementType "A"; none on a
    date Schwab says has no session. Beyond the year /markets answers (operator 2026-10-08): a
    PM-settled contract runs to Schwab's expirationDate as sent, an AM-settled one has none."""
    year = time_et.YEAR_SECONDS
    at = _et("2026-11-27 10:00")
    assert time_et.time_to_expiry_years("2026-11-27T21:00:00.000+00:00", at) == 3 * 3600 / year
    assert time_et.time_to_expiry_years("2026-11-27T21:00:00.000+00:00", _et("2026-11-27 09:00"),
                                        settlement_type="A") == 1800 / year
    assert time_et.time_to_expiry_years("2026-11-26T21:00:00.000+00:00", at) is None
    far = "2027-12-17T21:00:00.000+00:00"                          # $SPX's, as Schwab sent it
    assert time_et.time_to_expiry_years(far, at, settlement_type="P") == (
        datetime.fromisoformat(far).timestamp() - at.timestamp()) / year
    assert time_et.time_to_expiry_years(far, at, settlement_type="A") is None


# ── question 2: the screen shows what Schwab streams, whatever the label says ────────────────

def test_a_stock_quote_before_schwabs_pre_market_is_shown():
    """Operator 2026-10-07: stock quotes from 04:00 ET come through. At 05:00 ET Schwab's /markets
    says Closed (pre-market opens 07:00): CRWD's quote, received then, is the price served."""
    fx = json.loads((FX / "real_crwd_quote_2026_10_07.json").read_text(encoding="utf-8"))
    tk, native = fx["ticker"], fx["native"]
    try:
        lmp.record_from_level_one_equity(tk, native, received_ts=time.time())
        mark_feed_live(tk)
        publish_daemon_rows(tk)
        assert time_et.session_label(_et("2026-10-07 05:00")) == time_et.CLOSED
        assert lmp.outage(tk, "LEVELONE_EQUITIES", _et("2026-10-07 05:00").timestamp()) is None
        assert server.resolve_spot(tk)[0] == native["LAST_PRICE"]
    finally:
        ofs._price_rows.pop(tk, None)
        lmp._by_ticker.pop(tk, None)
        lmp._fields_by_ticker.pop(tk, None)
