"""The option-contract rule, Schwab to the screen, through the real code.

The capture daemon's connection (capture.Daemon.run) on the real schwab-py StreamClient, logged
in to Schwab's streamer played locally with Schwab's limits (tests/schwab_stream_standin.py:
LEVELONE_OPTIONS 3,000 and OPTIONS_BOOK 100, measured live 2026-10-07); the rule's inputs on the
daemon's bus as the chain sweep and the stream publish them (follow_market); the console bound to
the daemon it runs in and its route (server.post_flow_contract). The question each test answers:
did Schwab get exactly what the rule asks for, and hold all of it.

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
from datetime import datetime
from itertools import zip_longest
from pathlib import Path

import pytest

import live_market_plane as lmp
import live_price_rows
import server
import time_et
from app.market_data.schwab.streaming import capture
from app.options.order_flow import streaming as ofs
from calibration.complete_chain_capture import chain_messages
from option_contract import read_chain
from schwab_client import flatten_chain_contracts
from stream_spine import HealthRegistry, MessageBus, quote_msg
from terrain_engine import strike_window
from tests.real_chains import CRWD, MRVL, SPY_FULL, TSLA
from tests.schwab_rest_standin import LocalSchwab
from tests.schwab_stream_standin import LocalStreamer
from time_et import ET

_FX = Path(__file__).parent / "fixtures"
_MRVL = json.loads((_FX / "real_mrvl_full_chain_vs_strike_window.json").read_text(encoding="utf-8"))
_SPY = json.loads((_FX / "real_spy_2026_11_20_chain_and_quotes.json").read_text(encoding="utf-8"))
_SPY_NO_GAMMA = json.loads(
    (_FX / "real_spy_2026_10_14_chain_oi_zero.json").read_text(encoding="utf-8")
)
CHAINS = {"MRVL": flatten_chain_contracts(_MRVL["full"]), "SPY": _SPY["chain"]}
PRICES = {"MRVL": _MRVL["full"]["underlying"]["last"], "SPY": _SPY["spot"]}
MRVL_CLOSE = _MRVL["full"]["underlying"]["close"]
CAPTURED = _MRVL["captured_utc"]
L1, BOOK = "LEVELONE_OPTIONS", "OPTIONS_BOOK"
_MARK = "ZZTAKEN"  # a ticker no test streams: its price marks what the follower has taken


def _expires(ct: dict) -> float:
    return datetime.fromisoformat(ct["expirationDate"]).timestamp()


def _order(ct: dict, price: float) -> tuple:
    """Ed's order among contracts equally near the heatmap's corner: the highest Schwab gamma first.

    Absent, -999, or a -999 volatility is no gamma, last; of equal gammas the nearest
    expiration, then the strike nearest the price (the lower of two), calls before puts.
    """
    rest = (
        _expires(ct),
        abs(ct["strikePrice"] - price),
        ct["strikePrice"],
        ct["putCall"],
        ct["symbol"],
    )
    gamma = ct.get("gamma")
    known = isinstance(gamma, (int, float)) and gamma != -999 and ct.get("volatility") != -999
    return (0, -gamma, *rest) if known else (1, *rest)


#: Schwab's limit on each option service, as its own code-19 answers on the daemon's connection
#: stated it (2026-10-07: "(LEVELONE_OPTIONS=3000, DISCARDED=1)", "(OPTIONS_BOOK=100, ...)"):
#: the stand-in streamer's, never the daemon's
SCHWAB_LIMITS = {L1: 3000, BOOK: 100}


def by_definition(contracts: list[dict], price: float, now: float) -> list[str]:
    """Return the rule's order of a chain, from its definition.

    Its contracts not expired at `now` (Schwab's expirationDate), the ones the heatmap shows
    first (operator 2026-11-10: "it is our code"): by the larger of the expiration's place among
    the chain's expirations and twice the strike's count of listed strikes from the one nearest
    the price (the lower of two equally near), then in Ed's order.
    """
    live = [c for c in contracts if _expires(c) > now]
    expirations = sorted({_expires(c) for c in live})
    strikes = sorted({c["strikePrice"] for c in live})
    centre = min(range(len(strikes)), key=lambda i: (abs(strikes[i] - price), strikes[i]))

    def distance(c: dict) -> int:
        return max(
            expirations.index(_expires(c)), 2 * abs(strikes.index(c["strikePrice"]) - centre)
        )

    return [c["symbol"] for c in sorted(live, key=lambda c: (distance(c), *_order(c, price)))]


def recorded_by_definition(contracts: list[dict], price: float, now: float) -> set[str]:
    """Return a chain's recorded contracts, from their definition.

    Its soonest expiration not passed at `now`, at the listed strike nearest the price (the
    lower of two equally near) and the 5 listed strikes each side of it.
    """
    live = [c for c in contracts if _expires(c) > now]
    soonest = min(_expires(c) for c in live)
    strikes = sorted({c["strikePrice"] for c in live if _expires(c) == soonest})
    centre = min(range(len(strikes)), key=lambda i: (abs(strikes[i] - price), strikes[i]))
    near = set(strikes[max(0, centre - 5) : centre + 6])
    return {c["symbol"] for c in live if _expires(c) == soonest and c["strikePrice"] in near}


def _dealt(rows: list[list[str]]) -> list[str]:
    """Each row's first, then each row's second, ..."""
    return [s for row in zip_longest(*rows) for s in row if s is not None]


def _rule(
    chains: dict,
    prices: dict,
    now: float,
    watchlist: list[str],
    flow: str | None = None,
    shown: tuple[str, ...] = (),
) -> dict[str, set[str]]:
    """What Schwab holds, in the rule's order.

    The Flow contract; every ticker's recorded contracts; every contract of the tickers a page
    shows (`shown`); every other ticker's. Each group dealt across its tickers: each ticker's
    first, each one's second, ... Up to Schwab's limit on each service: asked for more, Schwab
    states its limit and the daemon asks once more, for the first that many.
    """
    ranked = {tk: by_definition(chains[tk], prices[tk], now) for tk in watchlist}
    windows = {tk: recorded_by_definition(chains[tk], prices[tk], now) for tk in watchlist}
    recorded = [[s for s in ranked[tk] if s in windows[tk]] for tk in watchlist]
    on_page = [ranked[tk] for tk in watchlist if tk in shown]
    order = list(
        dict.fromkeys(
            [
                *([flow] if flow else []),
                *_dealt(recorded),
                *_dealt(on_page),
                *_dealt(list(ranked.values())),
            ]
        )
    )
    return {svc: set(order[: SCHWAB_LIMITS[svc]]) for svc in (L1, BOOK)}


async def _until(cond, seconds: float = 20.0) -> None:
    deadline = time_et.elapsed() + seconds
    while not cond():
        assert time_et.elapsed() < deadline, "not reached in time"
        await asyncio.sleep(0.02)


class _Market:
    """Schwab's streamer (with its limits) and REST host played locally, the daemon on them.

    Its bus is fed as the chain sweep and the stream feed it.
    """

    def __init__(self, tmp_path, watchlist: list[str], clock, keeps_what_fits: bool = True):
        self.streamer = LocalStreamer(SCHWAB_LIMITS, data={}, keeps_what_fits=keeps_what_fits)
        self.rest = LocalSchwab(self.streamer.url)
        self.client = self.rest.client(tmp_path)
        self.bus = MessageBus()
        self.daemon = capture.Daemon(self.bus, HealthRegistry(), watchlist, clock=clock)
        self.marks = 0  # the prices taken() has published

    def chain(self, tk: str, ts: float = CAPTURED, contracts: list[dict] | None = None) -> None:
        for topic, msg in chain_messages(
            tk, CHAINS[tk] if contracts is None else contracts, ts, None, None
        ):
            self.bus.publish(topic, msg)

    def price(self, tk: str, last: float) -> None:
        self.bus.publish(
            f"quote.{tk}",
            quote_msg(
                symbol=tk, last=last, src="schwab_l1", native={"key": tk, "LAST_PRICE": last}
            ),
        )

    async def taken(self) -> None:
        """Wait until the daemon's market follower has taken every message published before.

        A price for a ticker no test uses goes on the bus after them, and is taken in turn: the
        follower takes each topic's messages in order, and a chain published before it woke its
        own reader first.
        """
        self.marks += 1
        self.price(_MARK, self.marks)
        await _until(lambda: live_price_rows.spot(_MARK) == self.marks)

    def holds(self, want: dict[str, set[str]]) -> bool:
        return all(
            set(self.daemon.held[s]) == want[s] == set(self.streamer.held[s]) for s in (L1, BOOK)
        )

    def run(self, steps) -> None:
        async def go():
            stop = asyncio.Event()
            tasks = [
                asyncio.create_task(self.daemon.run(lambda: self.client, stop)),
                asyncio.create_task(self.daemon.follow_market(stop)),
            ]
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
            for tk in [*CHAINS, _MARK]:  # the plane rows these prices wrote
                lmp._by_ticker.pop(tk, None)
                lmp._fields_by_ticker.pop(tk, None)


def _answers(streamer, service: str) -> list[int]:
    return [
        a["response"][0]["content"]["code"]
        for a in streamer.answers
        if a["response"][0]["service"] == service
    ]


@pytest.mark.parametrize("keeps_what_fits", [True, False])
def test_each_ticker_streams_its_highest_gamma_contracts_within_schwabs_limits(
    tmp_path, keeps_what_fits
):
    """MRVL and SPY on the watchlist: Schwab is asked for every contract of both, on each service.

    LEVELONE_OPTIONS holds them all (MRVL's 2,432 and the 442 of SPY's 2026-11-20, under its
    3,000) and refuses nothing. OPTIONS_BOOK refuses, stating its limit of 100, and is asked
    once more, a SUBS of the first 100 of the rule's order (each ticker's highest gamma, dealt in
    turn), which it holds: whichever symbols of the refused request Schwab kept, the first that
    fit or none (induced: Schwab's document does not say which).
    """
    want = _rule(CHAINS, PRICES, CAPTURED, ["MRVL", "SPY"])
    market = _Market(tmp_path, ["MRVL", "SPY"], lambda: CAPTURED, keeps_what_fits)

    async def steps(m):
        for tk in ("MRVL", "SPY"):
            m.chain(tk)
            m.price(tk, PRICES[tk])
        await _until(lambda: m.holds(want))

    market.run(steps)
    assert (len(want[L1]), len(want[BOOK])) == (2432 + 442, 100)
    book = _answers(market.streamer, BOOK)
    assert set(_answers(market.streamer, L1)) == {0} and book[:2] == [19, 24] and book[-1] == 0
    subs = [len(keys) for command, keys in market.streamer.asked(BOOK) if command == "SUBS"]
    assert subs[0] > 100 and subs[1:] == [100], "asked again once, within the limit Schwab stated"


def test_a_contract_without_gamma_streams_after_the_ones_with_it_that_are_equally_near(tmp_path):
    """SPY's 2026-10-14 chain as the console served it: 60 contracts with Schwab's gamma.

    And 242 with -999, one expiration. OPTIONS_BOOK's 100 are every contract nearer the price
    than the last strike count it reaches, and of the contracts that far, the ones with gamma
    before any without.
    """
    contracts, price, ts = (
        _SPY_NO_GAMMA["contracts"],
        _SPY_NO_GAMMA["priced_at_spot"],
        _SPY_NO_GAMMA["chain_as_of_ts_utc"],
    )
    with_gamma = {c["symbol"] for c in contracts if c["gamma"] != -999}
    want = _rule({"SPY": contracts}, {"SPY": price}, ts, ["SPY"])
    market = _Market(tmp_path, ["SPY"], lambda: ts)

    async def steps(m):
        m.chain("SPY", ts, contracts)
        m.price("SPY", price)
        await _until(lambda: m.holds(want))

    market.run(steps)
    strikes = sorted({c["strikePrice"] for c in contracts})
    centre = strikes.index(min(strikes, key=lambda k: (abs(k - price), k)))
    far = {c["symbol"]: abs(strikes.index(c["strikePrice"]) - centre) for c in contracts}
    edge = max(far[s] for s in want[BOOK])
    at_edge = {s for s in far if far[s] == edge}
    assert len(with_gamma) == 60 and len(want[BOOK]) == 100
    assert {s for s in far if far[s] < edge} < want[BOOK]
    assert not (at_edge - want[BOOK]) & with_gamma or (at_edge & want[BOOK]) <= with_gamma
    assert len(want[L1]) == len(contracts)


def test_a_price_tick_asks_schwab_for_nothing_and_the_next_chain_only_the_difference(tmp_path):
    """MRVL moves from Schwab's last (263.51) to its close (258.95): nothing is asked.

    Its next chain, after its 2026-09-25 contracts expire at 20:00 UTC (Schwab still lists
    them), is ordered at the close price: on each option service one UNSUBS of the contracts
    that left and one ADD of those that came (none on LEVELONE_OPTIONS, which held every
    contract), and no 2026-09-25 contract streams anywhere.
    """
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
        await m.taken()
        sent["after_tick"] = {s: len(m.streamer.asked(s)) for s in (L1, BOOK)}
        clock[0] = after
        m.chain("MRVL", after)
        await _until(lambda: m.holds(then))

    market.run(steps)
    assert sent["after_tick"] == {s: sent[s] for s in (L1, BOOK)}, (
        "a price tick asks Schwab for nothing"
    )
    for svc in (L1, BOOK):
        moved = [(c, sorted(k)) for c, k in market.streamer.asked(svc)[sent[svc] :]]
        left, came = sorted(before[svc] - then[svc]), sorted(then[svc] - before[svc])
        assert moved == [(c, k) for c, k in (("UNSUBS", left), ("ADD", came)) if k], svc
        assert before[svc] != then[svc] and not expired & then[svc]
    assert expired & before[BOOK]
    assert then[L1] < before[L1] and then[BOOK] - before[BOOK]  # nothing to add, and an ADD


def test_a_chain_that_arrives_later_is_fitted_within_the_limit_schwab_stated(tmp_path):
    """MRVL's chain arrives alone, and SPY's once Schwab holds MRVL's contracts.

    OPTIONS_BOOK holds MRVL's first 100 of the rule's order, and has stated its limit. SPY's
    chain is fitted within it: one UNSUBS of MRVL's that give way and one ADD of as many of
    SPY's (its recorded contracts, then its share of the deal). LEVELONE_OPTIONS, which refused
    nothing, is asked for SPY's 442 on top. Schwab refuses nothing more: no contract past a
    limit it stated is asked for.
    """
    alone = _rule(CHAINS, PRICES, CAPTURED, ["MRVL"])
    both = _rule(CHAINS, PRICES, CAPTURED, ["MRVL", "SPY"])
    market = _Market(tmp_path, ["MRVL", "SPY"], lambda: CAPTURED)
    sent: dict = {}

    async def steps(m):
        m.chain("MRVL")
        m.price("MRVL", PRICES["MRVL"])
        await _until(lambda: m.holds(alone))
        sent.update({s: len(m.streamer.asked(s)) for s in (L1, BOOK)})
        sent["answers"] = len(m.streamer.answers)
        m.chain("SPY")
        m.price("SPY", PRICES["SPY"])
        await _until(lambda: m.holds(both))

    market.run(steps)
    for svc in (L1, BOOK):
        moved = [(c, sorted(k)) for c, k in market.streamer.asked(svc)[sent[svc] :]]
        left, came = sorted(alone[svc] - both[svc]), sorted(both[svc] - alone[svc])
        assert moved == [(c, k) for c, k in (("UNSUBS", left), ("ADD", came)) if k], svc
    spys = {c["symbol"] for c in CHAINS["SPY"]} & both[BOOK]
    recorded = recorded_by_definition(CHAINS["SPY"], PRICES["SPY"], CAPTURED)
    assert both[BOOK] - alone[BOOK] == spys and recorded < spys, "SPY's recorded ones, and more"
    assert len(alone[BOOK] - both[BOOK]) == len(spys) == 44
    assert alone[L1] < both[L1] and len(both[L1] - alone[L1]) == 442
    later = [
        a["response"][0]["content"]["code"] for a in market.streamer.answers[sent["answers"] :]
    ]
    assert later and set(later) == {0}, "Schwab refused nothing after it stated its limit"


def test_a_new_connection_is_asked_in_full_and_told_schwabs_limit_again(tmp_path):
    """Schwab drops the socket once it holds the rule's contracts.

    A limit Schwab stated belongs to the connection that heard it. The next one, a session that
    holds nothing, is asked for every contract again: OPTIONS_BOOK states its 100 again and is
    asked once more for the first 100, and Schwab holds the rule's contracts as before.
    """
    want = _rule(CHAINS, PRICES, CAPTURED, ["MRVL", "SPY"])
    market = _Market(tmp_path, ["MRVL", "SPY"], lambda: CAPTURED)
    sent: dict = {}

    def logins(m):
        return [r for r in m.streamer.requests if r["command"] == "LOGIN"]

    async def steps(m):
        for tk in ("MRVL", "SPY"):
            m.chain(tk)
            m.price(tk, PRICES[tk])
        await _until(lambda: m.holds(want))
        sent.update({s: len(m.streamer.asked(s)) for s in (L1, BOOK)})
        sent["answers"] = len(_answers(m.streamer, BOOK))
        await m.daemon.stream._socket.close()  # the socket is gone
        await _until(lambda: len(logins(m)) == 2 and m.holds(want))

    market.run(steps)
    again = {s: market.streamer.asked(s)[sent[s] :] for s in (L1, BOOK)}
    assert {k for _c, keys in again[L1] for k in keys} == want[L1], "every contract, once again"
    subs = [len(keys) for command, keys in again[BOOK] if command == "SUBS"]
    assert subs[0] > 100 and subs[1:] == [100], "told the limit again, asked once within it"
    book = _answers(market.streamer, BOOK)[sent["answers"] :]
    assert book[:2] == [19, 24] and book[-1] == 0


def test_the_rule_orders_a_chain_at_the_price_rows_price_and_waits_while_it_has_none(tmp_path):
    """The option rule's price is the price row's (live_price_rows.price_row).

    Not a second read of LAST_PRICE. Induced condition: after MRVL's last (263.51), Schwab marks
    LAST_PRICE invalid (-999), so the row has no price. MRVL's next chain, after its 2026-09-25
    contracts expire, is not ordered at the last price: the contracts held, and the contracts
    recorded, stay as they were. It is ordered at the next price Schwab sends (its close,
    258.95).
    """
    clock = [CAPTURED]
    expired = {c["symbol"] for c in CHAINS["MRVL"] if c["expirationDate"].startswith("2026-09-25")}
    after = _expires(next(c for c in CHAINS["MRVL"] if c["symbol"] in expired)) + 60
    before = _rule(CHAINS, PRICES, CAPTURED, ["MRVL", "SPY"])
    then = _rule(CHAINS, {**PRICES, "MRVL": MRVL_CLOSE}, after, ["MRVL", "SPY"])
    market = _Market(tmp_path, ["MRVL", "SPY"], lambda: clock[0])
    held: dict = {}

    async def steps(m):
        for tk in ("MRVL", "SPY"):
            m.chain(tk)
            m.price(tk, PRICES[tk])
        await _until(lambda: m.holds(before))
        recorded = m.daemon.saved_options
        m.price("MRVL", -999)
        clock[0] = after
        m.chain("MRVL", after)
        await m.taken()
        held.update(
            {s: set(m.daemon.held[s]) for s in (L1, BOOK)},
            recorded=(recorded, m.daemon.saved_options),
        )
        m.price("MRVL", MRVL_CLOSE)
        await _until(lambda: m.holds(then))
        held["then_recorded"] = m.daemon.saved_options

    market.run(steps)
    assert {s: held[s] for s in (L1, BOOK)} == {s: before[s] for s in (L1, BOOK)}, (
        "no chain is ordered at a price the row does not hold"
    )
    assert held["recorded"][1] == held["recorded"][0], (
        "the recorded window stands while the row has no price"
    )
    assert held["then_recorded"] != held["recorded"][0]  # at the next price it moves
    assert expired & before[L1] and not expired & then[L1]  # the next chain moved what is held


def test_a_watchlist_change_splits_schwabs_limits_again(tmp_path):
    """SPY removed from the watchlist: its contracts are released.

    MRVL's share is all of 3,000 (its 2,432 contracts) and all of 100 on OPTIONS_BOOK, its
    highest gamma.
    """
    market = _Market(tmp_path, ["MRVL", "SPY"], lambda: CAPTURED)
    want = _rule(CHAINS, PRICES, CAPTURED, ["MRVL"])

    async def steps(m):
        for tk in ("MRVL", "SPY"):
            m.chain(tk)
            m.price(tk, PRICES[tk])
        await _until(lambda: m.holds(_rule(CHAINS, PRICES, CAPTURED, ["MRVL", "SPY"])))
        m.daemon.console_frame({"op": "watchlist", "action": "remove", "ticker": "SPY", "id": 1})
        await _until(lambda: m.holds(want))

    market.run(steps)
    assert len(want[L1]) == len(CHAINS["MRVL"]) and len(want[BOOK]) == 100


def test_a_ticker_removed_and_added_again_records_nothing_until_its_next_chain(tmp_path):
    """SPY removed from the watchlist and added again, then a SPY price.

    Its check is answered by Schwab's /quotes, as captured. No SPY contract is recorded from the
    window it had before it was removed, and its price row's price orders nothing, until its
    next chain arrives.
    """
    market = _Market(tmp_path, ["MRVL", "SPY"], lambda: CAPTURED)
    spy = {c["symbol"] for c in CHAINS["SPY"]}
    seen: dict = {}

    async def steps(m):
        for tk in ("MRVL", "SPY"):
            m.chain(tk)
            m.price(tk, PRICES[tk])
        await _until(lambda: m.holds(_rule(CHAINS, PRICES, CAPTURED, ["MRVL", "SPY"])))
        seen["before"] = m.daemon.saved_options & spy
        m.daemon.console_frame({"op": "watchlist", "action": "remove", "ticker": "SPY", "id": 1})
        await _until(lambda: "SPY" not in m.daemon.watchlist)
        m.daemon.console_frame({"op": "watchlist", "action": "add", "ticker": "SPY", "id": 2})
        await _until(lambda: "SPY" in m.daemon.watchlist)
        m.price("SPY", PRICES["SPY"])
        await m.taken()
        seen["re_added"] = m.daemon.saved_options & spy
        m.chain("SPY")
        await _until(lambda: m.daemon.saved_options & spy)
        seen["next_chain"] = m.daemon.saved_options & spy

    market.run(steps)
    assert seen["before"] and seen["re_added"] == set(), "no window from before the removal"
    assert seen["next_chain"] == seen["before"]  # the same chain at the same price


def test_a_chain_that_arrives_after_its_ticker_is_removed_records_nothing(tmp_path):
    """SPY removed, then its chain sweep's last chain of it arrives.

    The sweep's batch was taken before the removal: no SPY contract is recorded.
    """
    market = _Market(tmp_path, ["MRVL", "SPY"], lambda: CAPTURED)
    spy = {c["symbol"] for c in CHAINS["SPY"]}
    seen: dict = {}

    async def steps(m):
        for tk in ("MRVL", "SPY"):
            m.chain(tk)
            m.price(tk, PRICES[tk])
        await _until(lambda: m.daemon.saved_options & spy)
        m.daemon.console_frame({"op": "watchlist", "action": "remove", "ticker": "SPY", "id": 1})
        await _until(lambda: "SPY" not in m.daemon.watchlist)
        m.chain("SPY")
        m.price("SPY", PRICES["SPY"])
        await m.taken()
        seen["after"] = m.daemon.saved_options & spy

    market.run(steps)
    assert seen["after"] == set()


def test_the_flow_panels_contract_streams_on_both_services_on_top_of_the_rule(tmp_path):
    """Ed selects MRVL's last contract in the rule's order on the Flow panel.

    Through the console's route to the daemon it runs in: Schwab streams it on LEVELONE_OPTIONS,
    which held every contract already, and on OPTIONS_BOOK, where it is the first of the 100 and
    the rule's first 99 follow. Ed's selection cleared, Schwab holds the rule's contracts alone
    again.
    """
    far = max(CHAINS["MRVL"], key=lambda c: _order(c, PRICES["MRVL"]))["symbol"]
    want = _rule(CHAINS, PRICES, CAPTURED, ["MRVL", "SPY"], flow=far)
    rule_alone = _rule(CHAINS, PRICES, CAPTURED, ["MRVL", "SPY"])
    market = _Market(tmp_path, ["MRVL", "SPY"], lambda: CAPTURED)
    # the console holds MRVL's chain, published by the one producer at its capture
    server._publish_levels(
        "MRVL",
        read_chain(CHAINS["MRVL"]),
        CAPTURED,
        chain_spot=(PRICES["MRVL"], CAPTURED),
        now=datetime.fromtimestamp(CAPTURED, ET),
    )
    held: dict = {}

    async def steps(m):
        for tk in ("MRVL", "SPY"):
            m.chain(tk)
            m.price(tk, PRICES[tk])
        ofs.bind_daemon(m.daemon)  # the console runs in this daemon's program
        answer = await server.post_flow_contract(server.FlowContract(contract=far))
        await _until(lambda: m.holds(want))
        held.update({s: set(m.daemon.held[s]) for s in (L1, BOOK)})
        cleared = server.FlowContract(contract=None)  # Ed's selection cleared
        assert await server.post_flow_contract(cleared) == {"ok": True, "contract": None}
        await _until(lambda: m.daemon.flow_contract is None and m.holds(rule_alone))
        assert answer == {"ok": True, "contract": far}

    try:
        market.run(steps)
    finally:
        ofs._daemon = None
        with server._terrain_cache_lock:
            server._terrain_cache.pop("MRVL", None)
    assert far in held[L1] and far in held[BOOK]
    # the rule alone streams it on LEVELONE_OPTIONS and not on OPTIONS_BOOK: the selection did
    assert far in rule_alone[L1] and far not in rule_alone[BOOK]


def test_the_ticker_a_page_shows_takes_schwabs_slots_and_a_switch_moves_them(tmp_path):
    """Operator 2026-11-11: the ticker on the screen first, and the others may lag.

    MRVL (2026-09-25's chain) and SPY's whole chain of 2026-11-09 (more contracts than
    LEVELONE_OPTIONS' 3,000) on the watchlist, at SPY's capture time. No page: Schwab's slots
    are dealt across both. A page selects SPY: every slot is SPY's but the recorded contracts
    of MRVL, which stay streamed so the writer still records them. The page switches to MRVL:
    every MRVL contract not expired streams, and SPY keeps the rest. On OPTIONS_BOOK (100) the
    recorded contracts of both come first and the shown ticker takes the rest.
    """
    now = SPY_FULL.now.timestamp()
    chains = {"MRVL": CHAINS["MRVL"], "SPY": SPY_FULL.chain}
    prices = {"MRVL": PRICES["MRVL"], "SPY": SPY_FULL.spot}
    both = ["MRVL", "SPY"]
    dealt = _rule(chains, prices, now, both)
    spy_shown = _rule(chains, prices, now, both, shown=("SPY",))
    mrvl_shown = _rule(chains, prices, now, both, shown=("MRVL",))
    on_page: set[str] = set()
    market = _Market(tmp_path, both, lambda: now)
    market.daemon.on_page = lambda: on_page

    async def steps(m):
        for tk in both:
            m.chain(tk, now, chains[tk])
            m.price(tk, prices[tk])
        await _until(lambda: m.holds(dealt))
        on_page.add("SPY")
        m.daemon.page_selected("SPY")
        await _until(lambda: m.holds(spy_shown))
        on_page.clear()
        on_page.add("MRVL")
        m.daemon.page_selected("MRVL")
        await _until(lambda: m.holds(mrvl_shown))

    try:
        market.run(steps)
    finally:
        server.stop_terrain_loop()  # the reprices the selections queued
    spy = {c["symbol"] for c in chains["SPY"]}
    mrvl_live = {c["symbol"] for c in chains["MRVL"] if _expires(c) > now}
    mrvl_recorded = recorded_by_definition(chains["MRVL"], prices["MRVL"], now)
    spy_recorded = recorded_by_definition(chains["SPY"], prices["SPY"], now)
    assert len(spy) > 3000 > len(mrvl_live) > 1500, "SPY alone is past Schwab's limit"
    assert all(len(held[L1]) == 3000 for held in (dealt, spy_shown, mrvl_shown))
    assert len(dealt[L1] & spy) == 1500, "no page: half of Schwab's slots each"
    assert spy_shown[L1] - spy == mrvl_recorded, "SPY on a page: every slot but MRVL's recorded"
    assert mrvl_live < mrvl_shown[L1] and spy_recorded < mrvl_shown[L1]
    assert mrvl_shown[L1] - mrvl_live < spy, "MRVL on a page: all of it, and SPY the rest"
    for held, shown in ((spy_shown, spy), (mrvl_shown, mrvl_live)):
        assert mrvl_recorded | spy_recorded < held[BOOK]
        assert held[BOOK] - mrvl_recorded - spy_recorded < shown, "the books left: the shown one's"


def test_a_contract_no_chain_the_console_holds_lists_is_not_taken():
    """The route takes only a contract Schwab listed in a chain the console holds."""
    selected = server.FlowContract(contract="ZZZZ  261120C00100000")
    daemon = capture.Daemon(MessageBus(), HealthRegistry())
    ofs.bind_daemon(daemon)
    try:
        answer = asyncio.run(server.post_flow_contract(selected))
    finally:
        ofs.bind_daemon(None)
    assert answer.status_code == 409 and daemon.flow_contract is None


@pytest.mark.parametrize("real", [SPY_FULL, CRWD, TSLA, MRVL], ids=lambda real: real.ticker)
def test_every_contract_the_heatmap_shows_is_in_the_tickers_share_of_schwabs_limit(real):
    """The heatmap's Auto window: strike_window's rows by as many of the nearest expirations.

    Production streams eight tickers, so each has an eighth of LEVELONE_OPTIONS' 3000. Every
    contract of the window comes within it (on 2026-11-10, under the highest gamma first, 20 to
    78 of each ticker's 121 cells were not streamed).
    """
    now = real.now.timestamp()
    listed = [c for c in read_chain(real.chain) if c.expires_at > now]
    strikes = sorted({c.strike for c in listed})
    first, last, _centre = strike_window(strikes, real.spot, "auto")
    rows = set(strikes[first : last + 1])
    columns = set(sorted({c.expires_at for c in listed})[: len(rows)])
    shown = {c.symbol for c in listed if c.strike in rows and c.expires_at in columns}
    share = set(capture.shown_first(listed, real.spot, now)[: SCHWAB_LIMITS[L1] // 8])
    assert len(shown) > len(rows) and shown <= share
