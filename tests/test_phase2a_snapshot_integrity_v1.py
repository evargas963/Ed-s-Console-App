"""The price-level producer (materialize_price_level_snapshot) serves one result per generation.

(a) a change to any bar field, an interior one included, is a new generation with new levels;
    the same input is the same object;
(b) concurrent callers with one input get one object and one generation.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import datetime, timedelta
from pathlib import Path

from calc import liquidity_value_engine as LVE
from calc.micro_structure import Candle
from state import price_level_store
from state.price_level_store import materialize_price_level_snapshot
from tests.conftest import MARKETS_DAY, most_recent_trading_day_et
from time_et import ET, sessions

REPO = Path(__file__).resolve().parent.parent


def _bars(session, high_of_interior: float = 105.0) -> list:
    """Return the prior trading session plus this one.

    The interior bar's HIGH is the mutation target.
    """
    prior = most_recent_trading_day_et(on_or_before=session - timedelta(days=1))
    out = []
    for d in (prior, session):
        for i in range(60):
            ts = datetime(d.year, d.month, d.day, 9, 30, tzinfo=ET) + timedelta(minutes=i)
            px = 100.0 + (i % 11) * 0.10
            hi = px + 0.05
            if d == prior and i == 30:  # interior bar of the PRIOR session -> PDH
                hi = high_of_interior
            out.append(
                {
                    "timestamp": int(ts.timestamp() * 1000),
                    "open": px,
                    "high": hi,
                    "low": px - 0.05,
                    "close": px,
                    "volume": 1000.0 + i,
                }
            )
    return out


def _fresh():
    """Drop this test ticker's snapshots from the producer's cache: the next one is generation 1."""
    for key in [k for k in price_level_store._MATERIALIZED_SNAPSHOTS if k[0] == "ZZRC324"]:
        del price_level_store._MATERIALIZED_SNAPSHOTS[key]


def _daily(session, bars) -> list:
    """Return the prior session's daily candle as Schwab dates it (midnight ET).

    It is made of its bars above.
    """
    prior = most_recent_trading_day_et(on_or_before=session - timedelta(days=1))
    held = [b for b in bars if datetime.fromtimestamp(b["timestamp"] / 1000, ET).date() == prior]
    return [
        Candle(
            ts=datetime(prior.year, prior.month, prior.day, tzinfo=ET).timestamp(),
            open=held[0]["open"],
            high=max(b["high"] for b in held),
            low=min(b["low"] for b in held),
            close=held[-1]["close"],
            volume=sum(b["volume"] for b in held),
        )
    ]


def _held_fingerprint(session):
    """Return the fingerprint the store holds with the test ticker's snapshot for `session`."""
    return price_level_store._MATERIALIZED_SNAPSHOTS[("ZZRC324", session.isoformat())][0]


def _mat(session, bars):
    return materialize_price_level_snapshot(
        "ZZRC324",
        session,
        LVE.bars_from_candles(
            [
                Candle(
                    ts=b["timestamp"] / 1000,
                    open=b["open"],
                    high=b["high"],
                    low=b["low"],
                    close=b["close"],
                    volume=b["volume"],
                )
                for b in bars
            ]
        ),
        daily=_daily(session, bars),
        bar_source="test_fixture",
    )


def test_an_interior_bar_change_is_a_new_generation():
    """(a) The prior session's high moved from 105 to 999: a new snapshot with the new PDH."""
    _fresh()
    session = MARKETS_DAY

    first = _mat(session, _bars(session, 105.0))
    first_fingerprint = _held_fingerprint(session)
    pdh_before = first.price("PDH")
    assert pdh_before == 105.0

    second = _mat(session, _bars(session, 999.0))
    assert second is not first, (
        "an interior bar changed and the producer returned the SAME object — the "
        "fingerprint is sampling the input instead of covering it (RC-324)"
    )
    assert _held_fingerprint(session) != first_fingerprint
    assert second.price("PDH") != pdh_before, (
        f"PDH stayed {pdh_before!r} after the high was moved to 999 — a stale value served "
        "for a new input"
    )

    # And the same input must still be ONE snapshot: no churn.
    again = _mat(session, _bars(session, 999.0))
    assert again is second, "an unchanged input minted a new object — one result per input"


def test_concurrent_materialization_yields_one_object_and_one_generation():
    """(b) Eight concurrent callers, one input: one object."""
    _fresh()
    session = MARKETS_DAY
    bars = _bars(session, 105.0)

    barrier = threading.Barrier(8)

    def go():
        barrier.wait(timeout=10)
        return _mat(session, bars)

    pool = ThreadPoolExecutor(max_workers=8)
    futures = [pool.submit(go) for _ in range(8)]
    done, _ = wait(futures, timeout=30)  # a deadlock fails below, never hangs the run
    pool.shutdown(wait=False)
    errors = [f.exception() for f in done if f.exception() is not None]
    results = [f.result() for f in done if f.exception() is None]

    assert not errors, f"materialization raised under concurrency: {errors[:2]}"
    assert len(results) == 8, f"only {len(results)} of 8 threads completed"
    assert len({id(r) for r in results}) == 1, (
        "concurrent callers received DIFFERENT snapshot objects — two results for one "
        "input, the exact defect Cursor reproduced with PDH 105 and 205 (RC-324)"
    )
    assert (
        price_level_store._MATERIALIZED_SNAPSHOTS[("ZZRC324", session.isoformat())][1]
        is (results[0])
    ), "the store holds the one object every caller received, with its one fingerprint"
    assert results[0].price("PDH") == 105.0


def test_the_fingerprint_covers_every_bar_field():
    """Each field that can move a level must move the key — checked field by field."""
    session = MARKETS_DAY
    base = _bars(session, 105.0)
    (prior,) = _daily(session, base)
    held = sessions()

    def key(bars, candle, hours=held):
        return LVE.snapshot_input_fingerprint(
            "ZZRC324", session, bars, "test_fixture", candle, hours
        )

    fp = key(base, prior)

    for field in ("open", "high", "low", "close", "volume"):
        mutated = [dict(b) for b in base]
        mutated[30][field] = mutated[30][field] + 7.0
        other = key(mutated, prior)
        assert other != fp, (
            f"changing an interior bar's {field} left the fingerprint unchanged — that "
            f"field can go stale (RC-324)"
        )

    # A timestamp change must also register.
    shifted = [dict(b) for b in base]
    shifted[30]["timestamp"] = shifted[30]["timestamp"] + 60_000
    assert key(shifted, prior) != fp

    # INDUCED: a volume absent (not a number as sent) is not a reported 0, and a bar before it
    # still moves the key
    absent, zero = [dict(b) for b in base], [dict(b) for b in base]
    absent[30]["volume"], zero[30]["volume"] = None, 0.0
    assert key(absent, prior) not in (fp, key(zero, prior))
    earlier = [dict(b) for b in absent]
    earlier[10]["high"] = earlier[10]["high"] + 7.0
    assert key(earlier, prior) != key(absent, prior)

    # So must each field of the prior session's daily candle, and its absence.
    for field in ("high", "low", "close"):
        moved = Candle(**{**prior.__dict__, field: getattr(prior, field) + 7.0})
        assert key(base, moved) != fp
    assert key(base, None) != fp

    # And Schwab's /markets answer for this session or the prior one, held or not: an answer
    # that arrives after the levels were built is a new input
    prior_day = datetime.fromtimestamp(prior.ts, ET).date().isoformat()
    for day in (session.isoformat(), prior_day):
        assert day in held, f"no /markets answer held for {day}: the check would be vacuous"
        assert key(base, prior, {d: s for d, s in held.items() if d != day}) != fp
