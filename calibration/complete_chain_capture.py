"""The option chains (DATA_FLOW decisions 1 and 7), run by the capture daemon.

While a watchlist ticker's options trade -- the regular session Schwab's /markets sends for its
option market (EQO for stock and ETF options, IND for index options) -- the daemon fetches its
full chain (every expiry, every strike) in turn with every other such ticker of the watchlist
(the daemon's one list, capture.Daemon.watchlist), without end (ChainSweep); once that session
closes, once more (the close values), and then nothing until the next one. Each chain is handed
to the console for the levels. The chain history: the first chain of each ticker begun in each
capture window -- every 30 minutes from its option market's open, and at its close (the day's
close capture) -- is written here, one row per expiry, compressed, with Schwab's own underlying
price. Schwab has no past option chains, so a chain not saved is gone. Nothing is written outside
those windows (weekend chains blank open interest). Research reads this table; the console loads
the newest capture per ticker at startup.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from schwab.client import Client

import option_ledger
from instrument_identity import ticker_storage_key
from json_blob_codec import decode_json_blob, encode_json_blob
from schwab_client import (QUOTES_BATCH_MAX, flatten_chain_contracts, option_expiries, safe_get_chain,
                           safe_get_quotes)
from time_et import ET, options_closed_at, options_open, record_markets, session

log = logging.getLogger("chain_history")

CAPTURE_EVERY_MIN = 30
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
    """The capture time a chain begun at `now_ts` is written for: the latest of the option
    markets' open, every CAPTURE_EVERY_MIN minutes after it, and their last close (the close
    capture) -- the regular sessions Schwab's /markets sent for the day (time_et.session) -- that is
    at most CAPTURE_EVERY_MIN minutes before `now_ts`. None outside those windows, and on a day with
    no regular option session or no answer: nothing is written."""
    today = session(datetime.fromtimestamp(now_ts, ET).date().isoformat())
    if today is None:
        return None
    windows = [w for _p, ws in today.options for w in ws]
    if not windows:
        return None
    opens, close = min(s for s, _e in windows).timestamp(), max(e for _s, e in windows).timestamp()
    slots = [*range(int(opens), int(close), CAPTURE_EVERY_MIN * 60), close]
    past = [s for s in slots if s <= now_ts]
    if not past or now_ts - past[-1] >= CAPTURE_EVERY_MIN * 60:
        return None
    return past[-1]


def chain_answer_message(ticker: str, expiry: str, status: int, answer, fetched_ts: float) -> tuple[str, dict]:
    """Schwab's /chains answer for one expiry of `ticker`, as sent, with its status: for the
    journal (it posts to its contracts' records, option_ledger.opening)."""
    return f"chainanswer.{ticker}", {"src": "schwab_chains", "symbol": ticker, "expiry": expiry,
                                     "status": status, "ts_recv": fetched_ts, "answer": answer}


def expiration_answer_message(ticker: str, status: int, answer, fetched_ts: float) -> tuple[str, dict]:
    """Schwab's /expirationchain answer for `ticker`, as sent, with its status: for the journal."""
    return f"expirationanswer.{ticker}", {"src": "schwab_expirations", "symbol": ticker, "status": status,
                                          "ts_recv": fetched_ts, "answer": answer}


def quotes_answer_message(symbols: "list[str]", status: int, answer, fetched_ts: float) -> tuple[str, dict]:
    """Schwab's /quotes answer for option contracts, as sent, with its status and the symbols
    asked: for the journal (each quote posts to its contract's record, option_ledger.from_quote)."""
    return "quotesanswer.options", {"src": "schwab_quotes", "symbols": list(symbols), "status": status,
                                    "ts_recv": fetched_ts, "answer": answer}


def _answer(resp) -> "tuple[Any, str | None]":
    """Schwab's answer as sent: its JSON, or its text with why it is not JSON."""
    try:
        return resp.json(), None
    except ValueError as e:
        return resp.text, f"{type(e).__name__}: {e}"


def chain_round_message(ticker: str, started: float, opening: bool = False) -> tuple[str, dict]:
    """`ticker`'s round is in: each of its contracts' records holds Schwab's answers asked in the
    round begun at `started` (the levels' as-of time). An `opening` round posted every contract
    Schwab lists for the ticker today: a record it did not post is of a contract no longer listed."""
    msg = {"src": "schwab_chain", "ticker": ticker, "ts_recv": started, "opening": opening}
    return f"chain.{ticker}", msg


#: Schwab's price history of every ticker (GET /pricehistory,
#: docs/schwab/schwab_market_data_parameters_pricehistory_markets.txt): series -> (periodType,
#: period, frequencyType, frequency). Each request ends now (endDate; without it Schwab ends at the
#: previous business day's close), extended hours included. Both once per ET date: the 1-minute
#: bars (the stream's CHART_EQUITY bars carry them on from there) and two years of daily candles
#: (monthly ATR(14) needs 15 months; today's candle the console rolls up from the bars).
PRICE_HISTORY = {"1m": ("day", 10, "minute", 1), "1d": ("year", 2, "daily", 1)}


def price_history_message(ticker: str, series: str, answer: dict, fetched_ts: float) -> tuple[str, dict]:
    """One series of a ticker's price history as its bus message: Schwab's whole answer as sent
    (its candles and every other field), recorded by the daemon's writer like every stream
    message, with its finished wire frame (built here, off the event loop: a ticker's 1-minute
    answer is ~1 MB)."""
    topic = f"pricehistory.{ticker}.{series}"
    msg = {"src": "schwab_pricehistory", "symbol": ticker, "series": series, "ts_recv": fetched_ts,
           "answer": answer}
    return topic, {**msg, "frame": json.dumps({"topic": topic, "msg": msg}, separators=(",", ":"))}


#: Schwab answers GET /markets for a date as far as 7 days back ("Date cannot be more than 7 days
#: in the past.", its 400 for 2026-09-29 asked on 2026-10-07; 2026-10-06 answered 200)
MARKETS_DAYS_BACK = 7
#: Schwab's answer for a date, asked once per ET date: its sessions (200), or why it has none
#: (400, e.g. "Date cannot be beyond 1 year from today."). Any other answer is asked again.
MARKETS_ANSWERED = (200, 400)


def markets_message(day: str, status: int, answer: dict, fetched_ts: float) -> tuple[str, dict]:
    """Schwab's /markets answer for `day` as its bus message, as sent, with its status."""
    topic = f"markets.{day}"
    msg = {"src": "schwab_markets", "date": day, "ts_recv": fetched_ts, "status": status, "answer": answer}
    return topic, {**msg, "frame": json.dumps({"topic": topic, "msg": msg}, separators=(",", ":"))}


def chain_failure_message(ticker: str, reason: str, ts: float) -> tuple[str, dict]:
    msg = {"src": "schwab_chain", "ticker": ticker, "ts_recv": ts, "failed": reason}
    return f"chain.{ticker}", msg


@dataclass(eq=False)
class _Round:
    """A ticker's round from its first request until its last quote is in."""
    ticker: str
    started: float                                                 # its first request
    unquoted: "set[str]" = field(default_factory=set)              # contracts whose quote is not in
    opening: bool = False                                          # the day's opening: Schwab's whole listing


class ChainSweep:
    """The one fetcher of option chains: one thread, one request at a time on the daemon's one
    Schwab client, every ticker the same, in one rotation (sorted): every watchlist ticker
    (`watchlist`, which the daemon replaces on each add or removal: an added ticker is in the
    next rotation, a removed one is asked for no more). Each thing is asked for once, and again
    only for what the stream does not carry (option_ledger, the option ledger):
      - the opening, once per ET date: Schwab's expiration chain, then one chain request per expiry
        (strike_range=ALL), as Schwab says to break up a large chain; each answer is published as
        sent (chain_answer_message, the journal), and each contract it lists opens its record
        (option_ledger.opening: every field as sent but the rounded Greeks);
      - Schwab's quotes, QUOTES_BATCH_MAX symbols to a request across tickers, only for what no
        stream carries (operator 2026-10-13: "REST only for what no stream carries"): each round,
        every listed contract the stream does not hold (`held`). Each answer is published as sent
        (quotes_answer_message), and each quote posts to its contract's record
        (option_ledger.from_quote), unless the stream took the contract meanwhile.
    A round is in when the last of its quotes is (chain_round_message).

    The price history (candles, fetch_price_history): each watchlist ticker's 1-minute bars and
    daily candles once per ET date (candles_due).

    The market's sessions (fetch_markets): Schwab's /markets answer for today and the
    MARKETS_DAYS_BACK days before it, and for each expiry date of the chains, each date asked
    once per ET date, whatever the number of tickers.

    A ticker's chain is asked for (chain_due) while any option market is open by Schwab's
    answer for today (the last, IND, to 16:15 ET, when SPY's, QQQ's and IWM's options stop too),
    while that answer is not known yet, and once more after the newest close it has not been
    fetched since (its close values; a failed one again in the next pass); otherwise not, until
    the next session. A ticker whose expiration chain lists no option (or none asked yet) has
    its chain asked once per ET date, to learn whether options are listed. A ticker whose request
    fails (an answer other than 200, or none) is published as failed with the reason, and the
    rotation goes on."""

    def __init__(self, watchlist: "list[str]", publish: "callable", clock: "callable" = time.time, *,
                 held: "callable") -> None:
        self.watchlist = list(watchlist)  # the daemon's list, replaced whole on each change
        self.publish = publish          # (topic, msg) -> None, safe from any thread
        self.clock = clock              # when a request begins
        self.held = held                # () -> the option contracts the stream holds now
        self.round_sec: float | None = None
        self._expiries: "dict[str, tuple[date, list[date]]]" = {}   # ticker -> (ET date, expiries)
        self._markets_day: "dict[str, date]" = {}          # market date -> the ET date Schwab answered it
        self._optioned: "set[str]" = set()                 # tickers Schwab has answered a chain for
        self._fetched: "dict[str, float]" = {}             # ticker -> when its newest round began
        self._candled: "dict[str, float]" = {}             # ticker -> when its newest whole price history began
        self._opened: "dict[str, tuple[date, list[str]]]" = {}   # ticker -> (ET date, the contracts its chain listed)
        self._queue: "list[tuple[_Round, str]]" = []      # contracts whose quote is not asked for
        self._delivered: "set[str]" = set()                # the tickers this rotation delivered

    def work(self, schwab_client, stop: threading.Event) -> None:
        """The thread's life, until `stop`: on the daemon's client (`schwab_client()`), the
        market's sessions for today and the days before it, then a rotation of the watchlist
        tickers whose chain is due and the price history of those whose candles are due; with
        none due, it looks again each second. With the watchlist empty it asks Schwab for
        nothing and looks again each second."""
        while not stop.is_set():
            if not self.watchlist:
                stop.wait(1.0)
                continue
            today = datetime.fromtimestamp(self.clock(), ET).date()
            self.fetch_markets(schwab_client, [(today - timedelta(days=n)).isoformat()
                                               for n in range(MARKETS_DAYS_BACK, -1, -1)])
            now = datetime.fromtimestamp(self.clock(), ET)
            chains = [t for t in sorted(self.watchlist) if self.chain_due(t, now)]
            candles = [t for t in sorted(self.watchlist) if self.candles_due(t, now)]
            if chains:
                self.rotation(schwab_client, chains, stop)
            if candles:
                self.candles(schwab_client, candles, stop)
            if not chains and not candles:
                stop.wait(1.0)

    def candles_due(self, ticker: str, now: datetime) -> bool:
        """Whether `ticker`'s price history is asked for at `now`: not yet whole on this ET date."""
        return ticker not in self._candled or datetime.fromtimestamp(self._candled[ticker], ET).date() < now.date()

    def chain_due(self, ticker: str, now: datetime) -> bool:
        """Whether `ticker`'s chain is asked for at `now`: an option market open, or today's
        session not known (Schwab's /markets answer for today not held), or closed with the
        newest close after the ticker's newest delivered chain began. A ticker with no chain answer
        yet (none asked, or no option listed) is asked once per ET date."""
        if ticker not in self._optioned:
            return ticker not in self._fetched or datetime.fromtimestamp(self._fetched[ticker], ET).date() < now.date()
        if options_open(now) is not False:
            return True
        closed = options_closed_at(now)
        return closed is not None and (ticker not in self._fetched or self._fetched[ticker] < closed.timestamp())

    def fetch_markets(self, schwab_client, days: "list[str]") -> None:
        """Schwab's GET /markets?markets=equity,option answer for each of `days` (YYYY-MM-DD) not
        answered on this ET date, one request each: a 200 is that date's sessions from here on
        (time_et.record_markets), and every answer is published as sent (markets_message), for
        the daemon's writer to record and the console to take. An answer not in MARKETS_ANSWERED
        (log_request has it), or none, is asked again the next time."""
        today = datetime.fromtimestamp(self.clock(), ET).date()
        for day in days:
            if self._markets_day.get(day) == today:
                continue
            try:
                resp = schwab_client().get_market_hours(
                    [Client.MarketHours.Market.EQUITY, Client.MarketHours.Market.OPTION], date=date.fromisoformat(day))
                answer = resp.json()
            except Exception as e:  # noqa: BLE001 -- that date's answer is the failure; it is asked again
                log.warning("market hours for %s failed: %s: %s", day, type(e).__name__, e)
                continue
            if resp.status_code == 200:
                record_markets(answer)
            if resp.status_code in MARKETS_ANSWERED:
                self._markets_day[day] = today
            self.publish(*markets_message(day, resp.status_code, answer, self.clock()))

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
            while len(self._queue) >= QUOTES_BATCH_MAX:
                self.send_quotes(schwab_client)
        while self._queue and not stop.is_set():
            self.send_quotes(schwab_client)
        self.round_sec = self.clock() - started
        log.info("chain rotation: %d of %d tickers delivered in %.0f s",
                 len(self._delivered), len(tickers), self.round_sec)
        return self._delivered

    def candles(self, schwab_client, tickers: "list[str]", stop: threading.Event) -> None:
        """Each ticker's price history in turn (one removed from the watchlist meanwhile is not
        asked for)."""
        for ticker in tickers:
            if stop.is_set():
                break
            if ticker in self.watchlist:
                self.fetch_price_history(schwab_client, ticker)

    def fetch_price_history(self, schwab_client, ticker: str) -> None:
        """`ticker`'s price history (PRICE_HISTORY), each series published as Schwab sent its
        candles; a series Schwab does not answer 200 is not published (log_request has the answer)
        and the ticker's candles are asked again the next time they are due (candles_due)."""
        now = self.clock()
        whole = True
        for series, (period_type, period, frequency_type, frequency) in PRICE_HISTORY.items():
            try:
                resp = schwab_client().get_price_history(
                    ticker, period_type=period_type, period=period, frequency_type=frequency_type,
                    frequency=frequency, end_datetime=datetime.fromtimestamp(now, timezone.utc),
                    need_extended_hours_data=True)
                if resp.status_code != 200:
                    whole = False
                    continue
                answer = resp.json()
            except Exception as e:  # noqa: BLE001 -- that series' answer is the failure; the rotation goes on
                log.warning("price history %s %s failed: %s: %s", ticker, series, type(e).__name__, e)
                whole = False
                continue
            self.publish(*price_history_message(ticker, series, answer, self.clock()))
        if whole:
            self._candled[ticker] = now

    def fetch_chain(self, schwab_client, ticker: str) -> None:
        """`ticker`'s round: its opening when it has none on this ET date (open), then each of its
        contracts the stream does not carry queued for its quote; in at once when none is."""
        rnd = _Round(ticker, self.clock())
        today = datetime.fromtimestamp(rnd.started, ET).date()
        opened = self._opened.get(ticker)
        if opened is None or opened[0] != today:
            if not self.open(schwab_client, rnd, today):
                return
            rnd.opening = True
        held = self.held()
        listed = [s for s in self._opened[ticker][1] if s not in held]
        rnd.unquoted.update(listed)
        self._queue.extend((rnd, s) for s in listed)
        if not rnd.unquoted:
            self.round_in(rnd)

    def open(self, schwab_client, rnd: _Round, today: date) -> bool:
        """The ticker's opening: its expiration chain once per ET date, then each expiry's chain,
        each answer published as sent and each contract it lists opening its record; whether it
        came in (a failure is published with its reason)."""
        ticker = rnd.ticker
        try:
            client = schwab_client()
            listed = self._expiries.get(ticker)
            if listed is None or listed[0] != today:
                expiries, resp = option_expiries(client, ticker, today)
                self.publish(*expiration_answer_message(ticker, resp.status_code, _answer(resp)[0], self.clock()))
                if expiries is None:
                    self.fail([rnd], f"expiration chain returned HTTP {resp.status_code}")
                    return False
                listed = self._expiries[ticker] = (today, expiries)
            self.fetch_markets(schwab_client, [expiry.isoformat() for expiry in listed[1]])
            symbols: "list[str]" = []
            for expiry in listed[1]:
                resp = safe_get_chain(client, ticker, strike_range="ALL", from_date=expiry, to_date=expiry)
                answer, unreadable = _answer(resp)
                self.publish(*chain_answer_message(ticker, expiry.isoformat(), resp.status_code, answer, self.clock()))
                if resp.status_code != 200:
                    self.fail([rnd], f"chain for {expiry} returned HTTP {resp.status_code}")
                    return False
                if unreadable is not None:
                    self.fail([rnd], unreadable)
                    return False
                self._optioned.add(ticker)
                for ct in flatten_chain_contracts(answer):
                    self.publish(*option_ledger.posting(ct["symbol"], option_ledger.opening(ct, ticker),
                                                        ct.get("quoteTimeInLong"), self.clock()))
                    symbols.append(ct["symbol"])
        except Exception as e:  # noqa: BLE001 -- that ticker's answer is the failure; the rotation goes on
            log.warning("chain %s failed: %s: %s", ticker, type(e).__name__, e)
            self.fail([rnd], f"{type(e).__name__}: {e}")
            return False
        self._opened[ticker] = (today, symbols)
        return True

    def send_quotes(self, schwab_client) -> None:
        """One quotes request for the next QUOTES_BATCH_MAX queued contracts: Schwab's answer
        published as sent, and each quote posted to its contract's record; each round it completes
        is in. A request that fails fails every ticker in it. Schwab's answer carries a quote per
        symbol it knows and, beside them, an `errors` entry naming the symbols it does not
        (`invalidSymbols`; measured 2026-10-07: 8 SPY contracts its own chain lists, every one
        never quoted or traded): those records get no quote, logged once with their count, and the
        rest of the request is in."""
        self._queue = [(rnd, s) for rnd, s in self._queue if rnd.ticker in self.watchlist]  # removed: not asked
        batch, self._queue = self._queue[:QUOTES_BATCH_MAX], self._queue[QUOTES_BATCH_MAX:]
        rounds = list({id(rnd): rnd for rnd, _s in batch}.values())
        symbols = [s for _rnd, s in batch]
        try:
            resp = safe_get_quotes(schwab_client(), symbols)
        except Exception as e:  # noqa: BLE001 -- those tickers' answer is the failure; the rotation goes on
            log.warning("quotes for %d contracts failed: %s: %s", len(batch), type(e).__name__, e)
            return self.fail(rounds, f"{type(e).__name__}: {e}")
        answer, unreadable = _answer(resp)
        self.publish(*quotes_answer_message(symbols, resp.status_code, answer, self.clock()))
        if resp.status_code != 200:
            return self.fail(rounds, f"quotes for {len(batch)} contracts returned HTTP {resp.status_code}")
        if unreadable is not None:
            log.warning("quotes for %d contracts: the answer is not JSON: %s", len(batch), unreadable)
            return self.fail(rounds, unreadable)
        errors = answer["errors"] if "errors" in answer else {}
        if errors:
            log.warning("quotes for %d contracts: Schwab named symbols it does not know, which have no quote: %s",
                        len(batch), json.dumps(errors))
        held = self.held()                # a contract the stream took since it was asked: the stream's
        for rnd, s in batch:
            if s in answer and s != "errors" and s not in held:
                quote = answer[s]["quote"]
                self.publish(*option_ledger.posting(s, option_ledger.from_quote(quote), quote.get("quoteTime"),
                                                    self.clock()))
            rnd.unquoted.discard(s)
        for rnd in rounds:
            if not rnd.unquoted:
                self.round_in(rnd)

    def fail(self, rounds: "list[_Round]", reason: str) -> None:
        """Each round's ticker is published as failed with `reason`; its contracts leave the queue.
        The log has the cause already: Schwab's answer (schwab_client.log_request) or the error."""
        now = self.clock()
        self._queue = [(rnd, s) for rnd, s in self._queue if rnd not in rounds]
        for rnd in rounds:
            self.publish(*chain_failure_message(rnd.ticker, reason, now))

    def round_in(self, rnd: _Round) -> None:
        """The ticker's round is in: published with the time it began (its as-of everywhere: a
        round begun before the close is not the close values, whenever it is in)."""
        self.publish(*chain_round_message(rnd.ticker, rnd.started, rnd.opening))
        self._delivered.add(rnd.ticker)
        self._fetched[rnd.ticker] = rnd.started


def write_capture(db_path: Path | str, ticker: str, contracts: "list[dict]", spot: "float | None",
                  ts_utc: float) -> None:
    """The chain history of one window: the ticker's contract records as the ledger holds them,
    one row per expiry, with the ticker's price and the time its round began."""
    by_expiry: "dict[str, list[dict]]" = {}
    for ct in contracts:
        by_expiry.setdefault(str(ct["expirationDate"])[:10], []).append(ct)   # each opened from the chain
    for expiry, cts in by_expiry.items():
        persist_complete_chain_capture(db_path, ticker=ticker, expiry=expiry, contracts=cts, spot=spot,
                                       completeness_basis=CAPTURE_BASIS, ts_utc=ts_utc)


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
