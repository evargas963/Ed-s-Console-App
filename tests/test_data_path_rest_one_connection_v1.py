"""The chain path, Schwab to the console's bus, through the real code.

The daemon's ChainSweep asks Schwab's host (tests/schwab_rest_standin.py, on the real schwab-py
client as the daemon builds it) for each ticker's expiration chain, the market hours of each
expiry date not yet answered that day, its chain one expiry at a time and its contracts' quotes,
as many symbols to a request as its measured URL holds (quotes_batch) across tickers, one request
at a time. Each chain reaches the bus with
Schwab's exact Greeks: the stream's, with their times, for a contract the stream holds
(Daemon.option_record), which is not asked for on /quotes, the quote's for every other. Each
/quotes answer reaches the bus at once as Schwab sent it, with the time it was received.

Real data: the stand-in's (SPY 2026-11-20 chain and quotes, TSLA 2026-10-09 chain) and the
LEVELONE_OPTIONS events of SPY 260904C00772000
(tests/fixtures/real_options_stream_history_samples.json). STAND-INS: the held contract's stream
record is SPY 260904C00772000's events keyed as SPY 261120C00875000, each with its receive time as
Schwab's frame time (no captured stream of a 2026-11-20 contract carries its Greeks); the clock.
"""

from __future__ import annotations

import asyncio
import gc
import itertools
import json
import logging
import sqlite3
import threading
import time
from contextlib import closing
from dataclasses import replace
from datetime import datetime
from urllib.parse import urlencode

import app.options.order_flow.state as ofls
import app.options.order_flow.streaming as ofs
from app.market_data.schwab.streaming import capture
from calc.math_exposure_core import compute_exposures_by_strike, put_call_volume_ratio
from db import last_capture_per_day
from feed import schwab_client as sc
from feed.chain_sweep import REFUSED_WAITS_SEC, ChainSweep
from json_blob_codec import decode_text_blob
from option_contract import quote_values
from stream_spine import LOG, CaptureWriter, HealthRegistry, MessageBus, held_key, verbatim_msg
from tests.schwab_rest_standin import (
    CHAIN,
    CHAINS,
    EXPIRATIONS,
    FX,
    MARKETS,
    QUOTES,
    SPY,
    SPY_QUOTES,
    TSLA,
    LocalSchwab,
    delivered,
)
from tests.shared_helpers import et_ts
from time_et import ET, sessions

_STREAM = next(
    c
    for c in json.loads(
        (FX / "real_options_stream_history_samples.json").read_text(encoding="utf-8")
    )["contracts"]
    if c["symbol"] == "SPY   260904C00772000"
)
HELD = "SPY   261120C00875000"
GREEKS = ("gamma", "delta", "theta", "vega", "rho", "volatility")


def _setup(tmp_path, schwab: LocalSchwab, now: float, on_bus: bool = False):
    """Build the daemon's bus holding HELD's stream record, its sweep and the client.

    The sweep runs on a fixed clock. What it publishes is listed (`published`) and, `on_bus`, goes
    on the daemon's bus as the daemon's own sweep puts it there.
    """
    client = schwab.client(tmp_path)
    daemon = capture.Daemon(MessageBus(), HealthRegistry(), ["SPY", "TSLA"])
    # Schwab accepted it on this connection, its hold beginning before its first message came
    daemon.connection.held["LEVELONE_OPTIONS"] = frozenset({HELD})
    first = min(e["ts_recv"] for e in _STREAM["events"] if e["kind"] == "l1")
    daemon.connection.since["LEVELONE_OPTIONS"] = {HELD: first}
    for e in _STREAM["events"]:
        if e["kind"] == "l1":
            daemon.bus.publish(
                f"optquote.{HELD}",
                verbatim_msg(
                    symbol=HELD,
                    content={**e["content"], "key": HELD},
                    src="schwab_options_l1",
                    ts_recv=e["ts_recv"],
                    schwab_ts=int(e["ts_recv"] * 1000),
                ),
            )
    published: list = []

    def publish(topic: str, msg: dict) -> None:
        published.append((topic, msg))
        if on_bus:
            daemon.bus.publish(topic, msg)

    sweep = ChainSweep(
        tmp_path / "ed_console.db",
        daemon.watchlist,
        publish,
        clock=lambda: now,
        failures=CaptureWriter(tmp_path / "ed_console.db"),  # the daemon's one database
        streamed=daemon.option_record,
    )
    return daemon, sweep, (lambda: client), published


def test_market_hours_are_not_asked_for_a_date_beyond_the_year_schwab_answers(tmp_path):
    """On 2026-10-01 an expiry a year and a week out is not asked; one inside the year is.

    The one out is 2027-10-08, whose captured answer is Schwab's 400 "Date cannot be beyond 1
    year from today."; the one inside is published as Schwab sent it.
    """
    schwab = LocalSchwab()
    _daemon, sweep, client, published = _setup(tmp_path, schwab, et_ts("2026-10-01 10:15"))
    try:
        sweep.fetch_markets(client, ["2026-10-09", "2027-10-08"])
    finally:
        schwab.close()
    assert [q["date"] for path, q, *_ in schwab.requests if path == MARKETS] == ["2026-10-09"]
    assert [topic for topic, _msg in published] == ["markets.2026-10-09"]


def test_market_hours_are_asked_to_the_last_day_schwab_answered(tmp_path):
    """At the capture's own moment, 2026-10-07 22:16 ET, the last day Schwab answered is asked.

    Schwab answered 2027-10-07 (200) and refused 2027-10-08 (400, "beyond 1 year"): the first is
    asked, the second is not.
    """
    schwab = LocalSchwab()
    _daemon, sweep, client, published = _setup(tmp_path, schwab, et_ts("2026-10-07 22:16"))
    try:
        sweep.fetch_markets(client, ["2027-10-07", "2027-10-08"])
    finally:
        schwab.close()
    assert [q["date"] for path, q, *_ in schwab.requests if path == MARKETS] == ["2027-10-07"]
    assert [(topic, msg["status"]) for topic, msg in published] == [("markets.2027-10-07", 200)]


def test_a_rotation_asks_schwab_as_documented_one_request_at_a_time_with_exact_greeks(
    tmp_path, caplog
):
    schwab = LocalSchwab()
    daemon, sweep, client, published = _setup(tmp_path, schwab, et_ts("2026-10-01 10:15"))
    assert sweep.began is None, "no round has begun"
    try:
        with caplog.at_level(logging.INFO, logger="chain_history"):
            assert sweep.rotation(client, ["SPY", "TSLA"], threading.Event()) == {"SPY", "TSLA"}
        first = list(schwab.requests)
        sweep.rotation(client, ["SPY", "TSLA"], threading.Event())
        second = schwab.requests[len(first) :]
    finally:
        schwab.close()
    # the console judges a chain fetched since then live before a round is reported
    assert sweep.began == et_ts("2026-10-01 10:15"), "the first round's start, kept"

    asked = [(path, q.get("symbol") or q.get("date")) for path, q, *_ in first]
    n_quoted = len(SPY["chain"]) + len(TSLA["chain"]) - 1  # every contract but HELD
    # SPY's quotes go as a request fills, before TSLA's chain; the rest at the rotation's end
    assert [a for a in asked if a[0] != QUOTES] == [
        (EXPIRATIONS, "SPY"),
        (MARKETS, "2026-11-20"),
        (CHAIN, "SPY"),
        (EXPIRATIONS, "TSLA"),
        (MARKETS, "2026-10-09"),
        (CHAIN, "TSLA"),
    ], (
        "the expiration chain, each expiry's market hours, each expiry (the price history has "
        "its own schedule, ChainSweep.candles)"
    )
    assert asked[3] == asked[-1] == (QUOTES, None), "quotes as a request fills, the rest last"
    lists = [q["symbols"].split(",") for path, q, *_ in first if path == QUOTES]
    assert [sc.quotes_batch(a + b[:1]) for a, b in itertools.pairwise(lists)] == [
        len(a) for a in lists[:-1]
    ], "each request but the rotation's last as full as its measured URL holds"
    assert sum(len(a) for a in lists) == n_quoted
    for path, q, *_ in first:
        if path == CHAIN:
            assert (q["fromDate"], q["toDate"], q["range"]) == (CHAINS[q["symbol"]][0],) * 2 + (
                "ALL",
            )
    quoted = [s for path, q, *_ in first if path == QUOTES for s in q["symbols"].split(",")]
    unheld = sorted(
        ct["symbol"] for _e, cts, _s in CHAINS.values() for ct in cts if ct["symbol"] != HELD
    )
    assert sorted(quoted) == unheld, "every contract the stream does not hold, asked for once"
    across = [q["symbols"].split(",") for path, q, *_ in first if path == QUOTES][1]
    assert {s.split()[0] for s in across} == {"SPY", "TSLA"}, "a request is filled across tickers"
    assert all(b[2] >= a[3] for a, b in zip(first, first[1:])), "one request at a time"
    assert len({r[4] for r in first}) == 1, "on one connection"
    assert [p for p, *_ in second].count(EXPIRATIONS) == 0, "the expiration chain once per day"
    assert [p for p, *_ in second].count(MARKETS) == 0, "each date's market hours once per day"

    spy, tsla = delivered(published, "SPY"), delivered(published, "TSLA")
    assert len(spy) == len(SPY["chain"]) and len(tsla) == len(TSLA["chain"])
    # the window's line for each chain says where its Greeks came from: the held contract pushed,
    # every other asked for on /quotes, as Schwab saw it asked
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("CHAIN SPY: ")]
    pushed, requested = 1, len(SPY["chain"]) - 1
    assert lines and (
        f"| Greeks: {pushed} pushed by LEVELONE_OPTIONS, {requested} requested on /quotes, "
        in lines[0]
    ), lines
    record = daemon.option_record(HELD)[1]
    content = record["content"]
    assert {f: getattr(spy[HELD], f) for f in GREEKS} == {f: content[f.upper()] for f in GREEKS}
    assert spy[HELD].greeks_time == {f: record["field_ts"][f.upper()][0] for f in GREEKS}
    rounded = {ct["symbol"]: ct["gamma"] for ct in SPY["chain"]}
    # each /quotes answer went to the console at once as Schwab sent it, its quoteTime included,
    # with the time it was received (the sweep's clock)
    answers = [msg for topic, msg in published if topic == "optquotes"]
    assert {msg["ts_recv"] for msg in answers} == {et_ts("2026-10-01 10:15")}
    sent = {sym: quote for msg in answers for sym, quote in msg["answer"].items()}
    for sym, ct in spy.items():
        if sym != HELD:
            quote = SPY_QUOTES[sym]["quote"]
            assert {f: getattr(ct, f) for f in GREEKS} == {f: quote[f] for f in GREEKS}, sym
            assert sent[sym] == quote, sym
    assert any(rounded[s] != spy[s].gamma for s in spy), "the chain's rounded Greeks are not kept"
    # bid, ask and volume are the quote's as sent; the chain's are not used, and the held
    # contract, not asked on /quotes, carries the stream's as the stream held them when its
    # chain was complete, so the chain as delivered and as stored has a quote for every contract
    for sym, ct in spy.items():
        if sym != HELD:
            quote = SPY_QUOTES[sym]["quote"]
            assert (ct.bid, ct.ask) == (quote["bidPrice"], quote["askPrice"]), sym
            assert ct.volume == quote["totalVolume"], sym
            assert ct.listing.get("quote") is None, "the answer is read, not listed"
    # (these twelve records carry TOTAL_VOLUME and no BID_PRICE or ASK_PRICE: Change delivery)
    assert content["TOTAL_VOLUME"] == 486836 and not {"BID_PRICE", "ASK_PRICE"} & set(content)
    assert (spy[HELD].bid, spy[HELD].ask, spy[HELD].volume) == (None, None, 486836)
    assert all(ct.volume is not None for ct in spy.values()), "no contract without a volume"
    # 10:15 ET is in the session: the chains are live and none is stored (the close capture only)
    assert last_capture_per_day(tmp_path / "ed_console.db", "SPY", 1) == []
    # so the chain as delivered, with nothing laid over it (the close values), has a put/call
    # volume ratio: one contract without a volume leaves it unknown
    held = sessions()
    book, _diag = compute_exposures_by_strike(
        list(spy.values()),
        spot=SPY["spot"],
        now=datetime.fromtimestamp(et_ts("2026-10-01 10:15"), ET),
        sessions=held,
    )
    assert put_call_volume_ratio(book.values()) is not None
    unknown, _diag = compute_exposures_by_strike(
        [replace(ct, volume=None) if sym == HELD else ct for sym, ct in spy.items()],
        spot=SPY["spot"],
        now=datetime.fromtimestamp(et_ts("2026-10-01 10:15"), ET),
        sessions=held,
    )
    assert put_call_volume_ratio(unknown.values()) is None
    assert all(
        getattr(ct, f) is None and ct.greeks_time is None and "greeksTime" in ct.sent
        for ct in tsla.values()
        for f in GREEKS
    ), "a Greek Schwab did not send is absent"

    with closing(sqlite3.connect(tmp_path / "ed_console.db")) as conn, conn:
        rows = conn.execute("SELECT ticker FROM complete_chain_captures").fetchall()
    assert rows == [], "no ticker's chain is stored in the session"


def test_every_quotes_answer_of_a_rotation_reaches_the_console_and_the_record(tmp_path):
    """Schwab's /quotes answers of one rotation each reach the console, and the Recorder whole.

    Schwab to the console and to the record, through the real code: the sweep's rotation on the
    real client, the daemon's bus, the console's own reader (order_flow.streaming._bus_loop) and
    the daemon's writer. The rotation asks three /quotes requests; SPY's 441 unheld contracts are
    quoted in the first two (TSLA's quotes were not captured). INDUCED: the console takes nothing
    while the rotation runs (it runs on the loop's own thread here, so the reader gets no turn),
    as when the program's loop runs late. Each answer carries its own contracts: every one of
    them is at the console with its answer's values and receive time, and rest_quotes_raw holds
    each answer's body as Schwab sent it.
    """
    schwab = LocalSchwab()
    now = et_ts("2026-10-01 10:15")
    daemon, sweep, client, published = _setup(tmp_path, schwab, now, on_bus=True)
    db = tmp_path / "stream_capture.db"

    async def go():
        stop = asyncio.Event()
        writer = CaptureWriter(db, batch_rows=1, batch_sec=0.01)
        record = asyncio.create_task(writer.run(daemon.bus.subscribe("", policy=LOG), stop=stop))
        ofs.FEED.running = True
        reader = asyncio.create_task(ofs._bus_loop(daemon.bus))
        try:
            await asyncio.sleep(0)  # the reader has subscribed and waits
            assert sweep.rotation(client, ["SPY", "TSLA"], threading.Event()) == {"SPY", "TSLA"}
            for _turn in range(50):
                await asyncio.sleep(0)
            return ofls.rest_quotes([ct["symbol"] for ct in SPY["chain"]], 0.0)
        finally:
            ofs.FEED.running = False
            reader.cancel()
            stop.set()
            await asyncio.gather(reader, record, return_exceptions=True)
            with ofls._rest_lock:
                ofls._REST_QUOTES.clear()

    failures = ofs.FEED.apply_failures
    try:
        held = asyncio.run(go())
    finally:
        schwab.close()
    assert ofs.FEED.apply_failures == failures, "every record applied"
    answers = [msg["answer"] for topic, msg in published if topic == "optquotes"]
    full = sc.quotes_batch(sorted(ct["symbol"] for ct in SPY["chain"]))
    assert [len(a) for a in answers if a] == [full, len(SPY["chain"]) - 1 - full], (
        "SPY's unheld contracts, in two answers (TSLA's contracts have no quote in the capture)"
    )
    assert not set(answers[0]) & set(answers[1])
    assert held == {
        sym: (now, quote_values(quote)) for answer in answers for sym, quote in answer.items()
    }
    assert set(held) == {ct["symbol"] for ct in SPY["chain"]} - {HELD}
    with closing(sqlite3.connect(db)) as conn:
        stored = [
            json.loads(decode_text_blob(body))
            for (body,) in conn.execute("SELECT body FROM rest_quotes_raw ORDER BY rowid")
        ]
    assert [{s: e["quote"] for s, e in body.items()} for body in stored] == answers
    assert stored == [
        json.loads(msg["body"]) for topic, msg in published if topic == "quotesanswer"
    ], "each answer's body, as received"


def test_the_one_connection_stands_through_a_pause(tmp_path):
    """The session as production builds it: two requests 6 s apart go on the same connection.

    6 s is longer than httpx keeps an idle connection by default.
    """
    schwab = LocalSchwab()
    client = sc.client_from_token_file_atomic(schwab.token_file(tmp_path), "k", "s")
    url = f"http://127.0.0.1:{schwab.server.server_address[1]}{EXPIRATIONS}?symbol=SPY"
    try:
        client.session.get(url)
        time.sleep(6)  # INDUCED: the pause, past httpx's own idle limit (5 s)
        client.session.get(url)
    finally:
        client.session.close()
        schwab.close()
    assert len(schwab.requests) == 2
    assert len({r[4] for r in schwab.requests}) == 1


def test_every_answer_read_is_freed_with_no_full_collection(tmp_path):
    """Each /quotes answer, read and dropped as the sweep does, is freed at once.

    The session runs no full collection (capture.set_collector), so an answer that only a full
    collection frees is held until the close. Here no collection runs while three answers are
    taken; one full collection after them, saving what it finds, finds no answer.
    """
    schwab = LocalSchwab()
    client = schwab.client(tmp_path)
    symbols = list(SPY_QUOTES)[:300]
    was_on = gc.isenabled()
    gc.collect()
    gc.disable()
    try:
        for _ in range(3):
            assert len(sc.safe_get_quotes(client, symbols).json()) == 300
        gc.set_debug(gc.DEBUG_SAVEALL)
        gc.collect()
        found = [type(o).__qualname__ for o in gc.garbage if type(o).__module__ == "httpx"]
    finally:
        gc.set_debug(0)
        gc.garbage.clear()
        if was_on:
            gc.enable()
        schwab.close()
    assert "Response" not in found, found


def test_a_streamed_no_value_code_does_not_block_the_quote(tmp_path):
    """The stream record holds every greek field as Schwab's -999.

    That is not a reported greek, so the contract is asked on the quotes endpoint and takes the
    quote's exact greeks. The same rule for every ticker.
    """
    schwab = LocalSchwab()
    daemon, sweep, client, published = _setup(tmp_path, schwab, et_ts("2026-10-01 10:15"))
    record = daemon.option_record(HELD)[1]
    daemon.bus.publish(
        f"optquote.{HELD}",
        verbatim_msg(
            symbol=HELD,
            content={**record["content"], **{f.upper(): -999 for f in GREEKS}},
            src="schwab_options_l1",
            ts_recv=record["ts_recv"] + 1,
            schwab_ts=int((record["ts_recv"] + 1) * 1000),
        ),
    )
    try:
        assert sweep.rotation(client, ["SPY"], threading.Event()) == {"SPY"}
    finally:
        schwab.close()
    assert HELD in [s for q in schwab.asked(QUOTES) for s in q["symbols"].split(",")]
    quote = SPY_QUOTES[HELD]["quote"]
    got = delivered(published, "SPY")[HELD]
    assert {f: getattr(got, f) for f in GREEKS} == {f: quote[f] for f in GREEKS}
    assert got.gamma is not None, "Schwab's quote, never its no-value"


def test_a_429_on_one_expiry_does_not_cost_the_ticker_its_round(tmp_path):
    """A 429 on one expiry is asked once more, and the ticker is delivered.

    Measured 2026-11-02: Schwab answered one of SPY's expiries 429, and SPY's levels stood 15
    minutes old until its next round. That expiry is asked once more, and SPY is delivered.
    """
    schwab = LocalSchwab()
    schwab.throttle_chain = {"SPY"}
    _daemon, sweep, client, published = _setup(tmp_path, schwab, et_ts("2026-08-28 09:05"))
    try:
        assert sweep.rotation(client, ["SPY", "TSLA"], threading.Event()) == {"SPY", "TSLA"}
    finally:
        schwab.close()
    assert [msg["failed"] for _topic, msg in published if "failed" in msg] == []
    assert [q["symbol"] for p, q, *_ in schwab.requests if p == CHAIN] == ["SPY", "SPY", "TSLA"]


def test_a_429_on_one_quotes_request_does_not_cost_its_tickers_their_round(tmp_path):
    """A 429 on one quotes request is sent again, and its tickers are delivered.

    INDUCED: Schwab answered none of its 1,339,785 /quotes requests of 2026-10-10 to 2026-11-22
    with a 429; the first quotes request here is. It goes again at once, as a refused expiry
    does, so no ticker fails and every contract is quoted.
    """
    schwab = LocalSchwab()
    schwab.throttle_quotes = 1
    _daemon, sweep, client, published = _setup(tmp_path, schwab, et_ts("2026-08-28 09:05"))
    try:
        assert sweep.rotation(client, ["SPY", "TSLA"], threading.Event()) == {"SPY", "TSLA"}
    finally:
        schwab.close()
    assert [msg["failed"] for _topic, msg in published if "failed" in msg] == []
    asked = [q["symbols"] for q in schwab.asked(QUOTES)]
    assert len(asked) == len(set(asked)) + 1, "the refused request, and no other, was sent again"


def _schwab_url(symbols: list[str]) -> int:
    """The length of GET /quotes for `symbols` at Schwab's host, worked out here (urlencode)."""
    query = urlencode({"symbols": ",".join(symbols), "fields": "quote"})
    return len(f"https://api.schwabapi.com/marketdata/v1/quotes?{query}")


def test_a_quotes_request_carries_as_many_contracts_as_its_measured_url_holds():
    """QUOTES_URL_MAX, measured 2026-11-28: 8,897 characters answered, 8,921 refused by the edge.

    SPY's contracts as Schwab listed them (2026-11-20): a request's URL at Schwab's host is
    within the measured limit, and one contract more would pass it. One that alone passes it is
    still asked, alone.
    """
    symbols = sorted(SPY_QUOTES)
    fits = sc.quotes_batch(symbols)
    assert _schwab_url(symbols[:fits]) <= sc.QUOTES_URL_MAX < _schwab_url(symbols[: fits + 1])
    assert fits > 300, "more than the support's guidance, which is not a limit"
    assert sc.quotes_batch([]) == 0
    assert sc.quotes_batch(["X" * (sc.QUOTES_URL_MAX + 1)]) == 1


def test_a_quotes_request_refused_each_time_fails_its_tickers_and_the_next_goes_at_once(
    tmp_path,
):
    """A refused quotes request is sent again at once, then after 1 and 2 seconds, then fails.

    INDUCED: Schwab's host answers the first four quotes requests 429, SPY's first request and
    its three more tries (REFUSED_WAITS_SEC). SPY fails with the reason and its other contracts
    are not asked for; the next request goes at once after the last refusal, and TSLA is
    delivered.
    """
    schwab = LocalSchwab()
    schwab.throttle_quotes = 1 + len(REFUSED_WAITS_SEC)
    _daemon, sweep, client, published = _setup(tmp_path, schwab, et_ts("2026-08-28 09:05"))
    try:
        assert sweep.rotation(client, ["SPY", "TSLA"], threading.Event()) == {"TSLA"}
    finally:
        schwab.close()
    failed = [(topic, msg["failed"]) for topic, msg in published if "failed" in msg]
    first = next(q for path, q, *_ in schwab.requests if path == QUOTES)["symbols"].split(",")
    assert len(first) == sc.quotes_batch(first)
    assert failed == [("chain.SPY", f"quotes for {len(first)} contracts returned HTTP 429")]
    quotes = [i for i, (path, *_) in enumerate(schwab.requests) if path == QUOTES]
    assert len(quotes) == 5, "SPY's first request four times, then TSLA's: SPY's others not asked"
    refused = [schwab.requests[i] for i in quotes[:4]]
    waits = [b[2] - a[3] for a, b in zip(refused, refused[1:])]
    assert all(wait >= least for wait, least in zip(waits, REFUSED_WAITS_SEC, strict=True)), waits
    assert waits[0] < 1.0, f"the first is sent again at once: {waits[0]:.2f} s"
    pause = schwab.requests[quotes[3] + 1][2] - refused[-1][3]
    assert pause < 1.0, f"a pause after Schwab's last 429: {pause:.2f} s"


def test_a_stop_ends_a_refused_requests_wait(tmp_path):
    """A stop asked while Schwab refuses: the request is not sent again; its 429 is the answer."""
    schwab = LocalSchwab()
    schwab.quotes_status = 429
    client = schwab.client(tmp_path)
    stop = threading.Event()
    stop.set()
    try:
        answer = ChainSweep.ask_quotes(lambda: client, [HELD], stop)
    finally:
        schwab.close()
    assert answer.status_code == 429 and len(schwab.asked(QUOTES)) == 1


def test_outside_the_option_session_every_watchlist_ticker_is_fetched_once_and_a_failed_one_again(
    tmp_path,
):
    schwab = LocalSchwab()
    schwab.refuse_chain = {"TSLA"}
    _daemon, sweep, client, published = _setup(
        tmp_path, schwab, et_ts("2026-10-03 12:00")
    )  # Saturday
    stop = threading.Event()
    try:
        # the passes of the sweep's thread (ChainSweep.work), until one asks for nothing: then
        # the thread waits, and its next pass asks for nothing again
        for _ in range(10):
            if not sweep.step(client, stop):
                break
        settled = len(schwab.requests)
        idle = not sweep.step(client, stop) and len(schwab.requests) == settled
    finally:
        schwab.close()
    chains = [(q["symbol"], q["fromDate"]) for q in schwab.asked(CHAIN)]
    assert chains == [("SPY", "2026-11-20"), ("TSLA", "2026-10-09"), ("TSLA", "2026-10-09")]
    assert [m["failed"] for t, m in published if "failed" in m] == [
        "chain for 2026-10-09 returned HTTP 502"
    ]
    assert idle, "the close values stand: nothing more is asked for until the next session"


def test_a_held_contracts_record_ends_with_its_connection(tmp_path):
    """The connection ends: HELD's record ends for the sweep with it.

    Its last values stand on the bus (D5), but the sweep takes no record of a contract the
    stream does not hold, so HELD is asked of the quotes endpoint rather than priced on the
    ended connection's Greeks. A new hold takes none of this one's Greeks
    (test_option_contract_rule_v1: a released contract's record stands and a new hold takes
    none of it).
    """
    schwab = LocalSchwab()
    daemon, sweep, client, published = _setup(tmp_path, schwab, et_ts("2026-10-01 10:15"))
    asyncio.run(daemon.connection.disconnect())
    assert held_key("LEVELONE_OPTIONS", HELD) in daemon.bus.current
    assert daemon.option_record(HELD) is None
    try:
        assert sweep.rotation(client, ["SPY"], threading.Event()) == {"SPY"}
    finally:
        schwab.close()
    assert HELD in [s for q in schwab.asked(QUOTES) for s in q["symbols"].split(",")]


def test_a_contract_the_stream_no_longer_holds_takes_its_quotes_greeks(tmp_path):
    """The stream's connection ends (it holds nothing).

    HELD's record from that connection is still on the bus, and its Greeks are asked of the
    quotes endpoint, never taken from a feed that is down.
    """
    schwab = LocalSchwab()
    daemon, sweep, client, published = _setup(tmp_path, schwab, et_ts("2026-08-28 09:05"))
    asyncio.run(daemon.connection.disconnect())
    try:
        assert sweep.rotation(client, ["SPY"], threading.Event()) == {"SPY"}
    finally:
        schwab.close()
    assert HELD in [s for q in schwab.asked(QUOTES) for s in q["symbols"].split(",")]
    quote = SPY_QUOTES[HELD]["quote"]
    assert {f: getattr(delivered(published, "SPY")[HELD], f) for f in GREEKS} == {
        f: quote[f] for f in GREEKS
    }


def test_a_quotes_answer_that_is_not_json_fails_its_tickers_and_the_sweep_goes_on(tmp_path):
    """STAND-IN: a 200 answer whose body is not JSON.

    Each ticker in the request is published as failed with the error, and the next rotation
    delivers.
    """
    schwab = LocalSchwab()
    schwab.quotes_body = b"<html>not json</html>"
    _daemon, sweep, client, published = _setup(tmp_path, schwab, et_ts("2026-08-28 09:05"))
    try:
        assert sweep.rotation(client, ["SPY"], threading.Event()) == set()
        schwab.quotes_body = None
        assert sweep.rotation(client, ["SPY"], threading.Event()) == {"SPY"}
    finally:
        schwab.close()
    (failed,) = [m["failed"] for _t, m in published if "failed" in m]
    assert failed.startswith("JSONDecodeError")


def test_a_ticker_check_answered_with_what_is_not_json_is_not_a_ticker_schwab_quotes(tmp_path):
    """STAND-IN: the watchlist's check of an added ticker (check_ticker) answered 200, not JSON.

    It is not a ticker Schwab quotes, with the answer's status and text as sent. AAPL: a ticker
    whose check Schwab's capture does not hold, so the stand-in answers it.
    """
    schwab = LocalSchwab()
    schwab.quotes_body = b"<html>not json</html>"
    try:
        checked = sc.check_ticker(schwab.client(tmp_path), "AAPL")
    finally:
        schwab.close()
    assert checked == (False, 200, "<html>not json</html>")


def test_contracts_schwab_names_invalid_get_no_greeks_and_every_ticker_in_the_request_is_delivered(
    tmp_path, caplog
):
    """Schwab's /quotes answers 200 with a quote per symbol it knows and an errors entry.

    Beside the quotes, the errors entry names the ones it does not know (measured 2026-10-07: 8
    SPY contracts its own chain lists, never quoted or traded). Every entry that is a quote is
    read; the 8 get no Greeks, logged once per request with their count; SPY and TSLA, which share
    a request, are both delivered. Real data: the 8 contracts' /chains entries and Schwab's errors
    entry as sent (tests/fixtures/real_spy_quotes_invalid_symbols_2026_10_07.json). STAND-IN: the
    8 are served in SPY's chain answer beside its 2026-11-20 contracts, as one more expiry's.
    """
    invalid = json.loads(
        (FX / "real_spy_quotes_invalid_symbols_2026_10_07.json").read_text(encoding="utf-8")
    )
    named = invalid["quotes_errors"]["invalidSymbols"]
    schwab = LocalSchwab()
    schwab.invalid = invalid["chain_entries"]
    _daemon, sweep, client, published = _setup(tmp_path, schwab, et_ts("2026-08-28 09:05"))
    with caplog.at_level("WARNING", logger="chain_history"):
        try:
            assert sweep.rotation(client, ["SPY", "TSLA"], threading.Event()) == {"SPY", "TSLA"}
        finally:
            schwab.close()
    assert [m for _t, m in published if "failed" in m] == [], "no ticker failed"
    answered = [
        q["symbols"].split(",")
        for q in schwab.asked(QUOTES)
        if set(named) & set(q["symbols"].split(","))
    ]
    assert any({s.split()[0] for s in symbols} == {"SPY", "TSLA"} for symbols in answered), (
        "a shared request"
    )
    spy = delivered(published, "SPY")
    assert len(spy) == len(SPY["chain"]) + len(named)
    assert all(
        getattr(spy[s], f) is None and spy[s].greeks_time is None and "greeksTime" in spy[s].sent
        for s in named
        for f in GREEKS
    )
    for sym, ct in spy.items():
        if sym not in named and sym != HELD:
            quote = SPY_QUOTES[sym]["quote"]
            assert {f: getattr(ct, f) for f in GREEKS} == {f: quote[f] for f in GREEKS}, sym
    assert len(delivered(published, "TSLA")) == len(TSLA["chain"])
    logged = [r.getMessage() for r in caplog.records]
    in_request = [[s for s in symbols if s in named] for symbols in answered]
    assert sum(len(n) for n in in_request) == len(named) == 8
    assert [m for m in logged if "named" in m] == [
        f"quotes for {len(symbols)} contracts: Schwab named {len(n)} invalid, which have no "
        f"Greeks: {json.dumps({'invalidSymbols': n})}"
        for symbols, n in zip(answered, in_request)
    ], "each request's named contracts logged once, with their count"
    assert not [m for m in logged if m.startswith("quotes for SPY: no quote came back")], (
        "logged once"
    )
