"""Technical debt retirement: Monte Carlo, regime, similarity filters, encoder spot — canonical alignment."""
from __future__ import annotations


import pytest



def _snap(spot: float):
    from features.inference_snapshot import build_inference_snapshot_v1_from_feature_row
    from features.canonical_contract import get_mvp_feature_names

    feats = {k: None for k in get_mvp_feature_names()}
    feats["price.spot"] = spot
    feats["price.spread_pts"] = 0.01
    feats["structure.zone"] = "pin_neutral"
    feats["structure.nearest_above_dist"] = 1.0
    feats["structure.nearest_below_dist"] = 1.0
    feats["structure.net_gamma"] = 0.0
    feats["anchor.vwap_side"] = "above"
    feats["anchor.vwap_dist_pts"] = 0.0
    feats["liquidity.absorption_score"] = None
    feats["liquidity.continuation_score"] = None
    return build_inference_snapshot_v1_from_feature_row(
        ticker="SPY", expiry=None, as_of_ts=1.0, features=feats
    )






def _snap_raw_spot(spot):
    from features.canonical_contract import get_mvp_feature_names

    feats = {k: None for k in get_mvp_feature_names()}
    feats["price.spot"] = spot
    return {
        "snapshot_type": "InferenceSnapshotV1",
        "feature_contract_version": "v1_1m_mvp",
        "canonical_timeframe": "1m",
        "features": feats,
    }












def test_production_default_parallel_unchanged_in_signals_doc():
    """TEST_SYSTEM_REHAB_V2_RESIDUAL_CLOSURE (weak-assertion item 4): was
    `assert "parallel" in src.lower() or "run_unified_stack_ml_once" in src` -- a
    presence-only substring grep over a ~75k-char module with two independently
    satisfied disjuncts. Measured: "parallel" matched 3 times (one of them PROSE in a
    docstring, two only via .lower() on the identifier ParallelRuntimeArtifactError)
    and "run_unified_stack_ml_once" 10 times. Deleting the entire parallel model
    stack would leave either behind and still pass -- the only thing that could
    actually fail was `import signals`, i.e. an import smoke test wearing a
    behavioral name. Nothing in the title ("production DEFAULT parallel UNCHANGED")
    was asserted.

    The real contract (Issue 13) is structural and checkable: XGB/LSTM/Transformer
    are driven by EXACTLY ONE run_unified_stack_ml_once(...) call per tick inside
    signals._run_model_stack. The regression to refuse is reverting to per-model or
    per-horizon invocation (N calls per tick), which silently re-splits the unified
    stack that the downstream authorization gate assumes scored together."""
    import ast

    import signals

    src = open(signals.__file__, encoding="utf-8").read()
    tree = ast.parse(src)
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
               and n.name == "_run_model_stack"), None)
    assert fn is not None, "signals._run_model_stack is gone; the unified stack entry point moved"
    calls = [
        c for c in ast.walk(fn)
        if isinstance(c, ast.Call)
        and ((isinstance(c.func, ast.Name) and c.func.id == "run_unified_stack_ml_once")
             or (isinstance(c.func, ast.Attribute) and c.func.attr == "run_unified_stack_ml_once"))
    ]
    assert len(calls) == 1, (
        f"_run_model_stack must invoke run_unified_stack_ml_once EXACTLY once per tick "
        f"(one unified stack scoring); found {len(calls)} call site(s) at lines "
        f"{[c.lineno for c in calls]}")
    assert "stack_probs_composition" in src, (
        "the unified stack must still publish stack_probs_composition — without it the "
        "authorization gate sees only the SHAPE of the triplet, which one renormalised "
        "leg can fake")


def test_canonical_reference_spot_first_bar_only():
    from lstm_data import canonical_reference_spot_from_sequence_window_first_bar

    assert canonical_reference_spot_from_sequence_window_first_bar([{"spot": 450.0}]) == 450.0
    with pytest.raises(ValueError):
        canonical_reference_spot_from_sequence_window_first_bar([{"spot": None}])
    with pytest.raises(ValueError):
        canonical_reference_spot_from_sequence_window_first_bar([{"spot": 0}])


def test_inference_and_training_sources_use_canonical_reference_helpers():
    """Production-relevant modules must wire explicit first-bar ref via lstm_data helpers."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    mp = (root / "ml_predict.py").read_text(encoding="utf-8")
    assert "canonical_reference_spot_from_merged_window" in mp
    tt = (root / "transformer_train.py").read_text(encoding="utf-8")
    assert "canonical_reference_spot_from_sequence_window_first_bar" in tt
    ld = (root / "lstm_data.py").read_text(encoding="utf-8")
    assert "canonical_reference_spot_from_sequence_window_first_bar" in ld
    sch = (root / "ml_scheduler.py").read_text(encoding="utf-8")
    assert "canonical_reference_spot_from_sequence_window_first_bar" in sch
