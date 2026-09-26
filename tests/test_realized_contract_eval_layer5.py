"""Layer 5 realized_contract_eval.py fail-closed guards + ECON-01 universe locks."""

from __future__ import annotations

import inspect












# ═══════════════════ ECON-01 replay-context starvation closure ═══════════════════
# Root cause (measured 2026-07-11): evaluation universe = labeled RTH training
# rows, which includes quote-only base_money_path rows and legacy no-signal rows;
# the eval counted every one as a skipped "signal" (89% missing_replay_context)
# while 100% of true long/short signals in the trailing 30 days (1,263/1,263)
# carried full context. These tests lock the denominator-first universe
# classification, fail-closed starvation semantics, point-in-time isolation,
# and the producer guard.

UNIVERSAL_TICKERS = ("SPY", "QQQ", "IWM", "NFLX", "PCG")
HORIZON_LABEL_COLUMNS = ("outcome_dir_1c", "outcome_dir_5c", "outcome_dir_15c", "outcome_dir_60c")
SESSION_BOUNDARY_TS = (
    ("premarket", 7, 15),
    ("rth_open", 9, 30),
    ("rth_close", 15, 59),
    ("after_hours", 17, 45),
)




def _chain(spot: float, expiry: str) -> list[dict]:
    # institutional-synthetic-ok: golden end-to-end eval test needs a controlled tradeable
    # setup (chain + walls + forward bars engineered to hit the target) — not real-sourceable.
    rows = []
    for k in (-1.0, 0.0, 1.0):
        strike = spot + k
        rows.append(
            {
                "putCall": "CALL",
                "strikePrice": strike,
                "bid": 1.00,
                "ask": 1.10,
                "openInterest": 500,
                "totalVolume": 200,
                "delta": 0.5,
                "gamma": 0.02,
                "multiplier": 100,
                "symbol": f"TCALL{int(strike)}",
                "expirationDate": expiry,
            }
        )
        rows.append(
            {
                "putCall": "PUT",
                "strikePrice": strike,
                "bid": 0.90,
                "ask": 1.00,
                "openInterest": 500,
                "totalVolume": 200,
                "delta": -0.5,
                "gamma": 0.02,
                "multiplier": 100,
                "symbol": f"TPUT{int(strike)}",
                "expirationDate": expiry,
            }
        )
    return rows


def _redirect_artifacts(tmp_path, monkeypatch):
    for name in ("TRADE_LOG_PARALLEL", "TRADE_LOG_CASCADE", "TRADE_LOG_LEGACY"):
        monkeypatch.setattr(f"realized_contract_eval.{name}", tmp_path / f"{name}.csv")
    monkeypatch.setattr("realized_contract_eval.CHAIN_DEBUG_JSON", tmp_path / "dbg.json")
    monkeypatch.setattr("realized_contract_eval.CHAIN_QUALITY_JSON", tmp_path / "q.json")
    monkeypatch.setattr("realized_contract_eval.COVERAGE_REPORT_JSON", tmp_path / "cov.json")




# ── Families 6+7+8+13: classification is ticker/horizon/session/label agnostic ──








# ── Families 2+10: golden deterministic replay + provenance decomposition ──




# ── Families 4+12: future rows / foreign-ticker rows cannot change the trade ──






# ── Families 5+12: fail-closed starvation on the tradeable tier only ──








# ── Family 3: no live/current-state access from the replay module ──




# ── Family 1: producer/consumer context parity (round-trip) ──






# ── Family 9: model-version pinning source lock (scheduler eval paths) ──


def test_scheduler_eval_pins_and_restores_model_dir():
    import ml_scheduler

    for fn in (
        ml_scheduler._evaluate_parallel_on_full_rth,
        ml_scheduler._evaluate_cascade_on_full_rth,
    ):
        s = inspect.getsource(fn)
        assert "mp.MODEL_DIR = model_dir" in s, "candidate eval must pin the explicit model dir"
        assert "mp.MODEL_DIR = orig_dir" in s, "candidate eval must restore the prior model dir"
        assert "set_ml_infer_horizon_slug" in s, "candidate eval must pin the horizon slug"


# ── Producer guard: tradeable rows persisting without context fail LOUD ──




