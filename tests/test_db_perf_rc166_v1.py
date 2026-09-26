"""RC-166: tier-1 lock hold + L1 light pool isolation (DB freeze / analytics wall)."""
from __future__ import annotations

import threading
import time
from pathlib import Path


def _collect_window_session_open_ts() -> float:
    """RC-183: price_bars_1m persists ET bar-END minutes (555, min(975, close+15)] on trading
    days only — the ONE write seam, so fixtures must use REAL in-window minutes. The synthetic
    stamps these tests carried (2_020_000 / 3_020_000, i.e. 1970) were silently dropped by that
    gate, which is the gate WORKING; the tests then asserted rows that could never land.
    Returns the epoch-second bar_start for 09:30 ET on a known trading Monday.
    """
    import datetime as _dt
    from zoneinfo import ZoneInfo

    return _dt.datetime(2026, 6, 15, 9, 30, tzinfo=ZoneInfo("America/New_York")).timestamp()


def test_identical_reseed_releases_tier1_without_outcome_refresh_work(tmp_path):
    """An identical live re-seed must rewrite only the OVERLAP TAIL, never the whole list.

    RC-243 note on this test's own history: it asserted `n == 0` and passed for years — but
    only because its 1970-epoch fixture stamps were rejected wholesale by the RC-183
    collect-window gate, so the FIRST write landed nothing either and "0 rewritten" was
    vacuously true. With real in-window minutes the first write lands 60 rows and the re-seed
    rewrites 4: the recent-overlap window (LIVE_BARS_REUPSERT_OVERLAP_SEC) plus the DB-max
    bar, which is the documented live-path contract and exactly what the sibling test in
    tests/test_db_sqlite_tier1_retry.py already encodes as `overlap + 1 + 1`. The contract
    this row cares about is bounded-tail, not literal zero.
    """
    from db import EdDB, LIVE_BARS_REUPSERT_OVERLAP_SEC

    db = EdDB(tmp_path / "idemp.db")
    t0 = _collect_window_session_open_ts()
    bars = [
        {
            "datetime": t0 + i * 60.0,
            "open": 50.0,
            "high": 51.0,
            "low": 49.0,
            "close": 50.0 + i * 0.01,
            "volume": 10.0,
        }
        for i in range(60)
    ]
    assert db.upsert_1m_bars("IWM", bars) == 60
    t_a = time.perf_counter()
    n = db.upsert_1m_bars("IWM", bars)
    elapsed_ms = (time.perf_counter() - t_a) * 1000.0
    overlap_tail = int(LIVE_BARS_REUPSERT_OVERLAP_SEC // 60) + 1 + 1
    assert n <= overlap_tail, (
        f"identical re-seed rewrote {n} rows, above the overlap tail of {overlap_tail} — the "
        f"live path is force-rewriting history and holding tier-1 for it (RC-166)"
    )
    assert n < 60, "identical re-seed rewrote the WHOLE list — the incremental path is gone"
    # Bound is generous (CI/disk); the contract is a bounded write, not a specific ms.
    assert elapsed_ms < 5000.0, f"identical re-seed unexpectedly slow: {elapsed_ms:.1f}ms"


def test_governed_refresh_runs_after_tier1_lock_release(tmp_path):
    """Outcome refresh must not hold _TIER1_SNAPSHOT_WRITE_LOCK (RC-166).

    Inserts a snapshot + bars, poisons a label, then mutates a bar while another
    thread tries to acquire the tier-1 lock during the upsert call. If refresh
    still ran under the lock, a concurrent acquire would wait for the whole
    refresh; with post-unlock refresh the second acquire can proceed between
    bar commit and (or during) refresh on a separate connection.
    """
    import db as db_mod
    from db import EdDB
    from horizon_outcomes import HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1
    from timeframe_config import CANONICAL_TIMEFRAME as CF

    ed = EdDB(tmp_path / "unlock.db")
    t0 = _collect_window_session_open_ts() + 3600.0
    t_snap = t0 + 90.0
    with ed._connect() as conn:
        conn.execute(
            """
            INSERT INTO snapshots (
                ticker, timeframe, ts_utc, ts_et, et_hour, et_minute, market_session, spot,
                horizon_outcome_schema_version, outcome_filled
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """,
            ("SPY", CF, t_snap, "test", 10, 30, "rth", 100.0, HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1),
        )
    bars = [
        {
            "datetime": t0 + i * 60.0,
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0 + 0.1 * i,
            "volume": 1.0,
        }
        for i in range(80)
    ]
    ed.upsert_1m_bars("SPY", bars)
    ed.fill_outcomes("SPY", CF, t_snap + 5000.0)

    # Source-level: refresh call site is OUTSIDE the nested _do that runs under tier-1.
    src = Path(db_mod.__file__).read_text(encoding="utf-8")
    # The post-unlock call uses _post_unlock_refresh and sits after _tier1_snapshot_write return.
    assert "_post_unlock_refresh" in src
    assert "post-unlock governed outcome refresh" in src

    saw_lock_free = threading.Event()
    refresh_entered = threading.Event()
    orig_refresh = db_mod._refresh_governed_outcomes_after_bar_mutation

    def _wrapped_refresh(*args, **kwargs):
        refresh_entered.set()
        # While refresh runs, tier-1 must be free so another writer can acquire.
        acquired = db_mod._TIER1_SNAPSHOT_WRITE_LOCK.acquire(blocking=False)
        if acquired:
            saw_lock_free.set()
            db_mod._TIER1_SNAPSHOT_WRITE_LOCK.release()
        return orig_refresh(*args, **kwargs)

    db_mod._refresh_governed_outcomes_after_bar_mutation = _wrapped_refresh  # type: ignore[assignment]
    try:
        mutated = list(bars)
        mutated[10] = {
            "datetime": t0 + 10 * 60.0,
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0 + 0.1 * 10 + 0.001,
            "volume": 1.0,
        }
        ed.upsert_1m_bars("SPY", mutated)
    finally:
        db_mod._refresh_governed_outcomes_after_bar_mutation = orig_refresh  # type: ignore[assignment]

    assert refresh_entered.is_set(), "mutation must trigger governed refresh"
    assert saw_lock_free.is_set(), "tier-1 lock must be free during governed refresh"




def test_rc243_one_bar_writer_contends_for_the_write_seam():
    """RC-243: bar writers all serialize on ONE process-wide tier-1 write lock, so writers past
    the first queue rather than parallelise — and each extra contender lengthens the queue
    against a 27 GB file. MEASURED live: ed_bars_0/1/2 took 426/407/405 lock waits (1,238 on
    upsert_1m_bars), lifetime max 180,340 ms, busy_retry_count 0 (the Python mutex, not
    SQLite's busy handler). The REST-poll bar pool (BARS_WORKERS / ed_bars) is gone: streamed
    bars are written by exactly ONE thread, so there is one contender for the seam, attributable
    by its own thread name."""
    import ast as _ast

    import server as srv

    src = Path(srv.__file__).read_text(encoding="utf-8")
    assert 'thread_name_prefix="ed_bars"' not in src and "BARS_WORKERS" not in src, (
        "a bar worker pool reappeared — it re-creates the fan-in this row measured")
    tree = _ast.parse(src)
    starter = next(n for n in _ast.walk(tree)
                   if isinstance(n, _ast.FunctionDef) and n.name == "start_bar_writer")
    threads = [c for c in _ast.walk(starter) if isinstance(c, _ast.Call)
               and isinstance(c.func, _ast.Attribute) and c.func.attr == "Thread"]
    assert len(threads) == 1, "the bar writer must be ONE thread"
    kw = {k.arg: k.value for k in threads[0].keywords}
    assert isinstance(kw["target"], _ast.Name) and kw["target"].id == "_bar_writer"
    assert _ast.literal_eval(kw["name"]) == "bar-writer"
    # and it is started from exactly one call site
    starts = [c for c in _ast.walk(tree) if isinstance(c, _ast.Call)
              and isinstance(c.func, _ast.Name) and c.func.id == "start_bar_writer"]
    assert len(starts) == 1, f"start_bar_writer is called {len(starts)} times"
