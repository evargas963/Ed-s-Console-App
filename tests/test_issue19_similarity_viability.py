"""
Issue 19 — similar-set tier stop must align with empirical MIN_SAMPLES_STATISTICAL per horizon.

Tier 1–2 use distance buckets; using query distances in the 5+ bucket while rows carry
tight distances forces those tiers to return 0 rows so tier 3 vs tier 4 exercises zone/vwap widening.

Proves: insufficient labeled at a tighter tier widens; narrowest viable preserved; honest withhold.
"""
from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from db import (
    EdDB,
)
from math_probabilities import MIN_SAMPLES_STATISTICAL
from timeframe_config import CANONICAL_TIMEFRAME


def _insert_viable_row(
    conn,
    *,
    ticker: str,
    ts: float,
    zone: str,
    vwap_side: str,
    nad: float,
    nbd: float,
    direction: str = "up",
):
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
            ticker,
            CANONICAL_TIMEFRAME,
            ts,
            "test",
            450.0,
            zone,
            vwap_side,
            nad,
            nbd,
            direction,
            direction,
            direction,
            direction,
            3,
        ),
    )


# Distances in 5+ bucket: tier 1/2 SQL will not match rows with nad=1, nbd=1 (0-1 bucket).
_FAR_NAD = 50.0
_FAR_NBD = 50.0




def test_issue19_preserves_narrowest_viable_tier(tmp_path):
    """Only tier 3 pool (40 rows vwap above); must stop at tier 3, not broaden to tier 4."""
    dbp = tmp_path / "i19b.db"
    db = EdDB(dbp)
    base_ts = 1_730_000_000.0
    with db._connect() as conn:
        for i in range(40):
            _insert_viable_row(
                conn,
                ticker="QQQ",
                ts=base_ts + i * 60,
                zone="ix19_narrow_ok",
                vwap_side="below",
                nad=1.0,
                nbd=1.0,
            )
        conn.commit()

    similar, tr = db.get_similar_setups(
        ticker="QQQ",
        timeframe=CANONICAL_TIMEFRAME,
        zone="ix19_narrow_ok",
        vwap_side="below",
        nearest_above_dist=_FAR_NAD,
        nearest_below_dist=_FAR_NBD,
        return_trace=True,
    )
    assert tr["chosen_tier"] == 3
    assert len(similar) == 40
    assert tr["final_empirically_viable"] is True
    assert tr["final_all_tracked_viable"] is True


def _insert_row_tier_stop_only(
    conn,
    *,
    ticker: str,
    ts: float,
    zone: str,
    vwap_side: str,
    nad: float,
    nbd: float,
    outcome_5c: str | None,
    outcome_15c: str | None,
    outcome_60: str | None,
):
    """Primary horizons; None marks unlabeled cells for tier-stop / empirical tests."""
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
            ticker,
            CANONICAL_TIMEFRAME,
            ts,
            "test",
            450.0,
            zone,
            vwap_side,
            nad,
            nbd,
            "up",
            outcome_5c,
            outcome_15c,
            outcome_60,
            3,
        ),
    )






def test_issue19_false_wait_removed_empirical_5c_ok_after_widen(tmp_path):
    from prediction_engine import _literal_empirical_horizon

    dbp = tmp_path / "i19d.db"
    db = EdDB(dbp)
    base_ts = 1_750_000_000.0
    with db._connect() as conn:
        for i in range(25):
            _insert_viable_row(
                conn,
                ticker="SPY",
                ts=base_ts + i * 60,
                zone="ix19_fw",
                vwap_side="above",
                nad=1.0,
                nbd=1.0,
            )
        for j in range(15):
            _insert_viable_row(
                conn,
                ticker="SPY",
                ts=base_ts + 60_000 + j * 60,
                zone="ix19_fw",
                vwap_side="below",
                nad=1.0,
                nbd=1.0,
            )
        conn.commit()

    similar = db.get_similar_setups(
        ticker="SPY",
        timeframe=CANONICAL_TIMEFRAME,
        zone="ix19_fw",
        vwap_side="above",
        nearest_above_dist=_FAR_NAD,
        nearest_below_dist=_FAR_NBD,
    )
    probs, src, _note, n = _literal_empirical_horizon(similar, "outcome_5c", 5)
    assert probs is not None
    assert n >= MIN_SAMPLES_STATISTICAL
    assert "insufficient" not in src


def test_issue19_trace_audit_fields(tmp_path):
    """return_trace exposes labeled_counts and viability per tier."""
    dbp = tmp_path / "i19e.db"
    db = EdDB(dbp)
    with db._connect() as conn:
        for i in range(35):
            _insert_viable_row(
                conn,
                ticker="DIA",
                ts=1_760_000_000.0 + i * 60,
                zone="ix19_trace",
                vwap_side="above",
                nad=1.0,
                nbd=1.0,
            )
        conn.commit()
    _similar, tr = db.get_similar_setups(
        ticker="DIA",
        timeframe=CANONICAL_TIMEFRAME,
        zone="ix19_trace",
        vwap_side="above",
        nearest_above_dist=_FAR_NAD,
        nearest_below_dist=_FAR_NBD,
        return_trace=True,
    )
    assert "MIN_SAMPLES_STATISTICAL" in tr
    assert tr["tier_stop_outcome_columns"] == ["outcome_1c", "outcome_5c", "outcome_15c"]
    assert tr["final_labeled_counts"]["outcome_5c"] >= MIN_SAMPLES_STATISTICAL
    for entry in tr["tiers"]:
        assert "labeled_counts" in entry
        assert "empirically_viable" in entry
        assert "all_tracked_viable" in entry
