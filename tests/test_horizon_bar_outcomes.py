"""Issue 3 — universal bar-based horizon math and DB fill."""
from __future__ import annotations

import math
import sqlite3
from pathlib import Path

import pytest

from horizon_outcomes import (
    HORIZON_OUTCOME_SCHEMA_BAR_V1,
    HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1,
    bar_complete_by_utc,
    forward_bar_start_utc,
    snapshot_bar_start_ts_utc,
    OUTCOME_BAR_SPECS,
)
from db import EdDB, get_snapshot_sql
from timeframe_config import CANONICAL_TIMEFRAME as CF


def test_forward_bar_start_grid():
    assert forward_bar_start_utc(100.0, 1) == math.floor(160.0 / 60.0) * 60.0
    t0 = 1700000000.0
    assert forward_bar_start_utc(t0, 60) == math.floor((t0 + 3600.0) / 60.0) * 60.0


def test_snapshot_bar_start_floors_poll_seconds():
    assert snapshot_bar_start_ts_utc(100.0) == 60.0
    assert snapshot_bar_start_ts_utc(120.0) == 120.0
    assert snapshot_bar_start_ts_utc(1_781_800_000.0) == 1_781_799_960.0


def test_insert_snapshot_stores_bar_start_not_poll_second(tmp_path: Path):
    from db import SnapshotRow

    db = EdDB(tmp_path / "barstamp.db")
    db.insert_snapshot(SnapshotRow(
        ticker="SPY",
        timeframe=CF,
        ts_utc=1_781_800_000.0,
        ts_et="2026-06-18 10:00:40 ET",
        et_hour=10,
        et_minute=0,
        market_session="rth",
        spot=500.0,
    ))
    from time_et import et_clock_from_ts_utc
    with db._connect() as conn:
        ts, minute = conn.execute(
            "SELECT ts_utc, et_minute FROM snapshots WHERE ticker='SPY'"
        ).fetchone()
    bar = snapshot_bar_start_ts_utc(1_781_800_000.0)
    assert ts == bar
    assert int(minute) == et_clock_from_ts_utc(bar)[1]


def test_bar_complete():
    assert not bar_complete_by_utc(120.0, 179.0)
    assert bar_complete_by_utc(120.0, 180.0)


def test_outcome_specs_cover_all_nc():
    names = [s[0] for s in OUTCOME_BAR_SPECS]
    assert names == [
        "outcome_1c",
        "outcome_5c",
        "outcome_15c",
        "outcome_60c",
    ]
    assert HORIZON_OUTCOME_SCHEMA_BAR_V1 == 2
    assert HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1 == 3


@pytest.fixture
def tmp_db(tmp_path: Path) -> EdDB:
    return EdDB(tmp_path / "t.db")


def test_fill_outcomes_bar_based_anchor_matches_last_completed_bar(tmp_db: EdDB):
    """Anchor = close of last bar with bar_end <= ts_utc; forward close unchanged (Issue 4)."""
    t0 = 1_785_506_400.0  # 2026-07-31 10:00 ET, on 1m grid — real PAST in-window session (RC-183)
    t_snap = t0 + 90.0  # after first bar ends (t0+60), inside second bar
    with tmp_db._connect() as conn:
        conn.execute(
            """
            INSERT INTO snapshots (
                ticker, timeframe, ts_utc, ts_et, et_hour, et_minute, market_session, spot,
                horizon_outcome_schema_version, outcome_filled
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
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
                HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1,
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
        row = conn.execute(
            get_snapshot_sql("tests/test_horizon_bar_outcomes.py:94"),
            (CF,),
        ).fetchone()
    assert row is not None
    assert row["outcome_1c"] is not None
    anchor_close = 100.0 + 0.1 * 0.0
    b1 = forward_bar_start_utc(t_snap, 1)
    i_fwd = int(round((b1 - t0) / 60.0))
    forward_close = 100.0 + 0.1 * float(i_fwd)
    pts = forward_close - anchor_close
    assert abs(float(row["outcome_1c_pts"]) - pts) < 1e-6


def test_fill_outcomes_live_batch_limit_caps_rows_per_call(tmp_db: EdDB, monkeypatch: pytest.MonkeyPatch):
    """Newest-first LIMIT bounds live fill_outcomes (no unbounded 14d scan)."""
    import db as dbmod

    monkeypatch.setattr(dbmod, "FILL_OUTCOMES_LIVE_BATCH_LIMIT", 2)
    t0 = 1_785_506_400.0  # 2026-07-31 10:00 ET
    # Bars first (no snapshots yet) so upsert mutation-refresh cannot pre-fill labels.
    bars = []
    for i in range(120):
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
    with tmp_db._connect() as conn:
        for i in range(5):
            t_snap = t0 + 90.0 + i * 60.0
            conn.execute(
                """
                INSERT INTO snapshots (
                    ticker, timeframe, ts_utc, ts_et, et_hour, et_minute, market_session, spot,
                    horizon_outcome_schema_version, outcome_filled
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                """,
                (
                    "SPY",
                    CF,
                    t_snap,
                    "test",
                    10,
                    30 + i,
                    "rth",
                    100.0,
                    HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1,
                ),
            )
    # Eval far enough that 60c horizons are complete for all five.
    tmp_db.fill_outcomes("SPY", CF, t0 + 90.0 + 4 * 60.0 + 5000.0)
    with tmp_db._connect() as conn:
        n_touched = conn.execute(
            """
            SELECT COUNT(*) AS n FROM snapshots
            WHERE ticker='SPY' AND timeframe=? AND outcome_1c IS NOT NULL
            """,
            (CF,),
        ).fetchone()["n"]
        n_still = conn.execute(
            """
            SELECT COUNT(*) AS n FROM snapshots
            WHERE ticker='SPY' AND timeframe=? AND outcome_filled=0
            """,
            (CF,),
        ).fetchone()["n"]
    # One call with LIMIT 2 fills at most 2 rows; at least 3 remain unfilled.
    assert n_touched <= 2
    assert n_still >= 3


def test_upsert_1m_bars_normalizes_epoch_ms_for_candle_objects_and_dicts(tmp_db: EdDB):
    """2026-06-09 regression: Candle objects with epoch-ms .ts (Schwab quoteTime passthrough)
    were stored raw on an ms grid, so fill_outcomes (seconds grid) matched zero bars all day.
    Both input shapes must land on the canonical whole-minute epoch-seconds grid."""
    from types import SimpleNamespace

    sec_start = 1_785_506_400.0  # 2026-07-31 10:00 ET — already whole-minute, seconds, past in-window (RC-183)
    obj_bar = SimpleNamespace(
        ts=sec_start * 1000.0, open=10.0, high=11.0, low=9.0, close=10.5, volume=5.0
    )
    dict_bar = {
        "datetime": (sec_start + 60.0) * 1000.0,
        "open": 10.5,
        "high": 12.0,
        "low": 10.0,
        "close": 11.5,
        "volume": 7.0,
    }
    n = tmp_db.upsert_1m_bars("SPY", [obj_bar, dict_bar])
    assert n == 2
    with tmp_db._connect() as conn:
        rows = conn.execute(
            "SELECT bar_start_ts_utc, bar_end_ts_utc, close FROM price_bars_1m"
            " WHERE ticker='SPY' ORDER BY bar_start_ts_utc"
        ).fetchall()
    assert [float(r["bar_start_ts_utc"]) for r in rows] == [sec_start, sec_start + 60.0]
    assert all(float(r["bar_end_ts_utc"]) - float(r["bar_start_ts_utc"]) == 60.0 for r in rows)
    assert [float(r["close"]) for r in rows] == [10.5, 11.5]


def test_migration_issue4_clears_v2_labels(tmp_path: Path):
    """Opening DB runs Issue 4 migration once: v2 rows lose derived outcomes, version -> 3."""
    db_path = tmp_path / "preissue4.db"
    with sqlite3.connect(str(db_path)) as conn:
        conn.executescript(
            """
            CREATE TABLE snapshots (
                snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT, timeframe TEXT, ts_utc REAL, ts_et TEXT,
                et_hour INTEGER, et_minute INTEGER, market_session TEXT, spot REAL,
                outcome_1c TEXT, outcome_1c_pts REAL,
                outcome_5c TEXT, outcome_5c_pts REAL,
                outcome_15c TEXT, outcome_15c_pts REAL,
                outcome_60c TEXT, outcome_60c_pts REAL,
                horizon_outcome_schema_version INTEGER DEFAULT 2,
                outcome_filled INTEGER DEFAULT 0
            );
            INSERT INTO snapshots (
                ticker, timeframe, ts_utc, ts_et, et_hour, et_minute,
                market_session, spot, outcome_1c, horizon_outcome_schema_version,
                outcome_filled
            ) VALUES ('X', '1m', 1.0, 't', 0, 0, 'rth', 1.0, 'up', 2, 1);
            CREATE TABLE ed_schema_flags (
                flag_key TEXT PRIMARY KEY, flag_value TEXT NOT NULL, set_ts_utc REAL
            );
            INSERT INTO ed_schema_flags VALUES ('horizon_bar_v1_legacy_poll_invalidated', '1', 1.0);
            """
        )
        conn.commit()

    EdDB(db_path)

    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            get_snapshot_sql("tests/test_horizon_bar_outcomes.py:145")
        ).fetchone()
        flag = conn.execute(
            "SELECT 1 FROM ed_schema_flags WHERE flag_key='horizon_outcome_anchor_bar_close_v1'"
        ).fetchone()
    assert row["outcome_1c"] is None
    assert int(row["horizon_outcome_schema_version"]) == HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1
    assert flag is not None


# ── Phase 1 (horizon-collapse fix): per-horizon vol-scaled outcome threshold ──────


def test_classify_direction_pts_threshold_and_fail_closed():
    """classify_direction_pts uses a points threshold and fails closed without a valid scale."""
    from math_probabilities import classify_direction, classify_direction_pts

    # up / down / flat by the supplied points threshold (strict inequality; boundary = flat)
    assert classify_direction_pts(0.6, 0.5) == "up"
    assert classify_direction_pts(-0.6, 0.5) == "down"
    assert classify_direction_pts(0.4, 0.5) == "flat"
    assert classify_direction_pts(-0.4, 0.5) == "flat"
    assert classify_direction_pts(0.5, 0.5) == "flat"

    # Fail-closed: no directional claim without a valid (>0) volatility scale.
    assert classify_direction_pts(10.0, 0.0) == "flat"
    assert classify_direction_pts(10.0, -1.0) == "flat"
    assert classify_direction_pts(10.0, None) == "flat"

    # Phase 1 substance: a per-horizon vol-scaled threshold disagrees with the legacy
    # fixed 0.05%-of-spot cut for the same move — the label is no longer a single uniform cut.
    spot = 100.0
    pts = 0.1
    fixed = classify_direction(pts, spot)          # thr = spot*0.0005 = 0.05 -> "up"
    perhz = classify_direction_pts(pts, 0.55)       # vol-scaled thr 0.55 -> "flat"
    assert fixed == "up"
    assert perhz == "flat"
    assert fixed != perhz


def test_outcome_fill_uses_per_horizon_threshold_all_horizons(tmp_db: EdDB):
    """Stored outcome_Nc matches the per-horizon ATR-scaled formula (not the fixed 0.05% cut),
    across 1c/5c/15c/60c, computed via the same public helpers the writer uses."""
    from math_probabilities import classify_direction_pts
    from movement_target_threshold import (
        load_movement_thresholds_by_horizon_v1,
        threshold_move_pts_for_slug,
    )

    t0 = 1_785_506_400.0  # 2026-07-31 10:00 ET — real PAST in-window session (RC-183 collect-window law)
    t_snap = t0 + 90.0
    atr_v = 1.0
    with tmp_db._connect() as conn:
        conn.execute(
            """
            INSERT INTO snapshots (
                ticker, timeframe, ts_utc, ts_et, et_hour, et_minute, market_session, spot, atr,
                horizon_outcome_schema_version, outcome_filled
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
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
                atr_v,
                HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1,
            ),
        )
    bars = []
    for i in range(120):
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
    tmp_db.fill_outcomes("SPY", CF, t_snap + 8000.0)

    cfg = load_movement_thresholds_by_horizon_v1()
    anchor_close = 100.0  # last bar with bar_end <= t_snap is bar i=0 (end t0+60)
    with tmp_db._connect() as conn:
        row = conn.execute(
            get_snapshot_sql("tests/test_horizon_bar_outcomes.py:per_horizon"),
            (CF,),
        ).fetchone()
    assert row is not None

    directional_seen = False
    for slug, n_min in (("1c", 1), ("5c", 5), ("15c", 15), ("60c", 60)):
        b = forward_bar_start_utc(t_snap, n_min)
        i_fwd = int(round((b - t0) / 60.0))
        forward_close = 100.0 + 0.1 * float(i_fwd)
        pts = forward_close - anchor_close
        thr = threshold_move_pts_for_slug(slug, anchor_close=anchor_close, atr=atr_v, cfg=cfg)
        expected = classify_direction_pts(pts, thr)
        assert row[f"outcome_{slug}"] == expected, (
            slug,
            pts,
            thr,
            row[f"outcome_{slug}"],
            expected,
        )
        if expected in ("up", "down"):
            directional_seen = True

    # The longest horizon has a large monotone move; the per-horizon path must still emit a
    # directional label (guards against an all-flat regression / classifier wired to a bad scale).
    assert directional_seen
    assert row["outcome_60c"] == "up"


# ── BAR_PERSISTENCE_GAP_TRACE_AND_FIX_V1 — stale-seed guard + explicit window locks ──


def test_candle_accumulator_seed_refuses_stale_payload():
    """A pricehistory payload OLDER than the existing grid must not erase newer bars."""
    from server import _CandleAccumulator

    acc = _CandleAccumulator(bar_seconds=60, max_bars=500)
    base = 1_800_000_000.0
    acc.tick("ZZT", 100.0, base)
    acc.tick("ZZT", 101.0, base + 60.0)  # completes the first tick-built bar
    newest_ts = acc.get_bars("ZZT")[-1].ts

    def _payload(ts_epoch: float) -> list[dict]:
        return [{
            "datetime": ts_epoch * 1000.0,
            "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 10.0,
        }]

    acc.seed("ZZT", _payload(base - 86_400.0))  # two-sessions-stale seed
    assert acc.get_bars("ZZT")[-1].ts == newest_ts, "stale seed replaced newer bars"

    acc.seed("ZZT", _payload(base + 3_600.0))  # newer seed still refreshes
    assert acc.get_bars("ZZT")[-1].ts == base + 3_600.0


def test_rc168_multi_minute_volume_delta_is_not_charged_to_one_bar():
    """RC-168 ROOT: totalVolume is CUMULATIVE, so a delta between two readings covers the whole
    span between them. Without a staleness bound, a ticker that went unpolled for minutes (42
    symbol rotation, stalled poll, mid-session restart) dumped its entire multi-minute delta
    into whichever ONE bar was open — MEASURED as a 40x spike rate against the vendor's own 1m
    bars for the same name. Past the bound the span is unknowable, so the bar must record NO
    volume rather than a fabricated minute."""
    from server import _CandleAccumulator

    acc = _CandleAccumulator(bar_seconds=60, max_bars=500)
    base = 1_800_000_000.0
    # normal polling cadence: consecutive readings inside the bound are attributed in full
    acc.tick("ZZV", 100.0, base, total_volume=1_000.0)
    acc.tick("ZZV", 100.5, base + 2.0, total_volume=1_600.0)
    cur = acc._current["ZZV"]
    assert cur["v"] == 600.0, "a normal-cadence delta must still be counted"

    # a long gap (ticker unpolled for 10 minutes) must NOT charge 10 minutes to this bar
    acc2 = _CandleAccumulator(bar_seconds=60, max_bars=500)
    acc2.tick("ZZG", 100.0, base, total_volume=1_000.0)
    acc2.tick("ZZG", 101.0, base + 600.0, total_volume=25_000_000.0)
    cur2 = acc2._current["ZZG"]
    assert cur2["v"] is None, (
        f"a 10-minute cumulative delta was attributed to one bar (v={cur2['v']!r}) — this is "
        f"the RC-168 spike mechanism"
    )
    assert cur2["volume_source"] == "schwab_quote_totalVolume_gap_unattributable"

    # the session reset (counter drops) keeps its own honest handling
    acc3 = _CandleAccumulator(bar_seconds=60, max_bars=500)
    acc3.tick("ZZR", 100.0, base, total_volume=9_000.0)
    acc3.tick("ZZR", 100.0, base + 2.0, total_volume=10.0)
    assert acc3._current["ZZR"]["volume_source"] == "schwab_quote_totalVolume_session_reset"


def test_candle_accumulator_seed_refresh_allowed_at_equal_ts():
    """Equal-newest-ts payloads refresh (pricehistory OHLCV beats sparse tick bars)."""
    from server import _CandleAccumulator

    acc = _CandleAccumulator(bar_seconds=60, max_bars=500)
    base = 1_800_000_000.0
    acc.tick("ZZE", 100.0, base)
    acc.tick("ZZE", 101.0, base + 60.0)
    bar_ts = acc.get_bars("ZZE")[-1].ts
    acc.seed("ZZE", [{
        "datetime": bar_ts * 1000.0,
        "open": 99.0, "high": 105.0, "low": 98.0, "close": 104.0, "volume": 500.0,
    }])
    got = acc.get_bars("ZZE")[-1]
    assert got.ts == bar_ts and got.high == 105.0  # refreshed from payload


def test_safe_get_price_history_passes_explicit_end_anchor(monkeypatch):
    """The seed request must anchor its window to now (endDate explicit, not implicit)."""
    import time as _time

    import schwab_client as sc

    monkeypatch.setattr(sc, "_block_live_schwab_in_ci_offline", lambda: None)
    captured: dict = {}

    class _FakeClient:
        def get_price_history(self, symbol, **kw):
            captured.update(kw)
            captured["symbol"] = symbol

            class _R:
                status_code = 200

            return _R()

    t0 = _time.time()
    sc.safe_get_price_history(_FakeClient(), "ZZT", frequency_minutes=1, period_days=1)
    end_dt = captured.get("end_datetime")
    assert end_dt is not None, "end_datetime anchor missing from pricehistory request"
    assert abs(end_dt.timestamp() - t0) < 60.0
    assert captured["symbol"] == "ZZT"
