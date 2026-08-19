"""Layer 5 realized_contract_eval.py fail-closed guards + ECON-01 universe locks."""

from __future__ import annotations

import ast
import dataclasses
import inspect
import io
import json
import sqlite3

import pytest

import realized_contract_eval as rce
from math_levels import WallsRow
from realized_contract_eval import (
    ROW_TIER_DECISION_NO_TRADE,
    ROW_TIER_NON_DECISION_NO_SIGNAL,
    ROW_TIER_NON_DECISION_QUOTE_ONLY,
    ROW_TIER_TRADEABLE,
    _chain_selection_quality_row,
    build_replay_context_payload,
    classify_replay_row_tier,
    decision_row_context_starvation_reason,
    evaluate_realized_contract_trades_for_rows,
    serialize_option_chain_for_eval,
)
from replay_hold_bars import replay_max_hold_bars_from_context


def test_replay_max_hold_bars_from_context_requires_explicit_value():
    assert replay_max_hold_bars_from_context({}) is None
    assert replay_max_hold_bars_from_context({"replay_max_hold_bars": None}) is None
    assert replay_max_hold_bars_from_context({"replay_max_hold_bars": 0}) is None
    assert replay_max_hold_bars_from_context({"replay_max_hold_bars": "bad"}) is None


def test_replay_max_hold_bars_from_context_accepts_valid_and_caps():
    assert replay_max_hold_bars_from_context({"replay_max_hold_bars": 15}) == 15
    assert replay_max_hold_bars_from_context({"replay_max_hold_bars": 500}) == 390


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
    assert row["alt_1"] is None or row["alt_1"]["strike"] != 0.0


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


def _golden_fixture(tmp_path, ticker="SPY", *, future_extra_rows=0, mixed_ticker_rows=0):
    """Temp sqlite snapshot table + one tradeable long row with full context and
    forward 1m bars whose second bar hits the target. Returns (db_path, rows_used,
    expected_expr)."""
    from market_state import recommend_option_expression
    from timeframe_config import CANONICAL_TIMEFRAME, SNAPSHOT_TABLE_1M

    tmp_path.mkdir(parents=True, exist_ok=True)
    spot = 500.0
    expiry = "2026-07-11"
    chain = _chain(spot, expiry)
    walls = [_walls_row(spot)]
    expr, _reasons, proof = recommend_option_expression(
        contracts=chain,
        spot=spot,
        call_signal="long",
        walls=walls,
        selected_expiry=expiry,
    )
    assert expr and not expr.upper().startswith("NO TRADE")

    replay_ctx = build_replay_context_payload(
        walls=walls,
        totals=[],
        option_chain_selection_proof=proof,
        regime_primary="trend",
        regime_confidence="high",
        zone="above_vwap",
        vol_regime="normal",
        trade_type="breakout",
        time_qualifier="early",
        replay_max_hold_bars_live=10,
        vwap=spot - 0.5,
        vwap_side="above",
    )
    chain_json = serialize_option_chain_for_eval(chain, expiry)
    assert chain_json

    db_path = str(tmp_path / "econ01_golden.db")
    conn = sqlite3.connect(db_path)
    conn.execute(
        f"""CREATE TABLE {SNAPSHOT_TABLE_1M} (
            snapshot_id INTEGER PRIMARY KEY,
            ticker TEXT, timeframe TEXT, ts_utc REAL, ts_et TEXT,
            candle_open REAL, candle_high REAL, candle_low REAL, candle_close REAL,
            spot REAL, option_chain_json TEXT)"""
    )
    t0 = 1_780_000_000.0
    exit_chain = json.dumps(
        [
            {**ct, "bid": (ct["bid"] + 0.40) if ct["putCall"] == "CALL" else ct["bid"]}
            for ct in chain
        ]
    )
    fwd = [
        # bar 1: drifts up, no touch (stop 499, target 501.5)
        (2, ticker, t0 + 60, "2026-07-11 09:31:00 ET", 500.0, 500.9, 499.8, 500.7, 500.7, exit_chain),
        # bar 2: target hit
        (3, ticker, t0 + 120, "2026-07-11 09:32:00 ET", 500.7, 501.8, 500.4, 501.6, 501.6, exit_chain),
    ]
    for i in range(future_extra_rows):
        fwd.append(
            (10 + i, ticker, t0 + 300 + 60 * i, f"2026-07-11 09:{35 + i}:00 ET",
             480.0, 480.1, 479.0, 479.5, 479.5, exit_chain)
        )
    for i in range(mixed_ticker_rows):
        fwd.append(
            (50 + i, "ZZOTHER", t0 + 90, "2026-07-11 09:31:30 ET",
             1.0, 1.0, 1.0, 1.0, 1.0, exit_chain)
        )
    conn.executemany(
        f"INSERT INTO {SNAPSHOT_TABLE_1M} (snapshot_id, ticker, timeframe, ts_utc, ts_et, "
        "candle_open, candle_high, candle_low, candle_close, spot, option_chain_json) "
        f"VALUES (?, ?, '{CANONICAL_TIMEFRAME}', ?, ?, ?, ?, ?, ?, ?, ?)",
        [(r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8], r[9]) for r in fwd],
    )
    conn.commit()
    conn.close()

    signal_row = {
        "snapshot_id": 1,
        "ticker": ticker,
        "ts_utc": t0,
        "ts_et": "2026-07-11 09:30:00 ET",
        "expiry": expiry,
        "spot": spot,
        "combined_signal": "long",
        "logger_source": None,
        "option_chain_json": chain_json,
        "replay_context_json": replay_ctx,
        "rules_entry": spot,
        "rules_stop": 499.0,
        "rules_target": 501.5,
    }
    return db_path, [signal_row], expr


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


def test_golden_replay_deterministic_trade_and_universe_decomposition(tmp_path, monkeypatch):
    _redirect_artifacts(tmp_path, monkeypatch)
    db_path, rows, _expr = _golden_fixture(tmp_path / "g")
    rows = rows + [
        {"combined_signal": None, "logger_source": "base_money_path", "ticker": "SPY"},
        {
            "combined_signal": "wait",
            "logger_source": "ui_sse",
            "ticker": "SPY",
            "snapshot_id": 99,
            "ts_utc": 1_780_000_000.0,
            "ts_et": "x",
            "expiry": None,
            "spot": 500.0,
        },
    ]
    agg1 = evaluate_realized_contract_trades_for_rows(db_path, "SPY", "parallel", list(rows))
    agg2 = evaluate_realized_contract_trades_for_rows(db_path, "SPY", "parallel", list(rows))

    for agg in (agg1, agg2):
        assert agg["universe_rows_total"] == 3
        assert agg["non_decision_row_counts"] == {ROW_TIER_NON_DECISION_QUOTE_ONLY: 1}
        assert agg["decision_no_trade_rows"] == 1
        assert agg["tradeable_signal_rows"] == 1
        assert agg["total_signals"] == 1
        assert agg["valid_trade_count"] == 1
        assert agg["skipped_trade_count"] == 0
        assert agg["skip_rate"] == 0.0
        assert agg["execution_economics_measurable"] is True
        assert agg["skip_rate_fail_flag"] is False
        assert agg["evaluation_quality_degraded"] is False
    assert agg1["total_pnl_dollars"] == agg2["total_pnl_dollars"]
    assert agg1["total_pnl_dollars"] is not None


# ── Families 4+12: future rows / foreign-ticker rows cannot change the trade ──


def test_future_rows_beyond_exit_do_not_change_trade(tmp_path, monkeypatch):
    _redirect_artifacts(tmp_path, monkeypatch)
    db_a, rows_a, _ = _golden_fixture(tmp_path / "a", future_extra_rows=0)
    db_b, rows_b, _ = _golden_fixture(tmp_path / "b", future_extra_rows=5)
    agg_a = evaluate_realized_contract_trades_for_rows(db_a, "SPY", "parallel", rows_a)
    agg_b = evaluate_realized_contract_trades_for_rows(db_b, "SPY", "parallel", rows_b)
    assert agg_a["valid_trade_count"] == agg_b["valid_trade_count"] == 1
    assert agg_a["total_pnl_dollars"] == agg_b["total_pnl_dollars"]


def test_mixed_ticker_rows_never_enter_forward_path(tmp_path, monkeypatch):
    _redirect_artifacts(tmp_path, monkeypatch)
    db_a, rows_a, _ = _golden_fixture(tmp_path / "a", mixed_ticker_rows=0)
    db_b, rows_b, _ = _golden_fixture(tmp_path / "b", mixed_ticker_rows=3)
    agg_a = evaluate_realized_contract_trades_for_rows(db_a, "SPY", "parallel", rows_a)
    agg_b = evaluate_realized_contract_trades_for_rows(db_b, "SPY", "parallel", rows_b)
    assert agg_a["total_pnl_dollars"] == agg_b["total_pnl_dollars"]
    assert agg_b["valid_trade_count"] == 1


# ── Families 5+12: fail-closed starvation on the tradeable tier only ──


def test_tradeable_row_missing_context_is_real_starvation_skip(tmp_path, monkeypatch):
    _redirect_artifacts(tmp_path, monkeypatch)
    db_path, rows, _ = _golden_fixture(tmp_path / "g")
    starved = dict(rows[0])
    starved["replay_context_json"] = None
    corrupt = dict(rows[0])
    corrupt["replay_context_json"] = "{not json"
    agg = evaluate_realized_contract_trades_for_rows(
        db_path, "SPY", "parallel", [starved, corrupt]
    )
    assert agg["tradeable_signal_rows"] == 2
    assert agg["valid_trade_count"] == 0
    assert agg["skip_reason_counts"] == {
        "missing_replay_context": 1,
        "replay_context_invalid": 1,
    }
    assert agg["skip_rate"] == 1.0
    assert agg["skip_rate_fail_flag"] is True
    assert agg["skip_reason_counts_coarse"]["missing_replay_context"] == 2


def test_wait_rows_never_demand_replay_context(tmp_path, monkeypatch):
    """A no-trade decision without context is NOT starvation — nothing to replay."""
    _redirect_artifacts(tmp_path, monkeypatch)
    db_path, _rows, _ = _golden_fixture(tmp_path / "g")
    wait_no_ctx = {
        "combined_signal": "wait",
        "logger_source": None,
        "ticker": "SPY",
        "snapshot_id": 7,
        "ts_utc": 1_780_000_000.0,
        "ts_et": "x",
        "expiry": None,
        "spot": 500.0,
        "replay_context_json": None,
        "option_chain_json": None,
    }
    agg = evaluate_realized_contract_trades_for_rows(db_path, "SPY", "parallel", [wait_no_ctx])
    assert agg["decision_no_trade_rows"] == 1
    assert agg["tradeable_signal_rows"] == 0
    assert agg["skipped_trade_count"] == 0
    assert agg["skip_rate"] is None
    assert agg["execution_economics_measurable"] is False
    assert agg["skip_rate_fail_flag"] is False


def test_replay_selection_mismatch_reconstruction_gate(tmp_path, monkeypatch):
    """Family 11: replay must reconcile with the persisted live selection proof."""
    _redirect_artifacts(tmp_path, monkeypatch)
    db_path, rows, _ = _golden_fixture(tmp_path / "g")
    row = dict(rows[0])
    ctx = json.loads(row["replay_context_json"])
    ctx["option_chain_selection_proof"]["winner"] = {"expression": "9999.0 CALL"}
    row["replay_context_json"] = json.dumps(ctx)
    agg = evaluate_realized_contract_trades_for_rows(db_path, "SPY", "parallel", [row])
    assert agg["skip_reason_counts"] == {"replay_selection_mismatch": 1}
    assert agg["valid_trade_count"] == 0


# ── Family 3: no live/current-state access from the replay module ──


def test_replay_module_imports_no_live_state():
    """Replay consumes ONLY sqlite rows + archived JSON — never live singletons."""
    tree = ast.parse(io.open(rce.__file__, encoding="utf-8").read())
    banned = {
        "server",
        "live_market_plane",
        "order_flow_live_state",
        "order_flow_streaming",
        "market_context",
        "schwab_client",
        "market_data_adapter",
    }
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    hits = imported & banned
    assert not hits, f"replay module must not import live-state modules: {hits}"


# ── Family 1: producer/consumer context parity (round-trip) ──


def test_replay_context_payload_round_trips_walls_hold_and_proof():
    spot = 500.0
    walls = [_walls_row(spot)]
    payload = build_replay_context_payload(
        walls=walls,
        totals=[],
        option_chain_selection_proof={"winner": {"expression": "500.0 CALL"}},
        regime_primary="trend",
        regime_confidence="high",
        zone="above_vwap",
        vol_regime="normal",
        trade_type="breakout",
        time_qualifier="early",
        replay_max_hold_bars_live=10,
        vwap=499.5,
        vwap_side="above",
    )
    obj = json.loads(payload)
    rebuilt = rce._walls_from_replay(obj)
    assert rebuilt is not None and len(rebuilt) == 1
    assert rebuilt[0].call_gamma_wall == walls[0].call_gamma_wall
    assert replay_max_hold_bars_from_context(obj) == 10
    assert obj["option_chain_selection_proof"]["winner"]["expression"] == "500.0 CALL"
    assert obj["regime_primary"] == "trend" and obj["vol_regime"] == "normal"


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


def test_decision_row_context_starvation_reason_matrix():
    ok_ctx = "x" * 200
    assert decision_row_context_starvation_reason(
        combined_signal="long", replay_context_json=None, option_chain_json=ok_ctx
    ) == "tradeable_missing_replay_context"
    assert decision_row_context_starvation_reason(
        combined_signal="short", replay_context_json=ok_ctx, option_chain_json=None
    ) == "tradeable_missing_option_chain"
    assert decision_row_context_starvation_reason(
        combined_signal="long", replay_context_json=ok_ctx, option_chain_json=ok_ctx
    ) is None
    assert decision_row_context_starvation_reason(
        combined_signal=None, replay_context_json=None, option_chain_json=None
    ) is None
    assert decision_row_context_starvation_reason(
        combined_signal="wait", replay_context_json=None, option_chain_json=None
    ) is None


def test_server_producer_guard_wired_before_snapshot_insert():
    """Mechanical lock: the ECON-01 guard must sit in server's snapshot build."""
    src = io.open("server.py", encoding="utf-8").read()
    assert "decision_row_context_starvation_reason(" in src
    assert "REPLAY_CONTEXT_STARVATION" in src
    guard_at = src.find("decision_row_context_starvation_reason(")
    insert_at = src.find("_ed_db.insert_snapshot(_snap)")
    assert 0 < guard_at < insert_at, "guard must run before insert_snapshot"
