"""Fusion-backfill shared helpers: typed failure classification and SQL shape.

Classification is producer-reason only. Message substrings (including "60")
must not change the category. Identical exceptions must classify identically;
distinct producer reasons must not collapse.
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


def test_classify_failure_uses_typed_reason_not_message_text():
    from features.monte_carlo_stack_input import MonteCarloStackInputError
    from features.xgb_model_input import XgbInferenceInputError
    from ml_predict import ParallelRuntimeArtifactError
    from tools._fusion_backfill_shared import _classify_failure

    missing = MonteCarloStackInputError("canonical MVP price.spot is missing", reason="MISSING_CANONICAL_SPOT")
    invalid = MonteCarloStackInputError("price.spot must be finite and > 0, got 60", reason="INVALID_CANONICAL_SPOT")
    lineage = MonteCarloStackInputError("SignalInput.spot disagrees with canonical", reason="LINEAGE_DISAGREEMENT")
    assert _classify_failure(missing) == "MISSING_CANONICAL_SPOT"
    assert _classify_failure(invalid) == "INVALID_CANONICAL_SPOT"
    assert _classify_failure(lineage) == "LINEAGE_DISAGREEMENT"
    assert len({_classify_failure(missing), _classify_failure(invalid), _classify_failure(lineage)}) == 3

    hist = XgbInferenceInputError("LSTM needs at least 60 snapshots", reason="INSUFFICIENT_HISTORY")
    contract = XgbInferenceInputError("missing feature column 60", reason="FEATURE_CONTRACT_INVALID")
    assert _classify_failure(hist) == "INSUFFICIENT_HISTORY"
    assert _classify_failure(contract) == "FEATURE_CONTRACT_INVALID"
    assert _classify_failure(hist) != _classify_failure(contract)

    assert _classify_failure(FileNotFoundError("x")) == "MISSING_ARTIFACTS"
    assert _classify_failure(ParallelRuntimeArtifactError("artifact")) == "MISSING_ARTIFACTS"
    assert _classify_failure(RuntimeError("no such file: y")) == "UNCLASSIFIED"
    assert _classify_failure(ValueError("inference failed")) == "UNCLASSIFIED"
    assert _classify_failure(RuntimeError("bad sequence length")) == "UNCLASSIFIED"
    assert _classify_failure(ImportError("cannot load model weights")) == "UNCLASSIFIED"


def test_classify_failure_identical_exceptions_cannot_diverge():
    from features.monte_carlo_stack_input import MonteCarloStackInputError
    from tools._fusion_backfill_shared import _classify_failure

    a = MonteCarloStackInputError("msg-a history 60 sequence", reason="MISSING_CANONICAL_SPOT")
    b = MonteCarloStackInputError("msg-b totally different wording", reason="MISSING_CANONICAL_SPOT")
    assert _classify_failure(a) == _classify_failure(b) == "MISSING_CANONICAL_SPOT"
    assert _classify_failure(a, "stack") == _classify_failure(b, "signal_input")


def test_classify_failure_hint_and_substring_cannot_reclassify():
    from features.monte_carlo_stack_input import MonteCarloStackInputError
    from tools._fusion_backfill_shared import _classify_failure

    exc = MonteCarloStackInputError("contains 60 history sequence artifact .pkl", reason="LINEAGE_DISAGREEMENT")
    assert _classify_failure(exc) == "LINEAGE_DISAGREEMENT"
    assert _classify_failure(exc, "history 60 sequence") == "LINEAGE_DISAGREEMENT"


def test_classify_failure_unclassified_when_producer_supplies_no_reason():
    from tools._fusion_backfill_shared import _classify_failure

    class Bare(ValueError):
        pass

    assert _classify_failure(Bare("60 history sequence")) == "UNCLASSIFIED"


def test_backfill_fusion_policy_complete_imports_cleanly():
    mod = importlib.import_module("tools.backfill_fusion_policy_complete_v1")
    shared = importlib.import_module("tools._fusion_backfill_shared")
    assert not hasattr(mod, "_classify_failure_complete")
    assert mod._classify_failure is shared._classify_failure


def test_validate_fusion_backfill_complete_imports_cleanly():
    importlib.import_module("tools.validate_fusion_backfill_complete_v1")


def test_backfill_fusion_policy_columns_expanded_imports_cleanly():
    importlib.import_module("tools.backfill_fusion_policy_columns_expanded_v1")


def test_analyze_fused_xgb_comparison_dataset_imports_cleanly():
    mod = importlib.import_module("tools.analyze_fused_xgb_comparison_dataset_v1")
    assert not hasattr(mod, "STRICT_GOV_WHERE")
    assert not hasattr(mod, "GOV_WHERE")
    assert not hasattr(mod, "_policy_tickers"), "orphaned by removing its only caller"


def test_legacy_horizon_7_directory_is_gone():
    assert not (ROOT / "tools" / "legacy" / "horizon_7").exists()


def test_no_substring_classifier_remains_in_fusion_backfill_family():
    shared = (ROOT / "tools" / "_fusion_backfill_shared.py").read_text(encoding="utf-8")
    complete = (ROOT / "tools" / "backfill_fusion_policy_complete_v1.py").read_text(encoding="utf-8")
    expanded = (ROOT / "tools" / "backfill_fusion_policy_columns_expanded_v1.py").read_text(encoding="utf-8")
    assert '"60"' not in shared and "'60'" not in shared
    assert "in s" not in shared
    assert "_classify_failure_complete" not in complete
    assert "from tools._fusion_backfill_shared import _classify_failure" in complete
    assert "from tools._fusion_backfill_shared import _classify_failure" in expanded
