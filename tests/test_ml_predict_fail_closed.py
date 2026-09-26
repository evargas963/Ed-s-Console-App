"""Fail-closed contracts for ml_predict model-probability → fusion/UI conversion."""
from __future__ import annotations

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




























def test_load_xgb_fail_closed_when_strict_bundle_blocked(monkeypatch):
    def _raise(_ticker: str) -> Path:
        raise FileNotFoundError("strict bundle blocked")

    monkeypatch.setattr(mp, "_model_dir_for_ticker", _raise)
    mp._xgb_registry.clear()
    mp._active_bundle_dir_cache.clear()
    mp._strict_bundle_warned.clear()
    assert mp._load_xgb("SPY") is False




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














# ── CLOSEOUT #3 — fusion meta<bases: collapsed-base exclusion in the combiner ──────────




















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








