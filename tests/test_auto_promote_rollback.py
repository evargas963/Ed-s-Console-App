"""Auto-promote checkpoint rollback via manual_rollback_to_checkpoint_explicit."""
from __future__ import annotations

import json
from pathlib import Path

from arch_competition.manual_control import (
    MANUAL_PROMOTE_CASCADE_INTENT,
    MANUAL_ROLLBACK_INTENT,
    manual_promote_to_active_explicit,
    manual_rollback_to_checkpoint_explicit,
)


def _dfp():
    return {
        "min_ts_utc": "2020-01-01",
        "max_ts_utc": "2020-06-01",
        "row_count": 1000,
        "table": "snap",
        "timeframe": "1m",
        "ticker": "SPY",
    }


def _write_horizon_bundle(bundle_dir: Path, ticker: str, hz: str, *, xgb_payload: bytes = b"x") -> None:
    from model_contract import contract_metadata_dict

    t = ticker.upper()
    contract = contract_metadata_dict()
    for kind in ("xgb", "lstm", "transformer"):
        ext = ".pkl" if kind == "xgb" else ".pt"
        payload = xgb_payload if kind == "xgb" else b"z"
        bundle_dir.joinpath(f"{kind}_{t}_{hz}{ext}").write_bytes(payload)
        meta = {
            **contract,
            "features": ["f1"],
            "training_timeframe": "1m",
            "target_column": f"outcome_{hz}",
            "target_definition": f"outcome ~{hz}",
            "rows_used": 500,
        }
        if kind == "xgb":
            meta["category_maps"] = {}
            meta["vol_medians"] = {}
            meta["impute_medians"] = {"f1": 0.0}
        bundle_dir.joinpath(f"{kind}_{t}_{hz}_meta.json").write_text(json.dumps(meta), encoding="utf-8")


def _minimal_governed(model_dir: Path) -> None:
    hz, tku = "1c", "SPY"
    pdir = model_dir / "parallel" / tku
    cdir = model_dir / "cascade" / tku
    pdir.mkdir(parents=True)
    cdir.mkdir(parents=True)
    common = {
        "schema_version": "2",
        "ticker": tku,
        "ml_horizon_suffix": hz,
        "data_fingerprint": _dfp(),
        "training_code_fingerprint": "trainfp_shared",
        "feature_cache_key": "fk_shared",
    }
    (pdir / "scheduler_run_manifest.json").write_text(json.dumps(common), encoding="utf-8")
    (cdir / "scheduler_run_manifest.json").write_text(json.dumps(common), encoding="utf-8")
    _write_horizon_bundle(pdir, tku, hz, xgb_payload=b"x")
    _write_horizon_bundle(cdir, tku, hz, xgb_payload=b"y")
    ev = {
        "schema_version": "1",
        "created_at_utc": "2026-01-01T00:00:00+00:00",
        "ticker": tku,
        "ml_horizon_slug": hz,
        "target_column": "outcome_1c",
        "db_path": str(model_dir / "db.sqlite"),
        "parallel_model_dir": str(pdir.resolve()),
        "cascade_model_dir": str(cdir.resolve()),
        "lineage": {
            "feature_cache_key": "fk_shared",
            "data_fingerprint": _dfp(),
            "ml_horizon_suffix": hz,
            "training_code_fingerprint": "trainfp_shared",
            "canonical_feature_contract_version": "v1",
            "canonical_timeframe": "1m",
        },
        "metrics": {
            "parallel": {"n_rows_scored": 10, "realized_contract_metrics": {}},
            "cascade": {"n_rows_scored": 10, "realized_contract_metrics": {}},
        },
        "rolling_oos_windows": [],
        "architecture_comparison_summary": {},
        "lineage_fingerprints": {},
        "metric_breakdown": {},
    }
    pr = {
        "schema_version": "1",
        "created_at_utc": "2026-01-01T00:00:00+00:00",
        "incumbent_architecture": "parallel",
        "challenger_architecture": "cascade",
        "promotion_decision": "promote_cascade",
        "would_promote_challenger": True,
        "auto_promote_executed": False,
        "policy": {},
        "reason_codes": [],
        "blocked_promotion_flags": [],
        "rollback_demotion_ready": True,
        "evaluation_manifest_reference": {
            "lineage_feature_cache_key": "fk_shared",
            "ml_horizon_slug": hz,
        },
    }
    base = model_dir / "arch_competition" / hz / tku
    base.mkdir(parents=True)
    (base / "evaluation_manifest.json").write_text(json.dumps(ev), encoding="utf-8")
    (base / "promotion_decision.json").write_text(json.dumps(pr), encoding="utf-8")


def test_manual_rollback_restores_prior_active_after_promote(tmp_path: Path):
    from active_bundle_contract import scheduler_active_root

    _minimal_governed(tmp_path)
    active_dir = scheduler_active_root(tmp_path, "1c") / "SPY"
    active_dir.mkdir(parents=True)
    (active_dir / "marker_prior.txt").write_text("prior", encoding="utf-8")

    out = manual_promote_to_active_explicit(
        tmp_path,
        "SPY",
        "1c",
        target_architecture="cascade",
        operator_id="op1",
        manual_intent=MANUAL_PROMOTE_CASCADE_INTENT,
    )
    assert (active_dir / "xgb_SPY_1c.pkl").exists()
    assert not (active_dir / "marker_prior.txt").exists()

    manual_rollback_to_checkpoint_explicit(
        tmp_path,
        "SPY",
        "1c",
        operator_id="op1",
        manual_intent=MANUAL_ROLLBACK_INTENT,
        checkpoint_id=out["checkpoint_id"],
    )
    assert (active_dir / "marker_prior.txt").read_text(encoding="utf-8") == "prior"
    assert not (active_dir / "xgb_SPY_1c.pkl").exists()
