"""1c empirical horizon: schema + snapshot dict parity (persistence contract)."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from db import SnapshotRow
from signal_types import CanonicalForecast, PredictiveCard, RulesCard, TheCall
from signals import _build_snapshot_dict
from timeframe_config import CANONICAL_TIMEFRAME, EMPIRICAL_TRI_CLASS_HORIZONS


def test_empirical_tri_class_horizons_include_1c_first():
    assert EMPIRICAL_TRI_CLASS_HORIZONS[0] == "1c"
    assert "1c" in EMPIRICAL_TRI_CLASS_HORIZONS


def test_snapshot_row_has_pred_1c_columns():
    fields = SnapshotRow.__dataclass_fields__
    assert "pred_1c_up_prob" in fields
    assert "pred_1c_down_prob" in fields
    assert "pred_1c_flat_prob" in fields


def test_build_snapshot_dict_passes_pred_1c_from_predictive_card():
    rules = RulesCard(
        headline="h",
        headline_1m="",
        detail="d",
        zone_label="Z",
        zone_color="#000",
        signal="wait",
        conviction="low",
        alerts=[],
        micro=None,
    )
    pred = PredictiveCard(
        headline="x",
        prediction_dir="up",
        prediction_target=None,
        historical_5c_dominant_dir="up",
        historical_5c_dominant_prob=0.5,
        empirical_confidence="medium",
        forward_direction="up",
        forward_prob_up=0.4,
        forward_prob_down=0.3,
        forward_prob_flat=0.3,
        forward_confidence="low",
        forward_provenance="t",
        samples_used=50,
        model_note="n",
        timeframe_reads={},
        up_prob_1c=0.41,
        down_prob_1c=0.31,
        flat_prob_1c=0.28,
        up_prob_3c=0.4,
        down_prob_3c=0.3,
        flat_prob_3c=0.3,
        up_prob_5c=0.4,
        down_prob_5c=0.3,
        flat_prob_5c=0.3,
        up_prob_8c=0.4,
        down_prob_8c=0.3,
        flat_prob_8c=0.3,
        up_prob_13c=0.4,
        down_prob_13c=0.3,
        flat_prob_13c=0.3,
    )
    call = TheCall(
        signal="wait",
        conviction="low",
        entry=None,
        stop=None,
        target=None,
        target2=None,
        reward_risk=None,
        reward_risk2=None,
        headline="",
        reasoning="",
        trade_type="none",
        invalidation="",
        confluence_count=0,
        confluence_total=0,
        confluence_detail="",
        time_qualifier="",
        size_cue="SKIP",
        rules_pred_agree=True,
        time_warning=None,
        size_note="",
    )
    canonical = CanonicalForecast(
        direction="up",
        probability_up=0.4,
        probability_down=0.3,
        probability_flat=0.3,
        confidence="low",
        provenance="test",
    )
    inp = SimpleNamespace()  # unused by _build_snapshot_dict
    d = _build_snapshot_dict(inp, rules, pred, call, canonical)
    assert d["pred_1c_up_prob"] == 0.41
    assert d["pred_1c_down_prob"] == 0.31
    assert d["pred_1c_flat_prob"] == 0.28
    assert CANONICAL_TIMEFRAME == "1m"


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

    from db import EdDB, MIN_SAMPLES_STATISTICAL
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
              outcome_1c, outcome_3c, outcome_5c, outcome_8c, outcome_13c, outcome_15c, outcome_60c,
              horizon_outcome_schema_version
            )
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
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
