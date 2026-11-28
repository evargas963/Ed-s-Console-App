"""US/Eastern wall-clock authority (DST-aware), and the market's sessions as Schwab answers them.

Each market date's sessions are Schwab's GET /markets?markets=equity,option answer for that date
(docs/schwab/schwab_market_data_parameters_pricehistory_markets.txt), held here as received
(record_markets): the stock market's pre-market, regular and post-market windows, and the regular
window of each option market (EQO: stock and ETF options; IND: index options). The capture daemon
asks it once per date per ET day: today, the days before it Schwab answers, and each expiry date
of the chains; the console takes every answer from the daemon, and at startup those the daemon
recorded (server._load_stored_sessions). A date with no answer held is
unknown. Past the year Schwab answers, a contract's expiry runs to its expirationDate as sent.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
CT = ZoneInfo("America/Chicago")


def ct_label(ts_utc: float) -> str:
    """Return an instant as the screen shows it: "Fri 09/25 06:59 PM CT"."""
    return datetime.fromtimestamp(float(ts_utc), CT).strftime("%a %m/%d %I:%M %p CT")


def age_text(sec: float) -> str:
    """Return an age as the screen shows it: "45s", "12m", "3h", "2d".

    A negative age (a time after the console's clock) shows as negative, never as 0.
    """
    sec = float(sec)
    if sec < 90:
        return f"{round(sec)}s"
    if sec < 5400:
        return f"{round(sec / 60)}m"
    if sec < 172800:
        return f"{round(sec / 3600)}h"
    return f"{round(sec / 86400)}d"


def ct_ticks(ts_utc: float) -> list[str]:
    """Return an instant's labels on a chart's time axis, by the chart's kind of mark.

    The year, the month, the day and the time of day, as the axis shows each: "2026", "Nov",
    "Nov 13", "09:30" (Lightweight Charts' TickMarkType: Year, Month, DayOfMonth, Time).
    """
    d = datetime.fromtimestamp(float(ts_utc), CT)
    year, month, time = d.strftime("%Y %b %H:%M").split(" ")
    return [year, month, f"{month} {d.day}", time]


def ct_clock(ts_utc: float) -> str:
    """Return an instant to the millisecond as the logs show it: "14:01:02.123 CT"."""
    return datetime.fromtimestamp(float(ts_utc), CT).strftime("%H:%M:%S.%f")[:-3] + " CT"


def ct_time(ts_utc: float) -> str:
    """Return an instant to the second as the header's clock shows it: "14:01:02 CT"."""
    return datetime.fromtimestamp(float(ts_utc), CT).strftime("%H:%M:%S CT")


def ct_day(ts_utc: float) -> str:
    """Return an instant's Central Time day as the header shows it: "Sat, Nov 14"."""
    return datetime.fromtimestamp(float(ts_utc), CT).strftime("%a, %b %d")


def ct_dated(ts_utc: float, now: float) -> str:
    """Return an instant as a line of dated items shows it at `now` (the header's news line).

    Its time alone on `now`'s Central day ("10:52 AM CT"), the whole label (ct_label) on any
    other day: an item of another day never reads as today's.
    """
    at = datetime.fromtimestamp(float(ts_utc), CT)
    if at.date() == datetime.fromtimestamp(float(now), CT).date():
        return at.strftime("%I:%M %p CT")
    return ct_label(ts_utc)


def now() -> float:
    """Return now, in epoch seconds: the one reading of the computer's clock in the repository.

    Every time of day the program uses (a value's age, whether it is live, a token's expiry, when
    a chain is due) comes from here, read at an entry point and passed on as `now`; Schwab's own
    times travel with its values as data (one clock, repo wide: AGENTS.md rule 11).
    """
    return time.time()


def elapsed() -> float:
    """Return the one stopwatch's reading, in seconds: for a span or a deadline on this machine.

    It is the system's monotonic counter, which a change of the clock never moves; its reading
    is not a time of day.
    """
    return time.monotonic()


def worked() -> float:
    """Return the seconds of CPU the calling thread has used: the work it did, not the wait.

    Other threads and other programs do not move it; a span of it measures a piece of code's own
    cost on a machine whatever else runs.
    """
    return time.thread_time()


async def set_within(event: asyncio.Event, seconds: float) -> bool:
    """Wait up to `seconds` for `event`; True when it is set.

    An asyncio Event takes no timeout of its own, and asyncio.wait reports one as its answer,
    not as an error.
    """
    waiter = asyncio.ensure_future(event.wait())
    try:
        await asyncio.wait({waiter}, timeout=seconds)
    finally:
        waiter.cancel()
    return event.is_set()


def et_date_str_from_ts_utc(ts_utc: float) -> str:
    """YYYY-MM-DD in America/New_York for the instant."""
    dt = datetime.fromtimestamp(float(ts_utc), tz=UTC).astimezone(ET)
    return dt.strftime("%Y-%m-%d")


def et_stamp(ts_utc: float) -> str:
    """Return an instant to the second in Eastern time as a log line stamps it.

    For example "2026-11-25 10:30:05 ET".
    """
    return datetime.fromtimestamp(float(ts_utc), ET).strftime("%Y-%m-%d %H:%M:%S ET")


#: the session states (session_label): no value is held back or stopped by them; a valid one is
#: live, and with none the last values stand
PRE_MARKET, RTH, AFTER_HOURS, CLOSED, UNKNOWN = (
    "Pre-Market",
    "RTH",
    "After-Hours",
    "Closed",
    "Unknown",
)
#: each session as the header says it, the program's words (AGENTS.md rule 4)
SESSION_WORDS = {
    RTH: "REGULAR",
    PRE_MARKET: "PRE-MARKET",
    AFTER_HOURS: "POST-MARKET",
    CLOSED: "CLOSED",
    UNKNOWN: "UNKNOWN",
}
#: Schwab's option markets in /markets: stock and ETF options, index options
EQUITY_OPTIONS, INDEX_OPTIONS = "EQO", "IND"
#: Underlyings whose listed options run to the index close: the symbols the exchanges list as
#: trading to 4:15 p.m. ET, as that list has them (docs/SOURCES.md: cboe-rule-5-1,
#: nasdaq-options-hours). Schwab's equity-option windows end earlier on a half day (13:00 ET, no
#: post-market) and Schwab marks no contract as one of them.
_INDEX_CLOSE_UNDERLYINGS = frozenset(
    ("DBA", "DBB", "DBC", "DBO", "DIA", "DRAM", "EEM", "EFA", "EWY", "EWZ", "FXI", "GLD", "HYG")
    + ("IBIT", "IEF", "IVV", "IWM", "IWN", "IWO", "IYR", "KBE", "KRE", "KWEB", "LQD", "MDY", "MOO")
    + ("NDX", "NDXP", "OEF", "QQQ", "RSP", "SLV", "SMH", "SOXL", "SOXX", "SPY", "SVIX", "SVXY")
    + ("TIP", "TLT", "UNG", "UUP", "UVIX", "UVXY", "VIXM", "VIXY", "VOO", "VXX", "VXZ", "XHB")
    + ("XLB", "XLC", "XLE", "XLF", "XLI", "XLK", "XLP", "XLRE", "XLU", "XLV", "XLY", "XME", "XND")
    + ("XOP", "XRT")
)


def option_close_product(ticker: str) -> str:
    """Return the option market whose regular close is this ticker's option close.

    An index Schwab names with "$", and a symbol on the exchanges' 4:15 p.m. ET list, stop at
    the index close. Every other ticker stops at the equity-option close.
    """
    t = ticker.strip().upper()
    if t.startswith("$") or t in _INDEX_CLOSE_UNDERLYINGS:
        return INDEX_OPTIONS
    return EQUITY_OPTIONS


Windows = tuple[tuple[datetime, datetime], ...]


@dataclass(frozen=True)
class Session:
    """One market date as Schwab's /markets answered it.

    It holds whether the stock market is open, each stock-market window it sent as (start, end)
    in ET, each option market's regular and post-market windows, joined where they meet
    (`options`: product -> windows; the stock options' post-market runs 16:00 to 16:15 ET), and
    every window of any option market, its pre-market included (`option_hours`). A closed date
    has no windows.
    """

    day: str
    is_open: bool
    pre: Windows
    regular: Windows
    post: Windows
    options: tuple[tuple[str, Windows], ...]
    option_hours: Windows

    def option_windows(self, product: str) -> Windows:
        """Return option market `product`'s windows that date (`options`).

        `product` is EQO or IND.
        """
        return next((w for p, w in self.options if p == product), ())


@dataclass
class Held:
    """What Schwab answered and streamed that the market's sessions are read from.

    `sessions`: ET date (YYYY-MM-DD) -> Schwab's /markets answer for it (record_markets);
    `first_trade`: ET date -> the earliest stock trade Schwab streamed that was made that day
    (record_trade). Each dict is replaced, never mutated: a reader on another thread keeps the one
    it began with, so a calculator handed it reads one consistent set.
    """

    sessions: dict[str, Session]
    first_trade: dict[str, datetime]


#: the program's one Held (record_markets and record_trade own it)
HELD = Held({}, {})


def _windows(hours: dict[str, Any], name: str) -> Windows:
    if name not in hours:
        return ()
    return tuple(
        (
            datetime.fromisoformat(w["start"]).astimezone(ET),
            datetime.fromisoformat(w["end"]).astimezone(ET),
        )
        for w in hours[name]
    )


def _hours(entry: dict[str, Any]) -> dict[str, Any]:
    return entry["sessionHours"] if "sessionHours" in entry else {}


def _unbroken(windows: Iterable[tuple[datetime, datetime]]) -> Windows:
    """Return `windows` in order, those that overlap or meet joined into one."""
    out: list[tuple[datetime, datetime]] = []
    for start, end in sorted(windows):
        if out and start <= out[-1][1]:
            out[-1] = (out[-1][0], max(end, out[-1][1]))
        else:
            out.append((start, end))
    return tuple(out)


def record_markets(answer: dict[str, Any]) -> Session:
    """Record Schwab's 200 answer to GET /markets?markets=equity,option for one date, as sent.

    Its equity entry (product EQ on a market day; "equity", isOpen false and no hours on a
    closed one) and its option entries (EQO and IND; "option" on a closed day) are that date's
    sessions from here on.
    """
    (eq,) = answer["equity"].values()
    hours = _hours(eq)
    s = Session(
        eq["date"],
        eq["isOpen"],
        _windows(hours, "preMarket"),
        _windows(hours, "regularMarket"),
        _windows(hours, "postMarket"),
        tuple(
            (
                product,
                _unbroken(
                    _windows(_hours(entry), "regularMarket") + _windows(_hours(entry), "postMarket")
                ),
            )
            for product, entry in answer["option"].items()
        ),
        tuple(
            window
            for entry in answer["option"].values()
            for name in ("preMarket", "regularMarket", "postMarket")
            for window in _windows(_hours(entry), name)
        ),
    )
    HELD.sessions = {**HELD.sessions, s.day: s}  # a new dict, never an insert (Held)
    return s


def sessions() -> Mapping[str, Session]:
    """Every date's sessions as Schwab answered them, by ET date (YYYY-MM-DD).

    The held dict itself: it is replaced on each answer, never mutated, so a calculator handed
    it reads one consistent set.
    """
    return HELD.sessions


def session(day: str) -> Session | None:
    """`day`'s (YYYY-MM-DD) sessions as Schwab answered them; None: no answer, unknown."""
    return HELD.sessions.get(day)


def record_trade(at: datetime) -> None:
    """Record a stock trade Schwab streamed, made at `at` (LEVELONE_EQUITIES TRADE_TIME_MILLIS).

    The earliest one of its ET date is when that date's trading began (session_label).
    """
    day = at.astimezone(ET).date().isoformat()
    if day not in HELD.first_trade or at < HELD.first_trade[day]:
        HELD.first_trade = {**HELD.first_trade, day: at}  # a new dict, never an insert (Held)


def session_label(now: datetime) -> str:
    """Return the stock market's session at `now`.

    PRE_MARKET, RTH or AFTER_HOURS inside the window Schwab's /markets sent for today. Before
    its first window, PRE_MARKET from the first stock trade Schwab streamed that was made today
    (record_trade): /markets starts the pre-market at 07:00 ET and Schwab streams the trades
    made from 04:00 (AGENTS.md rule 8). CLOSED otherwise (and on a day Schwab says is
    closed), UNKNOWN when Schwab's answer for today is not held. A valid session is live; with
    none the last values stand. What Schwab streams is shown and recorded whatever it says.
    """
    s = session(now.astimezone(ET).date().isoformat())
    if s is None:
        return UNKNOWN
    for state, windows in ((PRE_MARKET, s.pre), (RTH, s.regular), (AFTER_HOURS, s.post)):
        if any(start <= now < end for start, end in windows):
            return state
    starts = [start for start, _end in (*s.pre, *s.regular)]
    first = HELD.first_trade
    if s.day in first and starts and first[s.day] <= now < min(starts):
        return PRE_MARKET
    return CLOSED


#: the exchange auctions around Schwab's regular window: the opening auction's minutes before it
#: opens and the closing auction's minutes before it ends (no auction time is in Schwab's answer)
AUCTION_OPEN = timedelta(minutes=5)
AUCTION_CLOSE = timedelta(minutes=10)
#: auction(): inside the opening auction, the closing auction, or neither
OPEN_AUCTION, CLOSE_AUCTION, NO_AUCTION = "OPEN", "CLOSE", "NONE"


def auction(now: datetime) -> str | None:
    """Return the auction at `now`: OPEN_AUCTION, CLOSE_AUCTION, NO_AUCTION, or None.

    OPEN_AUCTION in the AUCTION_OPEN before today's regular window as Schwab sent it opens,
    CLOSE_AUCTION in the AUCTION_CLOSE before it ends (13:00 ET on an early close), NO_AUCTION
    otherwise and on a day Schwab says is closed; None when Schwab's answer for today is not
    held.
    """
    s = session(now.astimezone(ET).date().isoformat())
    if s is None:
        return None
    if not s.regular:
        return NO_AUCTION
    opens, ends = s.regular[0][0], s.regular[-1][1]
    if opens - AUCTION_OPEN <= now < opens:
        return OPEN_AUCTION
    if ends - AUCTION_CLOSE <= now < ends:
        return CLOSE_AUCTION
    return NO_AUCTION


def options_opened(now: datetime) -> datetime | None:
    """Return when the option markets' day starts on `now`'s date.

    That is the first window Schwab sent, its pre-market included; None when it sent none or
    its answer is not held.
    """
    s = session(now.astimezone(ET).date().isoformat())
    return min((start for start, _end in s.option_hours), default=None) if s else None


def option_window_began(now: datetime) -> datetime | None:
    """Return when the option windows Schwab sent that `now` is inside began, with no break since.

    Windows that overlap or meet are one: the stock options' post-market begins as their regular
    window ends, inside the index options' regular window, and the options did not stop there.
    None outside every window, and when Schwab's answer for today is not held.
    """
    s = session(now.astimezone(ET).date().isoformat())
    windows = _unbroken(s.option_hours if s else ())
    return next((start for start, end in windows if start <= now < end), None)


def options_open(now: datetime) -> bool | None:
    """Tell whether `now` is inside a window Schwab sent for any option market, as sent.

    It is what the chain sweep, the levels and an option's live mark follow; None when Schwab's
    answer for today is not held. option_market_open leaves the pre-market out, for the close
    values.
    """
    s = session(now.astimezone(ET).date().isoformat())
    if s is None:
        return None
    return any(start <= now < end for start, end in s.option_hours)


def option_market_open(now: datetime, product: str | None = None) -> bool | None:
    """Tell whether an option market is in a window of its day Schwab sent for today (`options`).

    The market is `product` (EQO, IND), or any option market when none is named (on a full day
    both run to 16:15 ET: IND's regular window, EQO's post-market). False outside its windows and
    all day on a day Schwab says is closed; None when Schwab's answer for today is not held.
    """
    s = session(now.astimezone(ET).date().isoformat())
    if s is None:
        return None
    return any(
        start <= now < end
        for p, windows in s.options
        if product in (None, p)
        for start, end in windows
    )


def options_closed_at(now: datetime, product: str | None = None) -> datetime | None:
    """Return the end of the newest `options` window that has ended by `now`, among answers held.

    The window is of option market `product`, or of any option market when none is named; None
    when none has.
    """
    ended = [
        end
        for s in HELD.sessions.values()
        for p, windows in s.options
        if product in (None, p)
        for _start, end in windows
        if end <= now
    ]
    return max(ended) if ended else None


def valuation_instant(now: datetime, product: str = EQUITY_OPTIONS) -> datetime:
    """Return the instant a live chain is priced.

    While `product`'s option market is not open
    (option_market_open) after a close earlier that day (options_closed_at, the one close
    instant; a gap between two windows counts as closed), that close, so the close numbers stand.
    While it is open, before it opens, on a day with no window, and on a date whose session is not
    held, it is `now`: the time to each expiry runs on the clock, and a day with no session has no
    same-day close.
    """
    if option_market_open(now, product) is not False:
        return now
    closed = options_closed_at(now, product)
    return (
        closed
        if closed is not None and closed.astimezone(ET).date() == now.astimezone(ET).date()
        else now
    )


def closed_since(now: datetime) -> datetime | None:
    """Return when the stock market closed, while it is CLOSED at `now` (session_label).

    That is the end of the newest window Schwab sent that has ended. None while a session is
    open or unknown, and when no answer held has a window that has ended.
    """
    if session_label(now) != CLOSED:
        return None
    ended = [
        end
        for s in HELD.sessions.values()
        for _start, end in (*s.pre, *s.regular, *s.post)
        if end <= now
    ]
    return max(ended) if ended else None


def market_session_date(now: datetime) -> date:
    """Return the session the market's values belong to at `now` (ET).

    Today's while a session is open (Pre-Market, RTH, After-Hours) or unknown, the newest
    session's while Closed, whose values stand until the next session opens (docs/DATA_FLOW.md
    §2 D5).
    """
    return (closed_since(now) or now).astimezone(ET).date()


def last_open(now: datetime) -> datetime | None:
    """Return the start of the newest regular session Schwab sent that has begun by `now`.

    None: none held.
    """
    begun = [start for s in HELD.sessions.values() for start, _end in s.regular if start <= now]
    return max(begun) if begun else None


def sessions_since(now: datetime, n: int) -> datetime | None:
    """Return the start (00:00 ET) of the `n`th newest session date, so `n` sessions run from it.

    The date is one Schwab's /markets says the market was open whose regular session has begun
    by `now`, so the newest `n` sessions run from it; None when fewer than `n` such dates are
    held.
    """
    begun = sorted(
        s.day
        for s in HELD.sessions.values()
        if s.is_open and any(start <= now for start, _end in s.regular)
    )
    if len(begun) < n:
        return None
    return datetime.combine(date.fromisoformat(begun[-n]), datetime.min.time(), ET)


#: Seconds in a 365-day year (ACT/365, the standard option-pricing day-count).
YEAR_SECONDS: float = 365.0 * 24.0 * 3600.0


#: Schwab's `settlementType` for an AM-settled contract (the $SPX monthly: its value is set from
#: the opening prices on the expiration date; Schwab's lastTradingDay is the day before).
SETTLEMENT_AM = "A"


def settles_at(
    expiration_date: str,
    now: datetime,
    *,
    sessions: Mapping[str, Session],
    settlement_type: str | None = None,
    product: str = EQUITY_OPTIONS,
) -> datetime | None:
    """Return the instant an option's time to expiry runs out (time_to_expiry_years).

    `expiration_date` is Schwab's expirationDate as sent. The settlement is option market
    `product`'s close Schwab's /markets sent for the expiry date (`sessions`, the answers by ET
    date, read by the caller's entry point; `product`, EQO unless the caller names another): the
    end of its day (Session.options, its post-market included: 16:15 ET on a full day for stock
    options as for index options, the close Schwab's own Greeks and theoretical values run to, as
    measured on every root), or its open for Schwab's settlementType "A". Schwab's expirationDate
    is not the settlement: it carries 16:00 ET on every contract, an AM-settled $SPX monthly's and
    a half day's included (as captured). For a date with no /markets answer held a PM-settled
    contract settles at Schwab's expirationDate as sent, and an AM-settled one too when that is
    past the year /markets answers. None when the instant is not known: an AM-settled contract
    within that year whose date /markets has not answered, a date it answers with no option
    session, and an expirationDate without its time.
    """
    s = sessions.get(str(expiration_date)[:10])
    if s is None:
        if len(str(expiration_date)) <= 10:
            return None
        sent = datetime.fromisoformat(str(expiration_date))
        left = sent.timestamp() - now.timestamp()
        nearer = settlement_type == SETTLEMENT_AM and 0.0 <= left <= YEAR_SECONDS
        return None if nearer else sent
    windows = s.option_windows(product)
    if not windows:
        return None
    return windows[0][0] if settlement_type == SETTLEMENT_AM else windows[-1][1]


def time_to_expiry_years(
    expiration_date: str,
    now: datetime,
    *,
    sessions: Mapping[str, Session],
    settlement_type: str | None = None,
    product: str = EQUITY_OPTIONS,
) -> float | None:
    """INTRADAY time-to-expiry in years (ACT/365), the one T of every Black-Scholes greek.

    Seconds from `now` (the caller's valuation instant) to the option's settlement (settles_at),
    over a 365-day year: the time left as it is, to the second, however short (the near-expiry
    gamma, vanna and charm are the formula's own); 0.0 at and after settlement, no time left,
    which every greek takes as no value; None when the settlement is not known.
    """
    settles = settles_at(
        expiration_date,
        now,
        sessions=sessions,
        settlement_type=settlement_type,
        product=product,
    )
    # instants, not civil time: a DST change between now and the expiry is counted as elapsed
    left = None if settles is None else settles.timestamp() - now.timestamp()
    return None if left is None else max(left / YEAR_SECONDS, 0.0)
