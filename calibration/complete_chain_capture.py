"""The option chains (DATA_FLOW decisions 1 and 7), run by the capture daemon.

In every open session the daemon fetches the full chain (every expiry, every strike) of every
watchlist ticker (the daemon's one list, capture.Daemon.watchlist), each in its turn in one
rotation, without end (ChainSweep); once the market is Closed it fetches every watchlist ticker
once (the close values) and then nothing until the next session. Each
chain is handed to the console for the levels. The chain history: the first chain of each ticker fetched in
each capture window -- every 30 minutes from 9:30 to the close (ET), and 15 minutes after the close
(the day's close capture), on market days -- is written here, one row per expiry, compressed, with
Schwab's own underlying price. Schwab has no past option chains, so a chain not saved is gone.
Nothing is written while the market is closed (weekend chains blank open interest). Research reads
this table; the console loads the newest capture per ticker at startup.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from instrument_identity import ticker_storage_key
from json_blob_codec import decode_json_blob, encode_json_blob
from numeric_contract import schwab_number
from schwab_client import (GREEK_FIELDS, QUOTES_BATCH_MAX, flatten_chain_contracts, option_expiries,
                           safe_get_chain, safe_get_quotes)
from stream_spine import CaptureWriter
from time_et import (ET, RTH_START_MINS, is_trading_day_et, session_close_mins_for_et_date,
                     session_label)

log = logging.getLogger("chain_history")

CAPTURE_EVERY_MIN = 30
#: the close capture: SPY, QQQ, IWM and the $SPX/NDX/RUT index options trade until 4:15 PM ET,
#: 15 minutes after the stock close (Cboe hours; checked 2026-09-26), so the day's last capture
#: is taken 15 minutes after the close, when every option has stopped trading
CLOSE_CAPTURE_AFTER_MIN = 15
#: why the daemon's captures are complete: every listed expiry, every strike. Older rows (one or
#: two expiries at scattered times, written by the console before 2026-09-27) carry
#: "strike_range=ALL" and are not full chains, so they are not read. The basis is stored before
#: the chain blob, so filtering on it never reads a chain (MEASURED 2026-09-26: filtering on
#: `source`, stored after the blob, read every old chain -- 15 s for SPY, 80 s at startup).
CAPTURE_BASIS = "every_expiry_strike_range_ALL"     # the only basis read: rows of any other are partial

TABLE_SQL = """
CREATE TABLE IF NOT EXISTS complete_chain_captures (
    ticker TEXT NOT NULL,
    expiry TEXT NOT NULL,
    ts_utc REAL NOT NULL,
    spot REAL,
    n_contracts INTEGER NOT NULL,
    completeness_basis TEXT NOT NULL,
    chain_json TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'schwab_chain_strike_range_all',
    created_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (ticker, expiry, ts_utc)
);
CREATE INDEX IF NOT EXISTS idx_complete_chain_captures_latest
    ON complete_chain_captures(ticker, expiry, ts_utc DESC);
"""


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(TABLE_SQL)
    conn.commit()


def persist_complete_chain_capture(
    db_path: Path | str,
    *,
    ticker: str,
    expiry: str,
    contracts: list[Any],
    spot: float | None,
    completeness_basis: str,
    ts_utc: float | None = None,
    source: str = "schwab_chain_strike_range_all",
) -> dict[str, Any]:
    """Append one COMPLETE single-expiry capture. A time series (PRIMARY KEY includes
    ts_utc): each capture time is its own set of rows, one per expiry. A stored capture is
    never replaced: a second write of the same (ticker, expiry, ts_utc) raises sqlite3.IntegrityError and the
    stored row stands.

    FAIL CLOSED: no contracts, or an unproven `completeness_basis`, writes NOTHING and
    says why — a persisted row with an empty or unverifiable completeness claim would be
    worse than no row, since a caller trusts what THIS table alone claims to be complete.
    """
    tk = ticker_storage_key(ticker)
    if not tk:
        return {"status": "skipped", "reason": "no_ticker"}
    exp = str(expiry or "").strip()[:10]
    if not exp:
        return {"status": "skipped", "reason": "no_expiry"}
    if not completeness_basis:
        return {"status": "skipped", "reason": "no_completeness_basis"}
    clean = [dict(c) for c in (contracts or []) if isinstance(c, dict)]
    if not clean:
        return {"status": "skipped", "reason": "no_contracts", "ticker": tk, "expiry": exp}

    ts = float(ts_utc if ts_utc is not None else time.time())
    conn = sqlite3.connect(str(db_path), timeout=60.0)
    try:
        ensure_schema(conn)
        conn.execute(
            "INSERT INTO complete_chain_captures "
            "(ticker, expiry, ts_utc, spot, n_contracts, completeness_basis, chain_json, source) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (tk, exp, ts, spot, len(clean), str(completeness_basis),
             encode_json_blob(clean, default=str), str(source)),
        )
        conn.commit()
    finally:
        conn.close()
    return {"status": "written", "ticker": tk, "expiry": exp, "ts_utc": ts,
            "n_contracts": len(clean), "completeness_basis": completeness_basis}


def capture_slot(now_ts: float) -> float | None:
    """The capture time a chain fetched at `now_ts` is written for: the latest of 9:30, 10:00, ...
    through the close (13:00 on an early close) ET, and the close capture 15 minutes after the
    close, that is at most CAPTURE_EVERY_MIN minutes before `now_ts`, on a market day (the one
    market calendar, time_et). None outside those windows: nothing is written."""
    now = datetime.fromtimestamp(now_ts, ET)
    day = now.date().isoformat()
    if not is_trading_day_et(day):
        return None
    close = session_close_mins_for_et_date(day)
    slots = [datetime(now.year, now.month, now.day, m // 60, m % 60, tzinfo=ET).timestamp()
             for m in [*range(RTH_START_MINS, close + 1, CAPTURE_EVERY_MIN),
                       close + CLOSE_CAPTURE_AFTER_MIN]]
    past = [s for s in slots if s <= now_ts]
    if not past or now_ts - past[-1] >= CAPTURE_EVERY_MIN * 60:
        return None
    return past[-1]


#: contracts per chain message to the console: one message is encoded and decoded whole, so a
#: whole chain in one ($SPX, 29,394 contracts: 40.7 MB, 924 ms to encode, measured 2026-10-01)
#: would hold the daemon's event loop; 500 contracts take tens of milliseconds
CHAIN_PART_CONTRACTS = 500


def chain_messages(ticker: str, contracts: list[dict], fetched_ts: float) -> list[tuple[str, dict]]:
    """A fetched chain as its bus messages, each carrying its finished wire frame: part i of n,
    CHAIN_PART_CONTRACTS contracts each, all with the fetch's time. The console assembles the
    parts; a chain missing a part is never priced."""
    parts = [contracts[i:i + CHAIN_PART_CONTRACTS]
             for i in range(0, len(contracts), CHAIN_PART_CONTRACTS)] or [[]]
    out = []
    for i, part in enumerate(parts):
        msg = {"src": "schwab_chain", "ticker": ticker, "ts_recv": fetched_ts,
               "part": i, "parts": len(parts), "contracts": part}
        out.append((f"chain.{ticker}", {**msg, "frame": json.dumps(
            {"topic": f"chain.{ticker}", "msg": msg}, separators=(",", ":"))}))
    return out


#: Schwab's price history of every ticker (GET /pricehistory,
#: docs/schwab/schwab_market_data_parameters_pricehistory_markets.txt): series -> (periodType,
#: period, frequencyType, frequency). Each request ends now (endDate; without it Schwab ends at the
#: previous business day's close), extended hours included. The 1-minute bars once per ET date
#: (the stream's CHART_EQUITY bars carry them on from there); the 15-minute and daily candles in
#: every rotation, so the current candle is Schwab's latest.
PRICE_HISTORY = {"1m": ("day", 10, "minute", 1), "15m": ("day", 10, "minute", 15), "1d": ("year", 1, "daily", 1)}


def price_history_message(ticker: str, series: str, answer: dict, fetched_ts: float) -> tuple[str, dict]:
    """One series of a ticker's price history as its bus message: Schwab's whole answer as sent
    (its candles and every other field), recorded by the daemon's writer like every stream
    message, with its finished wire frame (built here, off the event loop: a ticker's 1-minute
    answer is ~1 MB)."""
    topic = f"pricehistory.{ticker}.{series}"
    msg = {"src": "schwab_pricehistory", "symbol": ticker, "series": series, "ts_recv": fetched_ts,
           "answer": answer}
    return topic, {**msg, "frame": json.dumps({"topic": topic, "msg": msg}, separators=(",", ":"))}


def chain_failure_message(ticker: str, reason: str, ts: float) -> tuple[str, dict]:
    msg = {"src": "schwab_chain", "ticker": ticker, "ts_recv": ts, "failed": reason}
    return f"chain.{ticker}", {**msg, "frame": json.dumps(
        {"topic": f"chain.{ticker}", "msg": msg}, separators=(",", ":"))}


@dataclass(eq=False)
class _Chain:
    """A ticker's chain from its first request until its last quote is in."""
    ticker: str
    started: float                                                 # its first request
    spots: "dict[str, float | None]" = field(default_factory=dict)  # expiry -> Schwab's underlyingPrice in its answer
    by_expiry: "dict[str, list[dict]]" = field(default_factory=dict)
    unquoted: "set[str]" = field(default_factory=set)              # contracts whose quote is not in
    named_invalid: "set[str]" = field(default_factory=set)         # contracts Schwab's quotes named invalid

    def contracts(self) -> "list[dict]":
        return [ct for cts in self.by_expiry.values() for ct in cts]


class ChainSweep:
    """The one fetcher of option chains: one thread, one request at a time on the daemon's one
    Schwab client, every ticker the same, in one rotation (sorted): every watchlist ticker
    (`watchlist`, which the daemon replaces on each add or removal: an added ticker is in the
    next rotation, a removed one is asked for no more). For each ticker, Schwab's expiration chain once per ET
    date, then one chain request per expiry (strike_range=ALL), as Schwab says to break up a
    large chain. The chain's own Greeks (GREEK_FIELDS, rounded by Schwab) are never kept: a
    contract whose LEVELONE_OPTIONS record (`streamed`) carries all of them takes the stream's,
    each with its field's Schwab time; every other contract is asked for on the quotes endpoint,
    QUOTES_BATCH_MAX symbols to a request across tickers, and takes its quote's, with the
    quote's quoteTime. A Greek Schwab does not send is absent (None). Each contract carries the
    time of its Greeks as `greeksTime` ({field: Schwab's time, ms}).

    After each ticker's chain, its price history (fetch_price_history): Schwab's 1-minute bars
    once per ET date, its 15-minute and daily candles in every rotation.

    A chain is published to the console in parts (chain_messages) once all its quotes are in; a
    ticker whose request fails (an answer other than 200, or none) is published as failed with
    the reason, and the rotation goes on. While Closed (time_et.session_label) every watchlist ticker
    is fetched once, its close values (a failed one again in the next pass), and then nothing
    until the next session. The first chain of a ticker begun inside a capture window
    (capture_slot) is also written to the chain history; a history write that fails is a write
    failure, never the chain's: the chain as delivered is handed to `failures` (the daemon's
    writer) to keep."""

    def __init__(self, db_path: Path | str, watchlist: "list[str]", publish: "callable",
                 clock: "callable" = time.time, *, failures: "CaptureWriter",
                 streamed: "callable") -> None:
        self.db_path = db_path
        self.watchlist = list(watchlist)  # the daemon's list, replaced whole on each change
        self.publish = publish          # (topic, msg) -> None, safe from any thread
        self.clock = clock              # when a request begins, and when a chain is delivered
        self.failures = failures        # the daemon's writer: keeps a failed history write
        self.streamed = streamed        # option symbol -> its bus current (topic, record) or None
        self.round_sec: float | None = None
        self._expiries: "dict[str, tuple[date, list[date]]]" = {}   # ticker -> (ET date, expiries)
        self._minutes_day: "dict[str, date]" = {}          # ticker -> the ET date its 1-minute bars came
        self._queue: "list[tuple[_Chain, dict]]" = []     # contracts whose quote is not asked for
        self._delivered: "set[str]" = set()                # the tickers this rotation delivered
        self._written: "dict[str, float | None]" = {}       # ticker -> its newest history capture
        self._close_done: "set[str] | None" = None         # while Closed: the tickers whose close
                                                           # values are in; None while open

    def work(self, schwab_client, stop: threading.Event) -> None:
        """The thread's life, until `stop`: rotation after rotation on the daemon's client
        (`schwab_client()`). While Closed, once every watchlist ticker's close values are in (a
        ticker added while Closed is fetched once too), it looks each second for the next
        session. With the watchlist empty it asks Schwab for nothing and looks again each second."""
        while not stop.is_set():
            tickers = sorted(self.watchlist)
            if not tickers:
                stop.wait(1.0)
                continue
            if session_label(datetime.fromtimestamp(self.clock(), ET)) != "Closed":
                self._close_done = None
                self.rotation(schwab_client, tickers, stop)
                continue
            if self._close_done is None:              # the market has just closed, or the daemon
                self._close_done = set()              # started while it is Closed
            left = [t for t in tickers if t not in self._close_done]
            if left:
                self._close_done |= self.rotation(schwab_client, left, stop)
            else:
                stop.wait(1.0)

    def rotation(self, schwab_client, tickers: "list[str]", stop: threading.Event) -> "set[str]":
        """Each ticker's chain in turn (one removed from the watchlist since the rotation began is
        not asked for), the queued quotes asked for whenever a full request's worth is waiting
        and the rest at the end; the tickers delivered."""
        started = self.clock()
        self._delivered = set()
        for ticker in tickers:
            if stop.is_set():
                break
            if ticker not in self.watchlist:
                continue
            self.fetch_chain(schwab_client, ticker)
            self.fetch_price_history(schwab_client, ticker)
            while len(self._queue) >= QUOTES_BATCH_MAX:
                self.send_quotes(schwab_client)
        while self._queue and not stop.is_set():
            self.send_quotes(schwab_client)
        self.round_sec = self.clock() - started
        log.info("chain rotation: %d of %d tickers delivered in %.0f s",
                 len(self._delivered), len(tickers), self.round_sec)
        return self._delivered

    def fetch_price_history(self, schwab_client, ticker: str) -> None:
        """`ticker`'s price history (PRICE_HISTORY), each series published as Schwab sent its
        candles; a series Schwab does not answer 200 is not published (log_request has the answer)
        and is asked again in the next rotation."""
        now = self.clock()
        today = datetime.fromtimestamp(now, ET).date()
        for series, (period_type, period, frequency_type, frequency) in PRICE_HISTORY.items():
            if series == "1m" and self._minutes_day.get(ticker) == today:
                continue
            try:
                resp = schwab_client().get_price_history(
                    ticker, period_type=period_type, period=period, frequency_type=frequency_type,
                    frequency=frequency, end_datetime=datetime.fromtimestamp(now, timezone.utc),
                    need_extended_hours_data=True)
                if resp.status_code != 200:
                    continue
                answer = resp.json()
            except Exception as e:  # noqa: BLE001 -- that series' answer is the failure; the rotation goes on
                log.warning("price history %s %s failed: %s: %s", ticker, series, type(e).__name__, e)
                continue
            self.publish(*price_history_message(ticker, series, answer, self.clock()))
            if series == "1m":
                self._minutes_day[ticker] = today

    def fetch_chain(self, schwab_client, ticker: str) -> None:
        """`ticker`'s chain, every expiry: each contract's Greeks from the stream, or the contract
        queued for its quote; delivered at once when none is queued."""
        chain = _Chain(ticker, self.clock())
        try:
            client = schwab_client()
            today = datetime.fromtimestamp(chain.started, ET).date()
            listed = self._expiries.get(ticker)
            if listed is None or listed[0] != today:
                expiries, resp = option_expiries(client, ticker, today)
                if expiries is None:
                    return self.fail([chain], f"expiration chain returned HTTP {resp.status_code}")
                listed = self._expiries[ticker] = (today, expiries)
            for expiry in listed[1]:
                resp = safe_get_chain(client, ticker, strike_range="ALL", from_date=expiry, to_date=expiry)
                if resp.status_code != 200:
                    return self.fail([chain], f"chain for {expiry} returned HTTP {resp.status_code}")
                payload = resp.json()
                chain.spots[expiry.isoformat()] = schwab_number(payload.get("underlyingPrice"))
                chain.by_expiry[expiry.isoformat()] = flatten_chain_contracts(payload)
        except Exception as e:  # noqa: BLE001 -- that ticker's answer is the failure; the rotation goes on
            log.warning("chain %s failed: %s: %s", ticker, type(e).__name__, e)
            return self.fail([chain], f"{type(e).__name__}: {e}")
        for ct in chain.contracts():
            entry = self.streamed(ct["symbol"])
            if entry is not None and all(f.upper() in entry[1]["content"] for f in GREEK_FIELDS):
                ct.update({f: entry[1]["content"][f.upper()] for f in GREEK_FIELDS})
                ct["greeksTime"] = {f: entry[1]["field_ts"][f.upper()][0] for f in GREEK_FIELDS}
            else:
                ct.update(dict.fromkeys(GREEK_FIELDS))
                ct["greeksTime"] = None
                chain.unquoted.add(ct["symbol"])
                self._queue.append((chain, ct))
        if not chain.unquoted:
            self.deliver(chain)

    def send_quotes(self, schwab_client) -> None:
        """One quotes request for the next QUOTES_BATCH_MAX queued contracts, which take their
        quote's Greeks; each chain it completes is delivered. A request that fails fails every
        ticker in it. Schwab's answer carries a quote per symbol it knows and, beside them, an
        `errors` entry naming the symbols it does not (`invalidSymbols`; measured 2026-10-07: 8
        SPY contracts its own chain lists, every one never quoted or traded): those contracts get
        no Greeks, logged once with their count, and the rest of the request is delivered."""
        self._queue = [(chain, ct) for chain, ct in self._queue if chain.ticker in self.watchlist]  # removed: not asked
        batch, self._queue = self._queue[:QUOTES_BATCH_MAX], self._queue[QUOTES_BATCH_MAX:]
        chains = list({id(chain): chain for chain, _ct in batch}.values())
        try:
            resp = safe_get_quotes(schwab_client(), [ct["symbol"] for _chain, ct in batch])
            if resp.status_code != 200:
                return self.fail(chains, f"quotes for {len(batch)} contracts returned HTTP {resp.status_code}")
            answer = resp.json()
            errors = answer.pop("errors") if "errors" in answer else {}
            named = set(errors["invalidSymbols"]) if "invalidSymbols" in errors else set()
            quoted = {s: e["quote"] for s, e in answer.items()}
        except Exception as e:  # noqa: BLE001 -- those tickers' answer is the failure; the rotation goes on
            log.warning("quotes for %d contracts failed: %s: %s", len(batch), type(e).__name__, e)
            return self.fail(chains, f"{type(e).__name__}: {e}")
        if errors:
            log.warning("quotes for %d contracts: Schwab named %d invalid, which have no Greeks: %s",
                        len(batch), len(named), json.dumps(errors))
        for chain, ct in batch:
            quote = quoted.get(ct["symbol"])
            if quote is not None:
                ct.update({f: quote.get(f) for f in GREEK_FIELDS})
                ct["greeksTime"] = dict.fromkeys(GREEK_FIELDS, quote.get("quoteTime"))
            elif ct["symbol"] in named:
                chain.named_invalid.add(ct["symbol"])
            chain.unquoted.discard(ct["symbol"])
        for chain in chains:
            if not chain.unquoted:
                self.deliver(chain)

    def fail(self, chains: "list[_Chain]", reason: str) -> None:
        """Each chain's ticker is published as failed with `reason`; its contracts leave the queue.
        The log has the cause already: Schwab's answer (schwab_client.log_request) or the error."""
        now = self.clock()
        self._queue = [(chain, ct) for chain, ct in self._queue if chain not in chains]
        for chain in chains:
            self.publish(*chain_failure_message(chain.ticker, reason, now))

    def deliver(self, chain: _Chain) -> None:
        """The chain to the console, and to the chain history when it is the window's first."""
        now = self.clock()
        contracts = chain.contracts()
        for topic, msg in chain_messages(chain.ticker, contracts, now):
            self.publish(topic, msg)
        self._delivered.add(chain.ticker)
        missing = sum(1 for ct in contracts if ct["greeksTime"] is None and ct["symbol"] not in chain.named_invalid)
        if missing:
            log.warning("quotes for %s: no quote came back for %d of %d contracts; their Greeks are absent",
                        chain.ticker, missing, len(contracts))
        try:
            self._write_history(chain, now)
        except Exception as e:  # noqa: BLE001 -- the chain is delivered; a failed history write is the writer's to keep and show
            log.warning("chain history for %s not written, kept as delivered: %s: %s",
                        chain.ticker, type(e).__name__, e)
            self.failures.keep_failure(f"chain_history.{chain.ticker}",
                                       {"spots": chain.spots, "contracts": contracts}, e, now)

    def _write_history(self, chain: _Chain, now: float) -> None:
        """The chain history: a chain begun inside a capture window, the first one of the window
        for this ticker (a chain begun before 16:15 is not the close capture, whenever it ends),
        one row per expiry with the underlying price of that expiry's answer."""
        ticker = chain.ticker
        slot = capture_slot(chain.started)
        if slot is None:
            return
        if ticker not in self._written:
            self._written[ticker] = newest_capture_ts(self.db_path, ticker)
        before = self._written[ticker]
        if before is not None and before >= slot:
            return
        self._written[ticker] = slot                       # claim the window for this ticker
        try:
            for expiry, cts in chain.by_expiry.items():
                persist_complete_chain_capture(self.db_path, ticker=ticker, expiry=expiry, contracts=cts,
                                               spot=chain.spots[expiry], completeness_basis=CAPTURE_BASIS,
                                               ts_utc=now)
        except Exception:
            self._written[ticker] = before                 # unwritten: the window's next chain tries
            raise


def newest_capture_ts(db_path: Path | str, ticker: str) -> float | None:
    """When the ticker's newest full capture was taken; None when there is none."""
    if not Path(db_path).is_file():
        return None
    conn = sqlite3.connect(f"file:{Path(db_path).resolve().as_posix()}?mode=ro", uri=True)
    try:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                            "AND name='complete_chain_captures'").fetchone():
            return None
        return conn.execute("SELECT MAX(ts_utc) FROM complete_chain_captures WHERE ticker=? "
                            "AND completeness_basis=?",
                            (ticker_storage_key(ticker), CAPTURE_BASIS)).fetchone()[0]
    finally:
        conn.close()


def last_capture_per_day(db_path: Path | str, ticker: str, days: int, *,
                         before_et_date: str | None = None) -> list[dict[str, Any]]:
    """The last capture of each of the newest `days` market days (newest first) -- the close --
    each as {et_date, ts_utc, spot, basis, contracts} with every expiry of that capture.
    `before_et_date` keeps only days before it (the previous market day for a day-over-day
    view)."""
    tk = ticker_storage_key(ticker)
    conn = sqlite3.connect(f"file:{Path(db_path).resolve().as_posix()}?mode=ro", uri=True)
    try:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                            "AND name='complete_chain_captures'").fetchone():
            return []                     # no capture has ever been written
        picked: list[tuple[str, float]] = []
        for (ts,) in conn.execute(
                "SELECT DISTINCT ts_utc FROM complete_chain_captures "
                "WHERE ticker=? AND completeness_basis=? ORDER BY ts_utc DESC",
                (tk, CAPTURE_BASIS)):
            day = datetime.fromtimestamp(ts, ET).date().isoformat()
            if before_et_date is not None and day >= before_et_date:
                continue
            if picked and picked[-1][0] == day:
                continue
            picked.append((day, ts))
            if len(picked) == days:
                break
        out = []
        for day, ts in picked:
            rows = conn.execute(
                "SELECT spot, completeness_basis, chain_json FROM complete_chain_captures "
                "WHERE ticker=? AND completeness_basis=? AND ts_utc=?",
                (tk, CAPTURE_BASIS, ts)).fetchall()
            out.append({"et_date": day, "ts_utc": ts, "spot": rows[0][0], "basis": rows[0][1],
                        "contracts": [c for r in rows for c in decode_json_blob(r[2])]})
        return out
    finally:
        conn.close()
