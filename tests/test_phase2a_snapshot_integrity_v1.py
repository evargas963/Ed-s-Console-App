"""RC-324 — the canonical producer must not serve stale values, nor two results per generation.

Cursor's adversarial review of 5609617d proved both defects by execution, and these are
those two proofs, kept as controls:

(a) STALE. `_snapshot_input_fingerprint` identified a bar set by
    (ticker, date, source, len, first_ts, last_ts, last_close) — a SAMPLE, not a cover.
    Changing PDH from 105 to 999 leaves the length, both endpoints and the last close
    untouched, so the fingerprint matched, the cached object came back, and the stale 105
    was served under generation 1.

(b) RACE. `materialize_price_level_snapshot` read the cache, decided the generation, built
    and wrote back with no mutual exclusion. Two concurrent callers both saw
    `existing is None`, both computed generation 1, and produced two different objects
    carrying PDH 105 and 205 — two results under one generation, which is the half of the
    invariant this producer exists to guarantee.
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
from app.domain.time_et import ET  # noqa: E402

from tests.conftest import most_recent_trading_day_et  # noqa: E402


def _bars(session, high_of_interior: float = 105.0) -> list:
    """A prior session plus this one. The interior bar's HIGH is the mutation target."""
    out = []
    for off in (1, 0):
        d = session - timedelta(days=off)
        for i in range(60):
            ts = datetime(d.year, d.month, d.day, 9, 30, tzinfo=ET) + timedelta(minutes=i)
            px = 100.0 + (i % 11) * 0.10
            hi = px + 0.05
            if off == 1 and i == 30:            # interior bar of the PRIOR session -> PDH
                hi = high_of_interior
            out.append({"datetime": ts.timestamp(), "open": px, "high": hi,
                        "low": px - 0.05, "close": px, "volume": 1000.0 + i})
    return out


def _fresh(monkeypatch):
    monkeypatch.setattr(LVE, "_MATERIALIZED_SNAPSHOTS", {}, raising=False)


def _mat(session, bars):
    return materialize_price_level_snapshot(
        "ZZRC324", session, bars, bar_source="test_fixture", config=PlaybookConfig())


def test_an_interior_bar_change_is_a_new_generation(monkeypatch):
    """(a) Cursor's stale proof: mutate PDH 105 -> 999 and require the cache to notice."""
    _fresh(monkeypatch)
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


def test_concurrent_materialization_yields_one_object_and_one_generation(monkeypatch):
    """(b) Cursor's race proof: N threads, one result."""
    _fresh(monkeypatch)
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


def test_the_fingerprint_covers_every_bar_field(monkeypatch):
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
    shifted[30]["datetime"] = shifted[30]["datetime"] + 60.0
    assert LVE._snapshot_input_fingerprint("ZZRC324", session, shifted, "test_fixture") != fp


def test_the_lock_exists_and_spans_the_decision():
    """A lock declared but not taken around the read-decide-write is decoration."""
    import inspect

    assert isinstance(LVE._MATERIALIZE_LOCK, type(threading.Lock())), (
        "the materialization lock is gone")
    src = inspect.getsource(LVE.materialize_price_level_snapshot)
    body = src.split("_MATERIALIZE_LOCK", 1)
    assert len(body) == 2, "materialize_price_level_snapshot no longer takes the lock"
    guarded = body[1]
    for step in ("_MATERIALIZED_SNAPSHOTS.get", "generation =",
                 "build_price_level_snapshot", "_MATERIALIZED_SNAPSHOTS[key]"):
        assert step in guarded, (
            f"`{step}` sits OUTSIDE the critical section — the check-then-act is still racy")
