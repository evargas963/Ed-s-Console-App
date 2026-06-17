"""Action 12.12: similar_setup_filters must not fabricate 'unknown' SQL keys."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from db import EdDB, MIN_SAMPLES_STATISTICAL
from features.fusion_model_input import similar_setup_filters_from_canonical_features
from timeframe_config import CANONICAL_TIMEFRAME


def test_similar_filters_pass_none_when_zone_missing():
    f = similar_setup_filters_from_canonical_features(
        {"structure.zone": None, "anchor.vwap_side": "above"}
    )
    assert f["zone"] is None
    assert f["zone_fallback"] is True
    assert f["vwap_side"] == "above"


def test_similar_filters_pass_none_when_vwap_side_missing():
    f = similar_setup_filters_from_canonical_features(
        {"structure.zone": "pin_neutral", "anchor.vwap_side": None}
    )
    assert f["vwap_side"] is None
    assert f["vwap_side_fallback"] is True
    assert f["zone"] == "pin_neutral"


def _insert_row(conn, *, ts: float, zone: str, vwap_side: str):
    conn.execute(
        """
        INSERT INTO snapshots (
          ticker, timeframe, ts_utc, ts_et, spot, zone, vwap_side,
          nearest_above_dist, nearest_below_dist,
          outcome_1c, outcome_5c, outcome_15c,
          horizon_outcome_schema_version
        )
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            "SPY",
            CANONICAL_TIMEFRAME,
            ts,
            "test",
            450.0,
            zone,
            vwap_side,
            1.0,
            1.0,
            "up",
            "up",
            "up",
            3,
        ),
    )


def test_get_similar_setups_starts_tier4_when_vwap_side_none(tmp_path):
    """Missing vwap_side skips tiers 1–3 (no zone='unknown' string match)."""
    db = EdDB(tmp_path / "a12_12_vwap.db")
    base = 1_730_000_000.0
    with db._connect() as conn:
        for i in range(MIN_SAMPLES_STATISTICAL):
            _insert_row(conn, ts=base + i, zone="a12_zone", vwap_side="above")
        for i in range(MIN_SAMPLES_STATISTICAL):
            _insert_row(conn, ts=base + 10_000 + i, zone="a12_zone", vwap_side="below")
        conn.commit()

    similar, tr = db.get_similar_setups(
        ticker="SPY",
        timeframe=CANONICAL_TIMEFRAME,
        zone="a12_zone",
        vwap_side=None,
        nearest_above_dist=50.0,
        nearest_below_dist=50.0,
        return_trace=True,
    )
    assert tr["chosen_tier"] == 4
    assert len(similar) == MIN_SAMPLES_STATISTICAL * 2


def test_get_similar_setups_starts_tier5_when_zone_none(tmp_path):
    db = EdDB(tmp_path / "a12_12_zone.db")
    base = 1_731_000_000.0
    with db._connect() as conn:
        for i in range(MIN_SAMPLES_STATISTICAL):
            _insert_row(conn, ts=base + i, zone="other_zone", vwap_side="above")
        conn.commit()

    similar, tr = db.get_similar_setups(
        ticker="SPY",
        timeframe=CANONICAL_TIMEFRAME,
        zone=None,
        vwap_side="above",
        nearest_above_dist=None,
        nearest_below_dist=None,
        return_trace=True,
    )
    assert tr["chosen_tier"] == 5
    assert len(similar) >= MIN_SAMPLES_STATISTICAL
