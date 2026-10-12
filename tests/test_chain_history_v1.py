"""The daemon's chain sweep (DATA_FLOW decisions 1 and 7): the one fetcher of every watchlist ticker's
chain, what it hands the console, and the chain history it writes.

Real data: SPY's 2026-11-20 contracts from the capture daemon's full-chain capture of 2026-09-30
15:31:57 ET and Schwab's quotes for every one of them, served by Schwab's host as a local server
(tests/schwab_rest_standin.py) to the real sweep and client; MRVL's full chain as Schwab sent it
(tests/fixtures/real_mrvl_full_chain_vs_strike_window.json, 2,432 contracts, several parts)."""
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
from app.options.order_flow import streaming as ofs
from json_blob_codec import decode_json_blob
from stream_spine import LATEST, CaptureWriter, HealthRegistry, MessageBus
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
    """The daemon's sweep over SPY on `clock`, with the daemon's client of the stand-in host."""
    sqlite3.connect(tmp_path / "ed_console.db").close()          # the daemon's database exists
    published: list = []
    sweep = cch.ChainSweep(tmp_path / "ed_console.db", ["SPY"],
                           lambda topic, msg: published.append((topic, msg)), clock=clock,
                           failures=CaptureWriter(tmp_path / "stream_capture.db"),
                           streamed=lambda symbol: None)
    client = schwab.client(tmp_path)
    return sweep, published, (lambda: client)


def _rotate(sweep, client) -> "set[str]":
    return sweep.rotation(client, ["SPY"], threading.Event())


def _assembled(published):
    ofs._chain_parts.clear()
    return [o for _t, msg in published for o in ofs.assemble_chain_part(json.loads(msg["frame"])["msg"])]


def _parts(ts: float):
    """MRVL's chain as the sweep publishes it: 5 parts of CHAIN_PART_CONTRACTS."""
    return cch.chain_messages("MRVL", _MRVL, ts)


def test_a_chain_reaches_the_console_whole_in_parts():
    published = _parts(_ts("2026-09-30 15:31:57"))
    assert [m["part"] for _t, m in published] == [0, 1, 2, 3, 4]           # 2,432 contracts
    (tk, contracts, ts, reason), = _assembled(published)
    assert (tk, ts, reason) == ("MRVL", _ts("2026-09-30 15:31:57"), None)
    assert sorted(c["symbol"] for c in contracts) == sorted(c["symbol"] for c in _MRVL)


def test_a_chain_missing_a_part_is_never_priced_and_says_why():
    published = _parts(_ts("2026-09-30 15:31:57"))
    del published[2]                                     # one part lost on the way
    published += _parts(_ts("2026-09-30 15:35:57"))      # the next chain begins
    first, second = _assembled(published)
    assert first[1] is None and "arrived with 4 of its 5 parts" in first[3]
    assert second[1] is not None and second[3] is None


def test_a_chain_missing_a_part_is_reported_even_when_the_next_chain_is_one_part():
    """2026-10-01 audit: when the next chain completed in its first part, the report of the
    incomplete one before it was lost."""
    early = _parts(_ts("2026-09-30 15:31:57"))[:2]       # two of five parts arrived
    one_part = cch.chain_messages("MRVL", _MRVL[:cch.CHAIN_PART_CONTRACTS], _ts("2026-09-30 15:35:57"))
    first, second = _assembled(early + one_part)
    assert first[1] is None and "arrived with 2 of its 5 parts" in first[3]
    assert second[1] is not None and len(second[1]) == cch.CHAIN_PART_CONTRACTS


def test_a_chain_begun_before_the_console_connected_is_no_failure():
    """2026-10-01 audit: a console connecting mid-chain got its last parts only and reported the
    chain as arriving incomplete."""
    published = _parts(_ts("2026-09-30 15:31:57"))[2:]  # the console connected after part 1
    published += _parts(_ts("2026-09-30 15:35:57"))
    (tk, contracts, _ts_, reason), = _assembled(published)
    assert contracts is not None and reason is None and len(contracts) == len(_MRVL)


def test_a_refused_chain_reaches_the_console_as_schwabs_answer(tmp_path, schwab):
    schwab.refuse_chain = {"SPY"}
    sweep, published, client = _sweep(tmp_path, schwab, lambda: _ts("2026-09-30 15:31:57"))
    assert _rotate(sweep, client) == set()
    (tk, contracts, _ts_, reason), = _assembled(published)
    assert tk == "SPY" and contracts is None and reason == "chain for 2026-11-20 returned HTTP 502"


def test_the_history_is_written_once_per_capture_window_and_never_outside_one(tmp_path, schwab):
    clock = {"now": 0.0}
    sweep, _published, client = _sweep(tmp_path, schwab, lambda: clock["now"])
    for at in ("2026-09-30 15:31:57", "2026-09-30 15:35:00",      # the 15:30 window, twice
               "2026-09-30 16:01:00",                             # the 16:00 window
               "2026-09-30 17:00:00"):                            # after the close capture's window
        clock["now"] = _ts(at)
        assert _rotate(sweep, client) == {"SPY"}
    with sqlite3.connect(tmp_path / "ed_console.db") as c:
        rows = c.execute("SELECT ts_utc, expiry, spot, n_contracts, chain_json FROM complete_chain_captures "
                         "ORDER BY ts_utc").fetchall()
    assert [(_et(r[0]), r[1], r[2], r[3]) for r in rows] == [
        ("2026-09-30 15:31", "2026-11-20", 766.31, 442), ("2026-09-30 16:01", "2026-11-20", 766.31, 442)]
    assert isinstance(rows[0][4], bytes), "stored compressed"
    stored = {c["symbol"]: c for c in decode_json_blob(rows[0][4])}
    assert all(stored[s]["gamma"] == q["gamma"] for s, q in _QUOTED.items()), "the quote's gamma is stored"


def test_an_added_ticker_joins_the_rotation_in_its_turn(tmp_path, schwab):
    """Operator 2026-10-06: every ticker the same, in one rotation; none has priority. TSLA added
    to the watchlist beside SPY: SPY first, then TSLA, in sorted order."""
    sweep, published, client = _sweep(tmp_path, schwab, lambda: _ts("2026-08-28 09:05"))
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
    close capture. A chain is written for the window it began in."""
    clock = {"times": iter([])}
    sweep, _published, client = _sweep(tmp_path, schwab, lambda: next(clock["times"]))
    clock["times"] = itertools.repeat(_ts("2026-09-30 16:00:30"))
    _rotate(sweep, client)                                 # the 16:00 window's capture
    clock["times"] = itertools.chain([_ts("2026-09-30 16:14:30")] * 2,      # the rotation and chain begin
                                     itertools.repeat(_ts("2026-09-30 16:15:10")))
    _rotate(sweep, client)                                 # begun 16:14:30, delivered 16:15:10
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
    sweep, published, client = _sweep(tmp_path, schwab, lambda: clock["now"])
    assert _rotate(sweep, client) == {"SPY"}
    assert all("failed" not in m for _t, m in published)
    (tk, contracts, _t, reason), = _assembled(published)
    assert contracts is not None and reason is None
    with sqlite3.connect(db) as conn:
        conn.execute("DROP TABLE complete_chain_captures")
    clock["now"] += 120                                    # the same window's next chain
    _rotate(sweep, client)
    with sqlite3.connect(db) as c:
        assert c.execute("SELECT COUNT(DISTINCT ts_utc) FROM complete_chain_captures").fetchone()[0] == 1


def test_the_daemon_task_stops_when_told(tmp_path):
    daemon = capture.Daemon(MessageBus(), HealthRegistry())

    async def go():
        stop = asyncio.Event()
        task = asyncio.create_task(capture.run_chains(
            daemon, "unused.db", lambda: None, stop,
            failures=CaptureWriter(tmp_path / "stream_capture.db")))
        await asyncio.sleep(0)
        stop.set()
        await asyncio.wait_for(task, timeout=5)
        return task
    task = asyncio.run(go())
    assert task.done() and task.exception() is None


def test_the_daemons_chain_is_the_current_record_whole_once_all_parts_are_in():
    """The sweep publishes a chain in parts on the daemon's bus; the chain becomes the ticker's
    current record only once every part is in, and a console that connects later starts with that
    whole chain (docs/DATA_FLOW.md §2 D3), every part in order -- never a partial one."""
    bus = MessageBus()

    async def go():
        sub = bus.subscribe("chain.", policy=LATEST)
        parts = _parts(_ts("2026-09-30 15:31:57"))
        for topic, msg in parts[:-1]:
            bus.publish(topic, msg)
        assert not sub.changed, "a partial chain is never current"
        bus.publish(*parts[-1])
        topic, record = await asyncio.wait_for(sub.get(), timeout=5)
        late = bus.subscribe("chain.", policy=LATEST)
        return topic, record, await asyncio.wait_for(late.get(), timeout=5)
    topic, record, (late_topic, late_record) = asyncio.run(go())
    assert topic == late_topic == "chain.MRVL"
    assert [m["part"] for m in record] == list(range(record[0]["parts"])) and len(record) > 1
    assert [m["part"] for m in late_record] == list(range(late_record[0]["parts"]))
    (tk, contracts, _ts_, reason), = _assembled([(late_topic, m) for m in late_record])
    assert tk == "MRVL" and reason is None
    assert sorted(c["symbol"] for c in contracts) == sorted(c["symbol"] for c in _MRVL)


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
