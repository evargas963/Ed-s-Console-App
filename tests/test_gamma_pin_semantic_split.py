"""RC-429 — snapshots.gamma_pin is two quantities across time; analyses must not mix them.

Writer land is commit 95a61031 (2026-08-19T14:10:58Z): persist switched from
getattr(consensus_summary, "gamma_pin") (selected-expiry net-GEX peak) to
terrain_cache_get / pick_pin_and_strength (total-gamma pin). Historical values
are not rewritten. Research: tests/test_institutional_key_levels.py
test_net_gex_peak_uses_net_gex_when_dollarized (743.0 vs 745.0 on the SPY 0DTE
fixture) and math_exposure_core.py pick_pin_and_strength vs pick_net_gex_peak_strike.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from time_et import (
    GAMMA_PIN_SEMANTIC_MIXED,
    GAMMA_PIN_SEMANTIC_NET_GEX_PEAK,
    GAMMA_PIN_SEMANTIC_TERRAIN,
    GAMMA_PIN_SEMANTIC_UNKNOWN,
    SNAPSHOTS_GAMMA_PIN_RESTART_PAD_SEC,
    SNAPSHOTS_GAMMA_PIN_TERRAIN_ANALYSIS_TS_UTC,
    SNAPSHOTS_GAMMA_PIN_WRITER_LAND_ISO_UTC,
    SNAPSHOTS_GAMMA_PIN_WRITER_LAND_TS_UTC,
    snapshots_gamma_pin_is_terrain_analysis_safe,
    snapshots_gamma_pin_semantic,
)

REPO = Path(__file__).resolve().parent.parent
REQUIRED = "SNAPSHOTS_GAMMA_PIN_TERRAIN_ANALYSIS_TS_UTC"
HELPER = "snapshots_gamma_pin_is_terrain_analysis_safe"
SEMANTIC_FN = "snapshots_gamma_pin_semantic"

_SELECT_PIN = re.compile(
    r"SELECT[\s\S]{0,1200}gamma_pin[\s\S]{0,1200}FROM\s+snapshots\b",
    re.IGNORECASE,
)

PIN_STUDIES = (
    "tools/study_pin_residence_v1.py",
    "tools/study_pin_regime_cut_v1.py",
    "tools/study_pin_direction_v1.py",
    "tools/study_pin_charm_v1.py",
)


def snapshot_gamma_pin_sql_without_era_split(src: str) -> bool:
    """True when SQL reads snapshots.gamma_pin without naming the era split."""
    if not _SELECT_PIN.search(src):
        return False
    return REQUIRED not in src and HELPER not in src and SEMANTIC_FN not in src


def test_writer_land_matches_rc292_commit_iso():
    assert SNAPSHOTS_GAMMA_PIN_WRITER_LAND_ISO_UTC == "2026-08-19T14:10:58+00:00"
    land = datetime.fromisoformat(SNAPSHOTS_GAMMA_PIN_WRITER_LAND_ISO_UTC)
    assert land.tzinfo is not None
    assert land.timestamp() == SNAPSHOTS_GAMMA_PIN_WRITER_LAND_TS_UTC
    assert SNAPSHOTS_GAMMA_PIN_RESTART_PAD_SEC == 3600.0
    assert SNAPSHOTS_GAMMA_PIN_TERRAIN_ANALYSIS_TS_UTC == (
        SNAPSHOTS_GAMMA_PIN_WRITER_LAND_TS_UTC + 3600.0
    )


def test_semantic_buckets_do_not_overlap():
    land = SNAPSHOTS_GAMMA_PIN_WRITER_LAND_TS_UTC
    pad = SNAPSHOTS_GAMMA_PIN_TERRAIN_ANALYSIS_TS_UTC
    assert snapshots_gamma_pin_semantic(land - 1) == GAMMA_PIN_SEMANTIC_NET_GEX_PEAK
    assert snapshots_gamma_pin_semantic(land) == GAMMA_PIN_SEMANTIC_MIXED
    assert snapshots_gamma_pin_semantic(pad - 1) == GAMMA_PIN_SEMANTIC_MIXED
    assert snapshots_gamma_pin_semantic(pad) == GAMMA_PIN_SEMANTIC_TERRAIN
    assert snapshots_gamma_pin_semantic(None) == GAMMA_PIN_SEMANTIC_UNKNOWN
    assert snapshots_gamma_pin_semantic("") == GAMMA_PIN_SEMANTIC_UNKNOWN
    assert snapshots_gamma_pin_is_terrain_analysis_safe(land - 1) is False
    assert snapshots_gamma_pin_is_terrain_analysis_safe(land) is False
    assert snapshots_gamma_pin_is_terrain_analysis_safe(pad) is True
    iso_old = datetime.fromtimestamp(land - 10, tz=timezone.utc).isoformat()
    assert snapshots_gamma_pin_semantic(iso_old) == GAMMA_PIN_SEMANTIC_NET_GEX_PEAK


def test_mixed_era_rows_cannot_form_one_gamma_pin_series():
    land = SNAPSHOTS_GAMMA_PIN_WRITER_LAND_TS_UTC
    pad = SNAPSHOTS_GAMMA_PIN_TERRAIN_ANALYSIS_TS_UTC
    rows = (
        (land - 10, 743.0),
        (land + 10, 744.0),
        (pad + 10, 745.0),
    )
    by_sem: dict[str, list[float]] = {}
    for ts, val in rows:
        by_sem.setdefault(snapshots_gamma_pin_semantic(ts), []).append(val)
    assert by_sem[GAMMA_PIN_SEMANTIC_NET_GEX_PEAK] == [743.0]
    assert by_sem[GAMMA_PIN_SEMANTIC_MIXED] == [744.0]
    assert by_sem[GAMMA_PIN_SEMANTIC_TERRAIN] == [745.0]
    joined = [v for vals in by_sem.values() for v in vals]
    assert joined == [743.0, 744.0, 745.0]
    assert len(by_sem) == 3, "one GAMMA_PIN label cannot span the three persist eras"


def test_injected_unsplit_select_is_caught():
    bad = (
        "rows = con.execute('''SELECT ticker, ts_utc, gamma_pin "
        "FROM snapshots WHERE gamma_pin IS NOT NULL''')"
    )
    assert snapshot_gamma_pin_sql_without_era_split(bad) is True
    good_sql = (
        "from time_et import SNAPSHOTS_GAMMA_PIN_TERRAIN_ANALYSIS_TS_UTC\n"
        "SELECT gamma_pin FROM snapshots WHERE ts_utc >= "
        "SNAPSHOTS_GAMMA_PIN_TERRAIN_ANALYSIS_TS_UTC"
    )
    assert snapshot_gamma_pin_sql_without_era_split(good_sql) is False
    good_helper = (
        "from time_et import snapshots_gamma_pin_is_terrain_analysis_safe\n"
        "SELECT ticker, ts_utc, gamma_pin FROM snapshots WHERE spot IS NOT NULL"
    )
    assert snapshot_gamma_pin_sql_without_era_split(good_helper) is False


def test_pin_studies_and_snapshot_sql_readers_split_eras():
    offenders: list[str] = []
    for rel in PIN_STUDIES:
        src = (REPO / rel).read_text(encoding="utf-8")
        if snapshot_gamma_pin_sql_without_era_split(src):
            offenders.append(rel)
        assert REQUIRED in src or HELPER in src
    roots = [REPO / "tools", REPO / "research"]
    for root in roots:
        if not root.is_dir():
            continue
        for path in root.rglob("*.py"):
            rel = str(path.relative_to(REPO)).replace("\\", "/")
            src = path.read_text(encoding="utf-8", errors="replace")
            if snapshot_gamma_pin_sql_without_era_split(src):
                offenders.append(rel)
    assert offenders == [], (
        "snapshots.gamma_pin SQL readers must name the RC-429 era split: " + ", ".join(offenders)
    )


def test_training_does_not_consume_snapshots_gamma_pin_column():
    ml = (REPO / "ml_train.py").read_text(encoding="utf-8")
    wall = ml.split("WALL_DISTANCE_COLS = [", 1)[1].split("]", 1)[0]
    all_db = ml.split("ALL_DB_COLS =", 1)[1].split("CATEGORICALS", 1)[0]
    assert "gamma_pin" not in wall
    assert "gamma_pin" not in all_db
    assert '"gamma_pin"' not in ml.split("NUMERIC_FEATURES", 1)[0]


def test_live_persist_stays_terrain_ssot_not_consensus_net():
    src = (REPO / "server.py").read_text(encoding="utf-8")
    assert "gamma_pin=_ssot_gamma_pin" in src
    assert 'getattr(consensus_summary, "gamma_pin"' not in src


def test_oi_vanna_dist_slots_remain_in_artifacts():
    """F4 retrain/requalification: do not drop withheld dist_* schema slots."""
    withheld = (
        "dist_call_oi_wall",
        "dist_put_oi_wall",
        "dist_call_vanna_wall",
        "dist_put_vanna_wall",
    )
    ml = (REPO / "ml_train.py").read_text(encoding="utf-8")
    wall_block = ml.split("WALL_DISTANCE_COLS = [", 1)[1].split("]", 1)[0]
    for col in withheld:
        assert f'"{col}"' in wall_block
