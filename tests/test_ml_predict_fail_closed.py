"""Fail-closed contracts for ml_predict model-probability → fusion/UI conversion."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import ml_predict as mp

REPO_ROOT = Path(__file__).resolve().parents[1]

STRICT_BUNDLE_BLOCK_TICKERS = (
    "SPY",
    "QQQ",
    "IWM",
    "NVDA",
    "BE",
    "ZZZ_ML_PREDICT_STRICT",
)


@pytest.fixture(autouse=True)
def _isolate_ml_predict_bundle_cache():
    mp._active_bundle_dir_cache.clear()
    mp._strict_bundle_warned.clear()
    yield
    mp._active_bundle_dir_cache.clear()
    mp._strict_bundle_warned.clear()


def _strict_bundle_block(monkeypatch) -> None:
    def _raise(_ticker: str) -> Path:
        raise FileNotFoundError("strict bundle blocked")

    monkeypatch.setattr(mp, "_model_dir_for_ticker", _raise)


def _write_fake_stack_artifacts(bundle_dir: Path, ticker: str, hz: str = "1c") -> None:
    bundle_dir.mkdir(parents=True, exist_ok=True)
    for name in (
        f"xgb_{ticker}_{hz}.pkl",
        f"lstm_{ticker}_{hz}.pt",
        f"transformer_{ticker}_{hz}.pt",
        f"meta_{ticker}_{hz}.pkl",
    ):
        (bundle_dir / name).write_bytes(b"x")


def _resolve_bundle_dir_for_ticker(ticker: str, tmp_path: Path) -> Path:
    repo_active = REPO_ROOT / "models" / "active" / ticker
    if repo_active.is_dir() and any(repo_active.glob(f"xgb_{ticker}_1c.pkl")):
        return repo_active
    bundle_dir = tmp_path / "bundles" / ticker
    _write_fake_stack_artifacts(bundle_dir, ticker)
    return bundle_dir


def _seed_stale_bundle_cache(ticker: str, bundle_dir: Path, hz: str = "1c") -> None:
    mp._active_bundle_dir_cache[mp._model_registry_key(ticker, hz)] = bundle_dir


def _seed_index_682_spy_pollution_cache() -> None:
    """Mirror cache keys left by index-682 live v2 logging polluter (SPY, all horizons)."""
    for hz, rel in (
        ("1c", "models/active/SPY"),
        ("5c", "models/active_5c/SPY"),
        ("15c", "models/active_15c/SPY"),
        ("60c", "models/active_60c/SPY"),
    ):
        mp._active_bundle_dir_cache[mp._model_registry_key("SPY", hz)] = REPO_ROOT / rel


def test_require_direction_probability_triplet_none_input():
    assert mp._require_direction_probability_triplet(None) is None


def test_require_direction_probability_triplet_missing_key():
    assert mp._require_direction_probability_triplet({"up": 0.5, "down": 0.3}) is None
    assert mp._require_direction_probability_triplet({"up": 0.5, "flat": 0.2}) is None


def test_require_direction_probability_triplet_complete():
    tri = mp._require_direction_probability_triplet({"up": 0.5, "down": 0.3, "flat": 0.2})
    assert tri == (0.5, 0.3, 0.2)


def test_model_probs_to_fusion_out_fail_closed_on_partial_dict():
    assert mp._model_probs_to_fusion_out({"up": 0.5, "down": 0.3}, "wait") is None


def test_model_probs_to_fusion_out_available_on_complete_dict():
    out = mp._model_probs_to_fusion_out(
        {"up": 0.5, "down": 0.3, "flat": 0.2},
        "long",
    )
    assert out is not None
    assert out["available"] is True
    assert out["prob_up"] == 0.5
    assert out["prob_down"] == 0.3
    assert out["prob_flat"] == 0.2
    assert out["dominant_class"] == "up"
    assert out["continuation_support"] == 0.5
    assert out["reversal_support"] == 0.3


def test_model_probs_to_fusion_out_none_input():
    assert mp._model_probs_to_fusion_out(None, "wait") is None


def test_model_probs_to_ui_output_fail_closed_on_partial_dict():
    out = mp._model_probs_to_ui_output({"up": 0.5, "down": 0.3}, approved=True)
    assert out["available"] is False
    assert out["dominant"] is None
    assert out["approved"] is False


def test_model_probs_to_ui_output_available_on_complete_dict():
    out = mp._model_probs_to_ui_output(
        {"up": 0.5, "down": 0.3, "flat": 0.2},
        approved=True,
    )
    assert out["available"] is True
    assert out["dominant"] == "up"
    assert out["up"] == 0.5
    assert out["down"] == 0.3
    assert out["flat"] == 0.2
    assert out["approved"] is True


def test_model_probs_to_ui_output_none_input():
    out = mp._model_probs_to_ui_output(None, approved=True)
    assert out["available"] is False


def test_get_model_version_fail_closed_when_strict_bundle_blocked(monkeypatch):
    _strict_bundle_block(monkeypatch)
    mp._active_bundle_dir_cache.clear()
    mp._strict_bundle_warned.clear()
    assert mp.get_model_version("SPY") == "rules_v1"


@pytest.mark.parametrize("ticker", STRICT_BUNDLE_BLOCK_TICKERS)
def test_get_model_version_fail_closed_when_strict_bundle_blocked_ticker_agnostic(
    ticker, tmp_path, monkeypatch
):
    bundle_dir = _resolve_bundle_dir_for_ticker(ticker, tmp_path)
    _seed_stale_bundle_cache(ticker, bundle_dir)
    _strict_bundle_block(monkeypatch)
    polluted = mp.get_model_version(ticker)
    assert polluted != "rules_v1"
    assert polluted.startswith("stack(")
    mp._active_bundle_dir_cache.clear()
    mp._strict_bundle_warned.clear()
    assert mp.get_model_version(ticker) == "rules_v1"


def test_get_model_version_fail_closed_survives_compute_signals_cache_pollution(monkeypatch):
    _seed_index_682_spy_pollution_cache()
    _strict_bundle_block(monkeypatch)
    polluted = mp.get_model_version("SPY")
    assert polluted != "rules_v1"
    assert polluted.startswith("stack(")
    mp._active_bundle_dir_cache.clear()
    mp._strict_bundle_warned.clear()
    assert mp.get_model_version("SPY") == "rules_v1"


def test_load_xgb_fail_closed_when_strict_bundle_blocked(monkeypatch):
    def _raise(_ticker: str) -> Path:
        raise FileNotFoundError("strict bundle blocked")

    monkeypatch.setattr(mp, "_model_dir_for_ticker", _raise)
    mp._xgb_registry.clear()
    mp._active_bundle_dir_cache.clear()
    mp._strict_bundle_warned.clear()
    assert mp._load_xgb("SPY") is False


def test_predict_xgb_movement_heads_fail_closed_when_strict_bundle_blocked(monkeypatch):
    def _raise(_ticker: str) -> Path:
        raise FileNotFoundError("strict bundle blocked")

    monkeypatch.setattr(mp, "_model_dir_for_ticker", _raise)
    mp._xgb_movehead_registry.clear()
    mp._active_bundle_dir_cache.clear()
    mp._strict_bundle_warned.clear()
    out = mp._predict_xgb_movement_heads({"ticker": "SPY", "spot": 500.0}, "SPY")
    assert out == {}


def test_active_bundle_dir_for_load_warns_once_per_ticker_horizon(monkeypatch, caplog):
    import logging

    def _raise(_ticker: str) -> Path:
        raise FileNotFoundError("strict bundle blocked")

    monkeypatch.setattr(mp, "_model_dir_for_ticker", _raise)
    monkeypatch.setattr(mp, "_strict_bundle_block_detail", lambda _t, _h: "encoder v3 required")
    mp._active_bundle_dir_cache.clear()
    mp._strict_bundle_warned.clear()
    caplog.set_level(logging.WARNING, logger="ed_console.ml")
    assert mp._active_bundle_dir_for_load("SPY") is None
    assert mp._active_bundle_dir_for_load("SPY") is None
    warns = [r for r in caplog.records if r.levelno == logging.WARNING and "Active bundle blocked" in r.message]
    assert len(warns) == 1


def test_rc244_never_trained_ticker_logs_info_not_warning(monkeypatch, caplog):
    """RC-244: a ticker enrolled for market data but never trained has NO bundle dir.

    That is a configuration state the operator chose, not a runtime failure — AMD emitted this
    every serve and was the SOLE remaining cause of the quiet-window FAIL. Serve is still
    skipped; only the severity changes, and the line says why.
    """
    import logging

    def _raise(_ticker: str) -> Path:
        raise FileNotFoundError("missing bundle dir")

    monkeypatch.setattr(mp, "_model_dir_for_ticker", _raise)
    monkeypatch.setattr(mp, "_never_trained_ticker", lambda _t, _h: True)
    mp._active_bundle_dir_cache.clear()
    mp._strict_bundle_warned.clear()
    caplog.set_level(logging.INFO, logger="ed_console.ml")

    assert mp._active_bundle_dir_for_load("ZZNEW") is None, "serve must still be skipped"
    warns = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warns == [], f"never-trained ticker must not WARN: {[r.message for r in warns]}"
    infos = [r for r in caplog.records
             if r.levelno == logging.INFO and "never been trained" in r.getMessage()]
    assert len(infos) == 1, "the skip must still be VISIBLE, at INFO"


def test_rc244_broken_bundle_still_warns(monkeypatch, caplog):
    """The other half, and the one the PM's order protects: a ticker whose bundle EXISTS but
    fails the strict contract is a real regression and keeps its WARNING."""
    import logging

    def _raise(_ticker: str) -> Path:
        raise FileNotFoundError("strict bundle blocked")

    monkeypatch.setattr(mp, "_model_dir_for_ticker", _raise)
    monkeypatch.setattr(mp, "_never_trained_ticker", lambda _t, _h: False)
    monkeypatch.setattr(mp, "_strict_bundle_block_detail", lambda _t, _h: "encoder v3 required")
    mp._active_bundle_dir_cache.clear()
    mp._strict_bundle_warned.clear()
    caplog.set_level(logging.INFO, logger="ed_console.ml")

    assert mp._active_bundle_dir_for_load("SPY") is None
    warns = [r for r in caplog.records
             if r.levelno == logging.WARNING and "Active bundle blocked" in r.getMessage()]
    assert len(warns) == 1, "a BROKEN bundle must still WARN — demoting it would hide a regression"


def test_rc244_discriminator_reads_the_filesystem_not_the_message(monkeypatch):
    """The branch must ask whether the bundle dir EXISTS, not parse the exception text —
    message wording is not a contract."""
    hz = mp.get_ml_infer_horizon_slug()
    from active_bundle_contract import active_bundle_dir

    spy_dir = active_bundle_dir("SPY", hz, models_dir=mp.MODEL_DIR)
    if spy_dir.exists():
        assert mp._never_trained_ticker("SPY", hz) is False
    assert mp._never_trained_ticker("ZZ_NO_SUCH_TICKER", hz) is True

    def _boom(*_a, **_k):
        raise RuntimeError("path resolution broke")

    monkeypatch.setattr("active_bundle_contract.active_bundle_dir", _boom)
    assert mp._never_trained_ticker("ZZ_NO_SUCH_TICKER", hz) is False, (
        "unresolvable path must fall through to the LOUDER branch, never silence"
    )


def test_parallel_base_stack_complete_requires_all_legs():
    tri = {"up": 0.4, "down": 0.3, "flat": 0.3}
    assert mp._parallel_base_stack_complete(tri, tri, tri) is True
    assert mp._parallel_base_stack_complete(tri, tri, None) is False
    assert mp._parallel_base_stack_complete(tri, {"up": 0.5}, tri) is False


def test_weighted_average_fail_closed_on_partial_stack():
    tri = {"up": 0.4, "down": 0.3, "flat": 0.3}
    assert mp._weighted_average("SPY", tri, tri, None) is None


def test_weighted_average_partial_renormalizes_available_legs():
    """5c xgb_plus_transformer: blend xgb+tr without requiring lstm."""
    xgb = {"up": 0.8, "down": 0.1, "flat": 0.1}
    tr = {"up": 0.1, "down": 0.2, "flat": 0.7}
    got = mp._weighted_average_partial(
        "SPY",
        [("xgb", xgb, 0.40), ("transformer", tr, 0.25)],
    )
    wl, wt = 0.40 / 0.65, 0.25 / 0.65
    assert got == {
        "up": round(0.8 * wl + 0.1 * wt, 4),
        "down": round(0.1 * wl + 0.2 * wt, 4),
        "flat": round(0.1 * wl + 0.7 * wt, 4),
    }


def test_weighted_average_partial_fail_closed_when_no_healthy_legs():
    assert mp._weighted_average_partial("SPY", [("xgb", None, 0.40), ("transformer", None, 0.25)]) is None
    tri = {"up": 0.4, "down": 0.3}  # incomplete triplet
    assert mp._weighted_average_partial("SPY", [("xgb", tri, 0.40), ("transformer", None, 0.25)]) is None


def test_stack_probs_fail_closed_on_partial_stack():
    tri = {"up": 0.4, "down": 0.3, "flat": 0.3}
    assert mp._stack_probs(tri, tri, None) is None


def test_ensemble_parallel_probs_fail_closed_on_partial_stack():
    tri = {"up": 0.4, "down": 0.3, "flat": 0.3}
    assert mp._ensemble_parallel_probs("SPY", tri, None, tri) is None


# ── CLOSEOUT #3 — fusion meta<bases: collapsed-base exclusion in the combiner ──────────


def test_weighted_average_backcompat_identical_without_collapse():
    """No collapse flags => the prior fixed 0.40/0.35/0.25 weighting, byte-identical."""
    xgb = {"up": 0.8, "down": 0.1, "flat": 0.1}
    lstm = {"up": 0.2, "down": 0.5, "flat": 0.3}
    tr = {"up": 0.1, "down": 0.2, "flat": 0.7}
    got = mp._weighted_average("SPY", xgb, lstm, tr)
    exp = {
        "up": round(0.8 * 0.40 + 0.2 * 0.35 + 0.1 * 0.25, 4),
        "down": round(0.1 * 0.40 + 0.5 * 0.35 + 0.2 * 0.25, 4),
        "flat": round(0.1 * 0.40 + 0.3 * 0.35 + 0.7 * 0.25, 4),
    }
    assert got == exp


def test_weighted_average_drops_collapsed_base_and_renormalizes():
    """A collapsed (confident all-flat) XGB is excluded; LSTM/TR weights re-normalize."""
    xgb = {"up": 0.8, "down": 0.1, "flat": 0.1}  # confident — must NOT pull the result up
    lstm = {"up": 0.2, "down": 0.5, "flat": 0.3}
    tr = {"up": 0.1, "down": 0.2, "flat": 0.7}
    got = mp._weighted_average("SPY", xgb, lstm, tr, collapsed={"xgb"})
    wl, wt = 0.35 / 0.60, 0.25 / 0.60
    assert got["up"] == pytest.approx(round(0.2 * wl + 0.1 * wt, 4))
    assert got["down"] == pytest.approx(round(0.5 * wl + 0.2 * wt, 4))
    assert got["flat"] == pytest.approx(round(0.3 * wl + 0.7 * wt, 4))
    assert got["up"] < 0.2  # XGB's 0.8 up did not leak in


def test_weighted_average_all_collapsed_returns_uniform():
    tri = {"up": 0.4, "down": 0.3, "flat": 0.3}
    got = mp._weighted_average("SPY", tri, tri, tri, collapsed={"xgb", "lstm", "transformer"})
    assert got == mp._UNIFORM_PROBS


def test_read_stack_layer_collapse_flags(tmp_path):
    for base, flag in (("xgb", True), ("lstm", False), ("transformer", True)):
        (tmp_path / f"{base}_SPY_1c_meta.json").write_text(
            json.dumps({"val_single_class_collapse": flag}), encoding="utf-8"
        )
    assert mp.read_stack_layer_collapse_flags(tmp_path, "SPY", "1c") == {"xgb", "transformer"}


def test_read_stack_layer_collapse_flags_missing_and_bad_json(tmp_path):
    # only xgb present + flagged; lstm absent; transformer unreadable -> only xgb
    (tmp_path / "xgb_SPY_1c_meta.json").write_text(
        json.dumps({"val_single_class_collapse": True}), encoding="utf-8"
    )
    (tmp_path / "transformer_SPY_1c_meta.json").write_text("{not json", encoding="utf-8")
    assert mp.read_stack_layer_collapse_flags(tmp_path, "SPY", "1c") == {"xgb"}


def test_ensemble_all_collapsed_returns_uniform(monkeypatch):
    tri = {"up": 0.4, "down": 0.3, "flat": 0.3}
    monkeypatch.setattr(mp, "_active_base_collapse_flags", lambda t: {"xgb", "lstm", "transformer"})
    got = mp._ensemble_parallel_probs("SPY", tri, tri, tri)
    assert got == mp._UNIFORM_PROBS


def test_ensemble_backcompat_no_collapse_uses_weighted_average(monkeypatch):
    """No collapse + no meta => falls to the unchanged weighted average."""
    xgb = {"up": 0.8, "down": 0.1, "flat": 0.1}
    lstm = {"up": 0.2, "down": 0.5, "flat": 0.3}
    tr = {"up": 0.1, "down": 0.2, "flat": 0.7}
    monkeypatch.setattr(mp, "_active_base_collapse_flags", lambda t: set())
    monkeypatch.setattr(mp, "_predict_meta", lambda *a, **k: None)
    assert mp._ensemble_parallel_probs("SPY", xgb, lstm, tr) == mp._weighted_average("SPY", xgb, lstm, tr)


def test_ensemble_reports_weighted_fallback_instead_of_crediting_meta(monkeypatch):
    tri = {"up": 0.5, "down": 0.3, "flat": 0.2}
    monkeypatch.setattr(mp, "_active_base_collapse_flags", lambda _t: set())
    monkeypatch.setattr(mp, "_predict_meta", lambda *a, **k: None)
    probs, executed = mp._ensemble_parallel_probs_with_execution(
        "SPY", tri, tri, tri
    )
    assert probs == mp._weighted_average("SPY", tri, tri, tri)
    assert executed == "weighted_average_fallback"


def test_ensemble_reports_meta_only_when_meta_produced_the_triplet(monkeypatch):
    tri = {"up": 0.5, "down": 0.3, "flat": 0.2}
    meta = {"up": 0.6, "down": 0.2, "flat": 0.2}
    monkeypatch.setattr(mp, "_active_base_collapse_flags", lambda _t: set())
    monkeypatch.setattr(mp, "_predict_meta", lambda *a, **k: meta)
    probs, executed = mp._ensemble_parallel_probs_with_execution(
        "SPY", tri, tri, tri
    )
    assert probs == meta
    assert executed == "meta_stack"


def test_model_dir_live_ablation_experiment_uses_parallel(tmp_path, monkeypatch):
    from arch_competition.stack_bundle_eval_v1 import LIVE_ABLATION_EXPERIMENT_ENV

    monkeypatch.setenv(LIVE_ABLATION_EXPERIMENT_ENV, "1")
    monkeypatch.setattr(mp, "MODEL_DIR", tmp_path / "models")
    monkeypatch.setattr(mp, "get_ml_infer_horizon_slug", lambda: "1c")
    root = tmp_path / "models" / "parallel" / "SPY"
    root.mkdir(parents=True)
    for name in ("xgb_SPY_1c.pkl", "lstm_SPY_1c.pt", "transformer_SPY_1c.pt"):
        (root / name).write_bytes(b"x")
    got = mp._model_dir_for_ticker("SPY")
    assert got == root


def test_guest_anchor_bundle_scope_loads_anchor_artifacts(tmp_path, monkeypatch):
    """Guest ticker features use anchor promoted bundle paths (SPY weights on NVDA tick)."""
    from active_bundle_contract import active_bundle_dir

    monkeypatch.setenv("ED_XGB_STRICT_ACTIVE_ONLY", "1")
    monkeypatch.setattr(mp, "MODEL_DIR", tmp_path / "models")
    monkeypatch.setattr(mp, "get_ml_infer_horizon_slug", lambda: "1c")
    spy_dir = active_bundle_dir("SPY", "1c", models_dir=tmp_path / "models")
    spy_dir.mkdir(parents=True)
    # MODEL-04 serve policy: bundles must carry honest provenance; the fixture
    # mirrors the approved SPY vintage (trained_at 2026-06-04).
    import json as _json

    (spy_dir / "xgb_SPY_1c_meta.json").write_text(
        _json.dumps({"trained_at": "2026-06-04 04:29:57"}), encoding="utf-8"
    )
    import active_bundle_contract as abc

    monkeypatch.setattr(
        abc,
        "check_active_bundle_complete",
        lambda *a, **k: {"compliant": True},
    )
    with mp.ml_bundle_ticker_scope("SPY"):
        resolved = mp._model_dir_for_ticker("NVDA")
    assert resolved == spy_dir


def test_guest_anchor_resolve_and_prob_source_remap(monkeypatch):
    from governed_stack_contract import (
        GUEST_ANCHOR_AFFILIATION_IWM_SMALL_CAP,
        GUEST_ANCHOR_AFFILIATION_SPY_BROAD,
        MH_PROB_SOURCE_GUEST_ANCHOR,
        guest_anchor_inference_enabled,
        is_ml_authoritative_ticker,
        remap_prob_sources_for_guest_anchor,
        resolve_guest_anchor_for_ticker,
        resolve_guest_anchor_route,
        route_guest_anchor_weights_ticker,
    )

    monkeypatch.setenv("ED_GUEST_ANCHOR_INFERENCE", "1")
    assert guest_anchor_inference_enabled()
    assert is_ml_authoritative_ticker("SPY")
    assert resolve_guest_anchor_for_ticker("SPY") is None
    # v2: mega-cap sample names default to SPY (not QQQ_TOP shortcut).
    nvda_ctx = resolve_guest_anchor_for_ticker("NVDA")
    assert nvda_ctx is not None
    assert nvda_ctx.guest_ticker == "NVDA"
    assert nvda_ctx.anchor_ticker == "SPY"
    assert nvda_ctx.affiliation == GUEST_ANCHOR_AFFILIATION_SPY_BROAD
    assert route_guest_anchor_weights_ticker("NVDA") == "SPY"
    assert route_guest_anchor_weights_ticker("AAPL") == "SPY"
    # IWM sample holdings → IWM anchor.
    iwm_anchor, iwm_aff, _ = resolve_guest_anchor_route("BE")
    assert iwm_anchor == "IWM"
    assert iwm_aff == GUEST_ANCHOR_AFFILIATION_IWM_SMALL_CAP
    be_ctx = resolve_guest_anchor_for_ticker("BE")
    assert be_ctx is not None
    assert be_ctx.anchor_ticker == "IWM"
    # Sector ETFs are not IWM stock routing targets.
    assert route_guest_anchor_weights_ticker("KRE") == "SPY"
    remapped = remap_prob_sources_for_guest_anchor(
        {"1c": "fusion_ml_primary", "5c": "fusion_unavailable"}
    )
    assert remapped["1c"] == MH_PROB_SOURCE_GUEST_ANCHOR
    assert remapped["5c"] == "fusion_unavailable"


def test_guest_wire_sequence_context_from_live_snapshot():
    """Guest tickers with insufficient DB history must still build LSTM/TR surface bars."""
    from features.canonical_contract import get_mvp_feature_names
    from features.inference_snapshot import build_inference_snapshot_v1_from_feature_row
    from features.shared_sequence_context import build_guest_wire_sequence_context
    from lstm_data import STREAM_5M_LOOKBACK

    feats = {k: None for k in get_mvp_feature_names()}
    feats["price.spot"] = 118.5
    feats["price.spread_pts"] = 0.03
    feats["structure.zone"] = "pin_neutral"
    inf = build_inference_snapshot_v1_from_feature_row(
        ticker="XOM",
        expiry=None,
        as_of_ts=1_700_000_200.0,
        features=feats,
    )
    ctx, err = build_guest_wire_sequence_context(inf)
    assert err is None
    assert ctx is not None
    assert len(ctx.lstm_merged_window) == STREAM_5M_LOOKBACK
    assert ctx.meta.get("guest_wire_surface") is True


def test_prewarm_inference_models_for_ticker_all_horizons(monkeypatch):
    """UI-MAXIMIZE — prewarm loads all primary horizons without forward pass."""
    loaded: list[str] = []

    def _fake_load(_ticker: str) -> bool:
        loaded.append(f"xgb_{mp.get_ml_infer_horizon_slug()}")
        return True

    monkeypatch.setattr(mp, "_load_xgb", _fake_load)
    monkeypatch.setattr(mp, "_load_lstm", lambda _t: True)
    monkeypatch.setattr(mp, "_load_transformer", lambda _t: True)
    import governed_stack_contract as gsc

    monkeypatch.setattr(gsc, "resolve_guest_anchor_for_ticker", lambda _t: None)
    monkeypatch.setattr(gsc, "guest_anchor_context_scope", mp.ml_bundle_ticker_scope)

    out = mp.prewarm_inference_models_for_ticker("SPY")
    assert len(out) == 12
    assert all(v is True for v in out.values())
    assert len(loaded) == 4
