"""
Adaptive Shadow v2 — strict tier-1 pool + Tier 3 context scoring (shadow only).
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from adaptive_shadow_v2_calibration import run_calibration_v1
from adaptive_similarity_engine import (
    ADAPTIVE_SHADOW_V2_TIER3_COLUMNS,
    TIER3_WEIGHT_RANGES_V1,
    calibration_weight_profiles_v1,
    default_tier3_mid_weights_v1,
    run_adaptive_shadow_v2,
)
from db import EdDB
from timeframe_config import CANONICAL_TIMEFRAME


def _insert_row(
    conn,
    *,
    ticker: str,
    zone: str,
    vwap_side: str,
    ts: float,
    nad: float,
    nbd: float,
    regime_primary: str,
    vix_bucket: str,
    market_session: str,
    regime_confidence: str,
) -> None:
    conn.execute(
        """
        INSERT INTO snapshots (
          ticker, timeframe, ts_utc, ts_et, et_hour, et_minute, market_session, spot,
          zone, vwap_side, nearest_above_dist, nearest_below_dist,
          regime_primary, vix_bucket, regime_confidence,
          outcome_1c, outcome_3c, outcome_5c, outcome_8c, outcome_13c, outcome_15c, outcome_60c,
          horizon_outcome_schema_version
        )
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            ticker,
            CANONICAL_TIMEFRAME,
            ts,
            "t",
            10,
            30,
            market_session,
            100.0,
            zone,
            vwap_side,
            nad,
            nbd,
            regime_primary,
            vix_bucket,
            regime_confidence,
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


def test_calibration_profiles_bounded_and_deterministic():
    p = calibration_weight_profiles_v1()
    p2 = calibration_weight_profiles_v1()
    assert p == p2
    assert len(p) <= 24
    assert all(set(x["tier3_weights"]) == set(ADAPTIVE_SHADOW_V2_TIER3_COLUMNS) for x in p)


def test_tier1_pool_excludes_wrong_zone(tmp_path):
    db = EdDB(tmp_path / "a2.db")
    t0 = 5_000_000.0
    with db._connect() as c:
        _insert_row(
            c,
            ticker="V2",
            zone="pin_bull",
            vwap_side="above",
            ts=t0,
            nad=1.0,
            nbd=0.5,
            regime_primary="pinning",
            vix_bucket="normal",
            market_session="rth",
            regime_confidence="high",
        )
        _insert_row(
            c,
            ticker="V2",
            zone="breakout",
            vwap_side="above",
            ts=t0 + 60,
            nad=1.0,
            nbd=0.5,
            regime_primary="pinning",
            vix_bucket="normal",
            market_session="rth",
            regime_confidence="high",
        )
        c.commit()

    r = run_adaptive_shadow_v2(
        db,
        ticker="V2",
        timeframe=CANONICAL_TIMEFRAME,
        zone="pin_bull",
        vwap_side="above",
        nearest_above_dist=1.0,
        nearest_below_dist=0.5,
        n_similar=10,
        structural_pool_cap=500,
        anchor_overlay={
            "regime_primary": "pinning",
            "vix_bucket": "normal",
            "market_session": "rth",
            "regime_confidence": "high",
        },
    )
    assert r.candidate_pool_size == 1
    assert r.mode == "adaptive_shadow_v2"


def test_context_score_changes_ranking(tmp_path):
    db = EdDB(tmp_path / "a3.db")
    t0 = 6_000_000.0
    with db._connect() as c:
        # Latest overlay row: regime mismatch for older "pinning" rows — use Gamma for overlay
        _insert_row(
            c,
            ticker="RK",
            zone="pin_bull",
            vwap_side="above",
            ts=t0 + 300,
            nad=1.0,
            nbd=0.5,
            regime_primary="breakout",
            vix_bucket="low",
            market_session="rth",
            regime_confidence="medium",
        )
        _insert_row(
            c,
            ticker="RK",
            zone="pin_bull",
            vwap_side="above",
            ts=t0 + 200,
            nad=1.0,
            nbd=0.5,
            regime_primary="breakout",
            vix_bucket="low",
            market_session="rth",
            regime_confidence="medium",
        )
        _insert_row(
            c,
            ticker="RK",
            zone="pin_bull",
            vwap_side="above",
            ts=t0 + 100,
            nad=1.0,
            nbd=0.5,
            regime_primary="pinning",
            vix_bucket="low",
            market_session="rth",
            regime_confidence="medium",
        )
        c.commit()

    heavy_regime = {k: 0.1 for k in ADAPTIVE_SHADOW_V2_TIER3_COLUMNS}
    heavy_regime["regime_primary"] = 5.0
    r = run_adaptive_shadow_v2(
        db,
        ticker="RK",
        timeframe=CANONICAL_TIMEFRAME,
        zone="pin_bull",
        vwap_side="above",
        nearest_above_dist=1.0,
        nearest_below_dist=0.5,
        n_similar=3,
        structural_pool_cap=500,
        tier3_weights=heavy_regime,
        anchor_overlay={
            "regime_primary": "breakout",
            "vix_bucket": "low",
            "market_session": "rth",
            "regime_confidence": "medium",
        },
    )
    # First selected = highest final score; breakout rows beat pinning with heavy regime weight
    assert r.selected_rows[0].get("regime_primary") == "breakout"
    assert r.scores[0] >= r.scores[-1]


def test_mini_calibration_repeatable(tmp_path):
    db = EdDB(tmp_path / "a4.db")
    t0 = 7_000_000.0
    with db._connect() as c:
        for i in range(15):
            _insert_row(
                c,
                ticker="MC",
                zone="pin_bull",
                vwap_side="above",
                ts=t0 + i * 30,
                nad=1.0,
                nbd=0.5,
                regime_primary="pinning",
                vix_bucket="normal",
                market_session="rth",
                regime_confidence="high",
            )
        c.commit()
    anchors = [
        {
            "anchor_id": "mc1",
            "ticker": "MC",
            "timeframe": CANONICAL_TIMEFRAME,
            "zone": "pin_bull",
            "vwap_side": "above",
            "nearest_above_dist": 1.0,
            "nearest_below_dist": 0.5,
        }
    ]
    profiles = [
        {"config_id": "mid_baseline", "tier3_weights": default_tier3_mid_weights_v1()},
        {
            "config_id": "all_low",
            "tier3_weights": {k: TIER3_WEIGHT_RANGES_V1[k][0] for k in ADAPTIVE_SHADOW_V2_TIER3_COLUMNS},
        },
    ]
    a = run_calibration_v1(
        db,
        anchors=anchors,
        weight_profiles=profiles,
        n_similar=8,
        structural_pool_cap=400,
        include_feature_ablation=False,
    )
    b = run_calibration_v1(
        db,
        anchors=anchors,
        weight_profiles=profiles,
        n_similar=8,
        structural_pool_cap=400,
        include_feature_ablation=False,
    )
    assert a == b
    assert a["schema"] == "adaptive_shadow_v2_calibration_v1"
    assert len(a["per_weight_configuration"]) == 2
    assert "tier1_structural_pool_diagnostics" in a
    assert a.get("tier1_pool_coverage", {}).get("schema") == "tier1_pool_coverage_report_v1"


def test_get_similar_setups_untouched():
    from db import EdDB

    src = inspect.getsource(EdDB.get_similar_setups)
    assert "PROGRESSIVE RELAXATION" in src
    assert "Tier 1: zone + vwap_side + both distance buckets" in src
