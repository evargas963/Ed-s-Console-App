"""The chain path, Schwab to the console's bus, through the real code: the daemon's ChainSweep asks
Schwab's host (tests/schwab_rest_standin.py, on the real schwab-py client as the daemon builds it)
for each ticker's expiration chain, its chain one expiry at a time and its contracts' quotes, 300
symbols to a request across tickers, one request at a time. Each chain reaches the bus with
Schwab's exact Greeks and their times: the stream's for a contract the stream holds
(Daemon.option_record), the quote's for every other.

Real data: the stand-in's (SPY 2026-11-20 chain and quotes, TSLA 2026-08-31 chain) and the
LEVELONE_OPTIONS events of SPY 260904C00772000 (tests/fixtures/real_options_stream_history_samples.json).
STAND-INS: the held contract's stream record is SPY 260904C00772000's events keyed as
SPY 261120C00875000, each with its receive time as Schwab's frame time (no captured stream of a
2026-11-20 contract carries its Greeks); the clock.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from datetime import datetime

from app.market_data.schwab.streaming import capture
from calibration.complete_chain_capture import ChainSweep
from stream_spine import CaptureWriter, HealthRegistry, MessageBus, options_quote_msg
from tests.schwab_rest_standin import (CHAIN, CHAINS, EXPIRATIONS, FX, QUOTES, SPY, SPY_QUOTES, TSLA,
                                       LocalSchwab, delivered)
from time_et import ET

_STREAM = next(c for c in json.loads((FX / "real_options_stream_history_samples.json")
                                     .read_text(encoding="utf-8"))["contracts"]
               if c["symbol"] == "SPY   260904C00772000")
HELD = "SPY   261120C00875000"
GREEKS = ("gamma", "delta", "theta", "vega", "rho", "volatility")


def _et(s: str) -> float:
    return datetime.fromisoformat(s).replace(tzinfo=ET).timestamp()


def _setup(tmp_path, schwab: LocalSchwab, now: float):
    """The daemon's bus holding HELD's stream record, its sweep on a fixed clock, and the client."""
    client = schwab.client(tmp_path)
    daemon = capture.Daemon(MessageBus(), HealthRegistry(), board=["SPY", "TSLA"])
    daemon.held["LEVELONE_OPTIONS"] = frozenset({HELD})          # Schwab accepted it on this connection
    for e in _STREAM["events"]:
        if e["kind"] == "l1":
            daemon.bus.publish(f"optquote.{HELD}", options_quote_msg(
                symbol=HELD, content={**e["content"], "key": HELD}, src="schwab_options_l1",
                ts_recv=e["ts_recv"], schwab_ts=int(e["ts_recv"] * 1000)))
    published: list = []
    sweep = ChainSweep(tmp_path / "ed_console.db", daemon.board, lambda topic, msg: published.append((topic, msg)),
                       clock=lambda: now, failures=CaptureWriter(tmp_path / "stream_capture.db"),
                       streamed=daemon.option_record)
    return daemon, sweep, (lambda: client), published


def test_a_rotation_asks_schwab_as_documented_one_request_at_a_time_with_exact_greeks(tmp_path):
    schwab = LocalSchwab()
    daemon, sweep, client, published = _setup(tmp_path, schwab, _et("2026-08-28 10:15"))
    try:
        assert sweep.rotation(client, ["SPY", "TSLA"], threading.Event()) == {"SPY", "TSLA"}
        first = list(schwab.requests)
        sweep.rotation(client, ["SPY", "TSLA"], threading.Event())
        second = schwab.requests[len(first):]
    finally:
        schwab.close()

    asked = [(path, q.get("symbol"), len(q["symbols"].split(",")) if "symbols" in q else None)
             for path, q, *_ in first]
    assert asked == [(EXPIRATIONS, "SPY", None), (CHAIN, "SPY", None), (QUOTES, None, 300),
                     (EXPIRATIONS, "TSLA", None), (CHAIN, "TSLA", None), (QUOTES, None, 300),
                     (QUOTES, None, 77)], "the expiration chain, each expiry, quotes as 300 fill"
    for path, q, *_ in first:
        if path == CHAIN:
            assert (q["fromDate"], q["toDate"], q["range"]) == (CHAINS[q["symbol"]][0],) * 2 + ("ALL",)
    quoted = [s for path, q, *_ in first if path == QUOTES for s in q["symbols"].split(",")]
    unheld = sorted(ct["symbol"] for _e, cts, _s in CHAINS.values() for ct in cts if ct["symbol"] != HELD)
    assert sorted(quoted) == unheld, "every contract the stream does not hold, asked for once"
    across = [q["symbols"].split(",") for path, q, *_ in first if path == QUOTES][1]
    assert {s.split()[0] for s in across} == {"SPY", "TSLA"}, "a request is filled across tickers"
    assert all(b[2] >= a[3] for a, b in zip(first, first[1:])), "one request at a time"
    assert len({r[4] for r in first}) == 1, "on one connection"
    assert [p for p, *_ in second].count(EXPIRATIONS) == 0, "the expiration chain once per day"

    spy, tsla = delivered(published, "SPY"), delivered(published, "TSLA")
    assert len(spy) == len(SPY["chain"]) and len(tsla) == len(TSLA["chain"])
    record = daemon.option_record(HELD)[1]
    assert {f: spy[HELD][f] for f in GREEKS} == {f: record["content"][f.upper()] for f in GREEKS}
    assert spy[HELD]["greeksTime"] == {f: record["field_ts"][f.upper()][0] for f in GREEKS}
    rounded = {ct["symbol"]: ct["gamma"] for ct in SPY["chain"]}
    for sym, ct in spy.items():
        if sym != HELD:
            quote = SPY_QUOTES[sym]["quote"]
            assert {f: ct[f] for f in GREEKS} == {f: quote[f] for f in GREEKS}, sym
            assert ct["greeksTime"] == dict.fromkeys(GREEKS, quote["quoteTime"]), sym
    assert any(rounded[s] != spy[s]["gamma"] for s in spy), "the chain's rounded Greeks are not kept"
    assert all(ct[f] is None and ct["greeksTime"] is None for ct in tsla.values() for f in GREEKS), \
        "a Greek Schwab did not send is absent"

    with sqlite3.connect(tmp_path / "ed_console.db") as conn:      # 10:15 ET: the 10:00 window
        rows = conn.execute("SELECT ticker, expiry, spot, n_contracts FROM complete_chain_captures "
                            "ORDER BY ticker").fetchall()
    assert rows == [("SPY", "2026-11-20", SPY["spot"], len(SPY["chain"])),
                    ("TSLA", "2026-08-31", None, len(TSLA["chain"]))]


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
    assert failed == [("chain.SPY", "quotes for 300 contracts returned HTTP 429"),
                      ("chain.TSLA", "quotes for 236 contracts returned HTTP 429")]
    assert [p for p, *_ in refused].count(QUOTES) == 2, "SPY's other contracts are not asked for"
    gaps = [b[2] - a[3] for a, b in zip(refused, refused[1:] + after[:1])]
    assert max(gaps) < 1.0, f"a pause after Schwab's 429: {max(gaps):.2f} s"


def test_while_closed_every_board_ticker_is_fetched_once_and_a_failed_one_again(tmp_path):
    schwab = LocalSchwab()
    schwab.refuse_chain = {"TSLA"}
    _daemon, sweep, client, published = _setup(tmp_path, schwab, _et("2026-08-29 12:00"))   # Saturday
    sweep.set_active("QQQ")                                       # on screen while Closed: not fetched
    stop = threading.Event()
    worker = threading.Thread(target=sweep.work, args=(client, stop), daemon=True)
    try:
        worker.start()
        deadline = time.monotonic() + 10
        while len({t for t, m in published if "contracts" in m}) < 2 and time.monotonic() < deadline:
            time.sleep(0.05)
        settled = len(schwab.requests)
        time.sleep(1.5)
        idle = len(schwab.requests) == settled
    finally:
        stop.set()
        worker.join(10)
        schwab.close()
    chains = [(q["symbol"], q["fromDate"]) for q in schwab.asked(CHAIN)]
    assert chains == [("SPY", "2026-11-20"), ("TSLA", "2026-08-31"), ("TSLA", "2026-08-31")]
    assert [m["failed"] for t, m in published if "failed" in m] == ["chain for 2026-08-31 returned HTTP 502"]
    assert idle, "the close values stand: nothing more is asked for until the next session"


def test_a_contract_the_stream_no_longer_holds_takes_its_quotes_greeks(tmp_path):
    """The stream's connection ends (it holds nothing): HELD's record from that connection is
    still on the bus, and its Greeks are asked of the quotes endpoint, never taken from a feed
    that is down."""
    schwab = LocalSchwab()
    daemon, sweep, client, published = _setup(tmp_path, schwab, _et("2026-08-28 09:05"))
    daemon.held["LEVELONE_OPTIONS"] = frozenset()                # as Daemon.disconnect leaves it
    try:
        assert sweep.rotation(client, ["SPY"], threading.Event()) == {"SPY"}
    finally:
        schwab.close()
    assert HELD in [s for q in schwab.asked(QUOTES) for s in q["symbols"].split(",")]
    quote = SPY_QUOTES[HELD]["quote"]
    assert {f: delivered(published, "SPY")[HELD][f] for f in GREEKS} == {f: quote[f] for f in GREEKS}


def test_a_quotes_answer_that_is_not_json_fails_its_tickers_and_the_sweep_goes_on(tmp_path):
    """STAND-IN: a 200 answer whose body is not JSON. Each ticker in the request is published as
    failed with the error, and the next rotation delivers."""
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


def test_contracts_schwab_names_invalid_get_no_greeks_and_every_ticker_in_the_request_is_delivered(tmp_path, caplog):
    """Schwab's /quotes answers 200 with a quote per symbol it knows and, beside them, an errors
    entry naming the ones it does not (measured 2026-10-07: 8 SPY contracts its own chain lists,
    never quoted or traded). Every entry that is a quote is read; the 8 get no Greeks, logged once
    per request with their count; SPY and TSLA, which share a request, are both delivered. Real data: the 8
    contracts' /chains entries and Schwab's errors entry as sent
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
    assert all(spy[s][f] is None and spy[s]["greeksTime"] is None for s in named for f in GREEKS)
    for sym, ct in spy.items():
        if sym not in named and sym != HELD:
            assert {f: ct[f] for f in GREEKS} == {f: SPY_QUOTES[sym]["quote"][f] for f in GREEKS}, sym
    assert len(delivered(published, "TSLA")) == len(TSLA["chain"])
    logged = [r.getMessage() for r in caplog.records]
    in_request = [[s for s in symbols if s in named] for symbols in answered]
    assert sum(len(n) for n in in_request) == len(named) == 8
    assert [m for m in logged if "named" in m] == [
        f"quotes for {len(symbols)} contracts: Schwab named {len(n)} invalid, which have no "
        f"Greeks: {json.dumps({'invalidSymbols': n})}" for symbols, n in zip(answered, in_request)], \
        "each request's named contracts logged once, with their count"
    assert not [m for m in logged if m.startswith("quotes for SPY: no quote came back")], "logged once"
