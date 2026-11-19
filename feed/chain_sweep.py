"""The option chains (DATA_FLOW decisions 1 and 7): Feed's chain sweep, run by the capture daemon.

While a watchlist ticker's options trade -- the regular session Schwab's /markets sends for its
option market (EQO for stock and ETF options, IND for index options) -- the daemon fetches its
full chain (every expiry, every strike) in turn with every other such ticker of the watchlist
(the daemon's one list, capture.Daemon.watchlist), without end (ChainSweep); once that session
closes, once more (the close values), and then nothing until the next one. Each chain is handed
to the console for the levels. The first chain of each ticker begun at or after its own option
close each day (capture_slot) holds the day's close values, the one capture the levels read; it
is stored first: the Recorder (stream_spine.CaptureWriter.store_capture) commits it to the
capture table (calibration/complete_chain_capture.py) before the console hears of it. Nothing
else is stored as a capture (weekend chains blank open interest); every /chains and /quotes
answer is recorded as received beside it (rest_chains_raw, rest_quotes_raw).
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import time_et
from app.options.order_flow.state import streamed_record
from calibration.complete_chain_capture import capture_message
from feed.schwab_client import (
    QUOTES_BATCH_MAX,
    REQUESTS_AT_ONCE,
    Answer,
    flatten_chain_contracts,
    get_market_hours,
    get_price_history,
    option_expiries,
    safe_get_chain,
    safe_get_quotes,
)
from live_price_rows import price_row
from numeric_contract import schwab_number
from option_contract import (
    GREEK_FIELDS,
    read_chain,
    streamed_greek_set,
    streamed_quote,
)
from state import capture_store
from stream_spine import CAPTURE_REFUSED, CAPTURE_STORED, CaptureWriter
from time_et import (
    CLOSED,
    ET,
    option_close_product,
    options_closed_at,
    options_open,
    record_markets,
    session,
    session_label,
)

log = logging.getLogger("chain_history")

#: seconds a chain waits for the Recorder to commit its capture before the console hears of it
#: (store first); a capture not committed by then is held by the Recorder and written later, and
#: the chain goes to the console as no capture. The Recorder commits every 0.25 s
#: (CaptureWriter.batch_sec), so only a database refusing writes reaches it.
CAPTURE_WAIT_SEC = 10.0
#: seconds a ticker's /chains answers are taken again before they are asked for again (the
#: operator's setting)
CHAINS_AGAIN_SEC = 300


def capture_slot(now_ts: float, ticker: str) -> float | None:
    """Return the close a chain of `ticker` begun at `now_ts` is the capture of; None if none.

    The ticker's own option close today (time_et.option_close_product: the equity options' close,
    or the index options' for an index), as Schwab's /markets sent it (time_et.session): a chain
    begun at or after it, that ET day, holds the day's close values, the one capture a day the
    levels read (a closed market's balance, the next day's prior day and its forces). None before
    it, and on a day with no regular option session or no answer: nothing is written.
    """
    today = session(datetime.fromtimestamp(now_ts, ET).date().isoformat())
    if today is None:
        return None
    product = option_close_product(ticker)
    windows = [w for p, ws in today.options if p == product for w in ws]
    if not windows:
        return None
    close = max(e for _s, e in windows).timestamp()
    return close if now_ts >= close else None


#: contracts per chain message to the console: one message is encoded and decoded whole, so a
#: whole chain in one ($SPX, 29,394 contracts: 40.7 MB, 924 ms to encode, measured)
#: would hold the daemon's event loop; 500 contracts take tens of milliseconds
CHAIN_PART_CONTRACTS = 500


def chain_messages(
    ticker: str,
    contracts: list[dict[str, Any]],
    fetched_ts: float,
    spot: float | None,
    spot_ts: float | None,
    capture: bool,
) -> list[tuple[str, dict[str, Any]]]:
    """Return a fetched chain as its bus messages.

    Part i of n, CHAIN_PART_CONTRACTS contracts each, all with the time the chain began, the
    chain's one spot with its trade time, and whether it is its day's stored close capture
    (`capture`: the console keeps it, state.capture_store). Each contract is read here, once
    (read_chain, on the sweep's own thread): the console's pricing and the daemon's option rule
    both take that read. The console assembles the parts; a chain missing a part is never priced.
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
                "capture": capture,
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
#: time one of theirs completes in a session (BAR_MINUTES); two years of daily, weekly and monthly
#: candles, each as Schwab sends it, once per ET date and again after the regular close, for that
#: day's (ATR(14) needs 15 candles).
PRICE_HISTORY: dict[str, tuple[str, int | None, str, int]] = {
    "1m": ("day", 10, "minute", 1),
    "1m60": ("day", None, "minute", 1),
    "5m": ("day", 10, "minute", 5),
    "15m": ("day", 10, "minute", 15),
    "30m": ("day", 10, "minute", 30),
    "1d": ("year", 2, "daily", 1),
    "1w": ("year", 2, "weekly", 1),
    "1mo": ("year", 2, "monthly", 1),
    "5m365": ("day", None, "minute", 5),
    "5m365r": ("day", None, "minute", 5),
}
#: the minute series asked again as each of their bars completes, by the bar's minutes
BAR_MINUTES = {"5m": 5, "15m": 15, "30m": 30}
#: the series asked from a start date instead of a period, by calendar days back, the regular
#: session's bars only: 90 days, about 60 sessions, of 1-minute bars for the levels' hold rates
#: (calc.liquidity_value_engine.hold_counts). Schwab documents startDate for every frequency but
#: not how far back it answers minute bars
HISTORY_DAYS_BACK = {"1m60": 90, "5m365": 365, "5m365r": 365}
#: the series asked from a start date with extended hours, the pre-market's bars among them: a
#: year of 5-minute bars, as far back as Schwab answers, for the open-gap record (open_gap.py).
#: Its twin 5m365r, the regular session's bars alone, is Schwab's own mark of each past day's
#: session (its first bar the open), which /markets answers only 7 days back
EXTENDED_FROM_START = ("5m365",)
#: the series asked once per ET date
DAILY_ONCE = ("1m", "1m60", "5m365", "5m365r")


def price_history_message(
    ticker: str, series: str, answer: dict[str, Any], fetched_ts: float
) -> tuple[str, dict[str, Any]]:
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


def markets_message(
    day: str, status: int, answer: dict[str, Any], fetched_ts: float
) -> tuple[str, dict[str, Any]]:
    """Schwab's /markets answer for `day` as its bus message, as sent, with its status."""
    return f"markets.{day}", {
        "src": "schwab_markets",
        "date": day,
        "ts_recv": fetched_ts,
        "status": status,
        "answer": answer,
    }


def chain_answer_message(
    ticker: str, expiry: date, resp: Answer, fetched_ts: float
) -> tuple[str, dict[str, Any]]:
    """One expiry's /chains answer as its bus message: the body exactly as received, its status.

    Recorded by the daemon's writer (rest_chains_raw); no screen reads it.
    """
    return f"chainanswer.{ticker}", {
        "src": "schwab_chains",
        "symbol": ticker,
        "expiry": expiry.isoformat(),
        "ts_recv": fetched_ts,
        "status": resp.status_code,
        "body": resp.text,
    }


def quotes_answer_message(resp: Answer, fetched_ts: float) -> tuple[str, dict[str, Any]]:
    """One /quotes answer as its bus message: the body exactly as received, its status.

    Recorded by the daemon's writer (rest_quotes_raw); the console takes the quotes from
    `optquotes`.
    """
    return "quotesanswer", {
        "src": "schwab_quotes",
        "ts_recv": fetched_ts,
        "status": resp.status_code,
        "body": resp.text,
    }


def chain_failure_message(ticker: str, reason: str, ts: float) -> tuple[str, dict[str, Any]]:
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
        default_factory=dict[str, float | None]
    )  # expiry -> Schwab's underlyingPrice in its answer
    spot: float | None = None  # the chain's one spot: LAST_PRICE when complete
    spot_ts: float | None = None  # that price's trade time
    by_expiry: dict[str, list[dict[str, Any]]] = field(
        default_factory=dict[str, list[dict[str, Any]]]
    )
    unquoted: set[str] = field(default_factory=set[str])  # contracts whose quote is not in
    # contracts Schwab's quotes named invalid
    named_invalid: set[str] = field(default_factory=set[str])
    pushed: int = 0  # contracts whose Greeks the stream pushed (LEVELONE_OPTIONS)
    requested: int = 0  # contracts asked for on /quotes for their Greeks
    answers_age: float = 0.0  # seconds from its /chains answers' request to its own (fetch_chain)
    # expiry -> Schwab's /chains answer body, the text exactly as received
    bodies: dict[str, str] = field(default_factory=dict[str, str])

    def contracts(self) -> list[dict[str, Any]]:
        return [ct for cts in self.by_expiry.values() for ct in cts]


#: a contract of a chain whose quote is not in, with its chain
type _Queued = tuple[_Chain, dict[str, Any]]
#: a ticker's /chains answers: (their capture window, when they were asked for, each expiry's
#: underlyingPrice, each expiry's contracts as sent, each expiry's answer body as received)
type _Answers = tuple[
    float | None,
    float,
    dict[str, float | None],
    dict[str, list[dict[str, Any]]],
    dict[str, str],
]
#: the daemon's Schwab client, built on each ask (capture.one_schwab_client): schwab-py's, untyped
type _SchwabClient = Callable[[], Any]


class ChainSweep:
    """The one fetcher of option chains.

    One thread on the daemon's one Schwab client, its /chains and /quotes requests sent
    REQUESTS_AT_ONCE together (each ticker's expiries; the queued quotes), in one rotation
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
    today, pre-market included, to the last close (16:15 ET, when the options on the exchanges'
    4:15 p.m. list stop too),
    while that answer is not known yet, and once more after the newest close it has not been
    fetched since (its close values; a failed one again in the next pass); otherwise not, until
    the next session. A ticker whose expiration chain lists no option (or none asked yet) has
    its chain asked once per ET date, to learn whether options are listed. A chain is published
    to the console in parts (chain_messages) once all its quotes are in; a ticker whose request
    fails (an answer other than 200, or none) is published as failed with the reason, and the
    rotation goes on. The first chain of a ticker begun at or after its option close each day
    (capture_slot) is also written to the chain history, its close capture; a history
    write that fails is a write failure, never the chain's: the chain as delivered is handed to
    `failures` (the daemon's writer) to keep.
    """

    def __init__(
        self,
        db_path: Path | str,
        watchlist: list[str],
        publish: Callable[[str, dict[str, Any]], object],
        clock: Callable[[], float] = time_et.now,
        *,
        failures: CaptureWriter,
        streamed: Callable[[str], tuple[str, dict[str, Any]] | None],
        shown: Callable[[], list[str]] = list,
    ) -> None:
        self.db_path = db_path
        self.shown = shown  # the watchlist tickers a page has selected, read before each chain
        self.watchlist = list(watchlist)  # the daemon's list, replaced whole on each change
        self.publish = publish  # (topic, msg) -> None, safe from any thread
        self.clock = clock  # when a request begins, and when a chain is delivered
        self.failures = failures  # the daemon's writer: keeps a failed history write
        self.streamed = streamed  # option symbol -> its stream record on the bus, or None
        self.began: float | None = None  # this run's first rotation began: a chain since is ours
        self.round_sec: float | None = None
        self.waiting: str | None = None  # why no chain is asked for (waits), else None
        self._expiries: dict[str, tuple[date, list[date]]] = {}  # ticker -> (ET date, expiries)
        self._markets_day: dict[str, date] = {}  # market date -> the ET date Schwab answered it
        self._optioned: set[str] = set()  # tickers Schwab has answered a chain for
        self._fetched: dict[str, float] = {}  # ticker -> when its newest delivered chain began
        # (ticker, series) -> when its newest answered request began
        self._candled: dict[tuple[str, str], float] = {}
        self._queue: list[_Queued] = []  # contracts whose quote is not asked for
        self._delivered: set[str] = set()  # the tickers this rotation delivered
        self._written: dict[str, float | None] = {}  # ticker -> its newest history capture
        self._asking = ThreadPoolExecutor(REQUESTS_AT_ONCE, thread_name_prefix="asking")
        #: ticker -> its newest /chains answers: (their capture window, when they were asked for,
        #: each expiry's underlyingPrice, each expiry's contracts as sent)
        self._answers: dict[str, _Answers] = {}

    def work(self, schwab_client: _SchwabClient, stop: threading.Event) -> None:
        """Run the thread's life, until `stop`.

        On the daemon's client (`schwab_client()`), the market's sessions for today and the days
        before it, then a rotation of the watchlist tickers whose chain is due, with their due
        price history (the ticker on a page first: its own candles, then its chain, before the
        other tickers' candles), and the price history of those whose chain is not due; with
        none due, it looks again each second. With the watchlist empty, or no
        sign-in held (waits), it asks Schwab for nothing and looks again each second: a sign-in
        Schwab refused fails every request at once, and a round of them would only log each
        failure.
        """
        while not stop.is_set():
            if not self.step(schwab_client, stop):
                stop.wait(1.0)

    def step(self, schwab_client: _SchwabClient, stop: threading.Event) -> bool:
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
        asked = bool(chains or candles)
        if chains:
            self.rotation(schwab_client, chains, stop, candles)
        self.candles(schwab_client, candles, stop)  # of the tickers whose chain is not due
        return asked

    def waits(self, schwab_client: _SchwabClient) -> str | None:
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
        """Return the series of `ticker`'s price history asked for at `now` (series_due)."""
        return [s for s in PRICE_HISTORY if self.series_due(ticker, s, now)]

    def series_due(self, ticker: str, series: str, now: datetime) -> bool:
        """Whether one series of `ticker`'s price history is asked for at `now`.

        Never answered yet: due. A minute series of BAR_MINUTES: once one of its bars has
        completed since it was asked, unless Schwab's sessions (time_et.session_label) were
        closed both then and now: the bar that ends a session is asked once after it, and a
        session not known (Schwab's /markets answer not held) is asked as an open one, as the
        chain is (chain_due). The daily, weekly and monthly
        candles: once per ET date, and once after today's regular window Schwab sent has ended.
        The 1-minute bars (DAILY_ONCE): once per ET date.
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
        if series in DAILY_ONCE:
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

    def fetch_markets(self, schwab_client: _SchwabClient, days: list[str]) -> None:
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
                resp = get_market_hours(schwab_client(), date.fromisoformat(day))
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

    def rotation(
        self,
        schwab_client: _SchwabClient,
        tickers: list[str],
        stop: threading.Event,
        candles: dict[str, list[str]] | None = None,
    ) -> set[str]:
        """Each ticker's chain in turn, a ticker on a page before each other one.

        The due price history (`candles`, taken from it as asked): a ticker on a page has its
        own just before its chain, so its levels do not wait for another's candles; every other
        ticker's is asked before the first other chain (the price-built levels wait for it, a
        rotation takes minutes).

        Before each ticker's chain, the chain of every ticker a page has selected (`shown`, read
        then: the ticker on the screen first, AGENTS.md rule 7) with all its quotes, so it is
        delivered before the next ticker is asked for; never the same ticker twice in a row. A
        chain is asked for only while it is due (chain_due), so one delivered after the close is
        not asked again. One removed from the watchlist since the rotation began is not asked
        for; the other queued quotes asked for whenever a full request's worth is waiting and
        the rest at the end; the tickers delivered. Its time is the round's (`round_sec`) only
        when it asked for every watchlist ticker: the console judges a ticker's chain overdue by
        the round, and a round of a few tickers is shorter than the watchlist's.
        """
        started = self.clock()
        if self.began is None:
            self.began = started
        self._delivered = set()
        last = None
        for ticker in tickers:
            shown = self.shown()
            for asked in (*shown, ticker):
                if stop.is_set() or asked == last or asked not in self.watchlist:
                    continue
                if not self.chain_due(asked, datetime.fromtimestamp(self.clock(), ET)):
                    continue
                if candles:
                    mine = [asked] if asked in shown else list(candles)
                    due = {t: candles.pop(t) for t in mine if t in candles}
                    self.candles(schwab_client, due, stop)
                self.fetch_chain(schwab_client, asked, stop)
                last = asked
                self.ask_queued(schwab_client, asked in shown, stop)
        while self._queue and not stop.is_set():
            self.send_quotes(schwab_client, REQUESTS_AT_ONCE)
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

    def ask_queued(self, schwab_client: _SchwabClient, shown: bool, stop: threading.Event) -> None:
        """Ask for the queued quotes after a chain, REQUESTS_AT_ONCE requests together.

        After a ticker a page shows (`shown`), every one now, the last request part-full;
        otherwise only full requests, the rest asked with the next chain's.
        """
        if shown:
            while self._queue and not stop.is_set():
                self.send_quotes(schwab_client, REQUESTS_AT_ONCE)
        while len(self._queue) >= QUOTES_BATCH_MAX and not stop.is_set():
            full = len(self._queue) // QUOTES_BATCH_MAX
            self.send_quotes(schwab_client, min(REQUESTS_AT_ONCE, full))

    def candles(
        self, schwab_client: _SchwabClient, due: dict[str, list[str]], stop: threading.Event
    ) -> None:
        """Each ticker's due series of its price history (`due`), ticker by ticker.

        One removed from the watchlist meanwhile is not asked for.
        """
        for ticker, series in due.items():
            if stop.is_set():
                break
            if ticker in self.watchlist:
                self.fetch_price_history(schwab_client, ticker, series)

    def fetch_price_history(
        self, schwab_client: _SchwabClient, ticker: str, due: list[str]
    ) -> None:
        """Fetch the `due` series of `ticker`'s price history (PRICE_HISTORY).

        Each is published as Schwab sent its candles; one Schwab does not answer 200 is not
        published (log_request has the answer) and is asked again the next time (series_due).
        """
        for series in due:
            now = self.clock()
            end = datetime.fromtimestamp(now, UTC)
            start = (
                end - timedelta(days=HISTORY_DAYS_BACK[series])
                if series in HISTORY_DAYS_BACK
                else None
            )
            try:
                resp = get_price_history(
                    schwab_client(),
                    ticker,
                    PRICE_HISTORY[series],
                    end,
                    start,
                    extended=start is None or series in EXTENDED_FROM_START,
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

    def fetch_chain(self, schwab_client: _SchwabClient, ticker: str, stop: threading.Event) -> None:
        """Fetch `ticker`'s chain, every expiry.

        Each contract's Greeks from the stream, or the contract queued for its quote; delivered
        at once when none is queued. A stop asked between two
        expiries ends it there: no expiry more is asked for, and the part fetched is not a chain.

        Schwab's /chains answers (the listed contracts, their terms and open interest, which
        Schwab says is the prior trading day's: docs/schwab/schwab_support_emails_2026_10_12.txt,
        item 5) are taken again, as sent, by each chain begun within CHAINS_AGAIN_SEC of their
        request, at any hour: that chain asks only for what moves, its Greeks and quotes. The
        first chain after the ticker's option close (capture_slot: the close capture the history
        stores) asks for them. A series an exchange adds during the trading day
        (it may: docs/SOURCES.md, sec-34-60365) is seen within CHAINS_AGAIN_SEC.
        """
        chain = _Chain(ticker, self.clock())
        window = capture_slot(chain.started, ticker)
        held = self._answers.get(ticker)
        if held is not None and chain.started - held[1] < CHAINS_AGAIN_SEC and held[0] == window:
            chain.answers_age, chain.spots = chain.started - held[1], dict(held[2])
            chain.by_expiry = {e: [dict(ct) for ct in cts] for e, cts in held[3].items()}
            chain.bodies = dict(held[4])
            return self.take_greeks(chain)
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
            # REQUESTS_AT_ONCE expiries asked together, their answers taken in expiry order
            answers = list(
                self._asking.map(lambda e: self.ask_expiry(client, ticker, e, stop), listed[1])
            )
            for expiry, resp in zip(listed[1], answers, strict=True):
                if resp is None:
                    return None
                self.publish(*chain_answer_message(ticker, expiry, resp, self.clock()))
                if resp.status_code != 200:
                    return self.fail(
                        [chain], f"chain for {expiry} returned HTTP {resp.status_code}"
                    )
                payload = resp.json()
                self._optioned.add(ticker)
                chain.spots[expiry.isoformat()] = schwab_number(payload.get("underlyingPrice"))
                chain.by_expiry[expiry.isoformat()] = flatten_chain_contracts(payload)
                chain.bodies[expiry.isoformat()] = resp.text
        except Exception as e:  # that ticker's answer is the failure; the rotation goes on
            log.warning("chain %s failed: %s: %s", ticker, type(e).__name__, e, exc_info=True)
            return self.fail([chain], f"{type(e).__name__}: {e}")
        # as sent: take_greeks writes each chain's own Greeks and quote
        sent = {e: [dict(ct) for ct in cts] for e, cts in chain.by_expiry.items()}
        self._answers[ticker] = (window, chain.started, dict(chain.spots), sent, dict(chain.bodies))
        return self.take_greeks(chain)

    @staticmethod
    def ask_expiry(client: Any, ticker: str, expiry: date, stop: threading.Event) -> Answer | None:
        """One expiry's /chains answer (fetch_chain); None when a stop came before it was asked.

        A 429 is asked once more: one refused expiry does not cost the ticker a round.
        """
        if stop.is_set():
            return None
        resp = safe_get_chain(client, ticker, strike_range="ALL", from_date=expiry, to_date=expiry)
        if resp.status_code == 429:
            resp = safe_get_chain(
                client, ticker, strike_range="ALL", from_date=expiry, to_date=expiry
            )
        return resp

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
            sent = streamed_record(entry)
            greeks = streamed_greek_set(sent.greeks.values())
            if entry is not None and greeks is not None:
                ct.update(greeks)
                ct["greeksTime"] = {g: entry[1]["field_ts"][g.upper()][0] for g in GREEK_FIELDS}
                ct["streamed"] = streamed_quote(sent)
                chain.pushed += 1
            else:
                ct.update(dict.fromkeys(GREEK_FIELDS))
                ct["greeksTime"] = None
                chain.unquoted.add(ct["symbol"])
                chain.requested += 1
                self._queue.append((chain, ct))
        if not chain.unquoted:
            self.deliver(chain)

    def send_quotes(self, schwab_client: _SchwabClient, at_once: int = 1) -> None:
        """Ask for the quotes of the next queued contracts, `at_once` requests at a time.

        Each request is for QUOTES_BATCH_MAX contracts; the requests are sent together and
        their answers taken in the order asked (take_quotes).
        """
        self._queue = [
            (chain, ct) for chain, ct in self._queue if chain.ticker in self.watchlist
        ]  # removed: not asked
        asked: list[tuple[list[_Queued], Future[Answer]]] = []
        while self._queue and len(asked) < at_once:
            batch, self._queue = self._queue[:QUOTES_BATCH_MAX], self._queue[QUOTES_BATCH_MAX:]
            symbols: list[str] = [ct["symbol"] for _chain, ct in batch]
            ask = self._asking.submit(lambda s=symbols: safe_get_quotes(schwab_client(), s))
            asked.append((batch, ask))
        for batch, ask in asked:
            self.take_quotes(batch, ask)

    def take_quotes(self, batch: list[_Queued], ask: Future[Answer]) -> None:
        """Take Schwab's answer to one quotes request (`ask`) for the contracts of `batch`.

        They take their quote's Greeks; each chain it completes is delivered. A request that
        fails fails every ticker in it. Schwab's answer carries a quote per symbol it knows and,
        beside them, an `errors` entry naming the symbols it does not (`invalidSymbols`;
        measured: 8 SPY contracts its own chain lists, every one never quoted or traded): those
        contracts get no Greeks, logged once with their count, and the rest of the request is
        delivered.
        """
        chains = list({id(chain): chain for chain, _ct in batch}.values())
        try:
            resp = ask.result()
            self.publish(*quotes_answer_message(resp, self.clock()))
            if resp.status_code != 200:
                self.fail(
                    chains, f"quotes for {len(batch)} contracts returned HTTP {resp.status_code}"
                )
                return
            answer = resp.json()
            errors: dict[str, Any] = answer.pop("errors") if "errors" in answer else {}
            named: set[str] = set(errors["invalidSymbols"]) if "invalidSymbols" in errors else set()
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
        captured = False  # a chain whose history is not stored is no capture
        try:
            captured = self._write_history(chain)
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
            chain.ticker, contracts, chain.started, chain.spot, chain.spot_ts, captured
        ):
            self.publish(topic, msg)
        self._delivered.add(chain.ticker)
        self._fetched[chain.ticker] = chain.started
        log.info(
            "CHAIN %s: %d contracts in %d expiries, /chains answers (open interest) asked %.0f s "
            "before | Greeks: %d "
            "pushed by LEVELONE_OPTIONS, %d requested on /quotes, %d Schwab named invalid | "
            "%.1f s from the first request",
            chain.ticker,
            len(contracts),
            len(chain.by_expiry),
            chain.answers_age,
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

    def _write_history(self, chain: _Chain) -> bool:
        """Write the chain history; whether the chain was stored as its day's close capture.

        A chain begun at or after the ticker's option close, the first one that day for this
        ticker (a chain begun before the close is not the close capture, whenever it ends), one
        row per expiry with the underlying price of that expiry's answer, at the time the chain
        began, every row in one transaction. Stored when at least one of its expiries' rows was
        written.
        """
        slot = capture_slot(chain.started, chain.ticker)
        return slot is not None and self._write_window(chain, slot)

    def _write_window(self, chain: _Chain, slot: float) -> bool:
        """Store the chain as window `slot`'s capture if it is the window's first for its ticker.

        Whether it was stored (_write_history).
        """
        ticker = chain.ticker
        if ticker not in self._written:
            self._written[ticker] = capture_store.newest_ts(self.db_path, ticker)
        before = self._written[ticker]
        if before is not None and before >= slot:
            return False
        self._written[ticker] = slot  # claim the window for this ticker
        capture = capture_message(
            ticker,
            chain.started,
            (chain.spot, chain.spot_ts),
            [
                {
                    "expiry": expiry,
                    "spot": chain.spots[expiry],
                    "contracts": cts,
                    "chains_answer": chain.bodies.get(expiry),  # absent: not recorded
                }
                for expiry, cts in chain.by_expiry.items()
            ],
        )
        outcome = self.failures.store_capture(capture, CAPTURE_WAIT_SEC)
        if outcome == CAPTURE_REFUSED:
            self._written[ticker] = before  # not stored: the window's next chain, if any, tries
        return outcome == CAPTURE_STORED
