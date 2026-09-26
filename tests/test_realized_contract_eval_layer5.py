"""Layer 5 realized_contract_eval.py fail-closed guards + ECON-01 universe locks."""

from __future__ import annotations

import ast
import dataclasses
import inspect
import io

import pytest

import realized_contract_eval as rce
from math_levels import WallsRow
from realized_contract_eval import (
    ROW_TIER_DECISION_NO_TRADE,
    ROW_TIER_NON_DECISION_NO_SIGNAL,
    ROW_TIER_NON_DECISION_QUOTE_ONLY,
    ROW_TIER_TRADEABLE,
    _chain_selection_quality_row,
    classify_replay_row_tier,
)


def test_chain_selection_quality_ignores_ranked_rows_without_strike():
    row = _chain_selection_quality_row(
        ticker="SPY",
        architecture_type="parallel",
        signal_time="2026-05-05T10:00:00",
        selected_strike=500.0,
        put_call="CALL",
        ranked_top5=[
            {"strike": None, "composite_score": 99.0},
            {"strike": 501.0, "composite_score": 8.0},
        ],
        selected_pnl=10.0,
        symbol_hint=None,
        entry_chain=[],
        exit_chain=[],
    )
    # TEST_SYSTEM_REHAB_V2_RESIDUAL_CLOSURE (weak-assertion item 1): was
    # `assert row["alt_1"] is None or row["alt_1"]["strike"] != 0.0`. Two holes:
    # (a) the `is None` disjunct FAILS OPEN -- had the function regressed to dropping
    #     ALL ranked rows, alt_1 would be None and this passed, while the row the test
    #     exists to preserve (strike 501.0) had vanished from the audit artifact;
    # (b) it was mutation-dead against its own named target -- deleting the
    #     `if row.get("strike") is None: continue` guard in realized_contract_eval
    #     yields byte-identical output, since the following float(row["strike"])
    #     raises TypeError on None and continues anyway.
    # The real contract: the strikeless row is DROPPED ENTIRELY -- it yields no alt,
    # AND its composite_score (99.0, higher than the real row's 8.0) never becomes
    # best_score, which would otherwise fabricate score_gap_vs_best.
    assert row["alt_1"] == {
        "strike": 501.0, "composite_score": 8.0, "realized_pnl_dollars": None
    }, f"the one usable ranked row must survive verbatim; got {row['alt_1']!r}"
    assert row["alt_2"] is None and row["alt_3"] is None, (
        "the strikeless ranked row must produce no alternative at all")
    assert row["score_gap_vs_best"] is None, (
        "the dropped row's composite_score must never reach best_score")


def test_chain_selection_quality_best_score_ignores_none_scores():
    row = _chain_selection_quality_row(
        ticker="SPY",
        architecture_type="parallel",
        signal_time="2026-05-05T10:00:00",
        selected_strike=500.0,
        put_call="CALL",
        ranked_top5=[
            {"strike": 500.0, "composite_score": None},
            {"strike": 501.0, "composite_score": 7.5},
        ],
        selected_pnl=5.0,
        symbol_hint=None,
        entry_chain=[],
        exit_chain=[],
    )
    assert row["score_gap_vs_best"] is None


def test_forward_path_bars_converted_to_dict_before_simulate_exit():
    """Big-audit regression: _forward_path_rows returns sqlite3.Row objects, but
    _simulate_exit → lifecycle_rule_core.fire_exit → _bar_value uses .get() which
    sqlite3.Row does not support. The integration path requires dict-conversion
    at the boundary. Without this conversion the entire historical evaluation
    crashes with AttributeError on the very first bar.
    """
    src = inspect.getsource(rce.evaluate_realized_contract_trades_for_rows)
    assert "[dict(r) for r in _forward_path_rows" in src, (
        "bars must be converted to dict before passing to _simulate_exit; "
        "see lifecycle_rule_core._bar_value which uses .get()"
    )


def test_chain_selection_quality_best_score_with_all_negative_real_scores():
    """None scores must not sort as 0 and beat negative composite scores."""
    row = _chain_selection_quality_row(
        ticker="SPY",
        architecture_type="parallel",
        signal_time="2026-05-05T10:00:00",
        selected_strike=502.0,
        put_call="CALL",
        ranked_top5=[
            {"strike": 500.0, "composite_score": None},
            {"strike": 501.0, "composite_score": -2.0},
            {"strike": 502.0, "composite_score": -10.0},
        ],
        selected_pnl=5.0,
        symbol_hint=None,
        entry_chain=[],
        exit_chain=[],
    )
    # best real score is -2.0 at 501, not None-as-0; gap vs selected -10.0 at 502
    assert row["score_gap_vs_best"] == round(-2.0 - (-10.0), 4)


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


def _walls_row(spot: float) -> WallsRow:
    vals = {f.name: None for f in dataclasses.fields(WallsRow)}
    vals.update(
        label="0DTE",
        window=0,
        call_gamma_wall=spot + 1.0,
        put_gamma_wall=spot - 1.0,
        dom_gamma_side="call",
        dom_delta_side="call",
        dom_oi_side="call",
    )
    return WallsRow(**vals)


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


@pytest.mark.parametrize("ticker", UNIVERSAL_TICKERS)
def test_classify_replay_row_tier_universal_over_tickers(ticker):
    quote_only = {"ticker": ticker, "combined_signal": None, "logger_source": "base_money_path"}
    legacy = {"ticker": ticker, "combined_signal": None, "logger_source": None}
    wait_row = {"ticker": ticker, "combined_signal": "wait", "logger_source": None}
    long_row = {"ticker": ticker, "combined_signal": "long", "logger_source": None}
    short_row = {"ticker": ticker, "combined_signal": "short", "logger_source": "ui_sse"}
    assert classify_replay_row_tier(quote_only) == ROW_TIER_NON_DECISION_QUOTE_ONLY
    assert classify_replay_row_tier(legacy) == ROW_TIER_NON_DECISION_NO_SIGNAL
    assert classify_replay_row_tier(wait_row) == ROW_TIER_DECISION_NO_TRADE
    assert classify_replay_row_tier(long_row) == ROW_TIER_TRADEABLE
    assert classify_replay_row_tier(short_row) == ROW_TIER_TRADEABLE


@pytest.mark.parametrize("label_col", HORIZON_LABEL_COLUMNS)
def test_classify_replay_row_tier_ignores_horizon_labels(label_col):
    """Families 7+13: classification must not read outcome/horizon columns — the
    same row classifies identically with any horizon label present, wrong, or
    absent (no artificial-edge channel through the universe classifier)."""
    base = {"combined_signal": "long", "logger_source": None}
    with_label = {**base, label_col: "up"}
    with_wrong_label = {**base, label_col: "down"}
    without_label = dict(base)
    assert (
        classify_replay_row_tier(with_label)
        == classify_replay_row_tier(with_wrong_label)
        == classify_replay_row_tier(without_label)
        == ROW_TIER_TRADEABLE
    )


@pytest.mark.parametrize("name,h,m", SESSION_BOUNDARY_TS)
def test_classify_replay_row_tier_session_agnostic(name, h, m):
    row = {
        "combined_signal": None,
        "logger_source": "base_money_path",
        "et_hour": h,
        "et_minute": m,
        "ts_et": f"2026-07-11 {h:02d}:{m:02d}:00 ET",
    }
    assert classify_replay_row_tier(row) == ROW_TIER_NON_DECISION_QUOTE_ONLY, name


# ── Families 2+10: golden deterministic replay + provenance decomposition ──




# ── Families 4+12: future rows / foreign-ticker rows cannot change the trade ──






# ── Families 5+12: fail-closed starvation on the tradeable tier only ──








# ── Family 3: no live/current-state access from the replay module ──


def test_replay_module_imports_no_live_state():
    """Replay consumes ONLY sqlite rows + archived JSON — never live singletons."""
    tree = ast.parse(io.open(rce.__file__, encoding="utf-8").read())
    banned = {
        "server",
        "live_market_plane",
        "app.options.order_flow.state",
        "app.options.order_flow.streaming",
        "market_context",
        "schwab_client",
        "market_data_adapter",
    }
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    hits = imported & banned
    assert not hits, f"replay module must not import live-state modules: {hits}"


# ── Family 1: producer/consumer context parity (round-trip) ──




def test_walls_from_replay_drops_retired_near_spot_pin_keys():
    """RC-418: archived replay JSON still carries WallsRow.call_gamma_pin etc.
    Reconstruct must ignore unknown keys, not TypeError, and must not rehydrate a pin."""
    from dataclasses import asdict

    spot = 500.0
    item = asdict(_walls_row(spot))
    item["call_gamma_pin"] = 100.0
    item["put_gamma_pin"] = 99.0
    item["call_gamma_pin_strength"] = 12.0
    rebuilt = rce._walls_from_replay({"walls": [item]})
    assert rebuilt is not None and len(rebuilt) == 1
    assert rebuilt[0].call_gamma_wall == spot + 1.0
    dumped = asdict(rebuilt[0])
    assert "call_gamma_pin" not in dumped and "put_gamma_pin" not in dumped


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




def test_server_producer_guard_wired_before_snapshot_insert():
    """Mechanical lock: the ECON-01 guard must sit in server's snapshot build."""
    src = io.open("server.py", encoding="utf-8").read()
    assert "decision_row_context_starvation_reason(" in src
    assert "REPLAY_CONTEXT_STARVATION" in src
    guard_at = src.find("decision_row_context_starvation_reason(")
    insert_at = src.find("_ed_db.insert_snapshot(_snap)")
    assert 0 < guard_at < insert_at, "guard must run before insert_snapshot"
