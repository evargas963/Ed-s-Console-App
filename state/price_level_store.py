"""Every ticker's price-level snapshot for the market's session, as last built.

The one store of it: the bar writer and the levels loop build it (server._publish_price_levels),
every live reader reads it here (canonical_price_level_snapshot), and none computes a level.
"""

from __future__ import annotations

import threading
from datetime import date, datetime

from instrument_identity import ticker_storage_key
from liquidity_models import PlaybookConfig
from liquidity_value_engine import (
    Bar,
    PriceLevelSnapshot,
    build_price_level_snapshot,
    prior_session,
    snapshot_input_fingerprint,
)
from micro_structure import Candle
from time_et import market_session_date, sessions

#: (ticker, session_date_iso) -> the ONE published price-level snapshot for its current bar input
_MATERIALIZED_SNAPSHOTS: dict[tuple[str, str], PriceLevelSnapshot] = {}
#: Guards the whole read-decide-build-write of materialize_price_level_snapshot: deciding to build
#: from a value then overwritten is a check-then-act, a race unless something serialises it.
_MATERIALIZE_LOCK = threading.Lock()


def materialize_price_level_snapshot(
    ticker: str,
    session_date: date,
    bars_norm: list[Bar],
    *,
    daily: list[Candle],
    bar_source: str,
    config: PlaybookConfig | None = None,
) -> PriceLevelSnapshot:
    """Build once per input; return the SAME object while the input is the same.

    Built by the calculator (liquidity_value_engine.build_price_level_snapshot) from normalized
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
        if existing is not None and existing.input_fingerprint == fingerprint:
            return existing
        snap = build_price_level_snapshot(
            tk,
            session_date,
            bars_norm,
            prior=prior,
            bar_source=bar_source,
            sessions=held,
            config=config,
        )
        snap.input_fingerprint = fingerprint
        _MATERIALIZED_SNAPSHOTS[key] = snap
        return snap


def canonical_price_level_snapshot(ticker: str, now: datetime) -> PriceLevelSnapshot | None:
    """Return the ticker's price-level snapshot for the market's session at `now`.

    The session is market_session_date's; the snapshot as its producer published it
    (server._publish_price_levels), or None when none is published yet. Every server surface
    reads this; none computes a level.
    """
    return _MATERIALIZED_SNAPSHOTS.get(
        (ticker_storage_key(ticker), market_session_date(now).isoformat())
    )
