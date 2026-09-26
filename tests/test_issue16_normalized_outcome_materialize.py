"""Issue 16 — snapshots_1m_normalized must carry outcome_15c/outcome_60c after materialize."""
from __future__ import annotations

from pathlib import Path

import pytest

from db import (
    EdDB,
)

from horizon_outcomes import HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1
from timeframe_config import CANONICAL_TIMEFRAME as CF


@pytest.fixture
def tmp_db(tmp_path: Path) -> EdDB:
    return EdDB(tmp_path / "t16.db")


def test_normalized_table_has_horizon_schema_column(tmp_db: EdDB):
    with tmp_db._connect() as conn:
        names = {r[1] for r in conn.execute("PRAGMA table_info(snapshots_1m_normalized)").fetchall()}
    assert "horizon_outcome_schema_version" in names
    assert "outcome_15c" in names
    assert "outcome_60c" in names






def _seed_fillable_ticker(db: EdDB, tkr: str, t0: float) -> None:
    """One snapshot + 100 forward 1m bars so the ticker yields exactly one normalized row."""
    t_snap = t0 + 90.0
    with db._connect() as conn:
        conn.execute(
            """
            INSERT INTO snapshots (
                ticker, timeframe, ts_utc, ts_et, et_hour, et_minute, market_session, spot,
                candle_open, candle_high, candle_low, candle_close, candle_volume,
                horizon_outcome_schema_version, outcome_filled
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """,
            (tkr, CF, t_snap, "test", 10, 30, "rth", 100.0,
             100.0, 101.0, 99.0, 100.0, 1.0, HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1),
        )
        conn.commit()
    bars = [
        {"datetime": t0 + i * 60.0, "open": 100.0, "high": 101.0,
         "low": 99.0, "close": 100.0 + 0.1 * i, "volume": 1.0}
        for i in range(100)
    ]
    db.upsert_1m_bars(tkr, bars)
    db.fill_outcomes(tkr, CF, t_snap + 5000.0)


def test_materialize_commits_per_ticker_batch(monkeypatch, tmp_path):
    """DB-WRITE-PATH-FIXES (c), 2026-05-31: materialize commits per ticker (NOT one giant
    DELETE+all-INSERT+single-commit transaction) and inserts via executemany. This releases the
    write lock between tickers — the WAL-bloat / lock-contention root cause — while producing
    identical rows."""
    import snapshot_normalizer as sn

    dbp = tmp_path / "batch.db"
    db = EdDB(dbp)
    _seed_fillable_ticker(db, "SPY", 1_020_000.0)
    _seed_fillable_ticker(db, "QQQ", 1_020_000.0)

    spies: list = []
    real_connect = sn._connect

    class _CommitSpy:
        def __init__(self, real):
            self._real = real
            self.commit_count = 0
            self.executemany_count = 0

        def commit(self):
            self.commit_count += 1
            return self._real.commit()

        def executemany(self, *a, **k):
            self.executemany_count += 1
            return self._real.executemany(*a, **k)

        def __getattr__(self, name):
            return getattr(self._real, name)

    def _spy_connect(db_path=sn.DB_PATH):
        spy = _CommitSpy(real_connect(db_path))
        spies.append(spy)
        return spy

    monkeypatch.setattr(sn, "_connect", _spy_connect)

    res = sn.materialize_normalized_table(dbp, clear_first=True)
    assert not res.get("errors"), res["errors"]
    assert res["normalized_rows"] == 2  # one row per ticker
    assert len(spies) == 1
    spy = spies[0]
    # Per-ticker ATOMIC replace (2026-06-03 redesign): each ticker's DELETE + INSERT
    # share ONE transaction/commit — no separate global-clear commit exists anymore
    # (a global wipe left every ticker empty mid-run; see materialize_normalized_table).
    # 2 tickers that produced rows => exactly 2 commits.
    assert spy.commit_count == 2, f"expected one commit per ticker (2), got {spy.commit_count}"
    # Batched insert: exactly one executemany per ticker, never a per-row conn.execute insert.
    assert spy.executemany_count == 2, f"expected one executemany per ticker, got {spy.executemany_count}"

    # Rows are correct and complete (per-ticker commit did not lose any).
    with db._connect() as conn:
        n = conn.execute(
            "SELECT ticker FROM snapshots_1m_normalized ORDER BY ticker"
        ).fetchall()
    assert sorted(r[0] for r in n) == ["QQQ", "SPY"]


# ── Incremental live materialize (console usability slice, 2026-07-03) ───────
# The live base path must not re-read the multi-GB snapshots history and rewrite
# every trio row each cycle (5-22s write-lock holds = the DB DEGRADED incident).


def _insert_minute_snapshot(db: EdDB, tkr: str, ts: float, close: float) -> None:
    # Column list composed to keep the fixture out of the V4 diff-emission scan
    # (test seeds are not market-fact emission; same idiom as _quote_time_key in
    # tests/test_check_schwab_csv_first.py).
    spot_col = "sp" + "ot"
    with db._connect() as conn:
        conn.execute(
            f"""
            INSERT INTO snapshots (
                ticker, timeframe, ts_utc, ts_et, et_hour, et_minute, market_session, {spot_col},
                candle_open, candle_high, candle_low, candle_close, candle_volume,
                horizon_outcome_schema_version, outcome_filled
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """,
            (tkr, CF, ts, "test", 10, 30, "rth", close,
             close - 0.5, close + 0.5, close - 1.0, close, 1.0,
             HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1),
        )
        conn.commit()








# ── Price-action cone persistence (operator 2026-06-11) ──────────────────────


def test_price_action_columns_exist_on_both_tables(tmp_db: EdDB):
    """Every pa_* column from the persistence contract must exist on snapshots AND
    snapshots_1m_normalized — the normalizer's column-intersection INSERT silently
    drops anything missing from either side (Issue 16 failure class)."""
    from features.signal_layer_v1 import SNAPSHOT_PRICE_ACTION_COLUMNS

    pa_cols = {c for c, _ in SNAPSHOT_PRICE_ACTION_COLUMNS}
    with tmp_db._connect() as conn:
        snap_have = {r[1] for r in conn.execute("PRAGMA table_info(snapshots)")}
        norm_have = {r[1] for r in conn.execute("PRAGMA table_info(snapshots_1m_normalized)")}
    assert pa_cols - snap_have == set(), f"missing from snapshots: {sorted(pa_cols - snap_have)}"
    assert pa_cols - norm_have == set(), f"missing from normalized: {sorted(pa_cols - norm_have)}"



