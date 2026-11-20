"""Every ticker's price-level snapshot for the market's session, as last built.

The one store of it: the bar writer and the levels loop build it (server._publish_price_levels),
every live reader reads it here (canonical_price_level_snapshot), and none computes a level.
"""

from __future__ import annotations

import threading
from datetime import date, datetime

from calc.liquidity_value_engine import (
    Bar,
    HoldCount,
    PriceLevelSnapshot,
    build_price_level_snapshot,
    hold_counts,
    hold_window,
    prior_session,
    snapshot_input_fingerprint,
)
from calc.micro_structure import Candle
from instrument_identity import ticker_storage_key
from time_et import market_session_date, sessions

#: (ticker, session_date_iso) -> the ONE published price-level snapshot, with the fingerprint of
#: the input it was built from (calc.liquidity_value_engine.snapshot_input_fingerprint)
_MATERIALIZED_SNAPSHOTS: dict[
    tuple[str, str], tuple[tuple[str, str, str, int, str], PriceLevelSnapshot]
] = {}
#: Guards the whole read-decide-build-write of materialize_price_level_snapshot: deciding to build
#: from a value then overwritten is a check-then-act, a race unless something serialises it.
_MATERIALIZE_LOCK = threading.Lock()
#: ticker -> its hold counts (calc.liquidity_value_engine.hold_counts), with the fingerprint of
#: their input: the bars to the newest closed session's close, Schwab's daily candles and its
#: /markets answers. A bar of the session still open is no input, so it recounts nothing.
_HOLD_COUNTS: dict[
    str, tuple[tuple[tuple[str, str, str, int, str], str], dict[str, dict[int, HoldCount]]]
] = {}
#: the counts' own lock: a count takes seconds, and the levels' builds never wait on it
_HOLD_LOCK = threading.Lock()


def materialize_price_level_snapshot(
    ticker: str,
    session_date: date,
    bars_norm: list[Bar],
    *,
    daily: list[Candle],
    bar_source: str,
) -> PriceLevelSnapshot:
    """Build once per input; return the SAME object while the input is the same.

    Built by the calculator (calc.liquidity_value_engine.build_price_level_snapshot) from normalized
    bars (bars_from_candles) and Schwab's daily candles (`daily`, state.bar_store), and held here,
    the one store of it. A new input (the bars, the prior session's candle or the regular hours
    Schwab's /markets sent changed) builds exactly once; every later ask with that input is a read,
    never a recomputation.
    """
    tk = ticker_storage_key(ticker)
    key = (tk, session_date.isoformat())
    prior = prior_session(daily, session_date)
    held = sessions()  # one set of Schwab's /markets answers for the key and the build
    fingerprint = snapshot_input_fingerprint(tk, session_date, bars_norm, bar_source, prior, held)
    # the read, the decision to build, the build and the write-back are one critical section:
    # unguarded, two concurrent callers can both see no result for this input and build two
    with _MATERIALIZE_LOCK:
        existing = _MATERIALIZED_SNAPSHOTS.get(key)
        if existing is not None and existing[0] == fingerprint:
            return existing[1]
        snap = build_price_level_snapshot(
            session_date, bars_norm, prior=prior, bar_source=bar_source, sessions=held
        )
        _MATERIALIZED_SNAPSHOTS[key] = (fingerprint, snap)
        return snap


def materialize_hold_counts(
    ticker: str,
    bars_norm: list[Bar],
    *,
    daily: list[Candle],
    now: datetime,
) -> dict[str, dict[int, HoldCount]]:
    """Count once per input; return the SAME counts while the input is the same.

    The counts at `now` read only the bars before the newest closed session's close
    (hold_window), so they are counted from those, and a new bar of the open session is a read,
    never a recount. Those bars, the daily candles and the sessions decide the counts: a session
    that closes adds its bars.
    """
    tk = ticker_storage_key(ticker)
    held = sessions()  # one set of Schwab's /markets answers for the key and the count
    window = hold_window(bars_norm, now, held)
    fingerprint = (
        snapshot_input_fingerprint(tk, date.min, window, "", None, held),
        repr(daily),
    )
    with _HOLD_LOCK:
        existing = _HOLD_COUNTS.get(tk)
        if existing is not None and existing[0] == fingerprint:
            return existing[1]
        counts = hold_counts(window, daily, now, sessions=held)
        _HOLD_COUNTS[tk] = (fingerprint, counts)
        return counts


def canonical_price_level_snapshot(ticker: str, now: datetime) -> PriceLevelSnapshot | None:
    """Return the ticker's price-level snapshot for the market's session at `now`.

    The session is market_session_date's; the snapshot as its producer published it
    (server._publish_price_levels), or None when none is published yet. Every server surface
    reads this; none computes a level.
    """
    held = _MATERIALIZED_SNAPSHOTS.get(
        (ticker_storage_key(ticker), market_session_date(now).isoformat())
    )
    return None if held is None else held[1]
