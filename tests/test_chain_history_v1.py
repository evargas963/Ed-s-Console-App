"""The daemon's chain sweep (DATA_FLOW decisions 1 and 7).

The one fetcher of every watchlist ticker's chain, what it hands the console, and the chain
history it writes.

Real data: SPY's 2026-11-20 contracts from the capture daemon's full-chain capture of 2026-09-30
15:31:57 ET and Schwab's quotes for every one of them, served by Schwab's host as a local server
(tests/schwab_rest_standin.py) to the real sweep and client; MRVL's full chain as Schwab sent it
(tests/fixtures/real_mrvl_full_chain_vs_strike_window.json, 2,432 contracts, several parts).
"""

from __future__ import annotations

import asyncio
import itertools
import json
import sqlite3
import threading
from contextlib import closing
from datetime import datetime
from pathlib import Path

import pytest

import calibration.complete_chain_capture as cch
import server
from app.market_data.schwab.streaming import capture
from app.options.order_flow import streaming as ofs
from feed import chain_sweep as cs
from feed import schwab_client as sc
from json_blob_codec import decode_json_blob, decode_text_blob
from option_contract import read_chain
from stream_spine import LATEST, CaptureWriter, HealthRegistry, MessageBus
from tests.capture_store import store_capture
from tests.schwab_rest_standin import CHAIN, QUOTES, SPY_QUOTES, LocalSchwab
from tests.shared_helpers import et_ts
from time_et import ET

_QUOTED = {s: e["quote"] for s, e in SPY_QUOTES.items()}
_MRVL = sc.flatten_chain_contracts(
    json.loads(
        (
            Path(__file__).resolve().parent
            / "fixtures"
            / "real_mrvl_full_chain_vs_strike_window.json"
        ).read_text(encoding="utf-8")
    )["full"]
)


def _et(ts: float) -> str:
    return datetime.fromtimestamp(ts, ET).strftime("%Y-%m-%d %H:%M")


@pytest.mark.parametrize(
    "ticker, now, slot",
    [
        ("MRVL", "2026-10-05 08:00", None),  # Monday before the open: nothing written
        ("MRVL", "2026-10-05 09:30", None),  # in the session: the chains are live, none stored
        ("MRVL", "2026-10-05 15:59", None),
        ("MRVL", "2026-10-05 16:00", "2026-10-05 16:00"),  # the equity options' close
        ("MRVL", "2026-10-05 16:05", "2026-10-05 16:00"),
        ("MRVL", "2026-10-05 23:59", "2026-10-05 16:00"),  # still that day's close values
        ("$SPX", "2026-10-05 16:05", None),  # index options trade to 16:15
        ("$SPX", "2026-10-05 16:20", "2026-10-05 16:15"),  # the index options' close
        ("MRVL", "2026-10-10 12:00", None),  # Saturday: Schwab sends no session
        ("MRVL", "2026-11-26 12:00", None),  # Thanksgiving: Schwab says closed
        ("MRVL", "2026-11-27 13:10", "2026-11-27 13:00"),  # early close: Schwab's EQO 13:00
        ("$SPX", "2026-11-27 13:10", None),
        ("$SPX", "2026-11-27 13:20", "2026-11-27 13:15"),  # and its IND close 13:15
        ("MRVL", "2026-11-02 16:01", "2026-11-02 16:00"),  # after the DST change, still ET
    ],
)
def test_the_close_a_fetch_is_the_capture_of(ticker, now, slot):
    """A ticker's capture is its own option close, as Schwab's /markets sent the day's session.

    tests/conftest.py holds the answers captured 2026-10-07.
    """
    got = cs.capture_slot(et_ts(now), ticker)
    assert (_et(got) if got is not None else None) == slot


@pytest.mark.parametrize("ticker, close", [("MRVL", "16:00"), ("$SPX", "16:15")])
def test_a_full_day_has_one_capture_its_option_close(ticker, close):
    """Operator 2026-11-18: "only keep what is absolutely needed": the close, once a day."""
    slots = {
        cs.capture_slot(et_ts(f"2026-10-05 {h:02d}:{m:02d}"), ticker)
        for h in range(0, 24)
        for m in range(0, 60)
    } - {None}
    assert [_et(s)[11:] for s in slots] == [close]


@pytest.fixture
def schwab():
    host = LocalSchwab()
    yield host
    host.close()


def _sweep(tmp_path, schwab, clock):
    """Run the daemon's sweep over SPY on `clock`, with the daemon's client of the stand-in host."""
    sqlite3.connect(tmp_path / "ed_console.db").close()  # the daemon's database exists
    published: list = []
    sweep = cs.ChainSweep(
        tmp_path / "ed_console.db",
        ["SPY"],
        lambda topic, msg: published.append((topic, msg)),
        clock=clock,
        failures=CaptureWriter(tmp_path / "ed_console.db"),  # the daemon's one database
        streamed=lambda _symbol: None,
    )
    client = schwab.client(tmp_path)
    return sweep, published, (lambda: client)


def _rotate(sweep, client) -> set[str]:
    return sweep.rotation(client, ["SPY"], threading.Event())


def _assembled(published):
    ofs._chain_parts.clear()
    return [o for _t, msg in published for o in ofs.assemble_chain_part(msg)]


def _parts(ts: float):
    """MRVL's chain as the sweep publishes it: 5 parts of CHAIN_PART_CONTRACTS.

    At no spot (a daemon holding no price).
    """
    return cs.chain_messages("MRVL", _MRVL, ts, None, None, False)


def test_a_chain_reaches_the_console_whole_in_parts():
    published = _parts(et_ts("2026-09-30 15:31:57"))
    assert [m["part"] for _t, m in published] == [0, 1, 2, 3, 4]  # 2,432 contracts
    ((tk, contracts, ts, reason, spot, capture),) = _assembled(published)
    assert (tk, ts, reason, spot) == ("MRVL", et_ts("2026-09-30 15:31:57"), None, (None, None))
    assert capture is False  # as published (_parts): not a capture
    assert sorted(c.symbol for c in contracts) == sorted(c["symbol"] for c in _MRVL)
    assert contracts == read_chain(_MRVL), "each contract as read once, in order"


def test_a_chain_missing_a_part_is_never_priced_and_says_why():
    published = _parts(et_ts("2026-09-30 15:31:57"))
    del published[2]  # one part lost on the way
    published += _parts(et_ts("2026-09-30 15:35:57"))  # the next chain begins
    first, second = _assembled(published)
    assert first[1] is None and "arrived with 4 of its 5 parts" in first[3]
    assert second[1] is not None and second[3] is None


def test_a_chain_missing_a_part_is_reported_even_when_the_next_chain_is_one_part():
    """2026-10-01 audit: the report of an incomplete chain was lost.

    It was lost when the next chain completed in its first part.
    """
    early = _parts(et_ts("2026-09-30 15:31:57"))[:2]  # two of five parts arrived
    one_part = cs.chain_messages(
        "MRVL", _MRVL[: cs.CHAIN_PART_CONTRACTS], et_ts("2026-09-30 15:35:57"), None, None, False
    )
    first, second = _assembled(early + one_part)
    assert first[1] is None and "arrived with 2 of its 5 parts" in first[3]
    assert second[1] is not None and len(second[1]) == cs.CHAIN_PART_CONTRACTS


def test_a_chain_begun_before_the_console_connected_is_no_failure():
    """2026-10-01 audit: a console connecting mid-chain got its last parts only.

    It reported the chain as arriving incomplete.
    """
    published = _parts(et_ts("2026-09-30 15:31:57"))[2:]  # the console connected after part 1
    published += _parts(et_ts("2026-09-30 15:35:57"))
    ((tk, contracts, _ts_, reason, _spot, _capture),) = _assembled(published)
    assert contracts is not None and reason is None and len(contracts) == len(_MRVL)


def test_a_refused_chain_reaches_the_console_as_schwabs_answer(tmp_path, schwab):
    schwab.refuse_chain = {"SPY"}
    sweep, published, client = _sweep(tmp_path, schwab, lambda: et_ts("2026-09-30 15:31:57"))
    assert _rotate(sweep, client) == set()
    ((tk, contracts, _ts_, reason, spot, capture),) = _assembled(published)
    assert (
        tk == "SPY"
        and contracts is None
        and spot is None
        and reason == "chain for 2026-11-20 returned HTTP 502"
        and capture is False
    )


def test_every_chains_and_quotes_answer_is_recorded_as_received(tmp_path, schwab):
    """Schwab's /chains and /quotes answers are recorded byte for byte (operator 2026-11-15).

    The sweep publishes each answer's body as received; the daemon's writer stores it
    (rest_chains_raw, rest_quotes_raw), and the capture keeps the expiry's /chains answer beside
    the chain the levels took (chains_answer). Each stored body decodes to the published text
    exactly, and that text is the stand-in host's answer: its contracts are the chain's.
    """
    # after SPY's option close (16:15 ET): the chain is the day's close capture
    sweep, published, client = _sweep(tmp_path, schwab, lambda: et_ts("2026-09-30 16:16:00"))
    assert _rotate(sweep, client) == {"SPY"}
    answers = [(t, m) for t, m in published if t in ("chainanswer.SPY", "quotesanswer")]
    writer = CaptureWriter(tmp_path / "stream_capture.db")
    for topic, msg in answers:
        writer.insert(topic, msg)
    with closing(sqlite3.connect(tmp_path / "stream_capture.db")) as c, c:
        chains = c.execute("SELECT symbol, expiry, status, body FROM rest_chains_raw").fetchall()
        quotes = c.execute("SELECT status, body FROM rest_quotes_raw").fetchall()
    with closing(sqlite3.connect(tmp_path / "ed_console.db")) as c, c:
        (kept,) = c.execute("SELECT chains_answer FROM complete_chain_captures").fetchall()
    sent = {m["expiry"]: m["body"] for t, m in answers if t == "chainanswer.SPY"}
    assert [(s, e, st, decode_text_blob(b)) for s, e, st, b in chains] == [
        ("SPY", e, 200, body) for e, body in sent.items()
    ]
    assert [(st, decode_text_blob(b)) for st, b in quotes] == [
        (m["status"], m["body"]) for t, m in answers if t == "quotesanswer"
    ] and quotes, "the /quotes answers are recorded"
    assert decode_text_blob(kept[0]) == sent["2026-11-20"]
    stored = {c["symbol"] for c in decode_json_blob(_stored_chain(tmp_path))}
    answered = sc.flatten_chain_contracts(json.loads(sent["2026-11-20"]))
    assert {c["symbol"] for c in answered} == stored


def _stored_chain(tmp_path) -> bytes:
    with closing(sqlite3.connect(tmp_path / "ed_console.db")) as c, c:
        return c.execute("SELECT chain_json FROM complete_chain_captures").fetchone()[0]


def test_the_history_is_written_once_a_day_at_the_close_and_never_in_the_session(tmp_path, schwab):
    """Chains in the session are live and never stored; the first after the close is (operator
    2026-11-18: "only keep what is absolutely needed")."""
    clock = {"now": 0.0}
    sweep, _published, client = _sweep(tmp_path, schwab, lambda: clock["now"])
    for at in (
        "2026-09-30 15:31:57",
        "2026-09-30 16:01:00",
        "2026-09-30 16:16:00",  # after SPY's option close, 16:15
    ):
        clock["now"] = et_ts(at)
        assert _rotate(sweep, client) == {"SPY"}
    with closing(sqlite3.connect(tmp_path / "ed_console.db")) as c, c:
        rows = c.execute(
            "SELECT ts_utc, expiry, spot, chain_json FROM complete_chain_captures ORDER BY ts_utc"
        ).fetchall()
    rows = [(*r[:3], len(decode_json_blob(r[3])), r[3]) for r in rows]
    assert [(_et(r[0]), r[1], r[2], r[3]) for r in rows] == [
        ("2026-09-30 16:16", "2026-11-20", 766.31, 442),
    ]
    assert isinstance(rows[0][4], bytes), "stored compressed"
    stored = {c["symbol"]: c for c in decode_json_blob(rows[0][4])}
    assert all(stored[s]["quote"] == q for s, q in _QUOTED.items()), (
        "Schwab's /quotes answer is stored as sent, its gamma in it"
    )
    read = {c.symbol: c for c in read_chain(stored.values())}
    assert all(read[s].gamma == q["gamma"] for s, q in _QUOTED.items()), (
        "the history's reader takes the quote's gamma"
    )


def test_schwabs_chains_answers_are_asked_every_five_minutes_and_its_quotes_every_chain(
    tmp_path, schwab
):
    """Operator 2026-11-12: "every five minutes should do" (an exchange may list a series intraday).

    Three chains of SPY in the regular session: 10:01, 10:04 and 10:07. The first asks /chains;
    the second, three minutes on, asks /chains for nothing and takes those answers again, as
    sent, with its own /quotes for every contract, and is delivered at its own time; the third,
    six minutes after the answers were asked for, asks /chains again. Each chain carries every
    contract with the same open interest and its quote's gamma, and no chain's quote reaches
    another's contracts.
    """
    clock = {"now": 0.0}
    sweep, published, client = _sweep(tmp_path, schwab, lambda: clock["now"])
    asked = []
    for at in ("2026-09-30 10:01", "2026-09-30 10:04", "2026-09-30 10:07"):
        clock["now"] = et_ts(at)
        assert _rotate(sweep, client) == {"SPY"}
        asked.append((len(schwab.asked(CHAIN)), len(schwab.asked(QUOTES))))
    (one, quotes), (two, quotes_two), (three, quotes_three) = asked
    assert one >= 1 and two == one and three == 2 * one, "/chains: once in five minutes"
    assert (quotes_two, quotes_three) == (2 * quotes, 3 * quotes), "/quotes: every chain"
    chains = [msg for _t, msg in published if "contracts" in msg]
    assert [_et(m["ts_recv"]) for m in chains if m["part"] == 0] == [
        "2026-09-30 10:01",
        "2026-09-30 10:04",
        "2026-09-30 10:07",
    ]
    by_time: dict[float, dict] = {}
    for m in chains:
        by_time.setdefault(m["ts_recv"], {}).update({c.symbol: c for c in m["contracts"]})
    first, again, later = by_time.values()
    assert len(first) == 442 and set(first) == set(again) == set(later)
    assert all(first[s].open_interest == again[s].open_interest for s in first)
    assert all(again[s].gamma == q["gamma"] for s, q in _QUOTED.items())
    with closing(sqlite3.connect(tmp_path / "ed_console.db")) as c, c:
        written = c.execute(
            "SELECT DISTINCT ts_utc FROM complete_chain_captures ORDER BY ts_utc"
        ).fetchall()
    assert written == [], "a chain in the session is live, never stored"


def test_before_the_open_the_chains_answers_are_asked_every_five_minutes_too(tmp_path, schwab):
    """Before the option session (2026-09-30 08:00 ET) the same five minutes hold.

    Production asked /chains for every pre-market chain (about 11,000 requests on 2026-11-11).
    Three chains of SPY at 08:00, 08:03 and 08:07: the first and the third ask /chains, the
    second takes the first's answers; each asks its own quotes.
    """
    clock = {"now": 0.0}
    sweep, published, client = _sweep(tmp_path, schwab, lambda: clock["now"])
    asked = []
    for at in ("2026-09-30 08:00", "2026-09-30 08:03", "2026-09-30 08:07"):
        clock["now"] = et_ts(at)
        sweep.fetch_chain(client, "SPY", threading.Event())
        while sweep._queue:
            sweep.send_quotes(client)
        asked.append((len(schwab.asked(CHAIN)), len(schwab.asked(QUOTES))))
    (one, quotes), (two, quotes_two), (three, quotes_three) = asked
    assert one >= 1 and (two, three) == (one, 2 * one), "/chains: once in five minutes"
    assert (quotes_two, quotes_three) == (2 * quotes, 3 * quotes), "/quotes: every chain"
    delivered = [_et(m["ts_recv"]) for _t, m in published if "contracts" in m and m["part"] == 0]
    assert delivered == ["2026-09-30 08:00", "2026-09-30 08:03", "2026-09-30 08:07"]


def test_an_added_ticker_joins_the_rotation_in_its_turn(tmp_path, schwab):
    """One rotation; while no page shows a ticker, none comes first (operator 2026-11-11).

    TSLA added to the watchlist beside SPY: SPY first, then TSLA, in sorted order.
    """
    sweep, published, client = _sweep(tmp_path, schwab, lambda: et_ts("2026-08-28 09:05"))
    sweep.watchlist = ["TSLA", "SPY"]  # the daemon's list after an add
    stop = threading.Event()
    worker = threading.Thread(target=sweep.work, args=(client, stop), daemon=True)
    worker.start()
    while not any(t == "chain.TSLA" for t, _m in published) and worker.is_alive():
        stop.wait(0.05)
    stop.set()
    worker.join(10)
    assert [q["symbol"] for q in schwab.asked(CHAIN)][:2] == ["SPY", "TSLA"]


def test_a_fetch_begun_before_the_close_capture_is_not_the_close_capture(tmp_path, schwab):
    """2026-10-01 audit: the capture window was judged by when a fetch finished.

    So an $SPX fetch begun at 16:14:30 (options still trading) and finished at 16:15:10 became
    the 16:15 close capture. A chain is the close capture only when it began at or after the close:
    SPY's, begun 16:14:30 and delivered 16:15:10, is not; the next one, begun 16:16, is.
    """
    clock = {"times": iter([])}
    sweep, _published, client = _sweep(tmp_path, schwab, lambda: next(clock["times"]))
    clock["times"] = itertools.chain(
        [et_ts("2026-09-30 16:14:30")] * 3,  # the rotation begins, the chain is due and begins
        itertools.repeat(et_ts("2026-09-30 16:15:10")),
    )
    _rotate(sweep, client)  # begun 16:14:30, delivered 16:15:10
    db = tmp_path / "ed_console.db"
    with closing(sqlite3.connect(db)) as c, c:
        assert c.execute("SELECT COUNT(*) FROM complete_chain_captures").fetchone()[0] == 0
    clock["times"] = itertools.repeat(et_ts("2026-09-30 16:16:00"))
    assert _rotate(sweep, client) == {"SPY"}  # the close values, once after the close
    with closing(sqlite3.connect(db)) as c, c:
        assert [
            _et(r[0]) for r in c.execute("SELECT DISTINCT ts_utc FROM complete_chain_captures")
        ] == ["2026-09-30 16:16"]


def test_a_failed_history_write_is_not_a_failed_chain_and_the_day_tries_again(tmp_path, schwab):
    """2026-10-01 audit: a failed history write after delivery was published as a failed chain.

    A history write that failed after the chain was delivered was published to the console as
    a failed chain. The history table refuses the close capture (a NOT NULL column the writer
    does not fill); once it takes writes, the day's next chain after the close (here, a restart's
    first) is written.
    """
    db = tmp_path / "ed_console.db"
    with closing(sqlite3.connect(db)) as conn, conn:
        conn.execute(
            "CREATE TABLE complete_chain_captures (ticker TEXT NOT NULL, expiry TEXT NOT NULL, "
            "ts_utc REAL NOT NULL, spot REAL, n_contracts INTEGER NOT NULL, "
            "completeness_basis TEXT NOT NULL, chain_json TEXT NOT NULL, source TEXT NOT NULL, "
            "created_at TEXT, refused TEXT NOT NULL, PRIMARY KEY (ticker, expiry, ts_utc))"
        )
    clock = {"now": et_ts("2026-09-30 16:16:00")}  # after SPY's option close
    sweep, published, client = _sweep(tmp_path, schwab, lambda: clock["now"])
    assert _rotate(sweep, client) == {"SPY"}
    assert all("failed" not in m for _t, m in published)
    ((tk, contracts, _t, reason, _spot, capture),) = _assembled(published)
    assert contracts is not None and reason is None
    assert capture is False, "a chain whose history was not stored is no capture"
    with closing(sqlite3.connect(db)) as conn, conn:  # the table takes writes again
        conn.execute("DROP TABLE complete_chain_captures")
        cch.ensure_schema(conn)
    clock["now"] += 120  # the daemon restarts: its first chain is the day's next after the close
    sweep, published, client = _sweep(tmp_path, schwab, lambda: clock["now"])
    assert _rotate(sweep, client) == {"SPY"}
    with closing(sqlite3.connect(db)) as c, c:
        assert (
            c.execute("SELECT COUNT(DISTINCT ts_utc) FROM complete_chain_captures").fetchone()[0]
            == 1
        )
    assert _assembled(published)[-1][5] is True, "the stored one is marked the capture"


def test_a_round_is_timed_only_when_it_asked_for_the_whole_watchlist(tmp_path, schwab):
    """Production 2026-11-06 08:29:29 CT: a rotation of one ticker timed every ticker's chain.

    A rotation before the open asked for one of the eight watchlist tickers ("1 of 1 tickers
    delivered in 32 s"), that became the round every ticker's chain was judged by, and at 08:31
    every ticker's levels read STALE against the 180 s floor while a whole round takes 234 to
    268 s. A round of part of the watchlist is not timed.
    """
    ticks = itertools.count(et_ts("2026-09-30 15:31:57"), 1.0)
    sweep, _published, client = _sweep(tmp_path, schwab, lambda: next(ticks))
    sweep.watchlist = ["SPY", "TSLA"]
    _rotate(sweep, client)  # SPY alone
    assert sweep.round_sec is None
    sweep.watchlist = ["SPY"]
    _rotate(sweep, client)
    assert sweep.round_sec is not None and sweep.round_sec > 0


def test_a_stop_asked_inside_a_ticker_asks_schwab_for_nothing_more(tmp_path, schwab):
    """Production's stop of 2026-11-06 06:41:51 CT: the sweep went on asking for 28 s.

    The sweep went on asking for the chain in hand and its quotes for 28 s, past launch.py's
    30 s wait. A stop asked once the ticker's sessions
    are in (its first publish, before its first expiry is asked) ends the rotation there: no chain
    and no quotes request reaches Schwab, and no chain is published, whole or failed.
    """
    sqlite3.connect(tmp_path / "ed_console.db").close()
    stop = threading.Event()
    published: list = []

    def publish(topic, msg):
        published.append((topic, msg))
        stop.set()

    sweep = cs.ChainSweep(
        tmp_path / "ed_console.db",
        ["SPY"],
        publish,
        clock=lambda: et_ts("2026-09-30 15:31:57"),
        failures=CaptureWriter(tmp_path / "stream_capture.db"),
        streamed={}.get,  # nothing streamed
    )
    client = schwab.client(tmp_path)
    assert sweep.rotation(lambda: client, ["SPY"], stop) == set()
    assert (schwab.asked(CHAIN), schwab.asked(QUOTES)) == ([], [])
    assert published and not [t for t, _m in published if t.startswith("chain")]


def test_the_daemon_task_stops_when_told(tmp_path):
    daemon = capture.Daemon(MessageBus(), HealthRegistry())

    async def go():
        stop = asyncio.Event()
        task = asyncio.create_task(
            capture.run_chains(
                daemon,
                "unused.db",
                lambda: None,
                stop,
                failures=CaptureWriter(tmp_path / "stream_capture.db"),
            )
        )
        await asyncio.sleep(0)
        stop.set()
        await asyncio.wait_for(task, timeout=5)
        return task

    task = asyncio.run(go())
    assert task.done() and task.exception() is None


def test_the_daemons_chain_is_the_current_record_whole_once_all_parts_are_in():
    """The sweep publishes a chain in parts on the daemon's bus.

    The chain becomes the ticker's current record only once every part is in, and a console that
    connects later starts with that whole chain (docs/DATA_FLOW.md §2 D3), every part in order --
    never a partial one.
    """
    bus = MessageBus()

    async def go():
        sub = bus.subscribe("chain.", policy=LATEST)
        parts = _parts(et_ts("2026-09-30 15:31:57"))
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
    ((tk, contracts, _ts_, reason, _spot, _capture),) = _assembled(
        [(late_topic, m) for m in late_record]
    )
    assert tk == "MRVL" and reason is None
    assert sorted(c.symbol for c in contracts) == sorted(c["symbol"] for c in _MRVL)


def test_the_reader_gives_the_last_full_capture_of_each_day(tmp_path):
    db = tmp_path / "ed_console.db"
    # the reader returns stored contracts verbatim; none is priced.
    ct = lambda e: {"symbol": f"ZZ {e}", "expirationDate": f"{e}T20:00:00.000+00:00"}

    def put(when, spot, expiries, basis=cch.CAPTURE_BASIS):
        for e in expiries:
            store_capture(
                db,
                ticker="ZZ",
                expiry=e,
                contracts=[ct(e)],
                spot=spot,
                chain_spot=spot,
                completeness_basis=basis,
                ts_utc=et_ts(when),
            )

    put("2026-09-24 15:30", 10.0, ["2030-01-04"])
    put("2026-09-24 16:00", 11.0, ["2030-01-04", "2030-01-11"])  # Thursday's last
    put("2026-09-25 16:00", 12.0, ["2030-01-04", "2030-01-11"])  # Friday's last
    put("2026-09-25 16:05", 99.0, ["2030-01-04"], basis="strike_range=ALL")  # old row
    caps = cch.last_capture_per_day(db, "ZZ", 2)
    assert [(c["et_date"], c["spot"], len(c["contracts"])) for c in caps] == [
        ("2026-09-25", 12.0, 2),
        ("2026-09-24", 11.0, 2),
    ]
    prior = cch.last_capture_per_day(db, "ZZ", 1, before_et_date="2026-09-25")
    assert [(c["et_date"], c["spot"]) for c in prior] == [("2026-09-24", 11.0)]


def test_a_partial_morning_capture_is_never_the_prior_day(tmp_path):
    """2026-09-28: the only 09-25 captures were the partial morning chains (expiries to 37 days).

    So the forces diffed Monday's full chain against them and every later expiry read as new open
    interest (SPY: +1.4M below and above spot in one day). Only full captures are read: with no
    full prior day there is no prior close for the forces, so their numbers are absent.
    """
    db = tmp_path / "ed_console.db"
    # the reader returns stored contracts verbatim; none is priced.
    ct = {"symbol": "ZZ 2030-01-04", "expirationDate": "2030-01-04T20:00:00.000+00:00"}
    store_capture(
        db,
        ticker="ZZ",
        expiry="2030-01-04",
        contracts=[ct],
        spot=5.0,
        completeness_basis="expiries_to_37_days_morning",
        ts_utc=et_ts("2026-09-25 10:00"),
    )
    store_capture(
        db,
        ticker="ZZ",
        expiry="2030-01-04",
        contracts=[ct],
        spot=5.0,
        completeness_basis=cch.CAPTURE_BASIS,
        ts_utc=et_ts("2026-09-28 16:15"),
    )
    caps = cch.last_capture_per_day(db, "ZZ", 2)
    assert [(c["et_date"], c["basis"]) for c in caps] == [("2026-09-28", cch.CAPTURE_BASIS)]
    assert server._prior_capture(caps, et_ts("2026-09-28 16:20")) is None
