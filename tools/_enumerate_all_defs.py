"""Enumerate every FunctionDef/AsyncFunctionDef in section files (all scopes)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from governance.section_inventory_gate import all_functions_in_file  # noqa: E402

SECTION1 = [
    "schwab_client.py",
    "reauth_schwab.py",
    "websocket_adapter.py",
    "polling_adapter.py",
    "sse_adapter.py",
    "market_data_adapter.py",
    "snapshot_normalizer.py",
    "snapshot_access.py",
]

SECTION2 = [
    "server.py",
    "live_market_plane.py",
    "live_decision_bundle.py",
    "live_pipeline_diag.py",
    "live_vs_replay_validation.py",
]

SECTION3 = [
    "market_context.py",
    "market_state.py",
    "math_snapshot_derive.py",
]

SECTION6 = [
    "signals.py",
    "signal_helpers.py",
    "signal_types.py",
    "rules_engine.py",
    "prediction_engine.py",
    "call_engine.py",
    "multi_horizon_decision.py",
    "multi_horizon_ml_bundle.py",
]

SECTION7 = sorted(
    f"v2_decision/{p.name}"
    for p in (ROOT / "v2_decision").glob("*.py")
    if p.name != "__init__.py"
) + ["lifecycle_rule_core.py"]

SECTION12 = [
    "liquidity_models.py",
    "liquidity_value_engine.py",
    "print_liquidity_value_snapshot.py",
    "run_liquidity_sample.py",
]

SECTION11 = sorted(
    p.relative_to(ROOT).as_posix().replace("\\", "/")
    for p in list((ROOT / "calibration").rglob("*.py"))
    + list((ROOT / "arch_competition").glob("*.py"))
    + [ROOT / "bayesian_fusion.py", ROOT / "governed_stack_contract.py"]
    if p.name != "__init__.py"
)

SECTION10 = sorted(
    [
        "ml_data_common.py",
        "ml_horizon.py",
        "ml_predict.py",
        "ml_train.py",
        "ml_scheduler.py",
        "lstm_model.py",
        "lstm_data.py",
        "xgboost_model.py",
        "transformer_train.py",
        "transformer_model.py",
        "train_all.py",
        "train_compare.py",
        "training_cache.py",
        "training_provenance.py",
        "training_cache_policy.py",
        "normalized_training_sync.py",
        "smoke_predict_active.py",
    ]
)

SECTION9 = sorted(
    f"features/{p.name}"
    for p in (ROOT / "features").glob("*.py")
    if p.name != "__init__.py"
)

SECTION8 = [
    "monte_carlo.py",
    "mc_fusion_adjustment.py",
    "volatility_regime.py",
    "regime_engine.py",
]

SECTION5 = [
    "order_flow_engine.py",
    "order_flow_live_state.py",
    "order_flow_streaming.py",
    "debug_flow_snapshot.py",
]

SECTION4 = [
    "math_exposure.py",
    "math_exposure_core.py",
    "math_levels.py",
    "math_volatility.py",
    "math_probabilities.py",
    "levels.py",
]


def main(files: list[str]) -> None:
    for rel in files:
        fns = all_functions_in_file(ROOT, rel)
        print(f"\n{rel}: {len(fns)} defs")
        for fn in fns:
            print(f"  L{fn.line:4d} {fn.qualified_name:50s} scope={fn.scope}")


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "1"
    files = {
        "1": SECTION1,
        "2": SECTION2,
        "3": SECTION3,
        "4": SECTION4,
        "5": SECTION5,
        "6": SECTION6,
        "7": SECTION7,
        "8": SECTION8,
        "9": SECTION9,
        "10": SECTION10,
        "11": SECTION11,
        "12": SECTION12,
    }.get(which, SECTION1)
    main(files)
