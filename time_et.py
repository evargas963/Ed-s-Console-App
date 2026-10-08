"""US/Eastern wall-clock authority (DST-aware), and the market's sessions as Schwab answers them.

Each market date's sessions are Schwab's GET /markets?markets=equity,option answer for that date
(docs/schwab/schwab_market_data_parameters_pricehistory_markets.txt), held here as received
(record_markets): the stock market's pre-market, regular and post-market windows, and the regular
window of each option market (EQO: stock and ETF options; IND: index options). The capture daemon
asks it once per date per ET day: today, the days before it Schwab answers, and each expiry date
of the chains; the console takes every answer from the daemon. A date with no answer held is
unknown: nothing is guessed.
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


#: the session states (session_label): a label only; no value is held back or stopped by it
PRE_MARKET, RTH, AFTER_HOURS, CLOSED, UNKNOWN = "Pre-Market", "RTH", "After-Hours", "Closed", "Unknown"
#: Schwab's option markets in /markets: stock and ETF options, index options
EQUITY_OPTIONS, INDEX_OPTIONS = "EQO", "IND"

Windows = tuple[tuple[datetime, datetime], ...]


@dataclass(frozen=True)
class Session:
    """One market date as Schwab's /markets answered it: whether the stock market is open, each
    stock-market window it sent as (start, end) in ET, and each option market's regular windows
    (`options`: product -> windows). A closed date has no windows."""
    day: str
    is_open: bool
    pre: Windows
    regular: Windows
    post: Windows
    options: tuple[tuple[str, Windows], ...]

    def option_windows(self, product: str) -> Windows:
        """The regular windows Schwab sent for option market `product` (EQO, IND) that date."""
        return next((w for p, w in self.options if p == product), ())


_sessions: dict[str, Session] = {}       # ET date (YYYY-MM-DD) -> Schwab's answer for it


def _windows(hours: dict, name: str) -> Windows:
    if name not in hours:
        return ()
    return tuple((datetime.fromisoformat(w["start"]).astimezone(ET), datetime.fromisoformat(w["end"]).astimezone(ET))
                 for w in hours[name])


def _hours(entry: dict) -> dict:
    return entry["sessionHours"] if "sessionHours" in entry else {}


def record_markets(answer: dict) -> Session:
    """Schwab's 200 answer to GET /markets?markets=equity,option for one date, as sent: its
    equity entry (product EQ on a market day; "equity", isOpen false and no hours on a closed
    one) and its option entries (EQO and IND; "option" on a closed day) are that date's sessions
    from here on."""
    (eq,) = answer["equity"].values()
    hours = _hours(eq)
    s = Session(eq["date"], eq["isOpen"], _windows(hours, "preMarket"), _windows(hours, "regularMarket"),
                _windows(hours, "postMarket"),
                tuple((product, _windows(_hours(entry), "regularMarket"))
                      for product, entry in answer["option"].items()))
    _sessions[s.day] = s
    return s


def session(day: str) -> Session | None:
    """`day`'s (YYYY-MM-DD) sessions as Schwab answered them; None: no answer, unknown."""
    return _sessions.get(day)


def session_label(now: datetime) -> str:
    """The stock market's session at `now`: PRE_MARKET, RTH or AFTER_HOURS inside the window
    Schwab sent for today, CLOSED outside them (and on a day Schwab says is closed), UNKNOWN when
    Schwab's answer for today is not held. A label: what Schwab streams is shown and recorded
    whatever it says."""
    s = session(now.astimezone(ET).date().isoformat())
    if s is None:
        return UNKNOWN
    for state, windows in ((PRE_MARKET, s.pre), (RTH, s.regular), (AFTER_HOURS, s.post)):
        if any(start <= now < end for start, end in windows):
            return state
    return CLOSED


def options_open(now: datetime, product: str) -> bool | None:
    """Whether option market `product` is in a regular window Schwab sent for today; None when
    Schwab's answer for today is not held."""
    s = session(now.astimezone(ET).date().isoformat())
    if s is None:
        return None
    return any(start <= now < end for start, end in s.option_windows(product))


def options_closed_at(now: datetime, product: str) -> datetime | None:
    """The end of the newest regular window of option market `product` that has ended by `now`,
    among the answers held; None when none has."""
    ended = [end for s in _sessions.values() for _start, end in s.option_windows(product) if end <= now]
    return max(ended) if ended else None


def closed_since(now: datetime) -> "datetime | None":
    """While the stock market is CLOSED at `now` (session_label): when it closed, the end of the
    newest window Schwab sent that has ended. None while a session is open or unknown, and when no
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


def prior_trading_day(day: date) -> date | None:
    """The newest date before `day` Schwab's /markets says the stock market was open; None when
    no answer held says so."""
    earlier = [date.fromisoformat(d) for d, s in _sessions.items() if s.is_open and date.fromisoformat(d) < day]
    return max(earlier) if earlier else None


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
    seconds from `now` (the caller's valuation instant) to the option's settlement on its
    expiration date, over a 365-day year.
    The settlement is the option market's (EQO) regular close Schwab's /markets sent for that
    date (16:00 ET, 13:00 on an early close), or its open for Schwab's settlementType "A".
    Schwab's own expirationDate is not the settlement: an AM-settled $SPX monthly carries the
    16:00 ET of its date (captured 2026-10-07).

    VALIDATED 2026-07-26 against Schwab-reported gamma on real chains: intraday-to-close matches
    Schwab to a MEASURED median ratio 0.987 (94% of ATM strikes within 10%) in the 2-6h window.

    None when Schwab's /markets answer for the expiry date is not held (beyond the year it
    answers, or not asked yet), when it sends no regular option session that date, or once the
    option has reached settlement. A 10-minute sub-floor guards the exact-expiry singularity."""
    s = session(str(expiry_et_date)[:10])
    windows = () if s is None else s.option_windows(EQUITY_OPTIONS)
    if not windows:
        return None
    settles = windows[0][0] if settlement_type == SETTLEMENT_AM else windows[-1][1]
    # instants, not civil time: a DST change between now and the expiry is counted as elapsed
    t = (settles.timestamp() - now.timestamp()) / YEAR_SECONDS
    if t <= 0.0:
        return None  # at/after settlement — no greeks for an expired contract
    return max(t, MIN_TIME_TO_EXPIRY_YEARS)
