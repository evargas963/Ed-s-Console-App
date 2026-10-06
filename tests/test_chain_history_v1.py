"""The daemon's chain sweep (DATA_FLOW decisions 1 and 7): the one fetcher of every board ticker's
chain, what it hands the console, and the chain history it writes.

Real data (tests/fixtures/real_spy_2026_11_20_chain_and_quotes.json): SPY's 2026-11-20 contracts
from the capture daemon's full-chain capture of 2026-09-30 15:31:57 ET, and Schwab's quotes for
every one of them, and MRVL's full chain as Schwab sent it. Schwab's host is the only stand-in,
played locally (tests/test_data_path_rules_v1._LocalSchwab) for schwab-py's own client: it answers
the chain with the captured contracts and each quotes request with the recorded quotes. Nothing
is patched."""
from __future__ import annotations

import asyncio
import itertools
import json
import sqlite3
import time
from datetime import datetime
from pathlib import Path

import httpx
import pytest
from schwab.client import Client

import calibration.complete_chain_capture as cch
import schwab_client as sc
from app.options.order_flow import streaming as ofs
from json_blob_codec import decode_json_blob
from stream_spine import CaptureWriter
from tests.test_data_path_rules_v1 import _LocalSchwab, _spy_chain_payload
from time_et import ET

_FX = json.loads((Path(__file__).resolve().parent / "fixtures"
                  / "real_spy_2026_11_20_chain_and_quotes.json").read_text(encoding="utf-8"))
_QUOTED = {s: e["quote"] for q in _FX["quotes"] for s, e in q["reply"].items()}


def _ts(s: str) -> float:
    return datetime.fromisoformat(s).replace(tzinfo=ET).timestamp()


def _et(ts: float) -> str:
    return datetime.fromtimestamp(ts, ET).strftime("%Y-%m-%d %H:%M")


@pytest.mark.parametrize("now, slot", [
    ("2026-09-28 08:00", None),                 # Monday before the open: nothing written
    ("2026-09-28 09:30", "2026-09-28 09:30"),
    ("2026-09-28 09:59", "2026-09-28 09:30"),
    ("2026-09-28 15:45", "2026-09-28 15:30"),
    ("2026-09-28 16:05", "2026-09-28 16:00"),
    ("2026-09-28 16:20", "2026-09-28 16:15"),   # the close capture: options trade to 16:15
    ("2026-09-28 16:46", None),                 # nothing after the close capture's window
    ("2026-09-26 12:00", None),                 # Saturday
    ("2026-11-26 12:00", None),                 # Thanksgiving
    ("2026-11-27 13:10", "2026-11-27 13:00"),   # early close
    ("2026-11-27 13:20", "2026-11-27 13:15"),   # early close: the close capture at 13:15
    ("2026-11-02 09:31", "2026-11-02 09:30"),   # after the DST change, still 9:30 ET
])
def test_the_capture_window_a_fetch_is_written_for(now, slot):
    got = cch.capture_slot(_ts(now))
    assert (_et(got) if got is not None else None) == slot


def test_fifteen_capture_windows_on_a_full_day():
    slots = {cch.capture_slot(_ts(f"2026-09-28 {h:02d}:{m:02d}"))
             for h in range(0, 24) for m in range(0, 60)} - {None}
    assert sorted(_et(s)[11:] for s in slots) == [
        f"{h:02d}:{m:02d}" for h in range(9, 17) for m in (0, 30)
        if (9, 30) <= (h, m) <= (16, 0)] + ["16:15"]


#: MRVL's full chain as Schwab sent it (2,432 contracts: five parts of CHAIN_PART_CONTRACTS, 500);
#: its quotes are not captured, so its contracts carry no Greeks from the quotes
_MRVL = json.loads((Path(__file__).resolve().parent / "fixtures"
                    / "real_mrvl_full_chain_vs_strike_window.json").read_text(encoding="utf-8"))["full"]
_MRVL_N = len(sc.flatten_chain_contracts(_MRVL))


@pytest.fixture
def schwab():
    """Schwab's host, played locally (tests/test_data_path_rules_v1._LocalSchwab: the captured
    SPY chain and its quotes, or another captured chain), and the daemon's one client on it:
    schwab-py's own Client, as capture.one_schwab_client hands the sweep."""
    host = _LocalSchwab()
    host.client = Client("k", httpx.Client(transport=host.transport), enforce_enums=False)
    yield host
    host.close()


def _chain_gets(host) -> int:
    return sum(1 for _t, method, path, _a in host.requests if method == "GET" and path == "/marketdata/v1/chains")


def _sweep(tmp_path, board, at):
    sqlite3.connect(tmp_path / "ed_console.db").close()          # the daemon's database exists
    published: list = []
    clock = {"now": _ts(at)}
    sweep = cch.ChainSweep(tmp_path / "ed_console.db", board,
                           lambda topic, msg: published.append((topic, msg)), clock=lambda: clock["now"],
                           failures=CaptureWriter(tmp_path / "stream_capture.db"))
    return sweep, published, clock


def _assembled(published):
    ofs._chain_parts.clear()
    return [o for _t, msg in published for o in ofs.assemble_chain_part(json.loads(msg["frame"])["msg"])]


def test_each_fetch_reaches_the_console_whole_in_parts_with_schwabs_exact_greeks(tmp_path, schwab):
    """SPY's chain reaches the console whole, each contract with its quote's exact gamma; MRVL's
    full chain reaches it whole in its five parts, in order."""
    sweep, published, _clock = _sweep(tmp_path, ["SPY"], "2026-09-30 15:31:57")
    sweep.fetch_one(schwab.client, "SPY")
    (tk, contracts, ts, reason), = _assembled(published)
    assert (tk, ts, reason) == ("SPY", _ts("2026-09-30 15:31:57"), None)
    assert sorted(c["symbol"] for c in contracts) == sorted(c["symbol"] for c in _FX["chain"])
    assert all(c["gamma"] == _QUOTED[c["symbol"]]["gamma"] for c in contracts)
    published.clear()
    schwab.chain = _MRVL
    sweep.fetch_one(schwab.client, "MRVL")
    assert [m["part"] for _t, m in published] == [0, 1, 2, 3, 4]           # 2,432 contracts
    (tk, contracts, ts, reason), = _assembled(published)
    assert (tk, ts, reason) == ("MRVL", _ts("2026-09-30 15:31:57"), None)
    assert sorted(c["symbol"] for c in contracts) == sorted(c["symbol"] for c in sc.flatten_chain_contracts(_MRVL))


def test_a_chain_missing_a_part_is_never_priced_and_says_why(tmp_path, schwab):
    schwab.chain = _MRVL                                 # five parts
    sweep, published, clock = _sweep(tmp_path, ["MRVL"], "2026-09-30 15:31:57")
    sweep.fetch_one(schwab.client, "MRVL")
    del published[2]                                     # one part lost on the way
    clock["now"] += 240
    sweep.fetch_one(schwab.client, "MRVL")               # the next chain begins
    first, second = _assembled(published)
    assert first[1] is None and "arrived with 4 of its 5 parts" in first[3]
    assert second[1] is not None and second[3] is None


def test_a_chain_missing_a_part_is_reported_even_when_the_next_chain_is_one_part(tmp_path, schwab):
    """2026-10-01 audit: when the next chain completed in its first part, the report of the
    incomplete one before it was lost. STAND-IN: one ticker's two chains are MRVL's full chain
    (five parts) and then SPY's captured chain (442 contracts, one part), both as Schwab sent them."""
    schwab.chain = _MRVL
    sweep, published, clock = _sweep(tmp_path, ["MRVL"], "2026-09-30 15:31:57")
    sweep.fetch_one(schwab.client, "MRVL")
    del published[2:]                                    # two of five parts arrived
    schwab.chain = _spy_chain_payload()
    clock["now"] += 240
    sweep.fetch_one(schwab.client, "MRVL")               # the next chain: one part
    first, second = _assembled(published)
    assert first[1] is None and "arrived with 2 of its 5 parts" in first[3]
    assert second[1] is not None and len(second[1]) == 442


def test_a_chain_begun_before_the_console_connected_is_no_failure(tmp_path, schwab):
    """2026-10-01 audit: a console connecting mid-chain got its last parts only and reported the
    chain as arriving incomplete."""
    schwab.chain = _MRVL                                 # five parts
    sweep, published, clock = _sweep(tmp_path, ["MRVL"], "2026-09-30 15:31:57")
    sweep.fetch_one(schwab.client, "MRVL")
    del published[:2]                                    # the console connected after part 1
    clock["now"] += 240
    sweep.fetch_one(schwab.client, "MRVL")
    (tk, contracts, _ts, reason), = _assembled(published)
    assert contracts is not None and reason is None and len(contracts) == _MRVL_N


def test_a_refused_chain_reaches_the_console_as_schwabs_answer(tmp_path, schwab):
    schwab.refusals[("/marketdata/v1/chains", "SPY")] = 400          # induced
    sweep, published, _clock = _sweep(tmp_path, ["SPY"], "2026-09-30 15:31:57")
    sweep.fetch_one(schwab.client, "SPY")
    (tk, contracts, _ts_, reason), = _assembled(published)
    assert tk == "SPY" and contracts is None and "HTTP 400" in reason


def test_a_429_pauses_every_chain_request(tmp_path, schwab):
    schwab.refusals[("/marketdata/v1/quotes", None)] = 429           # induced
    sweep, _published, _clock = _sweep(tmp_path, ["SPY"], "2026-09-30 15:31:57")
    sweep.fetch_one(schwab.client, "SPY")
    at = _ts("2026-09-30 15:31:57")
    assert sweep._next(at + cch.RATE_LIMITED_PAUSE_SEC - 0.01) is None, "a chain was taken during the pause"
    assert sweep._next(at + cch.RATE_LIMITED_PAUSE_SEC) == "SPY"


def test_the_history_is_written_once_per_capture_window_and_never_outside_one(tmp_path, schwab):
    db = tmp_path / "ed_console.db"
    sweep, _published, clock = _sweep(tmp_path, ["SPY"], "2026-09-30 15:31:57")
    for at in ("2026-09-30 15:31:57", "2026-09-30 15:35:00",      # the 15:30 window, twice
               "2026-09-30 16:01:00",                             # the 16:00 window
               "2026-09-30 17:00:00"):                            # after the close capture's window
        clock["now"] = _ts(at)
        sweep.fetch_one(schwab.client, "SPY")
    with sqlite3.connect(db) as c:
        rows = c.execute("SELECT ts_utc, expiry, spot, n_contracts, chain_json FROM complete_chain_captures "
                         "ORDER BY ts_utc").fetchall()
    assert [(_et(r[0]), r[1], r[2], r[3]) for r in rows] == [
        ("2026-09-30 15:31", "2026-11-20", 766.31, 442), ("2026-09-30 16:01", "2026-11-20", 766.31, 442)]
    assert isinstance(rows[0][4], bytes), "stored compressed"
    stored = {c["symbol"]: c for c in decode_json_blob(rows[0][4])}
    assert all(stored[s]["gamma"] == q["gamma"] for s, q in _QUOTED.items()), "the quote's gamma is stored"


def _fetched(sweep, now):
    """The ticker a worker takes next, its fetch then done (the worker's `finally`)."""
    tk = sweep._next(now)
    sweep._fetching.discard(tk)
    return tk


def test_the_sweep_fetches_every_board_ticker_in_turn(tmp_path):
    board = ["AAA", "BBB", "CCC"]
    sweep, _published, clock = _sweep(tmp_path, board, "2026-09-30 15:31:57")
    order = [_fetched(sweep, clock["now"]) for _ in range(3)]
    order += [_fetched(sweep, clock["now"] + 200)]
    assert order == ["AAA", "BBB", "CCC", "AAA"]
    assert sweep.round_sec == 200                       # the round it delivered


def test_the_active_ticker_is_fetched_back_to_back_ahead_of_the_board(tmp_path):
    """Operator 2026-10-01: the ticker on screen is fetched first and again the moment its last
    fetch ends, on or off the board; the other workers go round the board."""
    board = ["AAA", "BBB", "CCC"]
    sweep, _published, clock = _sweep(tmp_path, board, "2026-09-30 15:31:57")
    sweep.set_active("OFF")                             # not on the board
    assert sweep._next(clock["now"]) == "OFF"           # a worker is fetching OFF
    assert sweep._next(clock["now"]) == "AAA"           # never OFF twice at once
    assert sweep._next(clock["now"]) == "BBB"
    sweep._fetching.discard("OFF")                      # OFF's fetch ends
    assert sweep._next(clock["now"]) == "OFF"           # and it is fetched again at once
    sweep._fetching.discard("AAA")
    sweep._fetching.discard("BBB")
    assert sweep._next(clock["now"]) == "CCC"
    sweep._fetching.discard("CCC")
    assert sweep._next(clock["now"] + 30) == "AAA", "the round restarts while OFF is in flight"


def test_an_idle_worker_takes_a_new_active_ticker_at_once(tmp_path, schwab):
    """2026-10-01 audit: an idle worker slept up to 1 s before it looked again, so a ticker put
    on screen waited for it."""
    import threading
    sweep, _published, _clock = _sweep(tmp_path, [], "2026-09-30 15:31:57")
    halt = threading.Event()
    worker = threading.Thread(target=sweep.work, args=(lambda: schwab.client, halt), daemon=True)
    worker.start()
    time.sleep(0.1)                                     # the worker is idle: nothing to fetch
    assert _chain_gets(schwab) == 0
    put = time.monotonic()
    sweep.set_active("SPY")
    while _chain_gets(schwab) == 0 and time.monotonic() - put < 5:
        time.sleep(0.005)
    took = time.monotonic() - put
    halt.set()
    worker.join(5)
    assert _chain_gets(schwab) > 0 and took < 0.5, took


def test_no_ticker_is_fetched_twice_at_once(tmp_path):
    """2026-10-01 audit: two workers could fetch one ticker at the same time (a one-ticker
    board, or the active one)."""
    board = ["AAA", "BBB"]
    sweep, _published, clock = _sweep(tmp_path, board, "2026-09-30 15:31:57")
    assert sweep._next(clock["now"]) == "AAA"           # a worker is fetching AAA
    sweep.set_active("AAA")                             # AAA put on screen while in flight
    assert sweep._next(clock["now"]) == "BBB"           # not AAA a second time
    assert sweep._next(clock["now"] + 9) is None        # the round holds nothing else to take
    assert sweep.round_sec is None, "the round ends when its last fetch is done, not when handed out"


def test_a_fetch_begun_before_the_close_capture_is_not_the_close_capture(tmp_path, schwab):
    """2026-10-01 audit: the capture window was judged by when a fetch finished, so an $SPX
    fetch begun at 16:14:30 (options still trading) and finished at 16:15:10 became the 16:15
    close capture. A fetch is written for the window it began in."""
    db = tmp_path / "ed_console.db"
    sweep, _published, _clock = _sweep(tmp_path, ["SPY"], "2026-09-30 16:00:30")
    assert sweep.fetch_one(schwab.client, "SPY")           # the 16:00 window's capture
    times = itertools.chain([_ts("2026-09-30 16:14:30")], itertools.repeat(_ts("2026-09-30 16:15:10")))
    sweep.clock = lambda: next(times)
    assert sweep.fetch_one(schwab.client, "SPY")           # begun 16:14:30, received 16:15:10
    with sqlite3.connect(db) as c:
        assert [_et(r[0]) for r in c.execute("SELECT DISTINCT ts_utc FROM complete_chain_captures")] \
            == ["2026-09-30 16:00"]


def test_a_failed_history_write_is_not_a_failed_chain_and_the_window_tries_again(tmp_path, schwab):
    """2026-10-01 audit: a history write that failed after the chain was delivered was published
    to the console as a failed chain. INDUCED: the database path is a directory, so SQLite
    cannot open it; then it is a database again."""
    db = tmp_path / "ed_console.db"
    sweep, published, clock = _sweep(tmp_path, ["SPY"], "2026-09-30 15:31:57")
    db.unlink()
    db.mkdir()                                             # the history write fails
    sweep.fetch_one(schwab.client, "SPY")
    assert all("failed" not in m for _t, m in published)
    (tk, contracts, _t, reason), = _assembled(published)
    assert contracts is not None and reason is None
    db.rmdir()                                             # the database can be written again
    clock["now"] += 120                                    # the same window's next fetch
    sweep.fetch_one(schwab.client, "SPY")
    with sqlite3.connect(db) as c:
        assert c.execute("SELECT COUNT(DISTINCT ts_utc) FROM complete_chain_captures").fetchone()[0] == 1


def test_a_failing_schwab_client_is_tried_once_per_ticker_per_wait_instead_of_spinning(tmp_path):
    """A fetch that raises makes that ticker alone wait FAILED_PAUSE_SEC (5 s; operator
    2026-10-06): two workers whose client cannot be built (STAND-IN: the build raises what a
    refused token raises) try each board ticker once in the first second, never again and again
    around the board, and each failure says why."""
    import threading
    built, published = [], []

    def make_client():
        built.append(1)
        raise ConnectionError("Refresh token is invalid, expired or revoked")
    sweep = cch.ChainSweep(tmp_path / "ed_console.db", ["SPY", "QQQ", "IWM"],
                           lambda topic, msg: published.append(msg),
                           failures=CaptureWriter(tmp_path / "stream_capture.db"))
    halt = threading.Event()
    workers = [threading.Thread(target=sweep.work, args=(make_client, halt), daemon=True) for _ in range(2)]
    for w in workers:
        w.start()
    halt.wait(1.0)
    halt.set()
    for w in workers:
        w.join(10)
    assert len(built) == 3, len(built)                    # one try per ticker per wait
    assert sorted(m["ticker"] for m in published) == ["IWM", "QQQ", "SPY"]
    assert {m["failed"] for m in published} == {"ConnectionError: Refresh token is invalid, expired or revoked"}


def test_the_daemon_task_stops_when_told(tmp_path):
    from app.market_data.schwab.streaming import capture

    class _Daemon:
        board, chains = [], None
        bus = None
        active = None

    async def go():
        stop = asyncio.Event()
        task = asyncio.create_task(capture.run_chains(
            _Daemon(), "unused.db", lambda: None, stop,
            failures=CaptureWriter(tmp_path / "stream_capture.db")))
        await asyncio.sleep(0)
        stop.set()
        await asyncio.wait_for(task, timeout=5)
        return task
    task = asyncio.run(go())
    assert task.done() and task.exception() is None


def test_the_daemons_chain_is_the_current_record_whole_once_all_parts_are_in(tmp_path):
    """The daemon's chain sweep publishes a fetch in parts on its bus; the chain becomes the
    ticker's current record only once every part is in, and a console that connects later starts
    with that whole chain (docs/DATA_FLOW.md §2 D3), every part in order -- never a partial one.
    Real data: MRVL's full chain as Schwab sent it (tests/fixtures/real_mrvl_full_chain_vs_strike_window.json,
    2,432 contracts, so several parts of CHAIN_PART_CONTRACTS), from the local stand-in for
    Schwab's host (test_data_path_rules_v1._LocalSchwab), whose quotes for MRVL are not captured."""
    import httpx
    from schwab.client import Client

    from app.market_data.schwab.streaming import capture
    from stream_spine import LATEST, MessageBus
    from tests.test_data_path_rules_v1 import _LocalSchwab
    full = json.loads((Path(__file__).resolve().parent / "fixtures"
                       / "real_mrvl_full_chain_vs_strike_window.json").read_text(encoding="utf-8"))["full"]
    sqlite3.connect(tmp_path / "ed_console.db").close()
    host = _LocalSchwab(chain=full)
    client = Client("k", httpx.Client(transport=host.transport), enforce_enums=False)

    class _Daemon:
        board, chains, active = ["MRVL"], None, None
        bus = MessageBus()

    async def go():
        stop = asyncio.Event()
        sub = _Daemon.bus.subscribe("chain.", policy=LATEST)
        task = asyncio.create_task(capture.run_chains(
            _Daemon(), tmp_path / "ed_console.db", lambda: client, stop,
            failures=CaptureWriter(tmp_path / "stream_capture.db")))
        topic, record = await asyncio.wait_for(sub.get(), timeout=30)
        stop.set()
        await asyncio.wait_for(task, timeout=30)
        late = _Daemon.bus.subscribe("chain.", policy=LATEST)
        return topic, record, await asyncio.wait_for(late.get(), timeout=5)
    try:
        topic, record, (late_topic, late_record) = asyncio.run(go())
    finally:
        host.close()
    assert topic == late_topic == "chain.MRVL"
    assert [m["part"] for m in record] == list(range(record[0]["parts"])) and len(record) > 1
    assert [m["part"] for m in late_record] == list(range(late_record[0]["parts"]))
    (tk, contracts, _ts_, reason), = _assembled([(late_topic, m) for m in late_record])
    assert tk == "MRVL" and reason is None
    assert sorted(c["symbol"] for c in contracts) == sorted(c["symbol"] for c in sc.flatten_chain_contracts(full))


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
