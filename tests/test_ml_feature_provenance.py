"""Day 3 — ML feature provenance: per-field lineage, no silent defaults, m5 proxy labeling."""

from __future__ import annotations

import re
import sys
from pathlib import Path


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


#: TEST_SYSTEM_REHAB_V2: was an independent ROOT.rglob("*.py") + per-file read_text --
#: now sources from the shared tests/conftest.py `repo_index` corpus. Filter semantics
#: unchanged (SKIP_DIR_PARTS, plus tools/ excluded at iteration as before).
def _iter_repo_py_files(repo_index):
    for rel, text, _tree in repo_index.items():
        if set(rel.parts) & SKIP_DIR_PARTS:
            continue
        rel_posix = rel.as_posix()
        if rel_posix.startswith("tools/"):
            continue
        yield rel_posix, text


def _allowlisted(rel_posix: str) -> bool:
    for prefix, _reason in SILENT_DEFAULT_ALLOWLIST:
        if rel_posix == prefix or rel_posix.startswith(prefix):
            return True
    return False


def _repo_wide_pattern_hits(repo_index, pattern: re.Pattern[str]) -> list[str]:
    hits: list[str] = []
    for rel, text in _iter_repo_py_files(repo_index):
        if _allowlisted(rel):
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
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














def test_no_silent_default_in_feature_paths_repo_wide(repo_index):
    above_hits = _repo_wide_pattern_hits(repo_index, VWAP_SIDE_ABOVE_DEFAULT_RE)
    assert not above_hits, "vwap_side else-above violations:\n" + "\n".join(above_hits[:40])






# ── ML-PIPE-V2 Phase 2: point-in-time causal boundary (as-of) adversarial locks ──
# Acceptance ref: OPEN_ITEMS.md, ML_PIPELINE_CORRECTNESS →
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












# ── ML-PIPE-V2 Phase 3: meta training basis must travel with the artifact ──








# ── ML-PIPE-V2 Phase 3 completion: OOF strictness, routing trap, base semantics ──




# The parallel-path OOF routing contract this file used to re-prove here via its own
# _routing_trap harness (never-score-deployed-dir-while-folds-exist / in_sample_no_folds /
# in_sample_fallback, against the same ms._train_parallel_meta_oof) is already proven,
# symmetrically for BOTH parallel and cascade, by tests/test_oof_stacker.py's
# test_parallel_meta_trains_on_oof_fold_dirs_not_in_sample /
# test_parallel_meta_falls_back_in_sample_when_no_folds /
# test_parallel_meta_falls_back_when_oof_too_thin (plus their cascade counterparts, which
# this file's harness never covered at all). Removed as a true duplicate 2026-09-15.






# ── ML-PIPE-V2 Phase 5: feature-schema golden chain + train/serve parity locks ──

# Golden schema identity: names+order+contract version. Changing the contract
# REQUIRES regenerating this constant in the same governance-reviewed diff.
MVP_SCHEMA_GOLDEN_SHA256 = "e2c132ed09390c5a5a531ebeda6a9c58811a942d782f60d0cab33e71f27fd5d3"

_GOLDEN_DB_ROW = {
    "spot": 512.34, "spread": 0.02, "zone": "breakout",
    "nearest_above_dist": 1.25, "nearest_below_dist": 0.75, "net_gamma": -1234.5,
    "vwap_side": "above", "vwap_dist_pts": 0.6,
    "absorption_score": 0.41, "continuation_score": 0.59,
}
_GOLDEN_L1_PAYLOAD = {
    "spot": 512.34, "spread_pts": 0.02, "zone": "breakout",
    "nearest_above_dist": 1.25, "nearest_below_dist": 0.75, "net_gamma": -1234.5,
    "vwap_side": "above", "dist_to_vwap_pts": 0.6,
    "liquidity_summary": {"absorption_score": 0.41, "continuation_score": 0.59},
}
_GOLDEN_EXPECTED = {
    "price.spot": 512.34, "price.spread_pts": 0.02, "structure.zone": "breakout",
    "structure.nearest_above_dist": 1.25, "structure.nearest_below_dist": 0.75,
    "structure.net_gamma": -1234.5, "anchor.vwap_side": "above",
    "anchor.vwap_dist_pts": 0.6, "liquidity.absorption_score": 0.41,
    "liquidity.continuation_score": 0.59,
}








