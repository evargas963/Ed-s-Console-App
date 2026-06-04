"""P3-4b + P3-9: verify fail triggers rollback and verify_failed outcome shape."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch


from arch_competition.promotion_execution import execute_promotion_if_eligible


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
    from ml_horizon import target_definition as _hz_target_definition

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
            "target_definition": _hz_target_definition(hz),
            "rows_used": 500,
        }
        if kind == "xgb":
            meta["category_maps"] = {}
            meta["vol_medians"] = {}
            meta["impute_medians"] = {"f1": 0.0}
        bundle_dir.joinpath(f"{kind}_{t}_{hz}_meta.json").write_text(json.dumps(meta), encoding="utf-8")


def _minimal_governed(model_dir: Path) -> tuple[dict, dict]:
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
    manifest = {
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
            "parallel": {"n_rows_scored": 10, "accuracy": 0.45, "balanced_accuracy": 0.40, "realized_contract_metrics": {}},
            "cascade": {"n_rows_scored": 10, "accuracy": 0.45, "balanced_accuracy": 0.40, "realized_contract_metrics": {}},
        },
        "rolling_oos_windows": [],
        "architecture_comparison_summary": {},
        "lineage_fingerprints": {},
        "metric_breakdown": {},
    }
    record = {
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
    (base / "evaluation_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (base / "promotion_decision.json").write_text(json.dumps(record), encoding="utf-8")
    return manifest, record


def test_scheduler_auto_verify_fail_rolls_back(tmp_path: Path, monkeypatch):
    from active_bundle_contract import scheduler_active_root

    monkeypatch.setenv("ED_SCHEDULER_AUTO_PROMOTE", "1")
    monkeypatch.setenv("ED_SCHEDULER_AUTO_PROMOTE_REQUIRE_VERIFY", "1")
    manifest, record = _minimal_governed(tmp_path)
    active_dir = scheduler_active_root(tmp_path, "1c") / "SPY"
    active_dir.mkdir(parents=True)
    (active_dir / "marker_prior.txt").write_text("prior", encoding="utf-8")

    with patch(
        "verify_active_models.verify_single_bundle",
        return_value={"compliant": False, "issues": ["forced test failure"]},
    ):
        result = execute_promotion_if_eligible(
            tmp_path,
            "SPY",
            "1c",
            manifest=manifest,
            promotion_record=record,
            scheduler_run_id="test-run",
        )

    assert result["executed"] is False
    assert result["skipped_reason"] == "verify_failed"
    assert result.get("verify_failed_rolled_back") is True
    assert (active_dir / "marker_prior.txt").read_text(encoding="utf-8") == "prior"


def test_preflip_verify_fails_when_active_missing_expected_files(tmp_path: Path):
    from tools.validate_autopromote_preflip import PREFLIP_SCHEMA, _decisions_path

    decisions = {
        "schema_version": PREFLIP_SCHEMA,
        "run_id": "test1",
        "decisions": [
            {
                "ticker": "SPY",
                "horizon": "1c",
                "would_promote": True,
                "winner_architecture": "cascade",
                "expected_active_files": ["xgb_SPY_1c.pkl", "xgb_SPY_1c_meta.json"],
            }
        ],
    }
    _decisions_path(tmp_path, "test1").parent.mkdir(parents=True, exist_ok=True)
    _decisions_path(tmp_path, "test1").write_text(json.dumps(decisions), encoding="utf-8")
    from tools.validate_autopromote_preflip import verify

    assert verify(tmp_path, "test1") == 1
