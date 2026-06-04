"""G3-R1 active bundle contract shared by verify and ml_predict."""
from __future__ import annotations

from pathlib import Path


def _write_minimal_bundle(bundle_dir: Path, ticker: str, hz: str) -> None:
    from model_contract import contract_metadata_dict

    bundle_dir.mkdir(parents=True, exist_ok=True)
    t = ticker.upper()
    contract = contract_metadata_dict()
    feats = ["f1"]
    for kind in ("xgb", "lstm", "transformer"):
        ext = ".pkl" if kind == "xgb" else ".pt"
        model_name = f"{kind}_{t}_{hz}{ext}"
        meta_name = f"{kind}_{t}_{hz}_meta.json"
        bundle_dir.joinpath(model_name).write_bytes(b"x")
        meta = {
            **contract,
            "features": feats,
            "training_timeframe": "1m",
            "target_column": f"outcome_{hz}",
            "target_definition": f"outcome ~{hz}",
            "rows_used": 500,
        }
        if kind == "xgb":
            meta["category_maps"] = {}
            meta["vol_medians"] = {}
            meta["impute_medians"] = {"f1": 0.0}
        bundle_dir.joinpath(meta_name).write_text(__import__("json").dumps(meta), encoding="utf-8")
    bundle_dir.joinpath(f"meta_{t}_{hz}.pkl").write_bytes(b"meta-stack-test-stub")


def test_check_active_bundle_complete_all_present(tmp_path: Path):
    from active_bundle_contract import check_active_bundle_complete

    bd = tmp_path / "active" / "SPY"
    _write_minimal_bundle(bd, "SPY", "1c")
    r = check_active_bundle_complete("SPY", "1c", bundle_dir=bd, models_dir=tmp_path)
    assert r["compliant"] is True


def test_check_active_bundle_incomplete_without_meta_stack(tmp_path: Path):
    from active_bundle_contract import check_active_bundle_complete

    bd = tmp_path / "active" / "SPY"
    _write_minimal_bundle(bd, "SPY", "1c")
    (bd / "meta_SPY_1c.pkl").unlink()
    r = check_active_bundle_complete("SPY", "1c", bundle_dir=bd, models_dir=tmp_path)
    assert r["compliant"] is False
    assert "meta_SPY_1c.pkl missing" in str(r["artifacts"]["meta_stack"]["issues"])


def test_strict_active_bundle_dir_requires_full_triple(tmp_path: Path):
    from active_bundle_contract import strict_active_bundle_dir_for_horizon

    bd = tmp_path / "active" / "SPY"
    bd.mkdir(parents=True)
    (bd / "xgb_SPY_1c.pkl").write_bytes(b"x")
    (bd / "xgb_SPY_1c_meta.json").write_text("{}", encoding="utf-8")
    assert strict_active_bundle_dir_for_horizon("SPY", "1c", models_dir=tmp_path) is None

    _write_minimal_bundle(bd, "SPY", "1c")
    assert strict_active_bundle_dir_for_horizon("SPY", "1c", models_dir=tmp_path) == bd


def test_ml_predict_strict_uses_bundle_contract(tmp_path: Path, monkeypatch):
    from active_bundle_contract import active_bundle_dir

    bd = active_bundle_dir("SPY", "1c", models_dir=tmp_path)
    _write_minimal_bundle(bd, "SPY", "1c")

    import ml_predict

    monkeypatch.setattr(ml_predict, "MODEL_DIR", tmp_path)
    monkeypatch.setenv("ED_XGB_STRICT_ACTIVE_ONLY", "1")
    monkeypatch.setattr(ml_predict, "get_ml_infer_horizon_slug", lambda: "1c")

    resolved = ml_predict._model_dir_for_ticker("SPY")
    assert resolved == bd
