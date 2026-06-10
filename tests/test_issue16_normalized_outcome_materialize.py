"""Issue 16 — snapshots_1m_normalized must carry outcome_15c/outcome_60c after materialize."""
from __future__ import annotations

from pathlib import Path

import pytest

from db import EdDB, get_snapshot_sql
from horizon_outcomes import HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1, forward_bar_start_utc
from snapshot_normalizer import materialize_normalized_table
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


def test_materialize_copies_outcome_15c_60c_from_snapshots(tmp_db: EdDB):
    """Same bar contract as test_horizon_bar_outcomes: fill snapshots then materialize; normalized matches."""
    t0 = 1_020_000.0
    t_snap = t0 + 90.0
    with tmp_db._connect() as conn:
        conn.execute(
            """
            INSERT INTO snapshots (
                ticker, timeframe, ts_utc, ts_et, et_hour, et_minute, market_session, spot,
                candle_open, candle_high, candle_low, candle_close, candle_volume,
                horizon_outcome_schema_version, outcome_filled
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "SPY",
                CF,
                t_snap,
                "test",
                10,
                30,
                "rth",
                9999.0,
                100.0,
                101.0,
                99.0,
                100.0,
                1.0,
                HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1,
                0,
            ),
        )
    bars = []
    for i in range(100):
        bs = t0 + i * 60.0
        bars.append(
            {
                "datetime": bs,
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.0 + 0.1 * i,
                "volume": 1.0,
            }
        )
    tmp_db.upsert_1m_bars("SPY", bars)
    tmp_db.fill_outcomes("SPY", CF, t_snap + 5000.0)

    with tmp_db._connect() as conn:
        s = conn.execute(
            get_snapshot_sql("tests/test_issue16_normalized_outcome_materialize.py:snapshot_outcomes"),
            (CF,),
        ).fetchone()
    assert s["outcome_15c"] is not None
    assert s["outcome_60c"] is not None

    mat = materialize_normalized_table(Path(tmp_db.db_path), clear_first=True)
    assert not mat.get("errors"), mat["errors"]
    assert mat["normalized_rows"] == 1

    with tmp_db._connect() as conn:
        n = conn.execute(
            "SELECT outcome_1c, outcome_15c, outcome_60c, outcome_15c_pts, outcome_60c_pts "
            "FROM snapshots_1m_normalized WHERE ticker='SPY'"
        ).fetchone()
    assert n["outcome_15c"] == s["outcome_15c"]
    assert n["outcome_60c"] == s["outcome_60c"]
    assert abs(float(n["outcome_15c_pts"]) - float(s["outcome_15c_pts"])) < 1e-5
    assert abs(float(n["outcome_60c_pts"]) - float(s["outcome_60c_pts"])) < 1e-5

    # Semantic: 15c pts matches bar math (anchor = bar 0 close at t0 when ts inside bar 1)
    anchor_close = 100.0 + 0.1 * 0.0
    b15 = forward_bar_start_utc(t_snap, 15)
    i15 = int(round((b15 - t0) / 60.0))
    forward_close_15 = 100.0 + 0.1 * float(i15)
    pts15 = forward_close_15 - anchor_close
    assert abs(float(s["outcome_15c_pts"]) - pts15) < 1e-5


def test_raw_schwab_quote_primitives_roundtrip_snapshots_and_normalized(tmp_db: EdDB):
    """2026-06-10 operator: raw Schwab leaves (bidPrice/askPrice/bidSize/askSize/lastSize/
    totalVolume) must persist on snapshots AND survive materialize into normalized —
    the normalizer copies the column intersection, so a missing normalized column
    would silently drop the leaf."""
    from db import SnapshotRow

    # Schema-parity lock (FIND 2026-06-10): insert_snapshot writes every dataclass
    # field, so EVERY SnapshotRow field must exist on a fresh snapshots table —
    # pred_model_source/pred_override_source/reward_risk/reward_risk2 were missing.
    with tmp_db._connect() as conn:
        have = {r[1] for r in conn.execute("PRAGMA table_info(snapshots)")}
    missing = sorted(set(SnapshotRow.__annotations__) - have - {"snapshot_id"})
    assert not missing, f"SnapshotRow fields missing from fresh snapshots schema: {missing}"

    snap = SnapshotRow(
        ticker="SPY", timeframe=CF, ts_utc=2_000_000.0 + 90.0, ts_et="test",
        et_hour=10, et_minute=30, market_session="rth", spot=600.0,
        candle_open=599.5, candle_high=600.5, candle_low=599.0,
        candle_close=600.0, candle_volume=1.0,
        bid_price=599.9, ask_price=600.1, bid_size=12.0, ask_size=7.0,
        last_size=300.0, total_volume=41_250_000.0,
    )
    tmp_db.insert_snapshot(snap)

    with tmp_db._connect() as conn:
        s = conn.execute(
            "SELECT bid_price, ask_price, bid_size, ask_size, last_size, total_volume "
            "FROM snapshots WHERE ticker='SPY'"
        ).fetchone()
    assert s["bid_price"] == 599.9
    assert s["ask_price"] == 600.1
    assert s["bid_size"] == 12.0
    assert s["ask_size"] == 7.0
    assert s["last_size"] == 300.0
    assert s["total_volume"] == 41_250_000.0

    mat = materialize_normalized_table(Path(tmp_db.db_path), clear_first=True)
    assert not mat.get("errors"), mat["errors"]

    with tmp_db._connect() as conn:
        n = conn.execute(
            "SELECT bid_price, ask_price, bid_size, ask_size, last_size, total_volume "
            "FROM snapshots_1m_normalized WHERE ticker='SPY'"
        ).fetchone()
    assert n is not None
    assert n["bid_price"] == 599.9
    assert n["ask_size"] == 7.0
    assert n["total_volume"] == 41_250_000.0


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

