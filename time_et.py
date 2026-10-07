"""US/Eastern wall-clock authority (DST-aware), and the market's sessions as Schwab answers them.

Each market date's session (open or closed, and its pre-market, regular and post-market windows)
is Schwab's GET /markets answer for that date
(docs/schwab/schwab_market_data_parameters_pricehistory_markets.txt), recorded here as received
(record_markets): the daemon asks it for today when the ET date changes, for the days before it
that Schwab answers, and for every expiry date of the chains. A past day was a trading day when
Schwab's daily candles have a bar for it (record_candle_days). A date neither answers is unknown:
nothing is guessed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
CT = ZoneInfo("America/Chicago")


def ct_label(ts_utc: float) -> str:
    """An instant as the screen shows it: "Fri 09/25 06:59 PM CT"."""
    return datetime.fromtimestamp(float(ts_utc), CT).strftime("%a %m/%d %I:%M %p CT")


def ct_clock(ts_utc: float) -> str:
    """An instant to the millisecond as the logs show it: "14:01:02.123 CT"."""
    return datetime.fromtimestamp(float(ts_utc), CT).strftime("%H:%M:%S.%f")[:-3] + " CT"


def now_et() -> datetime:
    """Timezone-aware US/Eastern now."""
    return datetime.now(ET)


def et_date_str_from_ts_utc(ts_utc: float) -> str:
    """YYYY-MM-DD in America/New_York for the instant."""
    dt = datetime.fromtimestamp(float(ts_utc), tz=timezone.utc).astimezone(ET)
    return dt.strftime("%Y-%m-%d")


#: the session states (session_label)
PRE_MARKET, RTH, AFTER_HOURS, CLOSED, UNKNOWN = "Pre-Market", "RTH", "After-Hours", "Closed", "Unknown"


@dataclass(frozen=True)
class Session:
    """One market date as Schwab's /markets answered it for equities: open or closed, and each
    window it sent as (start, end) in ET. A closed date has no windows."""
    day: str
    is_open: bool
    pre: tuple[tuple[datetime, datetime], ...]
    regular: tuple[tuple[datetime, datetime], ...]
    post: tuple[tuple[datetime, datetime], ...]


_sessions: dict[str, Session] = {}       # ET date (YYYY-MM-DD) -> Schwab's answer for it
_candle_days: set[date] = set()          # the dates of Schwab's daily candles, every ticker's


def _windows(hours: dict, name: str) -> tuple[tuple[datetime, datetime], ...]:
    if name not in hours:
        return ()
    return tuple((datetime.fromisoformat(w["start"]).astimezone(ET), datetime.fromisoformat(w["end"]).astimezone(ET))
                 for w in hours[name])


def record_markets(answer: dict) -> Session:
    """Schwab's 200 answer to GET /markets?markets=equity,option for one date, as sent: its
    equity entry (product EQ on a market day; "equity", isOpen false and no hours on a closed
    one) is that date's session from here on."""
    (eq,) = answer["equity"].values()
    hours = eq["sessionHours"] if "sessionHours" in eq else {}
    s = Session(eq["date"], eq["isOpen"], _windows(hours, "preMarket"), _windows(hours, "regularMarket"),
                _windows(hours, "postMarket"))
    _sessions[s.day] = s
    return s


def record_candle_days(days) -> None:
    """The dates Schwab's daily candles have a bar for (a ticker's /pricehistory daily answer)."""
    _candle_days.update(days)


def session(day: str) -> Session | None:
    """`day`'s (YYYY-MM-DD) session as Schwab answered it; None: no answer, the session is unknown."""
    return _sessions.get(day)


def session_label(now: datetime) -> str:
    """The session at `now`: PRE_MARKET, RTH or AFTER_HOURS inside the window Schwab sent for
    today, CLOSED outside them (and on a day Schwab says is closed), UNKNOWN when Schwab's answer
    for today is not in."""
    s = session(now.astimezone(ET).date().isoformat())
    if s is None:
        return UNKNOWN
    for state, windows in ((PRE_MARKET, s.pre), (RTH, s.regular), (AFTER_HOURS, s.post)):
        if any(start <= now < end for start, end in windows):
            return state
    return CLOSED


def trading_day(day: date, now: datetime) -> bool | None:
    """Whether `day` is a trading day: a day before `now`'s date by Schwab's daily candles (a bar
    for it), today and later by Schwab's /markets answer. None: unknown (a past day outside the
    candles' span, a day with no /markets answer)."""
    if day < now.astimezone(ET).date():
        if not _candle_days or not min(_candle_days) <= day <= max(_candle_days):
            return None
        return day in _candle_days
    s = session(day.isoformat())
    if s is None:
        return None
    return s.is_open


def prior_trading_day(day: date) -> date | None:
    """The newest day before `day` Schwab's daily candles have a bar for; None before they come."""
    earlier = [d for d in _candle_days if d < day]
    return max(earlier) if earlier else None


def closed_since(now: datetime) -> "datetime | None":
    """While the market is CLOSED at `now` (session_label): when it closed, the end of the newest
    window Schwab sent that has ended. None while a session is open or unknown, and when no
    answer held has a window that has ended."""
    if session_label(now) != CLOSED:
        return None
    ended = [end for s in _sessions.values() for _start, end in (*s.pre, *s.regular, *s.post) if end <= now]
    return max(ended) if ended else None


def market_session_date(now: datetime) -> date:
    """The session the market's values belong to at `now` (ET): today's while a session is open
    (Pre-Market, RTH, After-Hours) or unknown, the newest session's while Closed, whose values
    stand until the next session opens (docs/DATA_FLOW.md §2 D5)."""
    return (closed_since(now) or now).astimezone(ET).date()


def last_open(now: datetime) -> datetime | None:
    """The start of the newest regular session Schwab sent that has begun by `now`; None: none held."""
    begun = [start for s in _sessions.values() for start, _end in s.regular if start <= now]
    return max(begun) if begun else None


#: Seconds in a 365-day year (ACT/365, the standard option-pricing day-count).
YEAR_SECONDS: float = 365.0 * 24.0 * 3600.0
#: Sub-floor on time-to-expiry (10 minutes) — guards the exact-expiry 1/sqrt(T) singularity
#: WITHOUT flattening the genuine near-expiry gamma/charm spike (which desks hedge minute by
#: minute).
MIN_TIME_TO_EXPIRY_YEARS: float = 600.0 / YEAR_SECONDS


#: Schwab's `settlementType` for an AM-settled contract (the $SPX monthly: its value is set from
#: the opening prices on the expiration date; Schwab's lastTradingDay is the day before).
SETTLEMENT_AM = "A"


def time_to_expiry_years(expiry_et_date: str, now: datetime, *,
                         settlement_type: str | None = None) -> float | None:
    """INTRADAY time-to-expiry in years (ACT/365), the one T of every Black-Scholes greek:
    seconds from `now` to the option's settlement on its expiration date, over a 365-day year.
    The settlement is the regular market's close Schwab's /markets sent for that date (16:00 ET,
    13:00 on an early close), or its open for Schwab's settlementType "A".

    VALIDATED 2026-07-26 against Schwab-reported gamma on real chains: intraday-to-close matches
    Schwab to a MEASURED median ratio 0.987 (94% of ATM strikes within 10%) in the 2-6h window.

    None when Schwab's /markets answer for the expiry date is not held (beyond the year it
    answers, or not asked yet), when it says the date has no regular session, or once the option
    has reached settlement. A 10-minute sub-floor guards the exact-expiry singularity."""
    s = session(str(expiry_et_date)[:10])
    if s is None or not s.regular:
        return None
    settles = s.regular[0][0] if settlement_type == SETTLEMENT_AM else s.regular[-1][1]
    # instants, not civil time: a DST change between now and the expiry is counted as elapsed
    t = (settles.timestamp() - now.timestamp()) / YEAR_SECONDS
    if t <= 0.0:
        return None  # at/after settlement — no greeks for an expired contract
    return max(t, MIN_TIME_TO_EXPIRY_YEARS)


def is_tradable_session_ts_utc(ts_utc: float) -> bool:
    """True iff ts_utc is inside a regular session Schwab's /markets sent (an unknown day is not)."""
    s = session(et_date_str_from_ts_utc(ts_utc))
    return s is not None and any(start.timestamp() <= ts_utc < end.timestamp() for start, end in s.regular)
