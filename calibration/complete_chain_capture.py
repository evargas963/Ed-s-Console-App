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
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from schwab.client import Client

import time_et
from app.options.order_flow.state import streamed_volume
from instrument_identity import ticker_storage_key
from json_blob_codec import decode_json_blob, encode_json_blob
from live_price_rows import price_row
from numeric_contract import schwab_number
from option_contract import (
    GREEK_FIELDS,
    read_chain,
    streamed_greek_set,
    streamed_greeks,
    streamed_top,
)
from schwab_client import (
    QUOTES_BATCH_MAX,
    flatten_chain_contracts,
    option_expiries,
    safe_get_chain,
    safe_get_quotes,
)
from stream_spine import CaptureWriter
from time_et import (
    CLOSED,
    ET,
    options_closed_at,
    options_open,
    record_markets,
    session,
    session_label,
)

log = logging.getLogger("chain_history")

CAPTURE_EVERY_MIN = 30
#: why the daemon's captures are complete: every listed expiry, every strike. The daemon writes
#: only this basis, and rows of any other are not read. The basis is stored before the chain
#: blob, so filtering on it never reads a chain (measured: filtering on `source`, stored after
#: the blob, read every chain -- 15 s for SPY, 80 s at startup).
CAPTURE_BASIS = (
    "every_expiry_strike_range_ALL"  # the only basis read: rows of any other are partial
)

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


#: the chain's one spot (Schwab's LAST_PRICE when the chain was complete) and its trade time; a
#: capture written before them has neither. `spot` is each expiry's own underlyingPrice, recorded
CHAIN_SPOT_COLUMNS = (("chain_spot", "REAL"), ("chain_spot_ts", "REAL"))


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(TABLE_SQL)
    have = {row[1] for row in conn.execute("PRAGMA table_info(complete_chain_captures)")}
    for name, kind in CHAIN_SPOT_COLUMNS:
        if name not in have:
            conn.execute(f"ALTER TABLE complete_chain_captures ADD COLUMN {name} {kind}")
    conn.commit()


@contextmanager
def capture_transaction(db_path: Path | str) -> Iterator[sqlite3.Connection]:
    """One transaction on the capture table.

    What is written in it commits together or not at all, so a reader finds a capture whole or
    finds none.
    """
    conn = sqlite3.connect(str(db_path), timeout=60.0)
    try:
        ensure_schema(conn)
        with conn:
            yield conn
    finally:
        conn.close()


def persist_complete_chain_capture(
    conn: sqlite3.Connection,
    *,
    ticker: str,
    expiry: str,
    contracts: list[Any],
    spot: float | None,
    completeness_basis: str,
    ts_utc: float,
    source: str = "schwab_chain_strike_range_all",
    chain_spot: float | None = None,
    chain_spot_ts: float | None = None,
) -> dict[str, Any]:
    """Append one COMPLETE single-expiry capture.

    `spot` is that expiry's underlyingPrice as Schwab sent it; `chain_spot` / `chain_spot_ts`
    the chain's one spot and its trade time (None when the daemon held no price). A time series
    (PRIMARY KEY includes ts_utc): each capture time is its own set of rows, one per expiry. A
    stored capture is never replaced: a second write of the same (ticker, expiry, ts_utc) raises
    sqlite3.IntegrityError and the stored row stands. `conn` is the capture_transaction the row
    joins.

    FAIL CLOSED: no contracts, or an unproven `completeness_basis`, writes NOTHING and
    says why — a persisted row with an empty or unverifiable completeness claim would be
    worse than no row, since a caller trusts what THIS table alone claims to be complete.
    """
    tk = ticker_storage_key(ticker)
    if not tk:
        return {"status": "skipped", "reason": "no_ticker"}
    exp = expiry.strip()[:10]
    if not exp:
        return {"status": "skipped", "reason": "no_expiry"}
    if not completeness_basis:
        return {"status": "skipped", "reason": "no_completeness_basis"}
    clean = [dict(c) for c in contracts if isinstance(c, dict)]
    if not clean:
        return {"status": "skipped", "reason": "no_contracts", "ticker": tk, "expiry": exp}

    ts = float(ts_utc)
    conn.execute(
        "INSERT INTO complete_chain_captures "
        "(ticker, expiry, ts_utc, spot, n_contracts, completeness_basis, chain_json, source, "
        "chain_spot, chain_spot_ts) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            tk,
            exp,
            ts,
            spot,
            len(clean),
            str(completeness_basis),
            encode_json_blob(clean, default=str),
            str(source),
            chain_spot,
            chain_spot_ts,
        ),
    )
    return {
        "status": "written",
        "ticker": tk,
        "expiry": exp,
        "ts_utc": ts,
        "n_contracts": len(clean),
        "completeness_basis": completeness_basis,
    }


def capture_slot(now_ts: float) -> float | None:
    """Return the capture time a chain begun at `now_ts` is written for.

    It is the latest of the option markets' open, every CAPTURE_EVERY_MIN minutes after it, and
    their last close (the close capture) -- the regular sessions Schwab's /markets sent for the
    day (time_et.session) -- that is at most CAPTURE_EVERY_MIN minutes before `now_ts`. None
    outside those windows, and on a day with no regular option session or no answer: nothing is
    written.
    """
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


#: contracts per chain message to the console: one message is encoded and decoded whole, so a
#: whole chain in one ($SPX, 29,394 contracts: 40.7 MB, 924 ms to encode, measured)
#: would hold the daemon's event loop; 500 contracts take tens of milliseconds
CHAIN_PART_CONTRACTS = 500


def chain_messages(
    ticker: str, contracts: list[dict], fetched_ts: float, spot: float | None, spot_ts: float | None
) -> list[tuple[str, dict]]:
    """Return a fetched chain as its bus messages.

    Part i of n, CHAIN_PART_CONTRACTS contracts each, all with the time the chain began and the
    chain's one spot with its trade time. Each contract is read here, once (read_chain, on the
    sweep's own thread): the console's pricing and the daemon's option rule both take that read.
    The console assembles the parts; a chain missing a part is never priced.
    """
    parts = [
        contracts[i : i + CHAIN_PART_CONTRACTS]
        for i in range(0, len(contracts), CHAIN_PART_CONTRACTS)
    ] or [[]]
    return [
        (
            f"chain.{ticker}",
            {
                "src": "schwab_chain",
                "ticker": ticker,
                "ts_recv": fetched_ts,
                "spot": spot,
                "spot_ts": spot_ts,
                "part": i,
                "parts": len(parts),
                "contracts": read_chain(part),
            },
        )
        for i, part in enumerate(parts)
    ]


#: Schwab's price history of every ticker (GET /pricehistory,
#: docs/schwab/schwab_market_data_parameters_pricehistory_markets.txt): series -> (periodType,
#: period, frequencyType, frequency). Each request ends now (endDate; without it Schwab ends at the
#: previous business day's close), extended hours included. The 1-minute bars once per ET date
#: (the stream's CHART_EQUITY bars carry them on from there); the 5-, 15- and 30-minute bars each
#: time one of theirs completes in a session (BAR_MINUTES); two years of daily candles once per ET
#: date and again after the regular close, for that day's (monthly ATR(14) needs 15 months).
PRICE_HISTORY = {
    "1m": ("day", 10, "minute", 1),
    "5m": ("day", 10, "minute", 5),
    "15m": ("day", 10, "minute", 15),
    "30m": ("day", 10, "minute", 30),
    "1d": ("year", 2, "daily", 1),
}
#: the minute series asked again as each of their bars completes, by the bar's minutes
BAR_MINUTES = {"5m": 5, "15m": 15, "30m": 30}


def price_history_message(
    ticker: str, series: str, answer: dict, fetched_ts: float
) -> tuple[str, dict]:
    """One series of a ticker's price history as its bus message.

    It is Schwab's whole answer as sent (its candles and every other field), recorded by the
    daemon's writer like every stream message.
    """
    return f"pricehistory.{ticker}.{series}", {
        "src": "schwab_pricehistory",
        "symbol": ticker,
        "series": series,
        "ts_recv": fetched_ts,
        "answer": answer,
    }


#: Schwab answers GET /markets for a date as far as 7 days back ("Date cannot be more than 7 days
#: in the past.", its 400 for a date 8 days back; 1 day back answered 200)
MARKETS_DAYS_BACK = 7
#: Schwab answers GET /markets for a date as far as a year ahead ("Valid date range is from
#: currentdate to 1 year from today",
#: docs/schwab/schwab_market_data_parameters_pricehistory_markets.txt line 17; its 400 "Date
#: cannot be beyond 1 year from today."): a later expiry is not asked until it is within that,
#: and its sessions stay unknown. The year is the calendar's: the same date next year (from
#: 29 February, 1 March), so a span that holds a 29 February is 366 days.


def markets_last_day(today: date) -> date:
    """Return the last date Schwab answers GET /markets for on ET date `today`: a year from it."""
    return date(today.year + 1, today.month, 1) + timedelta(days=today.day - 1)


#: Schwab's answer for a date, asked once per ET date: its sessions (200), or why it has none
#: (400). Any other answer is asked again.
MARKETS_ANSWERED = (200, 400)


def markets_message(day: str, status: int, answer: dict, fetched_ts: float) -> tuple[str, dict]:
    """Schwab's /markets answer for `day` as its bus message, as sent, with its status."""
    return f"markets.{day}", {
        "src": "schwab_markets",
        "date": day,
        "ts_recv": fetched_ts,
        "status": status,
        "answer": answer,
    }


def chain_failure_message(ticker: str, reason: str, ts: float) -> tuple[str, dict]:
    """Return a failed fetch as its one bus message: part 0 of 1, with Schwab's answer or error."""
    return f"chain.{ticker}", {
        "src": "schwab_chain",
        "ticker": ticker,
        "ts_recv": ts,
        "part": 0,
        "parts": 1,
        "failed": reason,
    }


@dataclass(eq=False)
class _Chain:
    """A ticker's chain from its first request until its last quote is in."""

    ticker: str
    started: float  # its first request
    spots: dict[str, float | None] = field(
        default_factory=dict
    )  # expiry -> Schwab's underlyingPrice in its answer
    spot: float | None = None  # the chain's one spot: LAST_PRICE when complete
    spot_ts: float | None = None  # that price's trade time
    by_expiry: dict[str, list[dict]] = field(default_factory=dict)
    unquoted: set[str] = field(default_factory=set)  # contracts whose quote is not in
    named_invalid: set[str] = field(default_factory=set)  # contracts Schwab's quotes named invalid
    pushed: int = 0  # contracts whose Greeks the stream pushed (LEVELONE_OPTIONS)
    requested: int = 0  # contracts asked for on /quotes for their Greeks

    def contracts(self) -> list[dict]:
        return [ct for cts in self.by_expiry.values() for ct in cts]


class ChainSweep:
    """The one fetcher of option chains.

    One thread, one request at a time on the daemon's one Schwab client, in one rotation
    (sorted, a ticker a page has selected before each other one, `rotation`): every watchlist
    ticker (`watchlist`, which the daemon replaces on
    each add or removal: an added ticker is in the next rotation, a removed one is asked for no
    more). For each ticker, Schwab's expiration
    chain once per ET date, then one chain request per expiry (strike_range=ALL), as Schwab says
    to break up a large chain. The chain's own Greeks (GREEK_FIELDS, rounded by Schwab) are never
    kept. A contract Schwab streams (its LEVELONE_OPTIONS record on the bus, `streamed`) with
    every Greek sent takes the stream's, each with its field's Schwab time (`greeksTime`,
    {field: ms}), and is not asked for again. Every other contract is asked for on the quotes
    endpoint, QUOTES_BATCH_MAX symbols to a request across tickers, and takes its quote as Schwab
    sent it (`quote`; its `greeksTime` is None). Each /quotes answer goes to the console at once
    with the time it was received (topic `optquotes`). A Greek Schwab does not send is absent
    (None).

    The price history (candles, fetch_price_history): each watchlist ticker's series of
    PRICE_HISTORY, each when it is due (series_due).

    The market's sessions (fetch_markets): Schwab's /markets answer for today and the
    MARKETS_DAYS_BACK days before it, and for each expiry date of the chains, each date asked
    once per ET date, whatever the number of tickers.

    A ticker's chain is asked for (chain_due) inside the option windows of Schwab's answer for
    today, pre-market included, to the last close (16:15 ET, when SPY's, QQQ's and IWM's stop too),
    while that answer is not known yet, and once more after the newest close it has not been
    fetched since (its close values; a failed one again in the next pass); otherwise not, until
    the next session. A ticker whose expiration chain lists no option (or none asked yet) has
    its chain asked once per ET date, to learn whether options are listed. A chain is published
    to the console in parts (chain_messages) once all its quotes are in; a ticker whose request
    fails (an answer other than 200, or none) is published as failed with the reason, and the
    rotation goes on. The first chain of a ticker
    begun inside a capture window (capture_slot) is also written to the chain history; a history
    write that fails is a write failure, never the chain's: the chain as delivered is handed to
    `failures` (the daemon's writer) to keep.
    """

    def __init__(
        self,
        db_path: Path | str,
        watchlist: list[str],
        publish: Callable[[str, dict], object],
        clock: Callable[[], float] = time_et.now,
        *,
        failures: CaptureWriter,
        streamed: Callable[[str], tuple[str, dict] | None],
        shown: Callable[[], list[str]] = list,
    ) -> None:
        self.db_path = db_path
        self.shown = shown  # the watchlist tickers a page has selected, read before each chain
        self.watchlist = list(watchlist)  # the daemon's list, replaced whole on each change
        self.publish = publish  # (topic, msg) -> None, safe from any thread
        self.clock = clock  # when a request begins, and when a chain is delivered
        self.failures = failures  # the daemon's writer: keeps a failed history write
        self.streamed = streamed  # option symbol -> its stream record on the bus, or None
        self.round_sec: float | None = None
        self.waiting: str | None = None  # why no chain is asked for (waits), else None
        self._expiries: dict[str, tuple[date, list[date]]] = {}  # ticker -> (ET date, expiries)
        self._markets_day: dict[str, date] = {}  # market date -> the ET date Schwab answered it
        self._optioned: set[str] = set()  # tickers Schwab has answered a chain for
        self._fetched: dict[str, float] = {}  # ticker -> when its newest delivered chain began
        # (ticker, series) -> when its newest answered request began
        self._candled: dict[tuple[str, str], float] = {}
        self._queue: list[tuple[_Chain, dict]] = []  # contracts whose quote is not asked for
        self._delivered: set[str] = set()  # the tickers this rotation delivered
        self._written: dict[str, float | None] = {}  # ticker -> its newest history capture

    def work(self, schwab_client, stop: threading.Event) -> None:
        """Run the thread's life, until `stop`.

        On the daemon's client (`schwab_client()`), the market's sessions for today and the days
        before it, then the price history of the watchlist tickers whose candles are due (the
        price-built levels wait for it, a rotation takes minutes) and a rotation of those whose
        chain is due; with none due, it looks again each second. With the watchlist empty, or no
        sign-in held (waits), it asks Schwab for nothing and looks again each second: a sign-in
        Schwab refused fails every request at once, and a round of them would only log each
        failure.
        """
        while not stop.is_set():
            if not self.step(schwab_client, stop):
                stop.wait(1.0)

    def step(self, schwab_client, stop: threading.Event) -> bool:
        """One pass of `work`: whether it asked for any price history or chain."""
        if self.waits(schwab_client) is not None or not self.watchlist:
            return False
        today = datetime.fromtimestamp(self.clock(), ET).date()
        self.fetch_markets(
            schwab_client,
            [(today - timedelta(days=n)).isoformat() for n in range(MARKETS_DAYS_BACK, -1, -1)],
        )
        now = datetime.fromtimestamp(self.clock(), ET)
        chains = [t for t in sorted(self.watchlist) if self.chain_due(t, now)]
        candles = {t: due for t in sorted(self.watchlist) if (due := self.candles_due(t, now))}
        if candles:
            self.candles(schwab_client, candles, stop)
        if chains:
            self.rotation(schwab_client, chains, stop)
        return bool(chains or candles)

    def waits(self, schwab_client) -> str | None:
        """Why the daemon holds no Schwab sign-in to ask with, kept as `waiting` for its status.

        Else None. Its client not built (capture.one_schwab_client: built again on each ask until
        a build succeeds), or Schwab having refused it (schwab_client.OneRefreshSession.refusal).
        A build that fails (no usable token file), or a token file locked past its wait, is
        logged once, until it passes.
        """
        try:
            self.waiting = schwab_client().session.refusal()
        except (ConnectionError, TimeoutError) as e:
            why = (
                f"the daemon holds no Schwab sign-in to ask with ({e}); a new one is saved by "
                "python reauth_schwab.py"
            )
            if why != self.waiting:
                log.warning(
                    "chain sweep waits for the daemon's Schwab client: %s", e, exc_info=True
                )
            self.waiting = why
        return self.waiting

    def candles_due(self, ticker: str, now: datetime) -> list[str]:
        """The series of `ticker`'s price history asked for at `now` (series_due)."""
        return [s for s in PRICE_HISTORY if self.series_due(ticker, s, now)]

    def series_due(self, ticker: str, series: str, now: datetime) -> bool:
        """Whether one series of `ticker`'s price history is asked for at `now`.

        Never answered yet: due. A minute series of BAR_MINUTES: once one of its bars has
        completed since it was asked, unless Schwab's sessions (time_et.session_label) were
        closed both then and now: the bar that ends a session is asked once after it, and a
        session not known (Schwab's /markets answer not held) is asked as an open one, as the
        chain is (chain_due). The daily
        candles: once per ET date, and once after today's regular window Schwab sent has ended.
        The 1-minute bars: once per ET date.
        """
        if (ticker, series) not in self._candled:
            return True
        asked = self._candled[(ticker, series)]
        if series in BAR_MINUTES:
            span = BAR_MINUTES[series] * 60
            in_session = (session_label(now), session_label(datetime.fromtimestamp(asked, ET))) != (
                CLOSED,
                CLOSED,
            )
            return now.timestamp() // span > asked // span and in_session
        if datetime.fromtimestamp(asked, ET).date() < now.date():
            return True
        if series != "1d":
            return False
        today = session(now.date().isoformat())
        if today is None or not today.regular:
            return False
        return asked < today.regular[-1][1].timestamp() <= now.timestamp()

    def chain_due(self, ticker: str, now: datetime) -> bool:
        """Whether `ticker`'s chain is asked for at `now`.

        It is inside an option window Schwab sent
        (time_et.options_open), or today's session not known (Schwab's /markets answer
        for today not held), or closed with the newest close after the ticker's newest delivered
        chain began. A ticker with no chain answer yet (none asked, or no option listed) is asked
        once per ET date.
        """
        if ticker not in self._optioned:
            return (
                ticker not in self._fetched
                or datetime.fromtimestamp(self._fetched[ticker], ET).date() < now.date()
            )
        if options_open(now) is not False:
            return True
        closed = options_closed_at(now)
        return closed is not None and (
            ticker not in self._fetched or self._fetched[ticker] < closed.timestamp()
        )

    def fetch_markets(self, schwab_client, days: list[str]) -> None:
        """Schwab's GET /markets?markets=equity,option answer for each of `days` (YYYY-MM-DD).

        Each day not answered on this ET date and inside the year Schwab answers
        (markets_last_day), one request each: a 200 is that date's sessions from here on
        (time_et.record_markets), and every answer is published as sent (markets_message), for
        the daemon's writer to record and the console to take. An answer not in MARKETS_ANSWERED
        (log_request has it), or none, is asked again the next time.
        """
        today = datetime.fromtimestamp(self.clock(), ET).date()
        for day in days:
            if self._markets_day.get(day) == today:
                continue
            if date.fromisoformat(day) > markets_last_day(today):
                continue
            try:
                resp = schwab_client().get_market_hours(
                    [Client.MarketHours.Market.EQUITY, Client.MarketHours.Market.OPTION],
                    date=date.fromisoformat(day),
                )
                answer = resp.json()
            except Exception as e:  # that date's answer is the failure; it is asked again
                log.warning(
                    "market hours for %s failed: %s: %s", day, type(e).__name__, e, exc_info=True
                )
                continue
            if resp.status_code == 200:
                record_markets(answer)
            if resp.status_code in MARKETS_ANSWERED:
                self._markets_day[day] = today
            self.publish(*markets_message(day, resp.status_code, answer, self.clock()))

    def rotation(self, schwab_client, tickers: list[str], stop: threading.Event) -> set[str]:
        """Each ticker's chain in turn, a ticker on a page before each other one.

        Before each ticker's chain, the chain of every ticker a page has selected (`shown`, read
        then: operator 2026-11-11, the ticker on the screen first) with all its quotes, so it is
        delivered before the next ticker is asked for; never the same ticker twice in a row. A
        chain is asked for only while it is due (chain_due), so one delivered after the close is
        not asked again. One removed from the watchlist since the rotation began is not asked
        for; the other queued quotes asked for whenever a full request's worth is waiting and
        the rest at the end; the tickers delivered. Its time is the round's (`round_sec`) only
        when it asked for every watchlist ticker: the console judges a ticker's chain overdue by
        the round, and a round of a few tickers is shorter than the watchlist's.
        """
        started = self.clock()
        self._delivered = set()
        last = None
        for ticker in tickers:
            shown = self.shown()
            for asked in (*shown, ticker):
                if stop.is_set() or asked == last or asked not in self.watchlist:
                    continue
                if not self.chain_due(asked, datetime.fromtimestamp(self.clock(), ET)):
                    continue
                self.fetch_chain(schwab_client, asked, stop)
                last = asked
                whole = 1 if asked in shown else QUOTES_BATCH_MAX
                while len(self._queue) >= whole and not stop.is_set():
                    self.send_quotes(schwab_client)
        while self._queue and not stop.is_set():
            self.send_quotes(schwab_client)
        took = self.clock() - started
        if set(self.watchlist) <= set(tickers):
            self.round_sec = took
        log.info(
            "chain rotation: %d of %d tickers delivered in %.0f s",
            len(self._delivered),
            len(tickers),
            took,
        )
        return self._delivered

    def candles(self, schwab_client, due: dict[str, list[str]], stop: threading.Event) -> None:
        """Each ticker's due series of its price history (`due`), ticker by ticker.

        One removed from the watchlist meanwhile is not asked for.
        """
        for ticker, series in due.items():
            if stop.is_set():
                break
            if ticker in self.watchlist:
                self.fetch_price_history(schwab_client, ticker, series)

    def fetch_price_history(self, schwab_client, ticker: str, due: list[str]) -> None:
        """Fetch the `due` series of `ticker`'s price history (PRICE_HISTORY).

        Each is published as Schwab sent its candles; one Schwab does not answer 200 is not
        published (log_request has the answer) and is asked again the next time (series_due).
        """
        for series in due:
            period_type, period, frequency_type, frequency = PRICE_HISTORY[series]
            now = self.clock()
            try:
                resp = schwab_client().get_price_history(
                    ticker,
                    period_type=period_type,
                    period=period,
                    frequency_type=frequency_type,
                    frequency=frequency,
                    end_datetime=datetime.fromtimestamp(now, UTC),
                    need_extended_hours_data=True,
                )
                if resp.status_code != 200:
                    continue
                answer = resp.json()
            except Exception as e:  # that series' answer is the failure; the next series is asked
                log.warning(
                    "price history %s %s failed: %s: %s",
                    ticker,
                    series,
                    type(e).__name__,
                    e,
                    exc_info=True,
                )
                continue
            self.publish(*price_history_message(ticker, series, answer, self.clock()))
            self._candled[(ticker, series)] = now

    def fetch_chain(self, schwab_client, ticker: str, stop: threading.Event) -> None:
        """Fetch `ticker`'s chain, every expiry.

        Each contract's Greeks from the stream, or the contract queued for its quote; delivered
        at once when none is queued. A stop asked between two
        expiries ends it there: no expiry more is asked for, and the part fetched is not a chain.
        """
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
            self.fetch_markets(schwab_client, [expiry.isoformat() for expiry in listed[1]])
            for expiry in listed[1]:
                if stop.is_set():
                    return None
                resp = safe_get_chain(
                    client, ticker, strike_range="ALL", from_date=expiry, to_date=expiry
                )
                if resp.status_code == 429:  # one refused expiry does not cost the ticker a round
                    resp = safe_get_chain(
                        client, ticker, strike_range="ALL", from_date=expiry, to_date=expiry
                    )
                if resp.status_code != 200:
                    return self.fail(
                        [chain], f"chain for {expiry} returned HTTP {resp.status_code}"
                    )
                payload = resp.json()
                self._optioned.add(ticker)
                chain.spots[expiry.isoformat()] = schwab_number(payload.get("underlyingPrice"))
                chain.by_expiry[expiry.isoformat()] = flatten_chain_contracts(payload)
        except Exception as e:  # that ticker's answer is the failure; the rotation goes on
            log.warning("chain %s failed: %s: %s", ticker, type(e).__name__, e, exc_info=True)
            return self.fail([chain], f"{type(e).__name__}: {e}")
        return self.take_greeks(chain)

    def take_greeks(self, chain: _Chain) -> None:
        """Each contract of a fetched chain takes its Greeks from the stream, or queues for them.

        With them it takes the stream's bid, ask and volume as the stream holds them now
        (`streamed`), so the chain as delivered and as stored carries a streamed contract's quote
        as it carries a quoted one's: the close values and a stored capture hold them. A contract
        the stream holds no full set of Greeks for is queued for its quote; the chain is
        delivered at once when none is queued.
        """
        for ct in chain.contracts():
            ct["totalVolume"] = None  # the stream's or the quote's
            entry = self.streamed(ct["symbol"])
            if (
                entry is not None
                and (greeks := streamed_greek_set(streamed_greeks(entry[1]["content"]))) is not None
            ):
                top = streamed_top(entry[1]["content"])
                ct.update(greeks)
                ct["greeksTime"] = {g: entry[1]["field_ts"][g.upper()][0] for g in GREEK_FIELDS}
                ct["streamed"] = {
                    "bid": top.get("bid"),
                    "ask": top.get("ask"),
                    "volume": streamed_volume(entry[1]["content"]),
                }
                chain.pushed += 1
            else:
                ct.update(dict.fromkeys(GREEK_FIELDS))
                ct["greeksTime"] = None
                chain.unquoted.add(ct["symbol"])
                chain.requested += 1
                self._queue.append((chain, ct))
        if not chain.unquoted:
            self.deliver(chain)

    def send_quotes(self, schwab_client) -> None:
        """One quotes request for the next QUOTES_BATCH_MAX queued contracts.

        They take their quote's Greeks; each chain it completes is delivered. A request that
        fails fails every ticker in it. Schwab's answer carries a quote per symbol it knows and,
        beside them, an `errors` entry naming the symbols it does not (`invalidSymbols`;
        measured: 8 SPY contracts its own chain lists, every one never quoted or traded): those
        contracts get no Greeks, logged once with their count, and the rest of the request is
        delivered.
        """
        self._queue = [
            (chain, ct) for chain, ct in self._queue if chain.ticker in self.watchlist
        ]  # removed: not asked
        batch, self._queue = self._queue[:QUOTES_BATCH_MAX], self._queue[QUOTES_BATCH_MAX:]
        chains = list({id(chain): chain for chain, _ct in batch}.values())
        try:
            resp = safe_get_quotes(schwab_client(), [ct["symbol"] for _chain, ct in batch])
            if resp.status_code != 200:
                self.fail(
                    chains, f"quotes for {len(batch)} contracts returned HTTP {resp.status_code}"
                )
                return
            answer = resp.json()
            errors = answer.pop("errors") if "errors" in answer else {}
            named = set(errors["invalidSymbols"]) if "invalidSymbols" in errors else set()
            quoted = {s: e["quote"] for s, e in answer.items()}
            # Schwab's quote per symbol as sent, to the console at once with its receive time
            self.publish(
                "optquotes", {"src": "schwab_quotes", "ts_recv": self.clock(), "answer": quoted}
            )
        except Exception as e:  # those tickers' answer is the failure; the rotation goes on
            log.warning(
                "quotes for %d contracts failed: %s: %s",
                len(batch),
                type(e).__name__,
                e,
                exc_info=True,
            )
            self.fail(chains, f"{type(e).__name__}: {e}")
            return
        if errors:
            log.warning(
                "quotes for %d contracts: Schwab named %d invalid, which have no Greeks: %s",
                len(batch),
                len(named),
                json.dumps(errors),
            )
        for chain, ct in batch:
            quote = quoted.get(ct["symbol"])
            if quote is not None:
                # Schwab's /quotes answer for the contract, as sent: its values are read from it
                ct["quote"] = quote
            elif ct["symbol"] in named:
                chain.named_invalid.add(ct["symbol"])
            chain.unquoted.discard(ct["symbol"])
        for chain in chains:
            if not chain.unquoted:
                self.deliver(chain)

    def fail(self, chains: list[_Chain], reason: str) -> None:
        """Each chain's ticker is published as failed with `reason`; its contracts leave the queue.

        The log has the cause already: Schwab's answer (schwab_client.log_request) or the error.
        """
        now = self.clock()
        self._queue = [(chain, ct) for chain, ct in self._queue if chain not in chains]
        for chain in chains:
            self.publish(*chain_failure_message(chain.ticker, reason, now))

    def deliver(self, chain: _Chain) -> None:
        """Deliver the chain to the chain history when it is the window's first, then the console.

        Ordered so a read on its arrival finds that capture, both carrying the time the chain
        began (its as-of everywhere: a chain begun before the close is not the close values,
        whenever it is delivered) and its one spot: Schwab's LAST_PRICE with its trade time, as the
        daemon's price row holds it now that the chain is complete.
        """
        now = self.clock()
        row = price_row(chain.ticker, now)
        if row["spot"] is not None:  # a trade time without its price is no spot
            chain.spot, chain.spot_ts = row["spot"], row["trade_ts"]
        contracts = chain.contracts()
        try:
            self._write_history(chain)
        except Exception as e:  # the chain still goes to the console; the failure is kept and shown
            log.warning(
                "chain history for %s not written, kept as delivered: %s: %s",
                chain.ticker,
                type(e).__name__,
                e,
                exc_info=True,
            )
            self.failures.keep_failure(
                f"chain_history.{chain.ticker}",
                {
                    "started": chain.started,
                    "spots": chain.spots,
                    "spot": chain.spot,
                    "spot_ts": chain.spot_ts,
                    "contracts": contracts,
                },
                e,
                now,
            )
        for topic, msg in chain_messages(
            chain.ticker, contracts, chain.started, chain.spot, chain.spot_ts
        ):
            self.publish(topic, msg)
        self._delivered.add(chain.ticker)
        self._fetched[chain.ticker] = chain.started
        log.info(
            "CHAIN %s: %d contracts in %d expiries asked on /chains (open interest) | Greeks: %d "
            "pushed by LEVELONE_OPTIONS, %d requested on /quotes, %d Schwab named invalid | "
            "%.1f s from the first request",
            chain.ticker,
            len(contracts),
            len(chain.by_expiry),
            chain.pushed,
            chain.requested,
            len(chain.named_invalid),
            now - chain.started,
        )
        missing = sum(
            1
            for ct in contracts
            if "quote" not in ct
            and ct["greeksTime"] is None
            and ct["symbol"] not in chain.named_invalid
        )
        if missing:
            log.warning(
                "quotes for %s: no quote came back for %d of %d contracts; their Greeks are absent",
                chain.ticker,
                missing,
                len(contracts),
            )

    def _write_history(self, chain: _Chain) -> None:
        """Write the chain history.

        A chain begun inside a capture window of the ticker's option market,
        the first one of the window for this ticker (a chain begun before the close is not the
        close capture, whenever it ends), one row per expiry with the underlying price of that
        expiry's answer, at the time the chain began, every row in one transaction.
        """
        ticker = chain.ticker
        slot = capture_slot(chain.started)
        if slot is None:
            return
        if ticker not in self._written:
            self._written[ticker] = newest_capture_ts(self.db_path, ticker)
        before = self._written[ticker]
        if before is not None and before >= slot:
            return
        self._written[ticker] = slot  # claim the window for this ticker
        try:
            with capture_transaction(self.db_path) as conn:
                for expiry, cts in chain.by_expiry.items():
                    persist_complete_chain_capture(
                        conn,
                        ticker=ticker,
                        expiry=expiry,
                        contracts=cts,
                        spot=chain.spots[expiry],
                        completeness_basis=CAPTURE_BASIS,
                        ts_utc=chain.started,
                        chain_spot=chain.spot,
                        chain_spot_ts=chain.spot_ts,
                    )
        except Exception:
            self._written[ticker] = before  # unwritten: the window's next chain, if any, tries
            raise


def newest_capture_ts(db_path: Path | str, ticker: str) -> float | None:
    """When the ticker's newest full capture was taken.

    None when there is none.
    """
    if not Path(db_path).is_file():
        return None
    conn = sqlite3.connect(f"file:{Path(db_path).resolve().as_posix()}?mode=ro", uri=True)
    try:
        if not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='complete_chain_captures'"
        ).fetchone():
            return None
        return conn.execute(
            "SELECT MAX(ts_utc) FROM complete_chain_captures WHERE ticker=? "
            "AND completeness_basis=?",
            (ticker_storage_key(ticker), CAPTURE_BASIS),
        ).fetchone()[0]
    finally:
        conn.close()


def last_capture_per_day(
    db_path: Path | str,
    ticker: str,
    days: int,
    *,
    before_et_date: str | None = None,
) -> list[dict[str, Any]]:
    """Return the last capture of each of the newest `days` market days (newest first).

    That is the close, each as {et_date, ts_utc, spot, spot_ts, basis, contracts} with every
    expiry of that capture, its contracts read once (option_contract.read_chain). `spot` is the
    chain's one spot with its trade time `spot_ts`: Schwab's LAST_PRICE when the chain was
    complete. A capture stored without one has no spot (None, None): the underlyingPrice of its
    /chains answers is recorded beside it and read by nothing.
    `before_et_date` keeps only days before it (the previous market day for a day-over-day
    view).
    """
    tk = ticker_storage_key(ticker)
    conn = sqlite3.connect(f"file:{Path(db_path).resolve().as_posix()}?mode=ro", uri=True)
    try:
        if not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='complete_chain_captures'"
        ).fetchone():
            return []  # no capture has ever been written
        picked: list[tuple[str, float]] = []
        for (ts,) in conn.execute(
            "SELECT DISTINCT ts_utc FROM complete_chain_captures "
            "WHERE ticker=? AND completeness_basis=? ORDER BY ts_utc DESC",
            (tk, CAPTURE_BASIS),
        ):
            day = datetime.fromtimestamp(ts, ET).date().isoformat()
            if before_et_date is not None and day >= before_et_date:
                continue
            if picked and picked[-1][0] == day:
                continue
            picked.append((day, ts))
            if len(picked) == days:
                break
        have = {row[1] for row in conn.execute("PRAGMA table_info(complete_chain_captures)")}
        chain_spot = (
            ", ".join(name for name, _kind in CHAIN_SPOT_COLUMNS)
            if "chain_spot" in have
            else "NULL, NULL"
        )
        out = []
        for day, ts in picked:
            rows = conn.execute(
                f"SELECT {chain_spot}, completeness_basis, chain_json "
                "FROM complete_chain_captures "
                "WHERE ticker=? AND completeness_basis=? AND ts_utc=? ORDER BY expiry",
                (tk, CAPTURE_BASIS, ts),
            ).fetchall()
            spot, spot_ts = rows[0][0], rows[0][1]
            out.append(
                {
                    "et_date": day,
                    "ts_utc": ts,
                    "spot": spot,
                    # a trade time without its price is no spot
                    "spot_ts": None if spot is None else spot_ts,
                    "basis": rows[0][2],
                    "contracts": read_chain(c for r in rows for c in decode_json_blob(r[3])),
                }
            )
        return out
    finally:
        conn.close()
