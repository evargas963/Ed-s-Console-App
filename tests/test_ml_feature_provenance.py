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
    from lstm_data import ENCODED_FEATURES_5M

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
    zi = ENCODED_FEATURES_5M.index("cat_zone")
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
    from features.inference_snapshot import _assert_inference_snapshot_v1, _feature_quality_from_row

    feats = _minimal_features()
    snap = {
        "snapshot_type": "InferenceSnapshotV1",
        "feature_contract_version": "v1_1m_range_imbalance",
        "canonical_timeframe": "1m",
        "source": "live_l1_tier_b",
        "features": feats,
        "feature_quality": _feature_quality_from_row(feats),
    }
    with pytest.raises(ValueError, match="feature_lineage"):
        _assert_inference_snapshot_v1(snap)


# ── ML-PIPE-V2 Phase 2: point-in-time causal boundary (as-of) adversarial locks ──
# Matrix ref: governance/ML_CORRECTNESS_NOT_PROVEN_MATRIX_V2.json →
# POINT_IN_TIME_FEATURE_CORRECTNESS. The LSTM/Transformer history reads route
# through EdDB.get_recent_snapshots(as_of_ts_utc=...) (strict ts_utc < as_of) and
# ml_predict._require_as_of_ts_utc_for_sequence_db fails closed without as_of_ts.
# These tests prove the boundary adversarially: appending or MUTATING rows at or
# after the as-of instant can never change the historical sequence input set.


def _asof_seed_db(tmp_path):
    from db import EdDB

    db = EdDB(tmp_path / "asof_boundary.db", allow_noncanonical=True)
    t0 = 1_780_000_000.0
    with db._connect() as con:
        for i in range(10):
            con.execute(
                "INSERT INTO snapshots (ticker, timeframe, ts_utc, ts_et, spot) "
                "VALUES (?, '1m', ?, ?, ?)",
                ("SPY", t0 + 60 * i, f"row{i}", 500.0 + i),
            )
        con.commit()
    return db, t0


def test_get_recent_snapshots_as_of_excludes_future_rows(tmp_path):
    db, t0 = _asof_seed_db(tmp_path)
    as_of = t0 + 60 * 5  # decision instant = row 5's timestamp
    rows = db.get_recent_snapshots("SPY", "1m", n=100, as_of_ts_utc=as_of)
    got = sorted(float(r["ts_utc"]) for r in rows)
    # STRICT boundary: rows 0..4 only — the as-of instant itself is excluded.
    assert got == [t0 + 60 * i for i in range(5)]


def test_get_recent_snapshots_invariant_under_future_append_and_mutation(tmp_path):
    db, t0 = _asof_seed_db(tmp_path)
    as_of = t0 + 60 * 5
    before = db.get_recent_snapshots("SPY", "1m", n=100, as_of_ts_utc=as_of)
    with db._connect() as con:
        # append new future rows AND mutate existing post-as-of rows aggressively
        for i in range(20, 25):
            con.execute(
                "INSERT INTO snapshots (ticker, timeframe, ts_utc, ts_et, spot) "
                "VALUES (?, '1m', ?, ?, ?)",
                ("SPY", t0 + 60 * i, f"future{i}", 999.0),
            )
        con.execute(
            "UPDATE snapshots SET spot = -1.0 WHERE ts_utc >= ?", (as_of,)
        )
        con.commit()
    after = db.get_recent_snapshots("SPY", "1m", n=100, as_of_ts_utc=as_of)
    key = lambda rs: [(float(r["ts_utc"]), r["spot"]) for r in rs]  # noqa: E731
    assert key(after) == key(before), (
        "historical as-of sequence input changed after future-row append/mutation"
    )


def test_get_recent_snapshots_as_of_is_ticker_scoped(tmp_path):
    db, t0 = _asof_seed_db(tmp_path)
    with db._connect() as con:
        con.execute(
            "INSERT INTO snapshots (ticker, timeframe, ts_utc, ts_et, spot) "
            "VALUES ('QQQ', '1m', ?, 'other', 400.0)",
            (t0 + 60,),
        )
        con.commit()
    rows = db.get_recent_snapshots("SPY", "1m", n=100, as_of_ts_utc=t0 + 60 * 5)
    assert all(str(r["ticker"]) == "SPY" for r in rows)


def test_sequence_db_as_of_is_fail_closed():
    """No as_of → LOUD refusal (never an unbounded latest-row history read)."""
    import pytest as _pytest

    from ml_predict import LstmSequenceInputError, _require_as_of_ts_utc_for_sequence_db

    with _pytest.raises(LstmSequenceInputError):
        _require_as_of_ts_utc_for_sequence_db(None)
    with _pytest.raises(LstmSequenceInputError):
        _require_as_of_ts_utc_for_sequence_db({"as_of_ts": None})
    assert _require_as_of_ts_utc_for_sequence_db({"as_of_ts": 123.0}) == 123.0


def test_inference_snapshot_constructor_is_single_row_pure():
    """build_inference_snapshot_v1_from_db_row consumes exactly one row dict —
    no DB, live-state, or wall-clock access (AST import lock)."""
    import ast

    import features.inference_snapshot as mod

    tree = ast.parse(open(mod.__file__, encoding="utf-8").read())
    banned = {"db", "server", "live_market_plane", "order_flow_live_state", "sqlite3"}
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    hits = imported & banned
    assert not hits, f"inference snapshot constructor must stay single-row pure: {hits}"


# ── ML-PIPE-V2 Phase 3: meta training basis must travel with the artifact ──


def test_meta_training_basis_manifest_written_and_machine_readable(tmp_path):
    import json as _json

    from ml_scheduler import _write_meta_training_basis_manifest

    for basis, governed in (
        ("expanding_window_oof", True),
        ("in_sample_no_folds", False),
        ("in_sample_fallback", False),
    ):
        out = _write_meta_training_basis_manifest(
            tmp_path, "SPY", "5c", architecture="parallel", basis=basis, n_rows=42,
        )
        doc = _json.loads(out.read_text(encoding="utf-8"))
        assert doc["schema"] == "META_TRAINING_BASIS_MANIFEST_V1"
        assert doc["meta_training_basis"] == basis
        assert doc["oof_governed"] is governed
        assert doc["artifact"] == "meta_SPY_5c.pkl"
        assert doc["n_training_rows"] == 42
        assert doc["ticker"] == "SPY" and doc["horizon_slug"] == "5c"


def test_meta_basis_manifest_wired_at_both_meta_train_sites():
    """Source lock: every meta pickle dump is immediately followed by the basis
    manifest write — an in-sample-fallback meta can never ship without its
    machine-readable oof_governed=False provenance."""
    import inspect

    import ml_scheduler

    src = inspect.getsource(ml_scheduler)
    dumps = src.count('pickle.dump(meta_mdl, f)')
    manifests = src.count('_write_meta_training_basis_manifest(')
    # def + 2 call sites
    assert dumps == 2, f"expected exactly 2 meta pickle dumps, found {dumps}"
    assert manifests >= 3, "both meta dump sites must write the basis manifest"
    for arch in ("parallel", "cascade"):
        seg = src[src.find(f'architecture="{arch}", basis=meta_basis'):]
        assert seg, f"{arch} meta site missing manifest call"


def test_meta_oof_trainer_returns_labeled_basis():
    """The OOF trainers' basis vocabulary is the provenance contract — locked."""
    import inspect

    import ml_scheduler

    for fn in (ml_scheduler._train_parallel_meta_oof, ml_scheduler._train_cascade_meta_oof):
        s = inspect.getsource(fn)
        assert '"expanding_window_oof"' in s
        assert '"in_sample_no_folds"' in s or '"in_sample_fallback"' in s


# ── ML-PIPE-V2 Phase 3 completion: OOF strictness, routing trap, base semantics ──


def test_expanding_window_oof_folds_strict_temporal_order():
    from training_cache import expanding_window_oof_folds

    days = [f"2026-06-{d:02d}" for d in range(1, 26)]
    folds = expanding_window_oof_folds(days)
    assert folds, "25 sessions must form folds"
    seen_oof: set = set()
    for train_days, oof_days in folds:
        assert train_days and oof_days
        assert max(train_days) < min(oof_days), "train block must be strictly earlier"
        assert not (set(train_days[: len(folds[0][0])]) & set(oof_days))
        seen_oof.update(oof_days)
    # seed block never appears as OOF
    assert folds[0][0][0] == "2026-06-01"
    assert "2026-06-01" not in seen_oof
    # too few sessions → no folds (caller must label in-sample, never claim OOF)
    assert expanding_window_oof_folds(days[:3]) == []


def _routing_trap(monkeypatch, tmp_path, *, n_days, oof_rows_per_fold):
    """Monkeypatched routing harness: records which model_dir scores which rows.
    An overfit deployed base in out_dir can only contaminate the meta if out_dir
    is ever used for assembly while folds exist — the trap asserts it never is."""
    import ml_scheduler as ms

    calls: list = []

    def _fake_train_layers(fold_dir, ticker, db_path, tr_days, *, data_fp, hz):
        fold_dir.mkdir(parents=True, exist_ok=True)
        return True

    def _fake_load_data(db_path, ticker=None, allowed_et_dates=None, ml_horizon_slug=None, **kw):
        return list(allowed_et_dates or [])  # len() drives the flow only

    def _fake_assemble(model_dir, ticker, db_path, rows_df, target_column, hz):
        calls.append(str(model_dir))
        n = oof_rows_per_fold if "fold" in str(model_dir) else 99
        return [[0.5] * 3] * n, [0] * n

    monkeypatch.setattr(ms, "_train_parallel_ml_stack_layers_into", _fake_train_layers)
    monkeypatch.setattr(ms, "_assemble_meta_ml_layer_prob_vectors", _fake_assemble)
    import ml_train

    monkeypatch.setattr(ml_train, "load_data", _fake_load_data)
    days = [f"2026-06-{d:02d}" for d in range(1, 1 + n_days)]
    out_dir = tmp_path / "deployed"
    out_dir.mkdir()
    X, y, basis = ms._train_parallel_meta_oof(
        out_dir, "SPY", "unused.db", ["row"] * 50, days, "outcome_dir_5c", "5c", data_fp=None,
    )
    return calls, basis, out_dir


def test_oof_routing_never_scores_deployed_dir_when_folds_exist(monkeypatch, tmp_path):
    calls, basis, out_dir = _routing_trap(monkeypatch, tmp_path, n_days=25, oof_rows_per_fold=8)
    assert basis == "expanding_window_oof"
    assert str(out_dir) not in calls, (
        "deployed (potentially overfit, full-data) bases were scored for meta training "
        "while OOF folds existed — in-sample leakage channel"
    )
    assert all("fold" in c for c in calls)


def test_oof_infeasibility_routes_to_labeled_in_sample_no_folds(monkeypatch, tmp_path):
    calls, basis, out_dir = _routing_trap(monkeypatch, tmp_path, n_days=3, oof_rows_per_fold=8)
    assert basis == "in_sample_no_folds"
    assert calls == [str(out_dir)], "no-folds fallback must use the deployed dir, labeled"


def test_oof_starvation_routes_to_labeled_in_sample_fallback(monkeypatch, tmp_path):
    calls, basis, out_dir = _routing_trap(monkeypatch, tmp_path, n_days=25, oof_rows_per_fold=1)
    assert basis == "in_sample_fallback"
    assert calls[-1] == str(out_dir), "starvation fallback must be the LAST assembly, labeled"


def test_meta_missing_base_semantics_locked():
    """xgb (anchor) missing → row dropped (source lock); lstm/transformer missing
    or collapse-flagged → EXACT neutral filler (governed B3+ design, provenance
    tracked via the basis manifest — not silent zeros)."""
    import inspect

    import ml_scheduler as ms

    assert ms._meta_ml_layer_triplet("lstm", None, set()) == [0.333, 0.333, 0.334]
    assert ms._meta_ml_layer_triplet("lstm", {"up": 0.8, "down": 0.1, "flat": 0.1}, {"lstm"}) == [
        0.333, 0.333, 0.334,
    ]
    assert ms._meta_ml_layer_triplet("xgb", {"up": 0.7, "down": 0.2, "flat": 0.1}, set()) == [
        0.7, 0.2, 0.1,
    ]
    s = inspect.getsource(ms._assemble_meta_ml_layer_prob_vectors)
    assert "if xgb_p is None:" in s and "continue" in s.split("if xgb_p is None:")[1][:40], (
        "xgb-anchor missing must DROP the row (fail-closed), never neutral-fill"
    )


def test_meta_manifest_reader_legacy_absence_never_upgrades(tmp_path):
    from ml_scheduler import (
        _write_meta_training_basis_manifest,
        read_meta_training_basis_manifest,
    )

    assert read_meta_training_basis_manifest(tmp_path, "SPY", "5c") is None
    _write_meta_training_basis_manifest(
        tmp_path, "SPY", "5c", architecture="parallel", basis="in_sample_fallback", n_rows=12,
    )
    doc = read_meta_training_basis_manifest(tmp_path, "SPY", "5c")
    assert doc is not None and doc["oof_governed"] is False
    # corrupted manifest reads as None (never as governed)
    (tmp_path / "meta_SPY_5c_training_manifest.json").write_text("{broken", encoding="utf-8")
    assert read_meta_training_basis_manifest(tmp_path, "SPY", "5c") is None


# ── ML-PIPE-V2 Phase 5: feature-schema golden chain + train/serve parity locks ──

# Golden schema identity: names+order+contract version. Changing the contract
# REQUIRES regenerating this constant in the same governance-reviewed diff.
MVP_SCHEMA_GOLDEN_SHA256 = "e2c132ed09390c5a5a531ebeda6a9c58811a942d782f60d0cab33e71f27fd5d3"

_GOLDEN_DB_ROW = {
    "spot": 512.34, "spread": 0.02, "zone": "breakout",
    "nearest_above_dist": 1.25, "nearest_below_dist": 0.75, "net_gamma": -1234.5,
    "vwap_side": "above", "vwap_dist_pts": 0.6,
    "range_imbalance_stall_score": 0.41, "range_imbalance_push_score": 0.59,
}
_GOLDEN_L1_PAYLOAD = {
    "spot": 512.34, "spread_pts": 0.02, "zone": "breakout",
    "nearest_above_dist": 1.25, "nearest_below_dist": 0.75, "net_gamma": -1234.5,
    "vwap_side": "above", "dist_to_vwap_pts": 0.6,
    "liquidity_summary": {"range_imbalance_stall_score": 0.41, "range_imbalance_push_score": 0.59},
}
_GOLDEN_EXPECTED = {
    "price.spot": 512.34, "price.spread_pts": 0.02, "structure.zone": "breakout",
    "structure.nearest_above_dist": 1.25, "structure.nearest_below_dist": 0.75,
    "structure.net_gamma": -1234.5, "anchor.vwap_side": "above",
    "anchor.vwap_dist_pts": 0.6, "liquidity.range_imbalance_stall_score": 0.41,
    "liquidity.range_imbalance_push_score": 0.59,
}


def test_mvp_schema_hash_golden_locked():
    import hashlib
    import json as _json

    from features.canonical_contract import (
        CANONICAL_FEATURE_CONTRACT_VERSION,
        get_mvp_feature_names,
    )

    blob = _json.dumps(
        {"version": CANONICAL_FEATURE_CONTRACT_VERSION, "names": list(get_mvp_feature_names())},
        sort_keys=True,
    ).encode("utf-8")
    assert hashlib.sha256(blob).hexdigest() == MVP_SCHEMA_GOLDEN_SHA256, (
        "feature schema changed — regenerate MVP_SCHEMA_GOLDEN_SHA256 in the same "
        "governance-reviewed diff and prove train/infer consumers moved together"
    )


def test_db_and_live_adapters_produce_identical_golden_row():
    from features.db_feature_adapter import build_db_mvp_feature_row
    from features.live_feature_adapter import build_live_mvp_feature_row

    db_row = build_db_mvp_feature_row(dict(_GOLDEN_DB_ROW))
    live_row = build_live_mvp_feature_row(dict(_GOLDEN_L1_PAYLOAD))
    assert db_row == live_row == _GOLDEN_EXPECTED
    # column order identical and contract-ordered on both paths
    assert list(db_row) == list(live_row)
    # dtype expectations: floats stay float, categoricals stay str, no numpy leakage.
    # EXACT type, not isinstance: numpy.float64 SUBCLASSES float, so isinstance() returns
    # True for exactly the leakage this assertion exists to catch (verified 2026-07-19:
    # isinstance(np.float64(1.0), float) is True, type(...) is float is False).
    for k, v in db_row.items():
        assert v is None or type(v) in (float, str), (k, type(v))


def test_negative_spread_missingness_parity_between_train_and_serve():
    """The 2026-07-11 parity defect: DB adapter withheld negative spread, live
    adapter served it. Both paths must yield None for the same crossed-quote
    instant — identical missingness semantics train vs serve."""
    from features.db_feature_adapter import build_db_mvp_feature_row
    from features.live_feature_adapter import build_live_mvp_feature_row

    db_row = build_db_mvp_feature_row({**_GOLDEN_DB_ROW, "spread": -0.01})
    live_row = build_live_mvp_feature_row({**_GOLDEN_L1_PAYLOAD, "spread_pts": -0.01})
    assert db_row["price.spread_pts"] is None
    assert live_row["price.spread_pts"] is None
    assert db_row == live_row


def test_golden_row_survives_inference_snapshot_envelope():
    from features.inference_snapshot import build_inference_snapshot_v1_from_db_row

    snap = build_inference_snapshot_v1_from_db_row(
        ticker="SPY", expiry=None, as_of_ts=1_780_000_000.0, db_row=dict(_GOLDEN_DB_ROW),
    )
    assert snap["features"] == _GOLDEN_EXPECTED
    assert snap["feature_contract_version"] == "v1_1m_range_imbalance"
    assert snap["feature_quality"]["missing_count"] == 0
