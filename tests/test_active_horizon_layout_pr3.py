"""PR3 P2-1/P2-4: canonical active layout and consolidation."""
from __future__ import annotations

from pathlib import Path


def _write_minimal_bundle(bundle_dir: Path, ticker: str, hz: str) -> None:
    from model_contract import contract_metadata_dict

    bundle_dir.mkdir(parents=True, exist_ok=True)
    t = ticker.upper()
    contract = contract_metadata_dict()
    feats = ["f1"]
    import torch
    from lstm_data import LSTM_ENCODER_SCHEMA_VERSION, encoded_width_5m, encoded_width_1m

    seq_stub = {
        "encoder_schema_version": LSTM_ENCODER_SCHEMA_VERSION,
        "encoder_width_5m_pre_mask": encoded_width_5m(),
        "encoder_width_1m_pre_mask": encoded_width_1m(),
        "n_features": encoded_width_5m(),
    }
    for kind in ("xgb", "lstm", "transformer"):
        ext = ".pkl" if kind == "xgb" else ".pt"
        model_name = f"{kind}_{t}_{hz}{ext}"
        if kind == "xgb":
            bundle_dir.joinpath(model_name).write_bytes(b"x")
        else:
            torch.save(seq_stub, str(bundle_dir / model_name))
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
        bundle_dir.joinpath(f"{kind}_{t}_{hz}_meta.json").write_text(
            __import__("json").dumps(meta),
            encoding="utf-8",
        )
    import pickle

    bundle_dir.joinpath(f"meta_{t}_{hz}.pkl").write_bytes(
        pickle.dumps({"meta_stack_test_stub": True}, protocol=pickle.HIGHEST_PROTOCOL)
    )


def test_strict_active_bundle_dir_single_canonical_root(tmp_path: Path):
    from active_bundle_contract import active_bundle_dir, strict_active_bundle_dir_for_horizon

    wrong = tmp_path / "active" / "SPY"
    _write_minimal_bundle(wrong, "SPY", "5c")
    canonical = active_bundle_dir("SPY", "5c", models_dir=tmp_path)
    assert not canonical.exists()
    assert strict_active_bundle_dir_for_horizon("SPY", "5c", models_dir=tmp_path) is None

    _write_minimal_bundle(canonical, "SPY", "5c")
    resolved = strict_active_bundle_dir_for_horizon("SPY", "5c", models_dir=tmp_path)
    assert resolved == canonical


def test_scheduler_active_root_matches_contract(tmp_path: Path):
    from active_bundle_contract import scheduler_active_root
    from arch_competition.manual_control import scheduler_active_root as mc_root

    assert scheduler_active_root(tmp_path, "1c") == tmp_path / "active"
    assert scheduler_active_root(tmp_path, "5c") == tmp_path / "active_5c"
    assert mc_root(tmp_path, "15c") == tmp_path / "active_15c"


def test_promote_horizon_bundle_copies_seven_files_only(tmp_path: Path):
    from active_bundle_contract import (
        active_bundle_dir,
        horizon_bundle_filenames,
        promote_horizon_bundle_from_candidate,
    )

    src = tmp_path / "parallel" / "SPY"
    src.mkdir(parents=True)
    _write_minimal_bundle(src, "SPY", "5c")
    _write_minimal_bundle(src, "SPY", "1c")
    extra = src / "readme.txt"
    extra.write_text("noise", encoding="utf-8")

    dest_root = promote_horizon_bundle_from_candidate(
        src,
        ticker="SPY",
        hz="5c",
        models_dir=tmp_path,
    )
    assert dest_root == active_bundle_dir("SPY", "5c", models_dir=tmp_path)
    names = {p.name for p in dest_root.iterdir()}
    assert names == set(horizon_bundle_filenames("SPY", "5c"))


def test_consolidate_plan_moves_from_legacy_active(tmp_path: Path):
    from active_bundle_contract import (
        active_bundle_dir,
        apply_consolidate_horizon_layout_plan,
        consolidate_horizon_layout_plan,
    )

    legacy = tmp_path / "active" / "SPY"
    _write_minimal_bundle(legacy, "SPY", "5c")
    plan = consolidate_horizon_layout_plan("SPY", "5c", models_dir=tmp_path)
    assert len(plan["moves"]) == 7
    canonical = active_bundle_dir("SPY", "5c", models_dir=tmp_path)
    assert plan["canonical_dir"] == str(canonical)
    copied = apply_consolidate_horizon_layout_plan(plan)
    assert len(copied) == 7
    assert (canonical / "xgb_SPY_5c.pkl").is_file()


def test_ml_predict_strict_uses_canonical_only(tmp_path: Path, monkeypatch):
    from active_bundle_contract import active_bundle_dir

    wrong = tmp_path / "active" / "SPY"
    _write_minimal_bundle(wrong, "SPY", "5c")
    canonical = active_bundle_dir("SPY", "5c", models_dir=tmp_path)
    _write_minimal_bundle(canonical, "SPY", "5c")

    import ml_predict

    monkeypatch.setattr(ml_predict, "MODEL_DIR", tmp_path)
    monkeypatch.setenv("ED_XGB_STRICT_ACTIVE_ONLY", "1")
    monkeypatch.setattr(ml_predict, "get_ml_infer_horizon_slug", lambda: "5c")

    resolved = ml_predict._model_dir_for_ticker("SPY")
    assert resolved == canonical
