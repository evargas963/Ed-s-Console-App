"""The price-level producer (materialize_price_level_snapshot) serves one result per generation:

(a) a change to any bar field, an interior one included, is a new generation with new levels;
    the same input is the same object;
(b) concurrent callers with one input get one object and one generation.
"""

from __future__ import annotations

import sys
import threading
from datetime import datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import liquidity_value_engine as LVE  # noqa: E402
from liquidity_value_engine import (  # noqa: E402
    PlaybookConfig,
    materialize_price_level_snapshot,
)
from micro_structure import Candle  # noqa: E402
from time_et import ET  # noqa: E402

from tests.conftest import most_recent_trading_day_et  # noqa: E402


def _bars(session, high_of_interior: float = 105.0) -> list:
    """The prior trading session plus this one; the interior bar's HIGH is the mutation target."""
    prior = most_recent_trading_day_et(on_or_before=session - timedelta(days=1))
    out = []
    for d in (prior, session):
        for i in range(60):
            ts = datetime(d.year, d.month, d.day, 9, 30, tzinfo=ET) + timedelta(minutes=i)
            px = 100.0 + (i % 11) * 0.10
            hi = px + 0.05
            if d == prior and i == 30:          # interior bar of the PRIOR session -> PDH
                hi = high_of_interior
            out.append({"timestamp": int(ts.timestamp() * 1000), "open": px, "high": hi,
                        "low": px - 0.05, "close": px, "volume": 1000.0 + i})
    return out


def _fresh():
    """This test ticker's snapshots leave the producer's cache: the next one is generation 1."""
    for key in [k for k in LVE._MATERIALIZED_SNAPSHOTS if k[0] == "ZZRC324"]:
        del LVE._MATERIALIZED_SNAPSHOTS[key]


def _mat(session, bars):
    return materialize_price_level_snapshot(
        "ZZRC324", session, LVE.bars_from_candles(
            [Candle(ts=b["timestamp"] / 1000, open=b["open"], high=b["high"], low=b["low"], close=b["close"],
                    volume=b["volume"]) for b in bars]), bar_source="test_fixture", config=PlaybookConfig())


def test_an_interior_bar_change_is_a_new_generation():
    """(a) The prior session's high moved from 105 to 999: a new generation with the new PDH."""
    _fresh()
    session = most_recent_trading_day_et()

    first = _mat(session, _bars(session, 105.0))
    assert first.generation == 1
    pdh_before = first.price("PDH")

    second = _mat(session, _bars(session, 999.0))
    assert second is not first, (
        "an interior bar changed and the producer returned the SAME object — the "
        "fingerprint is sampling the input instead of covering it (RC-324)")
    assert second.generation == first.generation + 1, (
        f"generation did not advance: {first.generation} -> {second.generation}")
    assert second.price("PDH") != pdh_before, (
        f"PDH stayed {pdh_before!r} after the high was moved to 999 — a stale value served "
        "under a fresh generation")

    # And the same input must still be ONE generation: no churn.
    again = _mat(session, _bars(session, 999.0))
    assert again is second, "an unchanged input minted a new object — one result per generation"


def test_concurrent_materialization_yields_one_object_and_one_generation():
    """(b) Eight concurrent callers, one input: one object, one generation."""
    _fresh()
    session = most_recent_trading_day_et()
    bars = _bars(session, 105.0)

    results: list = []
    errors: list = []
    barrier = threading.Barrier(8)

    def go():
        try:
            barrier.wait(timeout=10)
            results.append(_mat(session, bars))
        except Exception as exc:                       # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=go) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not errors, f"materialization raised under concurrency: {errors[:2]}"
    assert len(results) == 8, f"only {len(results)} of 8 threads completed"
    assert len({id(r) for r in results}) == 1, (
        "concurrent callers received DIFFERENT snapshot objects — two results for one "
        "generation, the exact defect Cursor reproduced with PDH 105 and 205 (RC-324)")
    assert len({r.generation for r in results}) == 1, (
        f"one input produced several generations: {sorted({r.generation for r in results})}")
    assert results[0].generation == 1


def test_the_fingerprint_covers_every_bar_field():
    """Each field that can move a level must move the key — checked field by field."""
    session = most_recent_trading_day_et()
    base = _bars(session, 105.0)
    fp = LVE._snapshot_input_fingerprint("ZZRC324", session, base, "test_fixture")

    for field in ("open", "high", "low", "close", "volume"):
        mutated = [dict(b) for b in base]
        mutated[30][field] = (mutated[30][field] or 0.0) + 7.0
        other = LVE._snapshot_input_fingerprint("ZZRC324", session, mutated, "test_fixture")
        assert other != fp, (
            f"changing an interior bar's {field} left the fingerprint unchanged — that "
            f"field can go stale (RC-324)")

    # A timestamp change must also register.
    shifted = [dict(b) for b in base]
    shifted[30]["timestamp"] = shifted[30]["timestamp"] + 60_000
    assert LVE._snapshot_input_fingerprint("ZZRC324", session, shifted, "test_fixture") != fp


def test_a_missing_volume_is_a_new_generation():
    """A bar with no volume is not that bar with volume 0: the producer serves a new generation."""
    _fresh()
    session = most_recent_trading_day_et()
    bars = _bars(session, 105.0)
    missing = [dict(b) for b in bars]
    missing[30]["volume"] = None
    zero = [dict(b) for b in bars]
    zero[30]["volume"] = 0.0
    first = _mat(session, missing)
    second = _mat(session, zero)
    assert second is not first, "a reported volume of 0 reused the snapshot of a missing volume"
    assert second.generation == first.generation + 1
