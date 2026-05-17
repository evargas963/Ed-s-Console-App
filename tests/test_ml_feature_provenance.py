"""Day 3 — ML feature provenance: per-field lineage, no silent defaults, m5 proxy labeling."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SKIP_DIR_PARTS = frozenset(
    {
        ".git",
        ".claude",
        "__pycache__",
        ".venv",
        "venv",
        "node_modules",
        ".pytest_cache",
        "backups",
        "governance",
        "schwab_field_inventory",
    }
)

VWAP_SIDE_ABOVE_DEFAULT_RE = re.compile(
    r'vwap_side["\']?\s*:\s*vs\s+if\s+vs\s+is\s+not\s+None\s+else\s+["\']above["\']',
    re.IGNORECASE,
)
FEATURE_OR_ABOVE_RE = re.compile(r'\bor\s+["\']above["\']')
FEATURE_OR_ZERO_RE = re.compile(r'\.get\([^)]+,\s*0(?:\.0)?\)\s*or\s*0(?:\.0)?')

SILENT_DEFAULT_ALLOWLIST: tuple[tuple[str, str], ...] = (
    ("tools/", "diagnostic scripts not production feature path"),
    ("tests/", "fixtures may document legacy defaults"),
    ("lstm_data.py", "legacy encoder defaults; Day 4 will add masks at train time"),
    ("features/signal_layer_v1.py", "derived signal layer counters not Schwab leaves"),
    ("features/fusion_policy_contract.py", "fusion policy prob normalization not feature inputs"),
    ("server.py", "non-ML paths outside Day 3 scope"),
    ("training_cache.py", "manifest counters"),
    ("ml_scheduler.py", "scheduler counters"),
    ("calibration/run_production_accumulation_validation.py", "audit counters"),
)


def _iter_repo_py_files() -> list[Path]:
    out: list[Path] = []
    for path in ROOT.rglob("*.py"):
        if set(path.parts) & SKIP_DIR_PARTS:
            continue
        rel = path.relative_to(ROOT).as_posix()
        if rel.startswith("tools/"):
            continue
        out.append(path)
    return out


def _allowlisted(rel_posix: str) -> bool:
    for prefix, _reason in SILENT_DEFAULT_ALLOWLIST:
        if rel_posix == prefix or rel_posix.startswith(prefix):
            return True
    return False


def _repo_wide_pattern_hits(pattern: re.Pattern[str]) -> list[str]:
    hits: list[str] = []
    for path in _iter_repo_py_files():
        rel = path.relative_to(ROOT).as_posix()
        if _allowlisted(rel):
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if line.strip().startswith("#"):
                continue
            if pattern.search(line):
                hits.append(f"{rel}:{lineno}:{line.strip()}")
    return hits


def _minimal_features(**overrides):
    from features.canonical_contract import get_mvp_feature_names

    feats = {k: None for k in get_mvp_feature_names()}
    feats.update(
        {
            "price.spot": 450.0,
            "price.spread_pts": 0.02,
            "structure.zone": "pin_bull",
            "structure.nearest_above_dist": 1.0,
            "structure.nearest_below_dist": -1.0,
            "structure.net_gamma": 0.0,
            "anchor.vwap_side": "above",
            "anchor.vwap_dist_pts": 0.1,
        }
    )
    feats.update(overrides)
    return feats


def test_inference_snapshot_per_field_lineage():
    from features.canonical_contract import get_mvp_feature_names
    from features.inference_snapshot import build_inference_snapshot_v1_from_feature_row

    feats = _minimal_features()
    snap = build_inference_snapshot_v1_from_feature_row(
        ticker="SPY", expiry=None, as_of_ts=1_700_000_000.0, features=feats
    )
    lineage = snap["feature_lineage"]
    for key in get_mvp_feature_names():
        entry = lineage[key]
        assert entry["source"] == snap["source"]
        assert entry["transform"] == "canonical_mvp_adapter"
        assert entry["fallback_flag"] is (feats[key] is None)


def test_fusion_input_vwap_side_unknown_not_above_when_missing():
    from features.fusion_model_input import similar_setup_filters_from_canonical_features

    feats = _minimal_features(**{"anchor.vwap_side": None, "structure.zone": None})
    out = similar_setup_filters_from_canonical_features(feats)
    assert out["vwap_side"] is None
    assert out["zone"] is None
    assert out["vwap_side_fallback"] is True
    assert out["zone_fallback"] is True


def test_fusion_vwap_side_parent_default_above_would_fail_gate():
    """Parent commit used `else \"above\"`; prove missing vwap is not that bucket."""
    from features.fusion_model_input import similar_setup_filters_from_canonical_features

    feats = _minimal_features(**{"anchor.vwap_side": None})
    out = similar_setup_filters_from_canonical_features(feats)
    parent_behavior = "above"
    assert out["vwap_side"] != parent_behavior


def test_lstm_missing_numerics_emit_mask_not_zero():
    from features.canonical_contract import get_mvp_feature_names
    from features.lstm_sequence_input import (
        ZONE_MISSING_ENCODED,
        encode_lstm_structure_bar_with_masks,
    )
    from lstm_data import FEATURES_5M

    cf = {k: None for k in get_mvp_feature_names()}
    cf["price.spot"] = 450.0
    cf["structure.zone"] = None
    cf["anchor.vwap_side"] = None
    cf["structure.net_gamma"] = None
    merged = {
        "spot": 450.0,
        "zone": "pin_neutral",
        "vwap_side": "above",
        "net_gamma": 99.0,
        "vwap_dist_pts": 1.0,
        "candle_body_pts": 0.1,
        "candle_range_pts": 0.2,
        "dist_call_gamma_wall": 1.0,
        "dist_put_gamma_wall": -1.0,
        "dist_gamma_inflection": 0.0,
        "dist_delta_inflection": 0.0,
        "dist_call_oi_wall": 0.0,
        "dist_put_oi_wall": 0.0,
        "spy_chg_pct": 0.0,
        "qqq_chg_pct": 0.0,
        "iwm_chg_pct": 0.0,
        "vix_level": 18.0,
        "iv_level": 0.2,
        "net_delta": 0.0,
        "charm_net": 0.0,
    }
    enc = encode_lstm_structure_bar_with_masks(merged, cf, 450.0)
    masks = enc["canonical_missing_masks"]
    assert masks[0] == 0.0
    assert masks[1] == 0.0
    zi = FEATURES_5M.index("zone")
    assert enc["features"][zi] == ZONE_MISSING_ENCODED


def test_m5_context_labels_proxy_when_1m_asof(monkeypatch, tmp_path):
    import sqlite3

    import pandas as pd

    import ml_data_common as mdc

    db_path = str(tmp_path / "m5.db")
    sqlite3.connect(db_path).close()

    def fake_read_sql_query(query, con, params=None):
        rows = []
        for ts in (100.0, 200.0):
            row: dict = {"ticker": "SPY", "ts_utc": ts}
            for c in mdc.M5_ADDITIVE_SOURCE_COLS:
                row[c] = float(ts)
            rows.append(row)
        return pd.DataFrame(rows)

    monkeypatch.setattr(pd, "read_sql_query", fake_read_sql_query)

    left = pd.DataFrame({"ticker": ["SPY"], "ts_utc": [150.0], "spot": [1.0]})
    out = mdc.attach_5m_additive_context(left, db_path=db_path)
    assert out.iloc[0][mdc.M5_SOURCE_TIMEFRAME_COL] == mdc.M5_SOURCE_TIMEFRAME_1M_ASOF


def test_v2_advisory_backfill_stamps_reconstructed_fields():
    from calibration.v2_advisory_backfill import (
        RECONSTRUCTED_LIVE_MS_SOURCE,
        build_v2_advisory_snapshot,
        ms_dict_from_snapshot_row,
    )

    row = {
        "ticker": "SPY",
        "ts_utc": 1_700_000_000.0,
        "rules_summary": "test headline",
        "replay_context_json": '{"zone": "pin_bull", "vwap_side": "above"}',
    }
    ms = ms_dict_from_snapshot_row(row)
    assert ms["live_ms_reconstruction_source"] == RECONSTRUCTED_LIVE_MS_SOURCE
    assert ms["live_ms_field_sources"]["rules_headline"] == RECONSTRUCTED_LIVE_MS_SOURCE
    payload = build_v2_advisory_snapshot(row)
    assert payload["source"] == RECONSTRUCTED_LIVE_MS_SOURCE
    assert payload["live_ms_field_sources"]["zone"] == RECONSTRUCTED_LIVE_MS_SOURCE


def test_no_silent_default_in_feature_paths_repo_wide():
    above_hits = _repo_wide_pattern_hits(VWAP_SIDE_ABOVE_DEFAULT_RE)
    assert not above_hits, "vwap_side else-above violations:\n" + "\n".join(above_hits[:40])


def test_fusion_model_input_no_vwap_else_above_in_source():
    text = (ROOT / "features" / "fusion_model_input.py").read_text(encoding="utf-8")
    assert 'else "above"' not in text
    assert "else 'above'" not in text


def test_inference_snapshot_parent_missing_lineage_fails():
    from features.canonical_contract import get_mvp_feature_names
    from features.inference_snapshot import _assert_inference_snapshot_v1, _feature_quality_from_row

    feats = _minimal_features()
    snap = {
        "snapshot_type": "InferenceSnapshotV1",
        "feature_contract_version": "v1_1m_mvp",
        "canonical_timeframe": "1m",
        "source": "live_l1_tier_b",
        "features": feats,
        "feature_quality": _feature_quality_from_row(feats),
    }
    with pytest.raises(ValueError, match="feature_lineage"):
        _assert_inference_snapshot_v1(snap)
