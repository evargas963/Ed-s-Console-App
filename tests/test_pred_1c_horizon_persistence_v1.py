"""1c empirical horizon: schema + snapshot dict parity (persistence contract)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from db import SnapshotRow
from timeframe_config import (
    CANONICAL_TIMEFRAME,
)




def test_snapshot_row_has_pred_1c_columns():
    fields = SnapshotRow.__dataclass_fields__
    assert "pred_1c_up_prob" in fields
    assert "pred_1c_down_prob" in fields
    assert "pred_1c_flat_prob" in fields




def test_server_snapshot_kwargs_includes_pred_1c_assignment():
    """Guard: server _snapshot_kwargs must wire ms.up_prob_1c → pred_1c_* (grep-level contract)."""
    from pathlib import Path

    text = Path(ROOT / "server.py").read_text(encoding="utf-8")
    assert "pred_1c_up_prob=ms.up_prob_1c" in text
    assert "pred_1c_down_prob=ms.down_prob_1c" in text
    assert "pred_1c_flat_prob=ms.flat_prob_1c" in text


def test_empirical_backfill_sets_pred_1c_when_similar_pool_sufficient(tmp_path):
    """End-to-end empirical path: similar-set + outcome_1c histogram → persisted pred_1c_*."""
    import sqlite3

    from db import EdDB
    from math_probabilities import MIN_SAMPLES_STATISTICAL
    from prediction_engine import _literal_empirical_horizon, _tri_probs

    dbp = tmp_path / "pred1c.db"
    db = EdDB(dbp)
    base_ts = 1_730_000_000.0
    zone = "pred1c_zone"
    vwap_side = "above"
    nad = 1.0
    nbd = 1.0

    def _insert(conn, ts: float) -> None:
        conn.execute(
            """
            INSERT INTO snapshots (
              ticker, timeframe, ts_utc, ts_et, spot, zone, vwap_side,
              nearest_above_dist, nearest_below_dist,
              outcome_1c, outcome_5c, outcome_15c, outcome_60c,
              horizon_outcome_schema_version
            )
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                "SPY",
                CANONICAL_TIMEFRAME,
                ts,
                "test",
                450.0,
                zone,
                vwap_side,
                nad,
                nbd,
                "up",
                "up",
                "up",
                "up",
                3,
            ),
        )

    need = MIN_SAMPLES_STATISTICAL + 5
    with db._connect() as conn:
        for i in range(need):
            _insert(conn, base_ts + i * 60.0)
        conn.commit()

    target_ts = base_ts + need * 60.0
    with db._connect() as conn:
        _insert(conn, target_ts)
        conn.commit()
        sid = int(conn.execute("SELECT snapshot_id FROM snapshots WHERE ts_utc = ?", (target_ts,)).fetchone()[0])

    similar = db.get_similar_setups(
        "SPY",
        CANONICAL_TIMEFRAME,
        zone,
        vwap_side,
        nad,
        nbd,
        as_of_ts_utc=target_ts,
    )
    probs, _src, _note, n_lab = _literal_empirical_horizon(similar, "outcome_1c", 1)
    assert probs is not None
    assert n_lab >= MIN_SAMPLES_STATISTICAL
    u, d, f = _tri_probs(probs)
    assert u is not None

    with db._connect() as conn:
        conn.execute(
            """
            UPDATE snapshots
            SET pred_1c_up_prob = ?, pred_1c_down_prob = ?, pred_1c_flat_prob = ?
            WHERE snapshot_id = ?
            """,
            (u, d, f, sid),
        )
        conn.commit()
        row = conn.execute(
            "SELECT pred_1c_up_prob, pred_1c_down_prob, pred_1c_flat_prob FROM snapshots WHERE snapshot_id = ?",
            (sid,),
        ).fetchone()
    assert row[0] is not None and row[1] is not None and row[2] is not None

    n_nonnull = sqlite3.connect(str(dbp)).execute(
        "SELECT COUNT(*) FROM snapshots WHERE pred_1c_up_prob IS NOT NULL"
    ).fetchone()[0]
    assert n_nonnull >= 1
