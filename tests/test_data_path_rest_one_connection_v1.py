"""The chain path, Schwab to the daemon's ledger, through the real code: the daemon's ChainSweep
asks Schwab's host (tests/schwab_rest_standin.py, on the real schwab-py client as the daemon builds
it) for each ticker's expiration chain, the market hours of each expiry date not yet answered that
day, its chain one expiry at a time and its contracts' quotes, QUOTES_BATCH_MAX symbols to a
request across tickers, one request at a time. REST only for what no stream carries (operator
2026-10-13): each contract's record opens from its chain entry once a day; its quote is asked for
only while the stream does not hold it, never for a contract the stream holds.

Real data: the stand-in's (SPY 2026-11-20 chain and quotes, TSLA 2026-10-09 chain) and the
LEVELONE_OPTIONS events of SPY 260904C00772000 (tests/fixtures/real_options_stream_history_samples.json).
STAND-INS: the held contract's stream messages are SPY 260904C00772000's events keyed as
SPY 261120C00875000, each with a Schwab time a second after the last, beginning a minute after its
quote (no captured stream of a 2026-11-20 contract carries its Greeks); the clock.
"""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime

from app.market_data.schwab.streaming import capture
from calibration.complete_chain_capture import ChainSweep
from schwab_client import QUOTES_BATCH_MAX
from stream_spine import HealthRegistry, MessageBus
from tests.schwab_rest_standin import (CHAIN, CHAINS, EXPIRATIONS, FX, MARKETS, QUOTES, SPY, SPY_QUOTES,
                                       TSLA, LocalSchwab, delivered)
from time_et import ET

_STREAM = next(c for c in json.loads((FX / "real_options_stream_history_samples.json")
                                     .read_text(encoding="utf-8"))["contracts"]
               if c["symbol"] == "SPY   260904C00772000")
HELD = "SPY   261120C00875000"
GREEKS = ("gamma", "delta", "theta", "vega", "rho", "volatility")
ALL = sorted(ct["symbol"] for _e, cts, _s in CHAINS.values() for ct in cts)


def _et(s: str) -> float:
    return datetime.fromisoformat(s).replace(tzinfo=ET).timestamp()


def _setup(tmp_path, schwab: LocalSchwab, now: float):
    """The daemon holding HELD on LEVELONE_OPTIONS, its sweep on a fixed clock posting to the
    daemon's bus (and kept in `published`), and the client."""
    client = schwab.client(tmp_path)
    daemon = capture.Daemon(MessageBus(), HealthRegistry(), ["SPY", "TSLA"])
    daemon.held["LEVELONE_OPTIONS"] = frozenset({HELD})          # Schwab accepted it on this connection
    published: list = []

    def publish(topic, msg):
        published.append((topic, msg))
        daemon.bus.publish(topic, msg)
    sweep = ChainSweep(daemon.watchlist, publish, clock=lambda: now,
                       held=lambda: daemon.held["LEVELONE_OPTIONS"])
    return daemon, sweep, (lambda: client), published


def _quoted(requests: list) -> "list[str]":
    return [s for path, q, *_ in requests if path == QUOTES for s in q["symbols"].split(",")]


def test_a_rotation_opens_every_contract_once_and_asks_only_what_the_stream_does_not_carry(tmp_path):
    schwab = LocalSchwab()
    daemon, sweep, client, published = _setup(tmp_path, schwab, _et("2026-10-01 10:15"))
    try:
        assert sweep.rotation(client, ["SPY", "TSLA"], threading.Event()) == {"SPY", "TSLA"}
        first = list(schwab.requests)
        sweep.rotation(client, ["SPY", "TSLA"], threading.Event())
        second = schwab.requests[len(first):]
    finally:
        schwab.close()

    asked = [(path, q.get("symbol") or q.get("date"), len(q["symbols"].split(",")) if "symbols" in q else None)
             for path, q, *_ in first]
    assert asked == [(EXPIRATIONS, "SPY", None), (MARKETS, "2026-11-20", None), (CHAIN, "SPY", None),
                     (EXPIRATIONS, "TSLA", None), (MARKETS, "2026-10-09", None), (CHAIN, "TSLA", None),
                     (QUOTES, None, QUOTES_BATCH_MAX), (QUOTES, None, len(ALL) - 1 - QUOTES_BATCH_MAX)], \
        "the opening: the expiration chain, each expiry's market hours, each expiry, then the quote " \
        "of every contract the stream does not hold as QUOTES_BATCH_MAX fill (the price history has " \
        "its own schedule)"
    for path, q, *_ in first:
        if path == CHAIN:
            assert (q["fromDate"], q["toDate"], q["range"]) == (CHAINS[q["symbol"]][0],) * 2 + ("ALL",)
    assert sorted(_quoted(first)) == [s for s in ALL if s != HELD], "the stream carries HELD: never asked"
    assert {s.split()[0] for s in _quoted(first)[:QUOTES_BATCH_MAX]} == {"SPY", "TSLA"}, "a request across tickers"
    assert all(b[2] >= a[3] for a, b in zip(first, first[1:])), "one request at a time"
    assert len({r[4] for r in first}) == 1, "on one connection"
    assert [p for p, *_ in second] == [QUOTES] * len([p for p, *_ in second]), "no chain asked again"
    assert sorted(_quoted(second)) == [s for s in ALL if s != HELD], "the stream carries HELD: never asked again"

    spy, tsla = delivered(published, "SPY"), delivered(published, "TSLA")
    assert len(spy) == len(SPY["chain"]) and len(tsla) == len(TSLA["chain"])
    for ct in (ct for ct in SPY["chain"] if ct["symbol"] != HELD):
        quote = SPY_QUOTES[ct["symbol"]]["quote"]
        record = spy[ct["symbol"]]
        assert {f: record[f] for f in GREEKS} == {f: quote[f] for f in GREEKS}, ct["symbol"]
        assert record["strikePrice"] == ct["strikePrice"] and record["putCall"] == ct["putCall"]
    rounded = {ct["symbol"]: ct["gamma"] for ct in SPY["chain"]}
    assert any(rounded[s] != spy[s]["gamma"] for s in spy), "the chain's rounded Greeks are never posted"
    assert all(f not in ct for ct in tsla.values() for f in GREEKS), "a Greek Schwab did not send is absent"
    answers = [(t, m["expiry"], m["status"]) for t, m in published if t.startswith("chainanswer.")]
    assert answers == [("chainanswer.SPY", "2026-11-20", 200), ("chainanswer.TSLA", "2026-10-09", 200)]
    expirations = [(t, m["status"], "expirationList" in m["answer"]) for t, m in published if t.startswith("expirationanswer.")]
    assert expirations == [("expirationanswer.SPY", 200, True), ("expirationanswer.TSLA", 200, True)], \
        "every Schwab answer saved as sent, the expiration chain's included"
    quotes = [m for t, m in published if t.startswith("quotesanswer.")]
    assert [len(m["symbols"]) for m in quotes] == [QUOTES_BATCH_MAX, len(ALL) - 1 - QUOTES_BATCH_MAX] * 2
    assert all(m["status"] == 200 and isinstance(m["answer"], dict) for m in quotes), "each answer as sent"


def test_a_held_contracts_stream_message_posts_over_its_rest_answer_by_schwabs_time(tmp_path):
    """Each field of a record is the newest Schwab sent: HELD's stream messages, newer than its
    quote, post their Greeks in place of the quote's, each with its own Schwab time."""
    schwab = LocalSchwab()
    daemon, sweep, client, _published = _setup(tmp_path, schwab, _et("2026-10-01 10:15"))
    try:
        sweep.rotation(client, ["SPY"], threading.Event())
    finally:
        schwab.close()
    handler = capture._publisher("LEVELONE_OPTIONS", daemon.bus, HealthRegistry())
    start = SPY_QUOTES[HELD]["quote"]["quoteTime"] + 60_000
    events = [e for e in _STREAM["events"] if e["kind"] == "l1"]
    for i, e in enumerate(events):
        handler({"timestamp": start + 1000 * i, "content": [{**e["content"], "key": HELD}]})
    _topic, record = daemon.bus.current[f"contract.{HELD}#ledger"]
    last = {}
    for i, e in enumerate(events):
        for f in GREEKS:
            if f.upper() in e["content"]:
                last[f] = (e["content"][f.upper()], start + 1000 * i)
    assert last, "the captured stream carries Greeks"
    assert {f: (record["fields"][f], record["field_ts"][f][0]) for f in last} == last


def test_a_contract_the_stream_takes_while_its_quote_is_asked_keeps_the_streams_values(tmp_path):
    """REST only for what no stream carries: a contract the stream took after its quote was asked
    (the option rule moved onto it) takes nothing from that quote; its record is the stream's."""
    schwab = LocalSchwab()
    daemon, sweep, client, published = _setup(tmp_path, schwab, _et("2026-10-01 10:15"))
    other = next(s for s in ALL if s.startswith("SPY") and s != HELD)
    asked = sweep.held

    def held_once_asked():                    # the stream holds `other` from its quote's answer on
        return asked() | ({other} if any(path == QUOTES for path, *_ in schwab.requests) else set())
    sweep.held = held_once_asked
    try:
        sweep.rotation(client, ["SPY"], threading.Event())
    finally:
        schwab.close()
    assert other in _quoted(schwab.requests), "asked while the stream did not hold it"
    # the chain's opening posts the contract's terms (its "symbol" among them); a quote does not
    posted = [m for t, m in published if t == f"contract.{other}" and "symbol" not in m["fields"]]
    assert posted == [], "a quote posted over the stream's contract"


def test_a_refused_quotes_request_fails_each_ticker_in_it_and_the_next_request_goes_at_once(tmp_path):
    schwab = LocalSchwab()
    schwab.quotes_status = 429
    _daemon, sweep, client, published = _setup(tmp_path, schwab, _et("2026-08-28 09:05"))
    try:
        assert sweep.rotation(client, ["SPY", "TSLA"], threading.Event()) == set()
        refused = list(schwab.requests)
        schwab.quotes_status = 200
        assert sweep.rotation(client, ["SPY", "TSLA"], threading.Event()) == {"SPY", "TSLA"}
        after = schwab.requests[len(refused):]
    finally:
        schwab.close()
    failed = [(topic, msg["failed"]) for topic, msg in published if "failed" in msg]
    assert failed == [("chain.SPY", f"quotes for {QUOTES_BATCH_MAX} contracts returned HTTP 429"),
                      ("chain.TSLA", f"quotes for {QUOTES_BATCH_MAX} contracts returned HTTP 429")]
    assert [p for p, *_ in refused].count(QUOTES) == 1, "the failed tickers' other contracts are not asked for"
    assert sorted(_quoted(after)) == [s for s in ALL if s != HELD], \
        "every contract not yet answered, and not streamed, is asked for in the next round"
    gaps = [b[2] - a[3] for a, b in zip(refused, refused[1:] + after[:1])]
    assert max(gaps) < 1.0, f"a pause after Schwab's 429: {max(gaps):.2f} s"


def test_outside_the_option_session_every_watchlist_ticker_is_fetched_once_and_a_failed_one_again(tmp_path):
    schwab = LocalSchwab()
    schwab.refuse_chain = {"TSLA"}
    _daemon, sweep, client, published = _setup(tmp_path, schwab, _et("2026-10-03 12:00"))   # Saturday
    stop = threading.Event()
    worker = threading.Thread(target=sweep.work, args=(client, stop), daemon=True)
    try:
        worker.start()
        deadline = time.monotonic() + 10
        while (len({t for t, m in published if t.startswith("chain.") and "failed" not in m}) < 2
               and time.monotonic() < deadline):
            time.sleep(0.05)
        settled = len(schwab.requests)
        time.sleep(1.5)
        idle = len(schwab.requests) == settled
    finally:
        stop.set()
        worker.join(10)
        schwab.close()
    chains = [(q["symbol"], q["fromDate"]) for q in schwab.asked(CHAIN)]
    assert chains == [("SPY", "2026-11-20"), ("TSLA", "2026-10-09"), ("TSLA", "2026-10-09")]
    assert [m["failed"] for t, m in published if "failed" in m] == ["chain for 2026-10-09 returned HTTP 502"]
    refused = [m for t, m in published if t == "chainanswer.TSLA" and m["status"] == 502]
    assert len(refused) == 1, "the refused answer is journaled as sent"
    assert idle, "the close values stand: nothing more is asked for until the next session"


def test_a_quotes_answer_that_is_not_json_fails_its_tickers_and_the_sweep_goes_on(tmp_path):
    """STAND-IN: a 200 answer whose body is not JSON. It is journaled as sent (its text), each
    ticker in the request is published as failed with the error, and the next rotation delivers."""
    schwab = LocalSchwab()
    schwab.quotes_body = b"<html>not json</html>"
    _daemon, sweep, client, published = _setup(tmp_path, schwab, _et("2026-08-28 09:05"))
    try:
        assert sweep.rotation(client, ["SPY"], threading.Event()) == set()
        schwab.quotes_body = None
        assert sweep.rotation(client, ["SPY"], threading.Event()) == {"SPY"}
    finally:
        schwab.close()
    (failed,) = [m["failed"] for _t, m in published if "failed" in m]
    assert failed.startswith("JSONDecodeError")
    assert [m["answer"] for t, m in published if t.startswith("quotesanswer.")][0] == "<html>not json</html>"


def test_contracts_schwab_names_invalid_get_no_quote_and_every_ticker_in_the_request_is_delivered(tmp_path, caplog):
    """Schwab's /quotes answers 200 with a quote per symbol it knows and, beside them, an errors
    entry naming the ones it does not (measured 2026-10-07: 8 SPY contracts its own chain lists,
    never quoted or traded). Every entry that is a quote posts; the 8 get no quote, logged once
    per request with their count; SPY and TSLA, which share a request, are both delivered. Real
    data: the 8 contracts' /chains entries and Schwab's errors entry as sent
    (tests/fixtures/real_spy_quotes_invalid_symbols_2026_10_07.json). STAND-IN: the 8 are served in
    SPY's chain answer beside its 2026-11-20 contracts, as one more expiry's."""
    invalid = json.loads((FX / "real_spy_quotes_invalid_symbols_2026_10_07.json").read_text(encoding="utf-8"))
    named = invalid["quotes_errors"]["invalidSymbols"]
    schwab = LocalSchwab()
    schwab.invalid = invalid["chain_entries"]
    _daemon, sweep, client, published = _setup(tmp_path, schwab, _et("2026-08-28 09:05"))
    with caplog.at_level("WARNING", logger="chain_history"):
        try:
            assert sweep.rotation(client, ["SPY", "TSLA"], threading.Event()) == {"SPY", "TSLA"}
        finally:
            schwab.close()
    assert [m for _t, m in published if "failed" in m] == [], "no ticker failed"
    answered = [q["symbols"].split(",") for q in schwab.asked(QUOTES) if set(named) & set(q["symbols"].split(","))]
    assert any({s.split()[0] for s in symbols} == {"SPY", "TSLA"} for symbols in answered), "a shared request"
    spy = delivered(published, "SPY")
    assert len(spy) == len(SPY["chain"]) + len(named)
    assert all(f not in spy[s] for s in named for f in GREEKS), "no quote: no Greek, never the chain's rounded one"
    for ct in (ct for ct in SPY["chain"] if ct["symbol"] != HELD):    # HELD is the stream's
        assert {f: spy[ct["symbol"]][f] for f in GREEKS} == {f: SPY_QUOTES[ct["symbol"]]["quote"][f] for f in GREEKS}
    assert len(delivered(published, "TSLA")) == len(TSLA["chain"])
    logged = [r.getMessage() for r in caplog.records]
    in_request = [[s for s in symbols if s in named] for symbols in answered]
    assert sum(len(n) for n in in_request) == len(named) == 8
    assert [m for m in logged if "named" in m] == [
        f"quotes for {len(symbols)} contracts: Schwab named symbols it does not know, which have no "
        f"quote: {json.dumps({'invalidSymbols': n})}" for symbols, n in zip(answered, in_request)], \
        "each request's named contracts logged once, as Schwab named them"


def test_after_the_days_opening_a_contract_schwab_no_longer_lists_has_no_record(tmp_path):
    """Day one (2026-10-01) opens TSLA's 2026-10-09 contracts; on day two (2026-10-12) that expiry
    has passed and Schwab lists none. After day two's opening round the daemon holds no TSLA record
    (an expired contract never feeds the levels), and SPY's, listed both days, stand."""
    import asyncio
    schwab = LocalSchwab()
    clock = {"now": _et("2026-10-01 10:15")}
    daemon, _sweep, client, published = _setup(tmp_path, schwab, 0.0)
    sweep = ChainSweep(daemon.watchlist, lambda t, m: (published.append((t, m)), daemon.bus.publish(t, m)),
                       clock=lambda: clock["now"], held=lambda: daemon.held["LEVELONE_OPTIONS"])

    def rotate() -> None:
        before = len(published)
        sweep.rotation(client, ["SPY", "TSLA"], threading.Event())

        async def take():
            for t, m in published[before:]:
                if t.startswith("chain."):
                    daemon._took_chain(t.split(".", 1)[1], m)
        asyncio.run(take())
    try:
        rotate()
        assert len(daemon.contracts("TSLA")) == len(TSLA["chain"])
        clock["now"] = _et("2026-10-12 10:15")
        rotate()
    finally:
        schwab.close()
    assert [m["opening"] for t, m in published if t == "chain.TSLA"] == [True, True]
    assert daemon.contracts("TSLA") == [], "a contract Schwab no longer lists kept its record"
    assert len(daemon.contracts("SPY")) == len(SPY["chain"])
