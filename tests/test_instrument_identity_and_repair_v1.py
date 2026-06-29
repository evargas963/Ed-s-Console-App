"""Contract tests: ticker_storage_key, anchor load, DB query normalization, pin_neutral repair."""
from __future__ import annotations

import inspect
import time

from adaptive_shadow_v2_calibration import load_survivorship_anchors_v1
from db import EdDB, CANONICAL_TIMEFRAME, HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1, get_snapshot_sql
from timeframe_config import DERIVED_TIMEFRAME
from instrument_identity import ticker_storage_key
from market_data_adapter import schwab_candles_to_bars


def test_get_similar_setups_issue19_uses_zone_not_regime_primary():
    """Hardening: tier SQL must not silently conflate regime_primary with structural zone."""
    src = inspect.getsource(EdDB.get_similar_setups)
    assert "regime_primary" not in src


def test_pin_neutral_backfill_bar_low_uses_wide_lookback():
    """Gap >5000s between last bar and snapshot must not drop anchor bars (Issue 19 repair)."""
    src = inspect.getsource(EdDB.fill_outcomes_pin_neutral_backfill_v1)
    assert "120.0 * 86400.0" in src or "120.0 * 86400" in src


def test_upsert_1m_bars_uses_ticker_storage_key_for_spx_family(tmp_path):
    """Bars must persist under $SPX when caller passes bare SPX (Issue 19 rehydration)."""
    dbp = tmp_path / "bars_id.db"
    db = EdDB(dbp)
    # Canonical 60s UTC grid (BAR_ANCHOR_V1); upsert snaps near-grid floats to the minute open.
    ts = 1_700_000_040.0
    bars = [
        {
            "datetime": ts * 1000.0,
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.5,
            "volume": 1.0,
        }
    ]
    db.upsert_1m_bars("spx", bars)
    with db._connect() as conn:
        rows = conn.execute(
            "SELECT ticker, bar_start_ts_utc FROM price_bars_1m WHERE bar_start_ts_utc = ?",
            (ts,),
        ).fetchall()
    assert len(rows) == 1
    assert rows[0]["ticker"] == "$SPX"


def test_schwab_candles_to_bars_round_trips_through_upsert_1m(tmp_path):
    """Adapter must emit fields upsert_1m_bars reads (regression: missing datetime skipped all rows)."""
    dbp = tmp_path / "schwab_bars.db"
    db = EdDB(dbp)
    ms = 1_771_848_000_000.0
    candles = [{"datetime": int(ms), "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 100.0}]
    bars = schwab_candles_to_bars(candles)
    n = db.upsert_1m_bars("COP", bars)
    assert n == 1
    exp_start = ms / 1000.0
    with db._connect() as conn:
        row = conn.execute(
            "SELECT ticker, bar_start_ts_utc, close FROM price_bars_1m WHERE bar_start_ts_utc = ?",
            (exp_start,),
        ).fetchone()
    assert row["ticker"] == "COP"
    assert row["close"] == 1.5


def test_ticker_storage_key_preserves_spx_prefix():
    assert ticker_storage_key("spy") == "SPY"
    assert ticker_storage_key("spx") == "$SPX"
    assert ticker_storage_key("SPX") == "$SPX"
    assert ticker_storage_key("$spx") == "$SPX"
    assert ticker_storage_key("$SPX") == "$SPX"
    assert ticker_storage_key("  $spx  ") == "$SPX"
    assert ticker_storage_key("vix") == "$VIX"


def test_ticker_storage_key_vxn_rvx_broker_index_roots():
    """Vol-index lane V1: VXN/RVX bare roots map to broker $ prefix (same as VIX/SPX)."""
    assert ticker_storage_key("VXN") == "$VXN"
    assert ticker_storage_key("vxn") == "$VXN"
    assert ticker_storage_key("$VXN") == "$VXN"
    assert ticker_storage_key("RVX") == "$RVX"
    assert ticker_storage_key("rvx") == "$RVX"
    assert ticker_storage_key("$RVX") == "$RVX"
    assert ticker_storage_key("VIX") == "$VIX"
    assert ticker_storage_key("$VIX") == "$VIX"


def test_survivorship_anchor_ticker_matches_snapshots_row(tmp_path):
    """Regression: anchors must use same key as snapshots for $SPX (no SPX-only form)."""
    p = tmp_path / "surv.json"
    p.write_text(
        '{"anchors_used":[{"ticker":"$SPX","timeframe":"1m","zone":"breakout","vwap_side":"above",'
        '"nearest_above_dist":1.0,"nearest_below_dist":1.0}]}',
        encoding="utf-8",
    )
    anchors = load_survivorship_anchors_v1(path=p)
    assert anchors[0]["ticker"] == "$SPX"


def test_get_similar_setups_normalizes_spx_alias(tmp_path):
    dbp = tmp_path / "t.db"
    db = EdDB(dbp)
    with db._connect() as conn:
        conn.execute(
            """
            INSERT INTO snapshots (
                ticker, timeframe, ts_utc, ts_et, spot,
                zone, vwap_side, outcome_1c,
                nearest_above_dist, nearest_below_dist,
                horizon_outcome_schema_version, outcome_filled
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """,
            (
                "$SPX",
                CANONICAL_TIMEFRAME,
                1000.0,
                "test_et",
                5000.0,
                "breakout",
                "above",
                "up",
                1.0,
                1.0,
                HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1,
            ),
        )
    rows = db.get_similar_setups(
        ticker="SPX",
        timeframe=CANONICAL_TIMEFRAME,
        zone="breakout",
        vwap_side="above",
        nearest_above_dist=1.0,
        nearest_below_dist=1.0,
        n_similar=50,
    )
    assert len(rows) >= 1
    assert rows[0].get("ticker") == "$SPX"


def test_pin_neutral_backfill_writes_when_bars_exist(tmp_path):
    dbp = tmp_path / "t2.db"
    db = EdDB(dbp)
    t_snap = float((int(time.time()) // 60) * 60) - 120 * 60.0

    with db._connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO snapshots (
                ticker, timeframe, ts_utc, ts_et, et_hour, et_minute, market_session, spot,
                zone, vwap_side, horizon_outcome_schema_version, outcome_filled
            )
            VALUES ('SPY', ?, ?, 'x', 10, 30, 'rth', 100.0,
                    'pin_neutral', 'above', ?, 0)
            """,
            (CANONICAL_TIMEFRAME, t_snap, HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1),
        )
        sid = int(cur.lastrowid)
    bars = []
    for i in range(-30, 200):
        bs = t_snap + i * 60.0
        c = 100.0 + i * 0.01
        bars.append(
            {"datetime": bs, "open": c, "high": c + 0.02, "low": c - 0.02, "close": c, "volume": 100.0}
        )
    db.upsert_1m_bars("SPY", bars)

    with db._connect() as conn:
        o1 = conn.execute(
            get_snapshot_sql("tests/test_instrument_identity_and_repair_v1.py:167"),
            (sid,),
        ).fetchone()
    assert o1["outcome_1c"] in ("up", "down", "flat")

    audit = db.fill_outcomes_pin_neutral_backfill_v1(dry_run=False)
    assert audit["snapshots_scanned"] == 0
    assert audit["updates_executed"] == 0


def test_pin_neutral_backfill_excludes_legacy_5m_timeframe(tmp_path):
    """Canonical repair is 1m-only; legacy 5m rows are counted as excluded, not updated."""
    dbp = tmp_path / "t5m.db"
    db = EdDB(dbp)
    t_snap = float((int(time.time()) // 60) * 60) - 120 * 60.0

    with db._connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO snapshots (
                ticker, timeframe, ts_utc, ts_et, et_hour, et_minute, market_session, spot,
                zone, vwap_side, horizon_outcome_schema_version, outcome_filled
            )
            VALUES ('SPY', ?, ?, 'x', 10, 30, 'rth', 100.0,
                    'pin_neutral', 'above', ?, 0)
            """,
            (DERIVED_TIMEFRAME, t_snap, HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1),
        )
        sid = int(cur.lastrowid)
    bars = []
    for i in range(-30, 200):
        bs = t_snap + i * 60.0
        c = 100.0 + i * 0.01
        bars.append(
            {"datetime": bs, "open": c, "high": c + 0.02, "low": c - 0.02, "close": c, "volume": 100.0}
        )
    db.upsert_1m_bars("SPY", bars)

    audit = db.fill_outcomes_pin_neutral_backfill_v1(dry_run=False)
    assert audit["snapshots_scanned"] == 0
    assert audit["legacy_timeframe_rows_excluded"] == 1
    assert audit["updates_executed"] == 0

    with db._connect() as conn:
        o1 = conn.execute(
            get_snapshot_sql("tests/test_instrument_identity_and_repair_v1.py:208"),
            (sid,),
        ).fetchone()
    assert o1["outcome_1c"] is None
    assert o1["timeframe"] == DERIVED_TIMEFRAME


def test_get_similar_setups_rejects_non_canonical_timeframe(tmp_path):
    """Issue 19 production similarity must not mix legacy snapshot timeframes."""
    dbp = tmp_path / "tnc.db"
    db = EdDB(dbp)
    similar, tr = db.get_similar_setups(
        ticker="SPY",
        timeframe=DERIVED_TIMEFRAME,
        zone="pin_neutral",
        vwap_side="above",
        nearest_above_dist=1.0,
        nearest_below_dist=1.0,
        return_trace=True,
    )
    assert similar == []
    assert tr.get("rejected") is True
    assert tr.get("reject_reason") == "non_canonical_timeframe_for_issue19"
