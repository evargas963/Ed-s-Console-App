"""The option-contract rule, Schwab to the screen, through the real code: the capture daemon's
connection (capture.Daemon.run) on the real schwab-py StreamClient, logged in to Schwab's streamer
played locally with Schwab's limits (tests/schwab_stream_standin.py: LEVELONE_OPTIONS 3,000 and
OPTIONS_BOOK 100, measured live 2026-10-07); the rule's inputs on the daemon's bus as the chain
sweep and the stream publish them (follow_market); the console's side of its socket and its route
(server.post_flow_contract). The question each test answers: did Schwab get exactly what the rule
asks for, and hold all of it.

Real data: MRVL's full chain as Schwab sent it (2,432 contracts, 21 expirations, captured
2026-09-25 12:27 ET, tests/fixtures/real_mrvl_full_chain_vs_strike_window.json), with the
underlying `last` (263.51) and `close` (258.95) Schwab sent in the same answer; SPY's 2026-11-20
contracts (442) with their stored underlying price (766.31), tests/fixtures/
real_spy_2026_11_20_chain_and_quotes.json. STAND-INS (named): each price reaches the daemon as a
LEVELONE_EQUITIES LAST_PRICE carrying the chain answer's price; the rule is applied at MRVL's
capture time (the daemon's clock), when its front expiration (2026-09-25 20:00 UTC) has not passed.
"""
from __future__ import annotations

import asyncio
import json
import socket
import time
from datetime import datetime
from pathlib import Path

import server
from app.market_data.schwab.streaming import capture
from app.market_data.schwab.streaming.live_push import serve_live_push
from app.options.order_flow import streaming as ofs
from calibration.complete_chain_capture import chain_messages
from schwab_client import flatten_chain_contracts
from stream_spine import HealthRegistry, MessageBus, quote_msg
from tests.schwab_rest_standin import LocalSchwab
from tests.schwab_stream_standin import LocalStreamer

_FX = Path(__file__).parent / "fixtures"
_MRVL = json.loads((_FX / "real_mrvl_full_chain_vs_strike_window.json").read_text(encoding="utf-8"))
_SPY = json.loads((_FX / "real_spy_2026_11_20_chain_and_quotes.json").read_text(encoding="utf-8"))
CHAINS = {"MRVL": flatten_chain_contracts(_MRVL["full"]), "SPY": _SPY["chain"]}
PRICES = {"MRVL": _MRVL["full"]["underlying"]["last"], "SPY": _SPY["spot"]}
MRVL_CLOSE = _MRVL["full"]["underlying"]["close"]
CAPTURED = _MRVL["captured_utc"]
L1, BOOK = "LEVELONE_OPTIONS", "OPTIONS_BOOK"


def _expires(ct: dict) -> float:
    return datetime.fromisoformat(ct["expirationDate"]).timestamp()


def nearest_by_definition(contracts: "list[dict]", price: float, n: int, now: float, front: bool) -> "set[str]":
    """The rule's set, from its definition: the contracts not expired at `now` (Schwab's
    expirationDate), on the nearest expiration alone for the book, ordered by distance of the
    strike from the price (of two strikes equally near, the lower), then nearest expiration,
    then calls before puts; the first `n`."""
    live = [c for c in contracts if _expires(c) > now]
    if front:
        first = min(_expires(c) for c in live)
        live = [c for c in live if _expires(c) == first]
    live.sort(key=lambda c: (abs(c["strikePrice"] - price), c["strikePrice"], _expires(c), c["putCall"], c["symbol"]))
    return {c["symbol"] for c in live[:n]}


def _rule(prices: dict, now: float, watchlist: "list[str]", flow: "str | None" = None) -> "dict[str, set[str]]":
    taken = 1 if flow else 0
    out = {L1: set(), BOOK: set()}
    for tk in watchlist:
        out[L1] |= nearest_by_definition(CHAINS[tk], prices[tk], (3000 - taken) // len(watchlist), now, False)
        out[BOOK] |= nearest_by_definition(CHAINS[tk], prices[tk], (100 - taken) // len(watchlist), now, True)
    if flow:
        out[L1].add(flow)
        out[BOOK].add(flow)
    return out


async def _until(cond, seconds: float = 20.0) -> None:
    deadline = time.monotonic() + seconds
    while not cond():
        assert time.monotonic() < deadline, "not reached in time"
        await asyncio.sleep(0.02)


class _Market:
    """Schwab's streamer (with its limits) and REST host played locally, the daemon on them, and
    its bus fed as the chain sweep and the stream feed it."""

    def __init__(self, tmp_path, watchlist: "list[str]", clock):
        self.streamer = LocalStreamer(capture.OPTION_LIMITS)
        self.rest = LocalSchwab(self.streamer.url)
        self.client = self.rest.client(tmp_path)
        self.bus = MessageBus()
        self.daemon = capture.Daemon(self.bus, HealthRegistry(), watchlist, clock=clock)

    def chain(self, tk: str, ts: float = CAPTURED) -> None:
        for topic, msg in chain_messages(tk, CHAINS[tk], ts):
            self.bus.publish(topic, msg)

    def price(self, tk: str, last: float) -> None:
        self.bus.publish(f"quote.{tk}", quote_msg(symbol=tk, last=last, src="schwab_l1",
                                                  native={"key": tk, "LAST_PRICE": last}))

    def holds(self, want: "dict[str, set[str]]") -> bool:
        return all(set(self.daemon.held[s]) == want[s] == set(self.streamer.held[s]) for s in (L1, BOOK))

    def run(self, steps) -> None:
        async def go():
            stop = asyncio.Event()
            tasks = [asyncio.create_task(self.daemon.run(lambda: self.client, stop)),
                     asyncio.create_task(self.daemon.follow_market(stop))]
            try:
                await steps(self)
            finally:
                stop.set()
                await asyncio.wait_for(asyncio.gather(*tasks), 10)
        try:
            asyncio.run(go())
        finally:
            self.streamer.close()
            self.rest.close()


def _answers(streamer, service: str) -> "list[int]":
    return [a["response"][0]["content"]["code"] for a in streamer.answers
            if a["response"][0]["service"] == service]


def test_each_ticker_streams_its_contracts_nearest_its_own_price_within_schwabs_limits(tmp_path):
    """MRVL and SPY on the watchlist: each streams its half of 3,000 on LEVELONE_OPTIONS (MRVL 1,500
    of its 2,432; SPY all 442 of its 2026-11-20 contracts), and its half of 100 on OPTIONS_BOOK on
    its nearest expiration; Schwab holds every one and refuses none."""
    want = _rule(PRICES, CAPTURED, ["MRVL", "SPY"])
    market = _Market(tmp_path, ["MRVL", "SPY"], lambda: CAPTURED)

    async def steps(m):
        for tk in ("MRVL", "SPY"):
            m.chain(tk)
            m.price(tk, PRICES[tk])
        await _until(lambda: m.holds(want))
    market.run(steps)
    assert (len(want[L1]), len(want[BOOK])) == (1500 + 442, 100)
    assert set(_answers(market.streamer, L1)) == set(_answers(market.streamer, BOOK)) == {0}


def test_a_price_move_asks_schwab_for_only_the_difference(tmp_path):
    """MRVL moves from Schwab's last (263.51) to its close (258.95): one UNSUBS of the contracts no
    longer nearest and one ADD of the newly nearest, on each option service, and nothing else."""
    before = _rule(PRICES, CAPTURED, ["MRVL", "SPY"])
    after = _rule({**PRICES, "MRVL": MRVL_CLOSE}, CAPTURED, ["MRVL", "SPY"])
    market = _Market(tmp_path, ["MRVL", "SPY"], lambda: CAPTURED)
    sent: dict = {}

    async def steps(m):
        for tk in ("MRVL", "SPY"):
            m.chain(tk)
            m.price(tk, PRICES[tk])
        await _until(lambda: m.holds(before))
        sent.update({s: len(m.streamer.asked(s)) for s in (L1, BOOK)})
        m.price("MRVL", MRVL_CLOSE)
        await _until(lambda: m.holds(after))
    market.run(steps)
    for svc in (L1, BOOK):
        moved = [(c, sorted(k)) for c, k in market.streamer.asked(svc)[sent[svc]:]]
        assert moved == [("UNSUBS", sorted(before[svc] - after[svc])), ("ADD", sorted(after[svc] - before[svc]))], svc
        assert before[svc] != after[svc]


def test_a_watchlist_change_splits_schwabs_limits_again(tmp_path):
    """SPY removed from the watchlist: its contracts are released, and MRVL's share is all of
    3,000 (its 2,432 contracts) and all of 100 on its nearest expiration."""
    market = _Market(tmp_path, ["MRVL", "SPY"], lambda: CAPTURED)
    want = _rule(PRICES, CAPTURED, ["MRVL"])

    async def steps(m):
        for tk in ("MRVL", "SPY"):
            m.chain(tk)
            m.price(tk, PRICES[tk])
        await _until(lambda: m.holds(_rule(PRICES, CAPTURED, ["MRVL", "SPY"])))
        m.daemon.console_frame({"op": "watchlist", "action": "remove", "ticker": "SPY", "id": 1}, None)
        await _until(lambda: m.holds(want))
    market.run(steps)
    assert len(want[L1]) == len(CHAINS["MRVL"]) and len(want[BOOK]) == 100


def test_an_expiration_schwab_still_lists_is_never_streamed_once_it_has_passed(tmp_path):
    """MRVL's 2026-09-25 contracts expire at 20:00 UTC (Schwab's expirationDate). Before it, the
    books stream that expiration; the chain Schwab sends after it still lists them, and then the
    books stream the next expiration (2026-10-02) and no 2026-09-25 contract streams anywhere."""
    clock = [CAPTURED]
    expired = {c["symbol"] for c in CHAINS["MRVL"] if c["expirationDate"].startswith("2026-09-25")}
    after = _expires(next(c for c in CHAINS["MRVL"] if c["symbol"] in expired)) + 60
    market = _Market(tmp_path, ["MRVL"], lambda: clock[0])
    held: dict = {}

    async def steps(m):
        m.chain("MRVL")
        m.price("MRVL", PRICES["MRVL"])
        await _until(lambda: m.holds(_rule(PRICES, CAPTURED, ["MRVL"])))
        held["before"] = set(m.daemon.held[BOOK])
        clock[0] = after
        m.chain("MRVL", after)                                   # the next pass: Schwab still lists them
        await _until(lambda: m.holds(_rule(PRICES, after, ["MRVL"])))
        held.update({s: set(m.daemon.held[s]) for s in (L1, BOOK)})
    market.run(steps)
    assert held["before"] <= expired
    assert not expired & (held[L1] | held[BOOK])
    assert {c["expirationDate"][:10] for c in CHAINS["MRVL"] if c["symbol"] in held[BOOK]} == {"2026-10-02"}


def test_the_flow_panels_contract_streams_on_both_services_on_top_of_the_rule(tmp_path):
    """Ed selects MRVL's farthest contract on the Flow panel, through the console's route and its
    socket to the daemon: Schwab streams it on LEVELONE_OPTIONS and OPTIONS_BOOK, and the rule
    splits what is left (2,999 and 99) across the watchlist. The console names it again on its
    next connection to a daemon (a restart)."""
    far = max(CHAINS["MRVL"], key=lambda c: (abs(c["strikePrice"] - PRICES["MRVL"]), _expires(c)))["symbol"]
    want = _rule(PRICES, CAPTURED, ["MRVL", "SPY"], flow=far)
    market = _Market(tmp_path, ["MRVL", "SPY"], lambda: CAPTURED)
    with server._terrain_cache_lock:                              # the console holds MRVL's chain
        server._terrain_cache["MRVL"] = {"_contract_symbols": frozenset(c["symbol"] for c in CHAINS["MRVL"])}
    restarted = capture.Daemon(MessageBus(), HealthRegistry(), ["MRVL"])
    held: dict = {}

    async def steps(m):
        from websockets.asyncio.client import connect
        for tk in ("MRVL", "SPY"):
            m.chain(tk)
            m.price(tk, PRICES[tk])
        stop = asyncio.Event()
        ports = [_free_port(), _free_port()]
        sockets = [asyncio.create_task(serve_live_push(m.bus, stop, port=ports[0], on_request=m.daemon.console_frame)),
                   asyncio.create_task(serve_live_push(MessageBus(), stop, port=ports[1],
                                                       on_request=restarted.console_frame))]
        ws = await _connect(connect, ports[0])
        console = asyncio.create_task(ofs.serve_push(ws))
        await _until(lambda: ofs._push_ws is ws)
        answer = await server.post_flow_contract({"contract": far})
        await _until(lambda: m.holds(want))
        held.update({s: set(m.daemon.held[s]) for s in (L1, BOOK)})
        await ws.close()
        await asyncio.wait_for(console, 5)
        ws2 = await _connect(connect, ports[1])                    # the console's next daemon
        console2 = asyncio.create_task(ofs.serve_push(ws2))
        await _until(lambda: restarted.flow_contract == far)
        await server.post_flow_contract({"contract": None})       # Ed's selection cleared
        await _until(lambda: restarted.flow_contract is None)
        await ws2.close()
        await asyncio.wait_for(console2, 5)
        stop.set()
        await asyncio.gather(*sockets)
        assert answer == {"ok": True, "contract": far}
    try:
        market.run(steps)
    finally:
        with server._terrain_cache_lock:
            server._terrain_cache.pop("MRVL", None)
    assert far in held[L1] and far in held[BOOK]
    assert far not in nearest_by_definition(CHAINS["MRVL"], PRICES["MRVL"], 1500, CAPTURED, False)


def test_a_contract_no_chain_the_console_holds_lists_is_not_taken():
    """The route takes only a contract Schwab listed in a chain the console holds."""
    answer = asyncio.run(server.post_flow_contract({"contract": "ZZZZ  261120C00100000"}))
    assert answer.status_code == 409 and ofs._flow_contract is None


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _connect(connect, port: int):
    for _ in range(100):
        try:
            return await connect(f"ws://127.0.0.1:{port}", max_size=None)
        except OSError:
            await asyncio.sleep(0.05)
    raise AssertionError(f"nothing listening on {port}")
