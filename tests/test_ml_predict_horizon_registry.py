"""Registry keys must include horizon so each slug loads its own artifacts."""
from __future__ import annotations

import json
import pickle

import numpy as np
from sklearn.dummy import DummyClassifier

from model_contract import contract_metadata_dict


def test_model_registry_key_format():
    import ml_predict as mp

    assert mp._model_registry_key("spy", "1c") == "parallel:SPY:1c"
    assert mp._model_registry_key("spy", "5c") == "parallel:SPY:5c"
    assert mp._model_registry_key("spy", "1c") != mp._model_registry_key("spy", "5c")


def test_all_governed_horizons_have_distinct_keys():
    import ml_predict as mp
    from ml_horizon import ML_HORIZON_SLUGS

    keys = {mp._model_registry_key("SPY", hz) for hz in ML_HORIZON_SLUGS}
    assert len(keys) == len(ML_HORIZON_SLUGS)


def _valid_xgb_meta(features: list[str]) -> dict:
    im = {f: 0.0 for f in features}
    return {**contract_metadata_dict(), "features": features, "impute_medians": im}


def test_distinct_xgb_models_per_horizon(tmp_path, monkeypatch):
    """Two horizons load different files → two registry entries with different model objects."""
    import ml_predict as mp

    mp.reset_caches()
    tkr = "ZZHZ"
    base = tmp_path / tkr
    base.mkdir(parents=True)

    def clf_for(hz: str) -> DummyClassifier:
        y = np.array([0, 1, 2, 0, 1], dtype=int)
        const = 0 if hz == "1c" else 1
        c = DummyClassifier(strategy="constant", constant=const)
        c.fit(np.zeros((5, 1)), y)
        return c

    for hz in ("1c", "5c"):
        mp_path = base / f"xgb_{tkr}_{hz}.pkl"
        meta_path = base / f"xgb_{tkr}_{hz}_meta.json"
        with open(mp_path, "wb") as f:
            pickle.dump(clf_for(hz), f)
        meta_path.write_text(json.dumps(_valid_xgb_meta(["a"])), encoding="utf-8")

    monkeypatch.setattr(mp, "_model_dir_for_ticker", lambda _t: base)

    tok1 = mp.set_ml_infer_horizon_slug("1c")
    try:
        assert mp._load_xgb(tkr) is True
        k1 = mp._model_registry_key(tkr, "1c")
        assert k1 in mp._xgb_registry and mp._xgb_registry[k1] is not None
        m1 = mp._xgb_registry[k1]["model"]
    finally:
        mp.reset_ml_infer_horizon_slug(tok1)

    tok2 = mp.set_ml_infer_horizon_slug("5c")
    try:
        assert mp._load_xgb(tkr) is True
        k2 = mp._model_registry_key(tkr, "5c")
        assert k2 in mp._xgb_registry and mp._xgb_registry[k2] is not None
        m2 = mp._xgb_registry[k2]["model"]
    finally:
        mp.reset_ml_infer_horizon_slug(tok2)

    assert k1 != k2
    assert m1 is not m2


def test_missing_xgb_for_1c_does_not_block_5c_load(tmp_path, monkeypatch):
    """Registry entry ...:1c = None must not prevent loading ...:5c when file exists.

    (Renamed from "_block_3c_load" — 3c migrated out of governed slugs in commit 794862d;
    test now exercises 5c, which is in ML_HORIZON_SLUGS = ('1c','5c','15c','60c').)
    """
    import ml_predict as mp

    mp.reset_caches()
    tkr = "ZZPO"
    base = tmp_path / tkr
    base.mkdir(parents=True)

    hz3 = "5c"
    mp_path = base / f"xgb_{tkr}_{hz3}.pkl"
    meta_path = base / f"xgb_{tkr}_{hz3}_meta.json"
    c = DummyClassifier(strategy="uniform")
    c.fit(np.zeros((5, 1)), np.zeros(5, dtype=int))
    with open(mp_path, "wb") as f:
        pickle.dump(c, f)
    meta_path.write_text(json.dumps(_valid_xgb_meta(["a"])), encoding="utf-8")

    monkeypatch.setattr(mp, "_model_dir_for_ticker", lambda _t: base)

    tok1 = mp.set_ml_infer_horizon_slug("1c")
    try:
        assert mp._load_xgb(tkr) is False
        k1 = mp._model_registry_key(tkr, "1c")
        assert mp._xgb_registry.get(k1) is None
    finally:
        mp.reset_ml_infer_horizon_slug(tok1)

    tok2 = mp.set_ml_infer_horizon_slug("5c")
    try:
        assert mp._load_xgb(tkr) is True
        k2 = mp._model_registry_key(tkr, "5c")
        assert mp._xgb_registry[k2] is not None
    finally:
        mp.reset_ml_infer_horizon_slug(tok2)


def test_reset_caches_clears_horizon_scoped_entries():
    import ml_predict as mp

    mp._xgb_registry["parallel:XX:1c"] = {"model": object()}
    mp.reset_caches()
    assert mp._xgb_registry == {}
