"""No-fallback lock repair (2026-09-17, calibration_ml_governance group): the entire
tools/legacy/horizon_7/ directory was deleted (17 files, every one carrying an identical
"DEPRECATED -- 7-horizon era... do not run against post-D3 databases" banner, confirmed by
its own README as a documented quarantine). Four files outside that directory had real,
live imports FROM it: tools/backfill_fusion_policy_complete_v1.py,
tools/validate_fusion_backfill_complete_v1.py,
tools/backfill_fusion_policy_columns_expanded_v1.py (all three importing the schema-agnostic
_incomplete_fused_sql, now relocated to tools/_fusion_backfill_shared.py, the ONE shared
producer rather than duplicated three times), and tools/analyze_fused_xgb_comparison_dataset_v1.py
(importing GOV_WHERE, which WAS genuinely schema-specific to the dropped outcome_3c/8c/13c
columns -- that one metric was removed, not relocated, since the query would raise
sqlite3.OperationalError against a current schema).

CORRECTED 2026-09-17 (operator point 12, "prove no duplicate classifier exists elsewhere"):
_classify_failure specifically was NOT actually shared by all three despite the original
relocation's docstring claiming it was -- backfill_fusion_policy_complete_v1.py kept its own
pre-existing local `_classify_failure_complete`, already drifted from this module's version
(a different label, "INSUFFICIENT_HISTORY" vs "HISTORICAL_CONTEXT_INSUFFICIENT", for the
identical MonteCarloStackInputError case, and a finer history-vs-reconstruction message
check this module's function lacked). Fixed by folding the finer distinction into this
module's `_classify_failure` as the single canonical classifier and deleting the local
duplicate -- now genuinely all three consumers share one producer.

These tests prove: (1) the shared module's two functions match their original behavior
exactly (values, not just "no crash"), including the finer distinction now folded in from
the former duplicate, (2) all four previously-dependent files still import cleanly (the
actual regression this repair fixes -- an import from a deleted module) and
backfill_fusion_policy_complete_v1.py specifically no longer defines a local
_classify_failure_complete, (3) the removed strict_v1_shape metric is genuinely gone from
analyze_fused_xgb_comparison_dataset_v1's output shape, not silently still referenced.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_incomplete_fused_sql_matches_original_shape():
    from tools._fusion_backfill_shared import _incomplete_fused_sql
    from ml_horizon import ML_HORIZON_SLUGS

    sql = _incomplete_fused_sql()
    assert sql.startswith("(") and sql.endswith(")")
    for hz in ML_HORIZON_SLUGS:
        assert f"fused_move_prob_{hz} IS NULL" in sql
    assert sql.count(" OR ") == len(ML_HORIZON_SLUGS) - 1


def test_classify_failure_matches_original_verdicts():
    from tools._fusion_backfill_shared import _classify_failure

    assert _classify_failure(FileNotFoundError("x")) == "MISSING_ARTIFACTS"
    assert _classify_failure(ValueError("inference failed")) == "FEATURE_RECONSTRUCTION_FAILURE"
    assert _classify_failure(RuntimeError("no such file: y")) == "MISSING_ARTIFACTS"
    assert _classify_failure(RuntimeError("bad sequence length")) == "HISTORICAL_CONTEXT_INSUFFICIENT"
    assert _classify_failure(ImportError("cannot load model weights")) == "MODEL_LOAD_FAILURE"
    assert _classify_failure(RuntimeError("something entirely unrelated")) == "OTHER"


def test_classify_failure_folds_in_the_former_duplicates_finer_distinction():
    """The deleted local _classify_failure_complete distinguished 'insufficient history'
    from 'feature reconstruction failure' within the Xgb/Lstm/Transformer/Fusion branch by
    checking the exception message -- this module's function lacked that distinction
    entirely before this repair. Proves it is now present in the single shared producer."""
    from features.xgb_model_input import XgbInferenceInputError

    from tools._fusion_backfill_shared import _classify_failure

    assert _classify_failure(XgbInferenceInputError("not enough snapshot rows")) == \
        "HISTORICAL_CONTEXT_INSUFFICIENT"
    assert _classify_failure(XgbInferenceInputError("missing feature column")) == \
        "FEATURE_RECONSTRUCTION_FAILURE"


def test_backfill_fusion_policy_complete_imports_cleanly():
    # The actual regression this repair fixes: this file used to import
    # _incomplete_fused_sql from the now-deleted tools/legacy/horizon_7/ directory.
    mod = importlib.import_module("tools.backfill_fusion_policy_complete_v1")
    assert not hasattr(mod, "_classify_failure_complete"), (
        "the local duplicate classifier must be gone -- this file now shares "
        "tools._fusion_backfill_shared._classify_failure like the other two consumers"
    )


def test_validate_fusion_backfill_complete_imports_cleanly():
    importlib.import_module("tools.validate_fusion_backfill_complete_v1")


def test_backfill_fusion_policy_columns_expanded_imports_cleanly():
    importlib.import_module("tools.backfill_fusion_policy_columns_expanded_v1")


def test_analyze_fused_xgb_comparison_dataset_imports_cleanly():
    mod = importlib.import_module("tools.analyze_fused_xgb_comparison_dataset_v1")
    # The removed metric must be genuinely gone, not silently still defined/imported.
    assert not hasattr(mod, "STRICT_GOV_WHERE")
    assert not hasattr(mod, "GOV_WHERE")
    assert not hasattr(mod, "_policy_tickers"), "orphaned by removing its only caller"


def test_legacy_horizon_7_directory_is_gone():
    assert not (ROOT / "tools" / "legacy" / "horizon_7").exists()
