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
