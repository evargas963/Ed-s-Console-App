"""The daemon's chain sweep (DATA_FLOW decisions 1 and 7): the one fetcher of every watchlist ticker's
chain, the records it posts to the ledger that the console takes, and the chain history the daemon
writes from them.

Real data: SPY's 2026-11-20 contracts from the capture daemon's full-chain capture of 2026-09-30
15:31:57 ET and Schwab's quotes for every one of them, served by Schwab's host as a local server
(tests/schwab_rest_standin.py) to the real sweep and client; MRVL's full chain as Schwab sent it
(tests/fixtures/real_mrvl_full_chain_vs_strike_window.json, 2,432 contracts)."""
from __future__ import annotations

import asyncio
import itertools
import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

import pytest

import calibration.complete_chain_capture as cch
import schwab_client as sc
from app.market_data.schwab.streaming import capture
from json_blob_codec import decode_json_blob
from stream_spine import LATEST, HealthRegistry, MessageBus
from tests.feed_live_helper import daemon_round
from tests.schwab_rest_standin import CHAIN, SPY_QUOTES, LocalSchwab
from time_et import ET

_QUOTED = {s: e["quote"] for s, e in SPY_QUOTES.items()}
_MRVL = sc.flatten_chain_contracts(json.loads((Path(__file__).resolve().parent / "fixtures"
                                               / "real_mrvl_full_chain_vs_strike_window.json")
                                              .read_text(encoding="utf-8"))["full"])


def _ts(s: str) -> float:
    return datetime.fromisoformat(s).replace(tzinfo=ET).timestamp()


def _et(ts: float) -> str:
    return datetime.fromtimestamp(ts, ET).strftime("%Y-%m-%d %H:%M")


@pytest.mark.parametrize("now, slot", [
    ("2026-10-05 08:00", None),                 # Monday before the open: nothing written
    ("2026-10-05 09:30", "2026-10-05 09:30"),
    ("2026-10-05 09:59", "2026-10-05 09:30"),
    ("2026-10-05 15:45", "2026-10-05 15:30"),
    ("2026-10-05 16:05", "2026-10-05 16:00"),
    ("2026-10-05 16:20", "2026-10-05 16:15"),   # the close capture: the last option market (IND) closes 16:15
    ("2026-10-05 16:46", None),                 # nothing after the close capture's window
    ("2026-10-10 12:00", None),                 # Saturday: Schwab sends no session
    ("2026-11-26 12:00", None),                 # Thanksgiving: Schwab says closed
    ("2026-11-27 13:10", "2026-11-27 13:00"),
    ("2026-11-27 13:20", "2026-11-27 13:15"),   # early close: Schwab's IND close 13:15
    ("2026-11-02 09:31", "2026-11-02 09:30"),   # after the DST change, still 9:30 ET
])
def test_the_capture_window_a_fetch_is_written_for(now, slot):
    """The windows are the regular option sessions Schwab's /markets sent for the day
    (tests/conftest.py holds the answers captured 2026-10-07)."""
    got = cch.capture_slot(_ts(now))
    assert (_et(got) if got is not None else None) == slot


def test_every_capture_window_of_a_full_day_ends_at_the_last_option_markets_close():
    slots = {cch.capture_slot(_ts(f"2026-10-05 {h:02d}:{m:02d}"))
             for h in range(0, 24) for m in range(0, 60)} - {None}
    assert sorted(_et(s)[11:] for s in slots) == [
        f"{h:02d}:{m:02d}" for h in range(9, 17) for m in (0, 30)
        if "09:30" <= f"{h:02d}:{m:02d}" <= "16:00"] + ["16:15"]


@pytest.fixture
def schwab():
    host = LocalSchwab()
    yield host
    host.close()


def _sweep(tmp_path, schwab, clock):
    """The daemon's sweep over SPY on `clock`, posting to the daemon's ledger, with the daemon's
    client of the stand-in host; the daemon writes the chain history to its database, and holds
    SPY's price as Schwab sent it at the capture (the chain answer's underlyingPrice, 766.31)."""
    sqlite3.connect(tmp_path / "ed_console.db").close()          # the daemon's database exists
    daemon = capture.Daemon(MessageBus(), HealthRegistry(), ["SPY"])
    daemon.history_db = tmp_path / "ed_console.db"
    daemon._took_price("SPY", {"native": {"LAST_PRICE": 766.31}})
    published: list = []

    def publish(topic, msg):
        published.append((topic, msg))
        daemon.bus.publish(topic, msg)
    sweep = cch.ChainSweep(["SPY"], publish, clock=clock, held=lambda: frozenset())
    client = schwab.client(tmp_path)
    return daemon, sweep, published, (lambda: client)


def _rotate(daemon, sweep, published, client) -> "set[str]":
    """One rotation, and each round it delivers taken by the daemon (Daemon._took_chain), its
    history write waited for."""
    async def go():
        before = len(published)
        delivered = sweep.rotation(client, ["SPY"], threading.Event())
        for topic, msg in published[before:]:
            if topic.startswith("chain."):
                write = daemon._took_chain(topic.split(".", 1)[1], msg)
                if write is not None:
                    await write
        return delivered
    return asyncio.run(go())


def test_a_refused_chain_reaches_the_console_as_schwabs_answer(tmp_path, schwab):
    schwab.refuse_chain = {"SPY"}
    daemon, sweep, published, client = _sweep(tmp_path, schwab, lambda: _ts("2026-09-30 15:31:57"))
    assert _rotate(daemon, sweep, published, client) == set()
    assert [(t, m["failed"]) for t, m in published if "failed" in m] == [
        ("chain.SPY", "chain for 2026-11-20 returned HTTP 502")]


def test_the_history_is_written_once_per_capture_window_and_never_outside_one(tmp_path, schwab):
    """Each window's first round is written from the daemon's ledger: every contract's record, its
    Greeks the quote's, and the time the round began, at Schwab's underlyingPrice as sent -- the
    newest by Schwab's time: the quotes' 762.63 (every one of the 442, each newer than the chain
    answer's 766.31), never the daemon's last trade (766.31 here)."""
    clock = {"now": 0.0}
    daemon, sweep, published, client = _sweep(tmp_path, schwab, lambda: clock["now"])
    for at in ("2026-09-30 15:31:57", "2026-09-30 15:35:00",      # the 15:30 window, twice
               "2026-09-30 16:01:00",                             # the 16:00 window
               "2026-09-30 17:00:00"):                            # after the close capture's window
        clock["now"] = _ts(at)
        assert _rotate(daemon, sweep, published, client) == {"SPY"}
    with sqlite3.connect(tmp_path / "ed_console.db") as c:
        rows = c.execute("SELECT ts_utc, expiry, spot, n_contracts, chain_json FROM complete_chain_captures "
                         "ORDER BY ts_utc").fetchall()
    assert [(_et(r[0]), r[1], r[2], r[3]) for r in rows] == [
        ("2026-09-30 15:31", "2026-11-20", 762.63, 442), ("2026-09-30 16:01", "2026-11-20", 762.63, 442)]
    assert {q["underlyingPrice"] for q in _QUOTED.values()} == {762.63}
    assert isinstance(rows[0][4], bytes), "stored compressed"
    stored = {c["symbol"]: c for c in decode_json_blob(rows[0][4])}
    assert all(stored[s]["gamma"] == q["gamma"] for s, q in _QUOTED.items()), "the quote's gamma is stored"
    assert all(stored[s]["fieldTimes"]["gamma"] == q["quoteTime"] for s, q in _QUOTED.items()), "with its time"


def test_an_added_ticker_joins_the_rotation_in_its_turn(tmp_path, schwab):
    """Operator 2026-10-06: every ticker the same, in one rotation; none has priority. TSLA added
    to the watchlist beside SPY: SPY first, then TSLA, in sorted order."""
    _daemon, sweep, published, client = _sweep(tmp_path, schwab, lambda: _ts("2026-08-28 09:05"))
    sweep.watchlist = ["TSLA", "SPY"]                      # the daemon's list after an add
    stop = threading.Event()
    worker = threading.Thread(target=sweep.work, args=(client, stop), daemon=True)
    worker.start()
    while not any(t == "chain.TSLA" for t, _m in published) and worker.is_alive():
        stop.wait(0.05)
    stop.set()
    worker.join(10)
    assert [q["symbol"] for q in schwab.asked(CHAIN)][:2] == ["SPY", "TSLA"]


def test_a_fetch_begun_before_the_close_capture_is_not_the_close_capture(tmp_path, schwab):
    """2026-10-01 audit: the capture window was judged by when a fetch finished, so an $SPX
    fetch begun at 16:14:30 (options still trading) and finished at 16:15:10 became the 16:15
    close capture. A round is written for the window it began in."""
    clock = {"times": iter([])}
    daemon, sweep, published, client = _sweep(tmp_path, schwab, lambda: next(clock["times"]))
    clock["times"] = itertools.repeat(_ts("2026-09-30 16:00:30"))
    _rotate(daemon, sweep, published, client)              # the 16:00 window's capture
    clock["times"] = itertools.chain([_ts("2026-09-30 16:14:30")] * 2,      # the rotation and round begin
                                     itertools.repeat(_ts("2026-09-30 16:15:10")))
    _rotate(daemon, sweep, published, client)              # begun 16:14:30, in at 16:15:10
    with sqlite3.connect(tmp_path / "ed_console.db") as c:
        assert [_et(r[0]) for r in c.execute("SELECT DISTINCT ts_utc FROM complete_chain_captures")] \
            == ["2026-09-30 16:00"]


def test_a_failed_history_write_is_not_a_failed_chain_and_the_window_tries_again(tmp_path, schwab):
    """2026-10-01 audit: a history write that failed after the chain was delivered was published
    to the console as a failed chain. The history table refuses the write (a NOT NULL column the
    writer does not fill); once it takes writes, the same window's next chain is written."""
    db = tmp_path / "ed_console.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE complete_chain_captures (ticker TEXT NOT NULL, expiry TEXT NOT NULL, "
                     "ts_utc REAL NOT NULL, spot REAL, n_contracts INTEGER NOT NULL, "
                     "completeness_basis TEXT NOT NULL, chain_json TEXT NOT NULL, source TEXT NOT NULL, "
                     "created_at TEXT, refused TEXT NOT NULL, PRIMARY KEY (ticker, expiry, ts_utc))")
    clock = {"now": _ts("2026-09-30 15:31:57")}
    daemon, sweep, published, client = _sweep(tmp_path, schwab, lambda: clock["now"])
    assert _rotate(daemon, sweep, published, client) == {"SPY"}
    assert all("failed" not in m for _t, m in published)
    with sqlite3.connect(db) as conn:
        conn.execute("DROP TABLE complete_chain_captures")
    clock["now"] += 120                                    # the same window's next round
    _rotate(daemon, sweep, published, client)
    with sqlite3.connect(db) as c:
        assert c.execute("SELECT COUNT(DISTINCT ts_utc) FROM complete_chain_captures").fetchone()[0] == 1


def test_the_daemon_task_stops_when_told(tmp_path):
    daemon = capture.Daemon(MessageBus(), HealthRegistry())

    async def go():
        stop = asyncio.Event()
        task = asyncio.create_task(capture.run_chains(daemon, "unused.db", lambda: None, stop))
        await asyncio.sleep(0)
        stop.set()
        await asyncio.wait_for(task, timeout=5)
        return task
    task = asyncio.run(go())
    assert task.done() and task.exception() is None


def test_a_console_that_connects_later_starts_with_every_contracts_record():
    """MRVL's round on the daemon's bus (2,432 contracts): a reader that subscribes after it
    (docs/DATA_FLOW.md §2 D3, a console connecting) starts with every contract's one record, then
    the round, never part of it."""
    bus = MessageBus()
    daemon_round(bus, "MRVL", _MRVL, _ts("2026-09-30 15:31:57"))

    async def go():
        late = bus.subscribe("", policy=LATEST)
        got = []
        while len(got) < len(_MRVL) + 1:
            got.append(await asyncio.wait_for(late.get(), timeout=5))
        return got
    got = asyncio.run(go())
    records = {rec["symbol"]: rec["fields"] for topic, rec in got if topic.startswith("contract.")}
    assert sorted(records) == sorted(c["symbol"] for c in _MRVL)
    assert all(records[c["symbol"]]["strikePrice"] == c["strikePrice"] for c in _MRVL)
    assert got[-1][0] == "chain.MRVL", "the round after its records"


def test_the_reader_gives_the_last_full_capture_of_each_day(tmp_path):
    db = tmp_path / "ed_console.db"
    # institutional-synthetic-ok: the reader returns stored contracts verbatim; none is priced.
    ct = lambda e: {"symbol": f"ZZ {e}", "expirationDate": f"{e}T20:00:00.000+00:00"}
    def put(when, spot, expiries, basis=cch.CAPTURE_BASIS):
        for e in expiries:
            cch.persist_complete_chain_capture(
                db, ticker="ZZ", expiry=e, contracts=[ct(e)], spot=spot,
                completeness_basis=basis, ts_utc=_ts(when))
    put("2026-09-24 15:30", 10.0, ["2030-01-04"])
    put("2026-09-24 16:00", 11.0, ["2030-01-04", "2030-01-11"])       # Thursday's last
    put("2026-09-25 16:00", 12.0, ["2030-01-04", "2030-01-11"])       # Friday's last
    put("2026-09-25 16:05", 99.0, ["2030-01-04"], basis="strike_range=ALL")  # old row
    caps = cch.last_capture_per_day(db, "ZZ", 2)
    assert [(c["et_date"], c["spot"], len(c["contracts"])) for c in caps] == [
        ("2026-09-25", 12.0, 2), ("2026-09-24", 11.0, 2)]
    prior = cch.last_capture_per_day(db, "ZZ", 1, before_et_date="2026-09-25")
    assert [(c["et_date"], c["spot"]) for c in prior] == [("2026-09-24", 11.0)]


def test_a_partial_morning_capture_is_never_the_prior_day(tmp_path):
    """2026-09-28: the only 09-25 captures were the partial morning chains (expiries to 37 days),
    so the forces diffed Monday's full chain against them and every later expiry read as new open
    interest (SPY: +1.4M below and above spot in one day). Only full captures are read: with no
    full prior day the forces are absent with their reason."""
    import server
    db = tmp_path / "ed_console.db"
    # institutional-synthetic-ok: the reader returns stored contracts verbatim; none is priced.
    ct = {"symbol": "ZZ 2030-01-04", "expirationDate": "2030-01-04T20:00:00.000+00:00"}
    cch.persist_complete_chain_capture(db, ticker="ZZ", expiry="2030-01-04", contracts=[ct],
                                       spot=5.0, completeness_basis="expiries_to_37_days_morning",
                                       ts_utc=_ts("2026-09-25 10:00"))
    cch.persist_complete_chain_capture(db, ticker="ZZ", expiry="2030-01-04", contracts=[ct],
                                       spot=5.0, completeness_basis=cch.CAPTURE_BASIS,
                                       ts_utc=_ts("2026-09-28 16:15"))
    caps = cch.last_capture_per_day(db, "ZZ", 2)
    assert [(c["et_date"], c["basis"]) for c in caps] == [("2026-09-28", cch.CAPTURE_BASIS)]
    forces = server._forces_from_captures("ZZ", caps)
    assert forces["available"] is False and "fewer than 2 market days" in forces["reason"]
