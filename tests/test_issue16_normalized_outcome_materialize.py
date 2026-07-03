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


# ── Incremental live materialize (console usability slice, 2026-07-03) ───────
# The live base path must not re-read the multi-GB snapshots history and rewrite
# every trio row each cycle (5-22s write-lock holds = the DB DEGRADED incident).


def _insert_minute_snapshot(db: EdDB, tkr: str, ts: float, close: float) -> None:
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
            (tkr, CF, ts, "test", 10, 30, "rth", close,
             close - 0.5, close + 0.5, close - 1.0, close, 1.0,
             HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1),
        )
        conn.commit()


def test_incremental_materialize_equivalent_to_full_rebuild(tmp_path):
    """Equivalence lock: after new rows land AND an in-window outcome backfill happens,
    the incremental refresh must leave the normalized table byte-equal (key fields) to a
    full clear+rebuild — while reading only the trailing window, not the full history."""
    lookback = 75.0 * 60.0
    dbp = tmp_path / "inc.db"
    db = EdDB(dbp)
    t0 = 1_020_000.0
    t_mid = t0 + 4 * 3600.0  # 4h after ancient history — outside the 75min lookback
    for tkr in ("SPY", "QQQ"):
        # Ancient history: must NOT be re-read incrementally (cutoff anchors to the
        # last NORMALIZED ts minus lookback; these sit 4h before that).
        _insert_minute_snapshot(db, tkr, t0, 100.0)
        _insert_minute_snapshot(db, tkr, t0 + 60.0, 101.0)
        _insert_minute_snapshot(db, tkr, t_mid, 104.0)
    full0 = materialize_normalized_table(dbp, clear_first=True)
    assert not full0.get("errors"), full0["errors"]

    # New tail row lands after the last materialize.
    for tkr in ("SPY", "QQQ"):
        _insert_minute_snapshot(db, tkr, t_mid + 60.0, 106.0)
    inc = materialize_normalized_table(
        dbp, clear_first=True, incremental_lookback_sec=lookback
    )
    assert not inc.get("errors"), inc["errors"]
    for tkr in ("SPY", "QQQ"):
        assert inc["by_ticker"][tkr]["mode"] == "incremental"
        # Windowed read: the in-window mid row + the new tail row — never the 2 ancient rows.
        assert inc["by_ticker"][tkr]["raw"] == 2

    def _norm_state(conn):
        return sorted(
            tuple(r) for r in conn.execute(
                "SELECT ticker, ts_utc, candle_close FROM snapshots_1m_normalized"
            ).fetchall()
        )

    with db._connect() as conn:
        after_incremental = _norm_state(conn)
    full1 = materialize_normalized_table(dbp, clear_first=True)
    assert not full1.get("errors"), full1["errors"]
    with db._connect() as conn:
        after_full = _norm_state(conn)
    assert after_incremental == after_full, (
        "incremental refresh must produce the same normalized rows as a full rebuild"
    )
    # Old rows survived the incremental pass untouched (4 minutes per ticker total).
    assert len(after_incremental) == 8


def test_incremental_first_run_falls_back_to_full(tmp_path):
    """A ticker with no normalized rows takes the full path even in incremental mode."""
    dbp = tmp_path / "inc0.db"
    db = EdDB(dbp)
    _insert_minute_snapshot(db, "SPY", 1_020_000.0, 100.0)
    res = materialize_normalized_table(
        dbp, clear_first=True, incremental_lookback_sec=75.0 * 60.0
    )
    assert not res.get("errors"), res["errors"]
    assert res["by_ticker"]["SPY"]["mode"] == "full"
    assert res["normalized_rows"] == 1


def test_base_money_path_materialize_wires_incremental_lookback(monkeypatch, tmp_path):
    """The live base trio refresh must pass the outcome-covering incremental window."""
    import normalized_training_sync as nts

    calls: list[dict] = []

    def _capture(db_path, tickers=None, clear_first=True, incremental_lookback_sec=None):
        calls.append(
            {
                "tickers": tickers,
                "incremental_lookback_sec": incremental_lookback_sec,
            }
        )
        return {"raw_rows": 0, "normalized_rows": 0, "by_ticker": {}, "errors": []}

    monkeypatch.setattr(nts, "materialize_normalized_table", _capture)
    nts.materialize_base_money_path_tickers(tmp_path / "x.db")
    assert len(calls) == 1
    assert sorted(calls[0]["tickers"]) == ["IWM", "QQQ", "SPY"]
    assert calls[0]["incremental_lookback_sec"] == nts.BASE_NORMALIZE_INCREMENTAL_LOOKBACK_SEC
    # Window must cover the longest outcome horizon (60c ≈ 60 min) with margin.
    assert nts.BASE_NORMALIZE_INCREMENTAL_LOOKBACK_SEC >= 65.0 * 60.0


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


def test_backfill_price_action_columns_fills_both_tables(tmp_path):
    """Backfill computes leak-free pa_* values from price_bars_1m and writes them
    to snapshots AND snapshots_1m_normalized; values match the canonical function."""
    from features.signal_layer_v1 import compute_price_action_snapshot_columns
    from snapshot_normalizer import backfill_price_action_columns, materialize_normalized_table

    dbp = tmp_path / "pa.db"
    db = EdDB(dbp)
    t0 = 1_020_000.0
    n_bars = 80
    bars = [
        {"datetime": t0 + i * 60.0, "open": 100.0 + 0.05 * i, "high": 100.2 + 0.05 * i,
         "low": 99.8 + 0.05 * i, "close": 100.0 + 0.05 * i, "volume": 1000.0 + i}
        for i in range(n_bars)
    ]
    db.upsert_1m_bars("SPY", bars)
    t_snap = t0 + 70 * 60.0  # 70 closed bars of history at decision time
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
            ("SPY", CF, t_snap, "test", 10, 30, "rth", 103.5,
             103.4, 103.7, 103.3, 103.5, 1.0, HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1),
        )
        conn.commit()
    mat = materialize_normalized_table(dbp, clear_first=True)
    assert not mat.get("errors"), mat["errors"]

    res = backfill_price_action_columns(dbp)
    assert res["rows_updated"] == 1

    expect_bars = [
        {"bar_start_ts_utc": b["datetime"], "bar_end_ts_utc": b["datetime"] + 60.0,
         "open": b["open"], "high": b["high"], "low": b["low"],
         "close": b["close"], "volume": b["volume"]}
        for b in bars
    ]
    expected = compute_price_action_snapshot_columns(expect_bars[:70], decision_ts_utc=t_snap)
    assert expected["pa_ret_5m_pct"] is not None and expected["pa_ret_5m_pct"] > 0.0

    with db._connect() as conn:
        s = conn.execute(
            "SELECT pa_ret_5m_pct, pa_ret_60m_pct, pa_trend_slope_log20, pa_mtf_trend_1m "
            "FROM snapshots WHERE ticker='SPY'"
        ).fetchone()
        n = conn.execute(
            "SELECT pa_ret_5m_pct, pa_ret_60m_pct FROM snapshots_1m_normalized WHERE ticker='SPY'"
        ).fetchone()
    assert s["pa_ret_5m_pct"] == pytest.approx(expected["pa_ret_5m_pct"])
    assert s["pa_ret_60m_pct"] == pytest.approx(expected["pa_ret_60m_pct"])
    assert s["pa_trend_slope_log20"] == pytest.approx(expected["pa_trend_slope_log20"])
    assert n["pa_ret_5m_pct"] == pytest.approx(expected["pa_ret_5m_pct"])
    assert n["pa_ret_60m_pct"] == pytest.approx(expected["pa_ret_60m_pct"])

