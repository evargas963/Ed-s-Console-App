from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from db import EdDB
from similarity_feature_search import (
    analyze_baseline_feature_outcome_divergence,
    run_staged_shadow_search,
    synthesize_per_feature_recommendations,
)
from similarity_feature_universe import (
    build_feature_universe_inventory_v1,
    sqlite_snapshot_column_names,
)
from timeframe_config import CANONICAL_TIMEFRAME


def _seed_rows(conn, ticker: str, zone: str, n: int, base_ts: float) -> None:
    for i in range(n):
        conn.execute(
            """
            INSERT INTO snapshots (
              ticker, timeframe, ts_utc, ts_et, spot, zone, vwap_side,
              nearest_above_dist, nearest_below_dist, regime_primary, session_bucket, vix_bucket,
              outcome_1c, outcome_3c, outcome_5c, outcome_8c, outcome_13c, outcome_15c, outcome_60c,
              horizon_outcome_schema_version
            )
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                ticker,
                CANONICAL_TIMEFRAME,
                base_ts + i * 60,
                "t",
                100.0,
                zone if i % 2 == 0 else "pin_bull",
                "above" if i % 3 else "below",
                1.0 if i % 2 == 0 else 2.5,
                1.0 if i % 2 == 0 else 2.5,
                "pinning" if i % 2 == 0 else "trend_continuation",
                "morning" if i % 2 == 0 else "midday",
                "vix_normal" if i % 2 == 0 else "vix_elevated",
                "up",
                "up",
                "up",
                "up",
                "up",
                "up" if i % 2 == 0 else "down",
                "up",
                3,
            ),
        )


def test_feature_universe_inventory_reproducible_and_partitioned(tmp_path):
    db = EdDB(tmp_path / "inv.db")
    cols = sqlite_snapshot_column_names(db)
    a = build_feature_universe_inventory_v1(sqlite_columns=cols)
    b = build_feature_universe_inventory_v1(sqlite_columns=cols)

    assert a == b
    assert a["schema"] == "similarity_feature_universe_inventory_v1"
    parts = a["partitions"]
    assert "CURRENT_BASELINE_FEATURES" in parts
    assert "HISTORICALLY_USABLE_CANDIDATES" in parts
    assert "LIVE_ONLY_OR_NOT_REPLAY_SAFE" in parts
    assert "EXCLUDED_WITH_REASON" in parts

    baseline = set(parts["CURRENT_BASELINE_FEATURES"])
    assert {"zone", "vwap_side", "nearest_above_dist", "nearest_below_dist"}.issubset(baseline)
    assert {"ticker", "timeframe", "outcome_1c"}.issubset(baseline)


def test_staged_search_structured_and_deterministic(tmp_path):
    db = EdDB(tmp_path / "search.db")
    with db._connect() as conn:
        _seed_rows(conn, "ZZ", "pin_neutral", 120, 2_000_000_000.0)
        conn.commit()

    kwargs = dict(
        db=db,
        ticker="ZZ",
        timeframe=CANONICAL_TIMEFRAME,
        zone="pin_neutral",
        vwap_side="above",
        nearest_above_dist=1.0,
        nearest_below_dist=1.0,
        n_similar=60,
        candidate_pool_cap=500,
        anchor_overlay={"session_bucket": "morning", "vix_bucket": "vix_normal"},
        extra_soft_candidates=["session_bucket", "vix_bucket", "not_allowlisted"],
    )
    a = run_staged_shadow_search(**kwargs)
    b = run_staged_shadow_search(**kwargs)

    assert a == b
    assert a["schema"] == "similarity_feature_staged_search_v1"
    assert a["production_authority_note"] == "shadow only — get_similar_setups unchanged"
    assert a["trial_count"] == len(a["trials"])
    assert len(a["top_robust_tier_stop_viable"]) <= 12


def test_divergence_and_synthesis_structured(tmp_path):
    db = EdDB(tmp_path / "div.db")
    with db._connect() as conn:
        _seed_rows(conn, "DV", "pin_neutral", 80, 2_100_000_000.0)
        conn.commit()

    div = analyze_baseline_feature_outcome_divergence(
        db,
        ticker="DV",
        timeframe=CANONICAL_TIMEFRAME,
        min_group_size=6,
    )
    assert div["schema"] == "similarity_baseline_divergence_v1"
    assert "ambiguous_baseline_groups" in div

    inv = build_feature_universe_inventory_v1(sqlite_columns=sqlite_snapshot_column_names(db))
    staged = run_staged_shadow_search(
        db,
        ticker="DV",
        timeframe=CANONICAL_TIMEFRAME,
        zone="pin_neutral",
        vwap_side="above",
        nearest_above_dist=1.0,
        nearest_below_dist=1.0,
        n_similar=50,
        candidate_pool_cap=500,
        anchor_overlay={"session_bucket": "morning"},
        extra_soft_candidates=["session_bucket"],
    )
    synth = synthesize_per_feature_recommendations(inv["partitions"], staged, div)
    assert synth["schema"] == "similarity_per_feature_recommendations_v1"
    assert any(r["feature_name"] == "zone" for r in synth["recommendations"])
