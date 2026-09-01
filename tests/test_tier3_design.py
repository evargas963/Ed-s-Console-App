"""
Tier 3 design artifacts — shadow / documentation only; production similarity unchanged.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from db import EdDB
from similarity_audit import baseline_feature_contract_v1, contract_expected_structural_filter_keys
from tier3_design import (
    build_final_tier_architecture_proposal_v1,
    build_tier3_candidate_inventory_v1,
    build_tier3_design_comparison_v1,
    build_tier3_feature_decisions_v1,
    run_tier3_context_probe,
)
from timeframe_config import CANONICAL_TIMEFRAME


def _seed_ctx(conn, *, ticker: str, zone: str, vs: str, ts: float, rp: str, vb: str, ms: str) -> None:
    conn.execute(
        """
        INSERT INTO snapshots (
          ticker, timeframe, ts_utc, ts_et, et_hour, et_minute, market_session, spot,
          zone, vwap_side, nearest_above_dist, nearest_below_dist,
          regime_primary, vix_bucket,
          outcome_1c, outcome_5c, outcome_15c, outcome_60c,
          horizon_outcome_schema_version
        )
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            ticker,
            CANONICAL_TIMEFRAME,
            ts,
            "t",
            10,
            30,
            ms,
            100.0,
            zone,
            vs,
            1.0,
            1.0,
            rp,
            vb,
            "up",
            "up",
            "up",
            "up",
            3,
        ),
    )


def test_tier3_inventory_reproducible_and_structured():
    a = build_tier3_candidate_inventory_v1()
    b = build_tier3_candidate_inventory_v1()
    assert a == b
    assert a["schema"] == "tier3_context_candidate_inventory_v1"
    g = {c["snapshot_columns"][0] for c in a["candidates"]}
    assert "regime_primary" in g
    assert any(
        c.get("ticker_specific_proxy") and c["snapshot_columns"][0] == "iwm_risk_regime"
        for c in a["candidates"]
    )


def test_tier3_proxy_abstraction_flags():
    inv = build_tier3_candidate_inventory_v1()
    iwm = next(c for c in inv["candidates"] if c["snapshot_columns"][0] == "iwm_risk_regime")
    assert iwm["generalized_name"] == "risk_regime_small_cap_proxy"
    assert iwm["must_abstract_before_universal_use"] is True
    dec = build_tier3_feature_decisions_v1()
    assert "iwm_risk_regime" in dec["proxy_features_do_not_universalize"]


def test_tier3_decisions_and_architecture_machine_readable():
    d = build_tier3_feature_decisions_v1()
    assert d["schema"] == "tier3_feature_decisions_v1"
    assert d["strong_tier3_shadow_members"]
    arch = build_final_tier_architecture_proposal_v1()
    assert arch["schema"] == "tier3_architecture_proposal_v1"
    assert arch["tier3_exists"] is True
    t3 = arch["tiers"]["Tier 3"]["generalized_features"]
    assert any(x["column"] == "regime_primary" for x in t3)


def test_tier3_design_comparison_has_recommendation():
    c = build_tier3_design_comparison_v1()
    assert c["schema"] == "tier3_design_comparison_v1"
    assert c["recommended_option_id"] == "tier3_hybrid_gate_score"


def test_tier3_context_probe_deterministic(tmp_path):
    db = EdDB(tmp_path / "t3.db")
    t0 = 4_000_000_000.0
    with db._connect() as c:
        for i in range(25):
            _seed_ctx(
                c,
                ticker="T3",
                zone="pin_bull",
                vs="above",
                ts=t0 + i * 60,
                rp="pinning",
                vb="vix_normal",
                ms="rth",
            )
        c.commit()
    anchors = [
        {
            "anchor_id": "T3_test",
            "ticker": "T3",
            "timeframe": CANONICAL_TIMEFRAME,
            "zone": "pin_bull",
            "vwap_side": "above",
            "nearest_above_dist": 1.0,
            "nearest_below_dist": 1.0,
        }
    ]
    r1 = run_tier3_context_probe(db, anchors=anchors, tier3_column="regime_primary", n_similar=15)
    r2 = run_tier3_context_probe(db, anchors=anchors, tier3_column="regime_primary", n_similar=15)
    assert r1 == r2
    assert r1["schema"] == "tier3_context_probe_v1"
    assert r1["per_anchor"][0]["skipped"] is False


def test_issue19_tier1_tier2_contract_unchanged():
    doc = baseline_feature_contract_v1()
    assert doc["production_authority"] == "db.EdDB.get_similar_setups"
    assert contract_expected_structural_filter_keys(1) == {"zone", "vwap_side", "nearest_above_dist", "nearest_below_dist"}
    assert "nearest_above_dist" in contract_expected_structural_filter_keys(2)


def test_eddb_has_unchanged_similarity_authority():
    import inspect

    from db import EdDB

    src = inspect.getsource(EdDB.get_similar_setups)
    assert "def get_similar_setups" in src
    # TEST_SYSTEM_REHAB_V2: was `"similarity_tier_stop_viable" in src or "tier_stop" in
    # src` -- "tier_stop" is a bare substring of "similarity_tier_stop_viable", so if
    # the real field were renamed away, an incidental "tier_stop" occurrence anywhere
    # (a comment, an unrelated variable) would still satisfy the OR and hide exactly
    # the "unchanged similarity authority" regression this test claims to catch.
    assert "similarity_tier_stop_viable" in src
