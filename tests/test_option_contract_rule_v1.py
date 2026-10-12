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
real_spy_2026_11_20_chain_and_quotes.json; SPY's 2026-10-14 contracts as the console served them
(302, 242 of them with Schwab's -999 gamma and volatility), tests/fixtures/
real_spy_2026_10_14_chain_oi_zero.json. STAND-INS (named): each price reaches the daemon as a
LEVELONE_EQUITIES LAST_PRICE carrying the chain answer's price; the rule is applied at each
chain's capture time (the daemon's clock).
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
_SPY_NO_GAMMA = json.loads((_FX / "real_spy_2026_10_14_chain_oi_zero.json").read_text(encoding="utf-8"))
CHAINS = {"MRVL": flatten_chain_contracts(_MRVL["full"]), "SPY": _SPY["chain"]}
PRICES = {"MRVL": _MRVL["full"]["underlying"]["last"], "SPY": _SPY["spot"]}
MRVL_CLOSE = _MRVL["full"]["underlying"]["close"]
CAPTURED = _MRVL["captured_utc"]
L1, BOOK = "LEVELONE_OPTIONS", "OPTIONS_BOOK"


def _expires(ct: dict) -> float:
    return datetime.fromisoformat(ct["expirationDate"]).timestamp()


def _order(ct: dict, price: float) -> tuple:
    """Ed's order: the highest Schwab gamma first (absent, -999, or a -999 volatility is no gamma,
    last); of equal gammas the nearest expiration, then the strike nearest the price (the lower
    of two), calls before puts."""
    rest = (_expires(ct), abs(ct["strikePrice"] - price), ct["strikePrice"], ct["putCall"], ct["symbol"])
    gamma = ct.get("gamma")
    known = isinstance(gamma, (int, float)) and gamma != -999 and ct.get("volatility") != -999
    return (0, -gamma, *rest) if known else (1, *rest)


def by_definition(contracts: "list[dict]", price: float, n: int, now: float) -> "set[str]":
    """The rule's set, from its definition: of the contracts not expired at `now` (Schwab's
    expirationDate), the first `n` in Ed's order."""
    live = sorted((c for c in contracts if _expires(c) > now), key=lambda c: _order(c, price))
    return {c["symbol"] for c in live[:n]}


def _rule(chains: dict, prices: dict, now: float, watchlist: "list[str]", flow: "str | None" = None) -> "dict[str, set[str]]":
    taken = 1 if flow else 0
    out = {L1: set(), BOOK: set()}
    for tk in watchlist:
        for svc in (L1, BOOK):
            out[svc] |= by_definition(chains[tk], prices[tk], (capture.OPTION_LIMITS[svc] - taken) // len(watchlist), now)
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

    def chain(self, tk: str, ts: float = CAPTURED, contracts: "list[dict] | None" = None) -> None:
        for topic, msg in chain_messages(tk, CHAINS[tk] if contracts is None else contracts, ts):
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


def test_each_ticker_streams_its_highest_gamma_contracts_within_schwabs_limits(tmp_path):
    """MRVL and SPY on the watchlist: each streams its half of 3,000 on LEVELONE_OPTIONS (MRVL the
    1,500 of its 2,432 with the highest gamma; SPY all 442 of its 2026-11-20 contracts), and its
    half of 100 on OPTIONS_BOOK, the highest gamma of every expiration; Schwab holds every one and
    refuses none."""
    want = _rule(CHAINS, PRICES, CAPTURED, ["MRVL", "SPY"])
    market = _Market(tmp_path, ["MRVL", "SPY"], lambda: CAPTURED)

    async def steps(m):
        for tk in ("MRVL", "SPY"):
            m.chain(tk)
            m.price(tk, PRICES[tk])
        await _until(lambda: m.holds(want))
    market.run(steps)
    assert (len(want[L1]), len(want[BOOK])) == (1500 + 442, 100)
    assert set(_answers(market.streamer, L1)) == set(_answers(market.streamer, BOOK)) == {0}


def test_a_contract_without_gamma_streams_only_after_every_one_with_it(tmp_path):
    """SPY's 2026-10-14 chain as the console served it: 60 contracts with Schwab's gamma, 242 with
    -999. OPTIONS_BOOK's 100 are the 60, then the 40 without gamma nearest the price."""
    contracts, price, ts = _SPY_NO_GAMMA["contracts"], _SPY_NO_GAMMA["priced_at_spot"], _SPY_NO_GAMMA["chain_as_of_ts_utc"]
    with_gamma = {c["symbol"] for c in contracts if c["gamma"] != -999}
    want = _rule({"SPY": contracts}, {"SPY": price}, ts, ["SPY"])
    market = _Market(tmp_path, ["SPY"], lambda: ts)

    async def steps(m):
        m.chain("SPY", ts, contracts)
        m.price("SPY", price)
        await _until(lambda: m.holds(want))
    market.run(steps)
    assert len(with_gamma) == 60 and with_gamma < want[BOOK] and len(want[BOOK]) == 100
    assert len(want[L1]) == len(contracts)


def test_a_price_tick_asks_schwab_for_nothing_and_the_next_chain_only_the_difference(tmp_path):
    """MRVL moves from Schwab's last (263.51) to its close (258.95): nothing is asked. Its next
    chain, after its 2026-09-25 contracts expire at 20:00 UTC (Schwab still lists them), is ordered
    at the close price: one UNSUBS of the contracts that left and one ADD of those that came, on
    each option service, and no 2026-09-25 contract streams anywhere."""
    clock = [CAPTURED]
    expired = {c["symbol"] for c in CHAINS["MRVL"] if c["expirationDate"].startswith("2026-09-25")}
    after = _expires(next(c for c in CHAINS["MRVL"] if c["symbol"] in expired)) + 60
    before = _rule(CHAINS, PRICES, CAPTURED, ["MRVL", "SPY"])
    then = _rule(CHAINS, {**PRICES, "MRVL": MRVL_CLOSE}, after, ["MRVL", "SPY"])
    market = _Market(tmp_path, ["MRVL", "SPY"], lambda: clock[0])
    sent: dict = {}

    async def steps(m):
        for tk in ("MRVL", "SPY"):
            m.chain(tk)
            m.price(tk, PRICES[tk])
        await _until(lambda: m.holds(before))
        sent.update({s: len(m.streamer.asked(s)) for s in (L1, BOOK)})
        m.price("MRVL", MRVL_CLOSE)
        await asyncio.sleep(1.0)
        sent["after_tick"] = {s: len(m.streamer.asked(s)) for s in (L1, BOOK)}
        clock[0] = after
        m.chain("MRVL", after)
        await _until(lambda: m.holds(then))
    market.run(steps)
    assert sent["after_tick"] == {s: sent[s] for s in (L1, BOOK)}, "a price tick asks Schwab for nothing"
    for svc in (L1, BOOK):
        moved = [(c, sorted(k)) for c, k in market.streamer.asked(svc)[sent[svc]:]]
        assert moved == [("UNSUBS", sorted(before[svc] - then[svc])), ("ADD", sorted(then[svc] - before[svc]))], svc
        assert before[svc] != then[svc] and not expired & then[svc]
    assert expired & before[BOOK]


def test_a_watchlist_change_splits_schwabs_limits_again(tmp_path):
    """SPY removed from the watchlist: its contracts are released, and MRVL's share is all of
    3,000 (its 2,432 contracts) and all of 100 on OPTIONS_BOOK, its highest gamma."""
    market = _Market(tmp_path, ["MRVL", "SPY"], lambda: CAPTURED)
    want = _rule(CHAINS, PRICES, CAPTURED, ["MRVL"])

    async def steps(m):
        for tk in ("MRVL", "SPY"):
            m.chain(tk)
            m.price(tk, PRICES[tk])
        await _until(lambda: m.holds(_rule(CHAINS, PRICES, CAPTURED, ["MRVL", "SPY"])))
        m.daemon.console_frame({"op": "watchlist", "action": "remove", "ticker": "SPY", "id": 1}, None)
        await _until(lambda: m.holds(want))
    market.run(steps)
    assert len(want[L1]) == len(CHAINS["MRVL"]) and len(want[BOOK]) == 100


def test_the_flow_panels_contract_streams_on_both_services_on_top_of_the_rule(tmp_path):
    """Ed selects MRVL's last contract in the rule's order on the Flow panel, through the
    console's route and its socket to the daemon: Schwab streams it on LEVELONE_OPTIONS and
    OPTIONS_BOOK, and the rule splits what is left (2,999 and 99) across the watchlist. The console
    names it again on its next connection to a daemon (a restart)."""
    far = max(CHAINS["MRVL"], key=lambda c: _order(c, PRICES["MRVL"]))["symbol"]
    want = _rule(CHAINS, PRICES, CAPTURED, ["MRVL", "SPY"], flow=far)
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
    assert far not in by_definition(CHAINS["MRVL"], PRICES["MRVL"], 1500, CAPTURED)


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
