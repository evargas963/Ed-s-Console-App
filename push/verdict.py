"""The levels' verdict every screen shows: LIVE, CLOSE, STALE or NOT LIVE, why, and the age.

Read from State: the published levels (state.level_store), the daemon's status and last beat
(live_market_plane) and why the ticker's newest chain is not priced (level_store.chain_failure).
"""

from __future__ import annotations

from datetime import datetime
from typing import TypedDict

import live_market_plane as lmp
from state.level_store import PublishedLevels, chain_failure, published_levels
from time_et import (
    ET,
    age_text,
    ct_label,
    option_close_product,
    option_window_began,
    options_closed_at,
    options_open,
    options_opened,
)

#: the levels' words beside the price's (live_market_plane LIVE / NOT_LIVE): the close values of the
#: ticker's own option market stand; the chain is overdue or the close values were never fetched
LEVELS_CLOSE, LEVELS_STALE = "CLOSE", "STALE"


class LevelsVerdict(TypedDict):
    """The levels' verdict every screen shows (terrain_staleness)."""

    levels_state: str
    levels_stale_reason: str | None
    levels_age_text: str | None
    levels_time_ct: str | None


def terrain_cache_get(ticker: str, now: float) -> tuple[PublishedLevels | None, LevelsVerdict]:
    """Return the ticker's published levels (None before the first) and their verdict at `now`.

    The verdict is terrain_staleness's: the cache holds the chain's time, never a verdict.
    """
    levels = published_levels(ticker)
    if levels is None:
        return None, terrain_staleness(None, ticker, now=now)
    return levels, terrain_staleness(
        levels.computed_ts_utc, ticker, now=now, levels_ts_utc=levels.levels_ts_utc
    )


def terrain_staleness(
    computed_ts_utc: float | None,
    ticker: str,
    *,
    now: float,
    levels_ts_utc: float | None = None,
) -> LevelsVerdict:
    """Return the levels' state at `now`, THE levels verdict every screen shows (`levels_state`).

    LIVE from the market day's start (time_et.options_open) until the ticker's own option market
    closes (time_et.option_close_product: stock options at 16:00 ET, index-close options at 16:15)
    with its chain current (in the daemon's first round, fetched since that round began); CLOSE
    once that market has closed, and through the day's first round, with a chain fetched after its
    close, however old (docs/DATA_FLOW.md §2 D5); STALE, with WHY, when the chain is overdue or the
    close values were never fetched; NOT LIVE when Schwab's /markets answer for today is not held,
    or in the daemon's first round with a chain from before it. The daemon's last answer for the
    ticker's chain (a failed fetch, an incomplete delivery) outranks the age, and its refused
    sign-in (`chains_waiting`) outranks both, on every verdict but LIVE and CLOSE. While its option
    market is open the daemon fetches every watchlist ticker's chain without end, so age past two
    of its delivered rounds is a gap, never a schedule. Served beside it: the time of the newest
    Schwab option value the levels hold (`levels_ts_utc`: the chain, or a value pushed since) and
    its age.
    """
    state, reason = _levels_state(computed_ts_utc, ticker, now, chain_failure(ticker))
    age = None if levels_ts_utc is None else now - float(levels_ts_utc)
    return {
        "levels_state": state,
        "levels_stale_reason": reason,
        "levels_age_text": None if age is None else age_text(age),
        "levels_time_ct": None if levels_ts_utc is None else ct_label(levels_ts_utc),
    }


def _in_first_round(
    computed_ts_utc: float, opened: float, now: float, stale_after: float | None
) -> bool:
    """Whether a chain from before today's open stands while the day's first round runs.

    The round runs until two of the daemon's reported rounds have passed since the open; with
    none reported yet, it is still running. Yesterday's close values stand meanwhile.
    """
    return float(computed_ts_utc) < opened and (stale_after is None or now - opened <= stale_after)


def _current_at(computed_ts_utc: float, close: float, stale_after: float | None) -> bool:
    """Whether levels computed at `computed_ts_utc` were current at the option `close`.

    Its last values while it was open are the close values (operator 2026-11-15: "keep the last
    known data on the screen until we get new data"): current when computed at or after the
    close, or within two of the daemon's rounds (`stale_after`) before it; with no round
    reported, only at or after it.
    """
    behind = close - float(computed_ts_utc)
    return behind <= 0 or (stale_after is not None and behind <= stale_after)


def _levels_state(
    computed_ts_utc: float | None, ticker: str, now: float, failure: str | None
) -> tuple[str, str]:
    """(levels_state, why it is not LIVE or CLOSE) for terrain_staleness.

    While the daemon asks Schwab for nothing (its status's `chains_waiting`: a refused sign-in),
    that is the why.
    """
    status = lmp.daemon_status(now)
    waiting = None if status is None else status["chains_waiting"]
    if waiting:
        failure = f"no chain is fetched: {waiting}"
    sep = f" — {failure}" if failure else ""
    if computed_ts_utc is None:
        return LEVELS_STALE, "no terrain snapshot has been computed yet" + sep
    at = datetime.fromtimestamp(now, ET)
    product = option_close_product(ticker)
    market_open = options_open(at)
    if market_open is None:
        return lmp.NOT_LIVE, "the market session is unknown" + sep
    age = now - float(computed_ts_utc)
    # judged against the round the daemon's chain sweep last reported (every watchlist ticker
    # once), and nothing of ours: a chain is overdue past two of them (one missed round is
    # jitter, two a gap). A chain's age is its own, and a late heartbeat does not shorten the
    # round; with no round reported yet, the first is in progress.
    last = lmp.last_beat()
    round_sec = None if last is None else last["chain_round_sec"]
    stale_after = None if round_sec is None else 2.0 * float(round_sec)
    closed = options_closed_at(at, product)
    opened = options_opened(at)  # a window is open (market_open), so Schwab sent one: its start
    if (
        not market_open
        or (closed is not None and closed.date() == at.date())  # its own market has closed today
        or (
            opened is not None
            and _in_first_round(computed_ts_utc, opened.timestamp(), now, stale_after)
        )
    ):
        if closed is None or not _current_at(computed_ts_utc, closed.timestamp(), stale_after):
            return (
                LEVELS_STALE,
                "this ticker's options are closed and its levels were not current at the close"
                + sep,
            )
        return LEVELS_CLOSE, ""
    if stale_after is None:
        # the first round: a chain Schwab sent since it began is current (none newer can come
        # before the round ends); one from before this run stands, not live, until its own
        began = None if last is None else last["chains_began"]
        if began is not None and float(computed_ts_utc) >= float(began):
            return lmp.LIVE, ""
        return (
            lmp.NOT_LIVE,
            "this ticker's first chain since the daemon started has not arrived" + sep,
        )
    if age <= stale_after:
        return lmp.LIVE, ""
    if waiting:
        return LEVELS_STALE, f"levels are {age:.0f}s old{sep}"
    return LEVELS_STALE, _overdue_why(computed_ts_utc, at, now, stale_after, failure)


def _overdue_why(
    computed_ts_utc: float, at: datetime, now: float, stale_after: float, failure: str | None
) -> str:
    """Why levels past two of the daemon's rounds (`stale_after`) are overdue (_levels_state)."""
    age = now - float(computed_ts_utc)
    if failure:
        return f"levels are {age:.0f}s old and every chain since has failed — {failure}"
    window = option_window_began(at)  # the window `at` is inside: overdue is judged only in one
    began = None if window is None else window.timestamp()
    if began is not None and float(computed_ts_utc) < began and now - began <= stale_after:
        # no chain is asked for between two of Schwab's option windows: the first since is due
        return (
            f"levels are {age:.0f}s old: Schwab's option session reopened {ct_label(began)} and "
            "its first chain since has not arrived"
        )
    return (
        f"levels are {age:.0f}s old; the daemon's chain sweep has not delivered this "
        f"ticker in two of its rounds ({stale_after / 2:.0f}s each)"
    )
