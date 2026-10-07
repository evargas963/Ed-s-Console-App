"""The one watchlist and the daemon's subscriptions, Schwab to the screen, through the real code:
the capture daemon's connection (capture.Daemon.run) on the real schwab-py StreamClient, logged in to
Schwab's streamer played locally (tests/schwab_stream_standin.py) through Schwab's REST host played
locally (tests/schwab_rest_standin.py); the daemon's console socket (live_push); the console's side of
it (streaming.serve_push) and its routes (server.post_watchlist, delete_watchlist, get_watchlist).

Real data: Schwab's /quotes answers to SPY, TSLA, SPCX, META, QQQ, IWM and ZQZQZ asked alone, as the
watchlist check asks (2026-10-07; ZQZQZ is named in errors.invalidSymbols); Schwab's answers to an ADD
past LEVELONE_OPTIONS' limit as logged on 2026-10-07 04:40:39 (code 19, then code 24 "ADD command
failed"); SPY option contract symbols from SPY's captured 2026-11-20 chain. STAND-INS (named in the
stand-ins): the streamer's login, a code-0 answer's message, the limit a test sets.
"""
from __future__ import annotations

import asyncio
import json
import socket
import threading
import time

import live_market_plane as lmp
import push_changes
import server
from app.market_data.schwab.streaming import capture
from app.market_data.schwab.streaming.live_push import MARKET_CONTEXT, serve_live_push
from app.options.order_flow import streaming as ofs
from calibration.complete_chain_capture import ChainSweep
from stream_spine import LOG, CaptureWriter, HealthRegistry, MessageBus
from tests.schwab_rest_standin import CHECKS, QUOTES, SPY_QUOTES, LocalSchwab
from tests.schwab_stream_standin import LocalStreamer, refusal

#: three of SPY's 2026-11-20 contracts, as Schwab's chain names them
CONTRACTS = sorted(SPY_QUOTES)[:3]
EQUITY = ("LEVELONE_EQUITIES", "CHART_EQUITY", "NEWS_HEADLINE", "NYSE_BOOK", "NASDAQ_BOOK")


async def _until(cond, seconds: float = 15.0) -> None:
    deadline = time.monotonic() + seconds
    while not cond():
        assert time.monotonic() < deadline, "not reached in time"
        await asyncio.sleep(0.02)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _Schwab:
    """The local streamer and REST host, and the daemon's client of them as the daemon builds it."""

    def __init__(self, tmp_path, limits=None):
        self.streamer = LocalStreamer(limits)
        self.rest = LocalSchwab(self.streamer.url)
        self.client = self.rest.client(tmp_path)

    def close(self) -> None:
        self.streamer.close()
        self.rest.close()


def _answers(log) -> "list[tuple[str, str, int, str]]":
    """(service, command, code, Schwab's message) of each answer the daemon recorded, in order."""
    out = []
    while not log.queue.empty():
        topic, msg = log.queue.get_nowait()
        if topic.startswith("sub."):
            out.append((msg["service"], msg["command"], msg["code"], msg["reason"]))
    return out


def test_the_daemon_subscribes_once_and_each_of_schwabs_answers_reaches_its_own_request(tmp_path):
    """2026-10-07 (stream_capture.log 04:40:39): Schwab answered a refused ADD twice, code 19 and
    then code 24, and every request after it was logged "unexpected requestid": each answer had
    been taken as the next request's. Now one reader matches each answer to its request by its
    requestid. Every watchlist ticker is asked for on each equity service and the header's
    market context on quotes, bars and news, in one request per service; the console's three
    contracts on LEVELONE_OPTIONS past a limit of two get Schwab's refusal, both answers recorded
    as sent, and nothing is asked again."""
    schwab = _Schwab(tmp_path, limits={"LEVELONE_OPTIONS": 2})
    bus = MessageBus()
    log = bus.subscribe("sub.", policy=LOG)
    daemon = capture.Daemon(bus, HealthRegistry(), ["SPY", "TSLA"])
    daemon.set_options({"op": "options", "LEVELONE_OPTIONS": CONTRACTS, "OPTIONS_BOOK": CONTRACTS[:1]}, "console")

    async def go():
        stop = asyncio.Event()
        run = asyncio.create_task(daemon.run(lambda: schwab.client, stop))
        await _until(lambda: len(schwab.streamer.answers) >= 9)          # login + 7 requests, one answered twice
        await asyncio.sleep(0.5)
        daemon.ask()                                                     # nothing changed: nothing is asked
        await asyncio.sleep(0.5)
        connected = (dict(daemon.held), {k: dict(v) for k, v in daemon.refused.items()}, daemon.status())
        stop.set()
        await asyncio.wait_for(run, 10)
        return connected
    try:
        held, refused, status = asyncio.run(go())
    finally:
        schwab.close()
    asked = [(r["service"], r["command"], sorted(r["parameters"]["keys"].split(",")))
             for r in schwab.streamer.requests if r["service"] != "ADMIN"]
    context = sorted(["SPY", "TSLA", *MARKET_CONTEXT])
    assert sorted(asked) == sorted([*[(svc, "SUBS", context) for svc in ("LEVELONE_EQUITIES", "CHART_EQUITY",
                                                                         "NEWS_HEADLINE")],
                                    *[(svc, "SUBS", ["SPY", "TSLA"]) for svc in ("NYSE_BOOK", "NASDAQ_BOOK")],
                                    ("LEVELONE_OPTIONS", "SUBS", CONTRACTS), ("OPTIONS_BOOK", "SUBS", CONTRACTS[:1])])
    answers = _answers(log)
    assert [a for a in answers if a[0] == "LEVELONE_OPTIONS"] == [
        ("LEVELONE_OPTIONS", "SUBS", 19, refusal("LEVELONE_OPTIONS", 2, 1)),
        ("LEVELONE_OPTIONS", "SUBS", 24, "SUBS command failed")], "both of Schwab's answers, as sent"
    assert all(code == 0 for svc, _c, code, _m in answers if svc != "LEVELONE_OPTIONS"), answers
    assert held["NYSE_BOOK"] == {"SPY", "TSLA"} and held["LEVELONE_OPTIONS"] == frozenset()
    assert refused["LEVELONE_OPTIONS"] == dict.fromkeys(CONTRACTS, refusal("LEVELONE_OPTIONS", 2, 1))
    assert status["refused"] == {"LEVELONE_OPTIONS": refused["LEVELONE_OPTIONS"]}


def test_a_subscription_split_under_schwabs_message_limit_keeps_every_part(tmp_path):
    """MRVL's 2,432 contracts (its full chain as Schwab sent it, tests/fixtures/
    real_mrvl_full_chain_vs_strike_window.json) are more than one request carries, so the
    subscription is sent in parts. A SUBS replaces all a service holds (measured live 2026-10-07:
    of 3,001 contracts sent as SUBS 2,181 + SUBS 819 + ADD 1, only the last 820 ever updated), so
    only the first part is SUBS and the rest ADD: Schwab holds them all."""
    from pathlib import Path

    from schwab_client import flatten_chain_contracts
    mrvl = json.loads((Path(__file__).parent / "fixtures" / "real_mrvl_full_chain_vs_strike_window.json")
                      .read_text(encoding="utf-8"))
    symbols = sorted(ct["symbol"] for ct in flatten_chain_contracts(mrvl["full"]))
    schwab = _Schwab(tmp_path)
    daemon = capture.Daemon(MessageBus(), HealthRegistry())
    daemon.set_options({"op": "options", "LEVELONE_OPTIONS": symbols, "OPTIONS_BOOK": []}, "console")

    async def go():
        stop = asyncio.Event()
        run = asyncio.create_task(daemon.run(lambda: schwab.client, stop))
        await _until(lambda: len(daemon.held["LEVELONE_OPTIONS"]) == len(symbols))
        stop.set()
        await asyncio.wait_for(run, 10)
    try:
        asyncio.run(go())
    finally:
        schwab.close()
    commands = [c for c, _k in schwab.streamer.asked("LEVELONE_OPTIONS")]
    assert len(commands) > 1 and commands == ["SUBS"] + ["ADD"] * (len(commands) - 1)
    assert sorted(schwab.streamer.held["LEVELONE_OPTIONS"]) == symbols, "Schwab holds every part"


def test_a_dropped_connection_subscribes_once_again_with_one_session_at_a_time(tmp_path):
    """Schwab drops the socket: the daemon logs out, connects again (a new session that holds
    nothing) and asks for everything once again; the frames are taken whole (no size cap)."""
    schwab = _Schwab(tmp_path)
    daemon = capture.Daemon(MessageBus(), HealthRegistry(), ["SPY"])

    def subs():
        return [r for r in schwab.streamer.requests if r["command"] == "SUBS" and r["service"] == "NYSE_BOOK"]

    async def go():
        stop = asyncio.Event()
        run = asyncio.create_task(daemon.run(lambda: schwab.client, stop))
        await _until(lambda: len(subs()) == 1 and daemon.held["NYSE_BOOK"])
        await daemon.stream._socket.close()                              # the socket is gone
        await _until(lambda: len(subs()) == 2 and daemon.held["NYSE_BOOK"])
        stop.set()
        await asyncio.wait_for(run, 10)
    try:
        asyncio.run(go())
    finally:
        schwab.close()
    logins = [r for r in schwab.streamer.requests if r["command"] == "LOGIN"]
    assert len(logins) == 2 and [r["parameters"]["keys"] for r in subs()] == ["SPY", "SPY"]


def test_a_request_schwab_never_answers_ends_the_connection(tmp_path):
    """A request unanswered for REQUEST_TIMEOUT_SEC means the connection is broken: it ends with
    that reason (Schwab's streamer here takes OPTIONS_BOOK requests and never answers them)."""
    schwab = _Schwab(tmp_path)
    answer = schwab.streamer.answer
    schwab.streamer.answer = lambda req: [] if req["service"] == "OPTIONS_BOOK" else answer(req)
    daemon = capture.Daemon(MessageBus(), HealthRegistry())
    daemon.set_options({"op": "options", "LEVELONE_OPTIONS": [], "OPTIONS_BOOK": CONTRACTS[:1]}, "console")
    started = time.monotonic()

    async def go():
        await daemon.run_connection(schwab.client, asyncio.Event())
    try:
        try:
            asyncio.run(asyncio.wait_for(go(), capture.REQUEST_TIMEOUT_SEC + 10))
            raise AssertionError("the connection did not end")
        except ConnectionError as e:
            assert str(e) == f"no answer to OPTIONS_BOOK SUBS in {capture.REQUEST_TIMEOUT_SEC:.0f} s"
    finally:
        schwab.close()
    assert time.monotonic() - started >= capture.REQUEST_TIMEOUT_SEC
    assert daemon.stream is None, "the broken session is logged out and dropped"


def test_an_added_ticker_is_checked_once_asked_for_everywhere_and_a_removed_one_no_more(tmp_path):
    """Through the console's route and the daemon's console socket: TSLA added is checked with one
    /quotes request (Schwab quotes it), added, asked for on every equity service and by the
    chain sweep, and stored; ZQZQZ (Schwab names it in errors.invalidSymbols) is not added; TSLA
    removed is asked for no more. The stored list is the daemon's after a restart."""
    schwab = _Schwab(tmp_path)
    db = tmp_path / "stream_capture.db"
    bus = MessageBus()
    daemon = capture.Daemon(bus, HealthRegistry(), ["SPY"])
    daemon.chains = ChainSweep(tmp_path / "ed_console.db", daemon.watchlist, lambda t, m: None,
                               failures=CaptureWriter(db), streamed=daemon.option_record)
    port = _free_port()

    def asked(svc):
        return [(c, k) for c, k in schwab.streamer.asked(svc)]

    async def go():
        from websockets.asyncio.client import connect
        stop = asyncio.Event()
        writer = CaptureWriter(db, batch_rows=1, batch_sec=0.01)
        tasks = [asyncio.create_task(writer.run(bus.subscribe("", policy=LOG), stop=stop)),
                 asyncio.create_task(serve_live_push(bus, stop, port=port, on_request=daemon.console_frame)),
                 asyncio.create_task(daemon.run(lambda: schwab.client, stop))]
        await _until(lambda: daemon.held["NASDAQ_BOOK"] == {"SPY"})
        for _ in range(100):
            try:
                ws = await connect(f"ws://127.0.0.1:{port}", max_size=None)
                break
            except OSError:
                await asyncio.sleep(0.05)
        console = asyncio.create_task(ofs.serve_push(ws))                 # the console's side of the socket
        await _until(lambda: ofs._push_ws is ws)
        added = json.loads((await server.post_watchlist({"ticker": "tsla"})).body)
        await _until(lambda: daemon.held["NASDAQ_BOOK"] == {"SPY", "TSLA"})
        swept_after_add = list(daemon.chains.watchlist)
        invalid = json.loads((await server.post_watchlist({"ticker": "ZQZQZ"})).body)
        removed = json.loads((await server.delete_watchlist("TSLA")).body)
        await _until(lambda: daemon.held["NASDAQ_BOOK"] == {"SPY"})
        await ws.close()
        await asyncio.wait_for(console, 5)
        stop.set()
        await asyncio.gather(*tasks)
        return added, invalid, removed, swept_after_add
    try:
        added, invalid, removed, swept_after_add = asyncio.run(go())
    finally:
        schwab.close()
    assert swept_after_add == ["SPY", "TSLA"], "the chain sweep fetches an added ticker"
    assert added == {"ok": True, "op": "added", "ticker": "TSLA", "tickers": ["SPY", "TSLA"], "status": 200,
                     "answer": CHECKS["TSLA"]["body"]}
    assert invalid == {"ok": False, "op": "invalid", "ticker": "ZQZQZ", "tickers": ["SPY", "TSLA"], "status": 200,
                       "answer": {"errors": {"invalidSymbols": ["ZQZQZ"]}}}
    assert removed == {"ok": True, "op": "removed", "ticker": "TSLA", "tickers": ["SPY"], "status": None,
                       "answer": None}
    assert [q["symbols"] for q in schwab.rest.asked(QUOTES)] == ["TSLA", "ZQZQZ"], "one check per add"
    for svc in EQUITY:
        assert [(c, k) for c, k in asked(svc) if "TSLA" in k] == [("ADD", ["TSLA"]), ("UNSUBS", ["TSLA"])], svc
    assert not any("ZQZQZ" in r["parameters"].get("keys", "") for r in schwab.streamer.requests)
    assert daemon.chains.watchlist == ["SPY"], "and stops fetching a removed one"
    assert capture.stored_watchlist(db) == ["SPY"], "the newest stored list"


def test_with_the_watchlist_empty_the_sweep_asks_for_nothing_and_waits(tmp_path, caplog):
    """An empty watchlist in an open session (Wednesday 2026-10-07 10:00 ET): no request to Schwab
    and no rotation, until a ticker is added."""
    from datetime import datetime

    from time_et import ET
    schwab = LocalSchwab()
    sweep = ChainSweep(tmp_path / "ed_console.db", [], lambda t, m: None,
                       clock=lambda: datetime(2026, 10, 7, 10, 0, tzinfo=ET).timestamp(),
                       failures=CaptureWriter(tmp_path / "stream_capture.db"), streamed=lambda s: None)
    client = schwab.client(tmp_path)
    stop = threading.Event()
    worker = threading.Thread(target=sweep.work, args=(lambda: client, stop), daemon=True)
    try:
        with caplog.at_level("INFO", logger="chain_history"):
            worker.start()
            time.sleep(1.5)
    finally:
        stop.set()
        worker.join(10)
        schwab.close()
    assert schwab.requests == [], "nothing asked of Schwab"
    assert not [r for r in caplog.records if "chain rotation" in r.getMessage()], "no rotation of nothing"


def test_the_contracts_a_console_named_are_withdrawn_when_its_connection_ends():
    """The daemon holds the option contracts of the console connection that sent them last; that
    connection ending withdraws them, and another connection ending (an old one noticed closed
    after the console reconnected) does not."""
    daemon = capture.Daemon(MessageBus(), HealthRegistry())
    a, b = object(), object()
    daemon.console_frame({"op": "options", "LEVELONE_OPTIONS": CONTRACTS[:1], "OPTIONS_BOOK": []}, a)
    daemon.console_frame({"op": "options", "LEVELONE_OPTIONS": CONTRACTS[1:2], "OPTIONS_BOOK": []}, b)
    daemon.console_frame(None, a)                                        # the old connection's end
    assert daemon.wanted()["LEVELONE_OPTIONS"] == frozenset(CONTRACTS[1:2])
    daemon.console_frame(None, b)                                        # the console's own connection ends
    assert daemon.wanted()["LEVELONE_OPTIONS"] == frozenset()


def test_the_console_names_its_option_contracts_for_the_daemon():
    """The primary contract on LEVELONE_OPTIONS and OPTIONS_BOOK, the views' contracts on
    LEVELONE_OPTIONS: the frame the console sends the daemon."""
    try:
        ofs.set_active_option_contract(CONTRACTS[0])
        ofs.set_active_option_contracts(CONTRACTS[1:])
        assert ofs.current_options() == {"op": "options", "LEVELONE_OPTIONS": CONTRACTS, "OPTIONS_BOOK": CONTRACTS[:1]}
    finally:
        ofs.set_active_option_contracts([])
        ofs.clear_active_option_contract(reason="test end")


def test_a_viewed_ticker_warms_only_on_the_watchlist_and_a_silent_daemon_says_so_first():
    """The gamma surface's reason for a ticker with no surface (server.get_options_gamma_surface):
    on the watchlist it warms (its chain is coming); off it, it says it is not on the watchlist;
    with the daemon's heartbeat late, every reason says first that the watchlist is unknown; a
    chain Schwab refused says Schwab's answer."""
    on, off = "ZZWLON", "ZZWLOFF"
    pages = [push_changes.subscribe(tk) for tk in (on, off)]
    with server._terrain_cache_lock:
        server._terrain_cache[off] = {"computed_ts_utc": time.time(), "spot": 100.0}   # levels, no surface
    try:
        lmp.record_feed_heartbeat({"ts": time.time(), "schwab_socket_open": True, "watchlist": [on]})
        d_on, d_off = (json.loads(server.get_options_gamma_surface(tk).body) for tk in (on, off))
        assert (d_on["warming"], d_on["reason"]) == (True, "no terrain snapshot has been computed yet")
        assert (d_off["warming"], d_off["reason"]) == (False, "no chain is fetched for this ticker: it is not on "
                                                              "the watchlist")
        server._on_chain(on, None, time.time(), "full chain returned HTTP 400")
        assert json.loads(server.get_options_gamma_surface(on).body)["reason"] == (
            "no terrain snapshot has been computed yet — chain fetch failed (full chain returned HTTP 400)")
        lmp.record_feed_heartbeat({"ts": time.time() - 100, "schwab_socket_open": True, "watchlist": [on]})
        silent = json.loads(server.get_options_gamma_surface(off).body)
        assert (silent["warming"], silent["reason"]) == (
            False, "the capture daemon is not reporting (no current heartbeat): its watchlist is unknown")
        assert "WATCHLIST UNKNOWN" in server._status_line()
    finally:
        for tk, page in zip((on, off), pages):
            push_changes.unsubscribe(tk, page)
        with server._terrain_cache_lock:
            server._terrain_cache.pop(off, None)
            server._terrain_cache.pop(on, None)
        server._terrain_refresh_last_error.pop(on, None)
        lmp.record_feed_down()


def test_the_ticker_on_screen_is_the_newest_open_page_and_asks_schwab_for_nothing():
    """One rule: the ticker on screen is the newest page still open (its /api/changes stream), in
    the order the pages open and close; it decides nothing the daemon asks Schwab for (the
    console's frame to the daemon names option contracts only)."""
    async def open_page(tk):
        stream = (await server.get_changes(ticker=tk)).body_iterator
        await stream.__anext__()                            # the page's connection is streaming
        return stream

    async def go():
        a = await open_page("ZZPAGEA")
        b = await open_page("ZZPAGEB")
        seen = [push_changes.on_screen(), set(ofs.current_options())]
        await b.aclose()
        seen.append(push_changes.on_screen())
        await a.aclose()
        return seen
    on_b, frame, on_a = asyncio.run(go())
    assert (on_b, on_a) == ("ZZPAGEB", "ZZPAGEA")
    assert frame == {"op", "LEVELONE_OPTIONS", "OPTIONS_BOOK"}


def test_the_page_is_told_the_market_context_with_its_display_names():
    """The header's market context, which the daemon streams whatever the watchlist holds, is
    served in the page with each symbol's display name."""
    html = server._with_live_ui_port(server._LIVE_UI_PORT_META + server._MARKET_CONTEXT_META)
    assert '[{"key": "$SPX", "display": "SPX"}, {"key": "$NDX", "display": "NDX"}, ' \
           '{"key": "$VIX", "display": "VIX"}]' in html.replace("&quot;", '"')
