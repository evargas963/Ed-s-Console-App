"""
Realized contract-level options PnL for ML evaluation (no delta proxy).

REPLAY (100% decision path):
  - Loads replay_context_json from snapshot: walls, totals, regime, persisted OE proof, max hold.
  - Re-runs market_state.recommend_option_expression with archived chain + walls (never walls=None).
          If optional live proof present and expression disagrees → skip (replay_selection_mismatch).
  - Exit matches Call plan on underlying: rules_entry / rules_stop / rules_target with 1m OHLC path;
    options priced bid@exit_bar (ask@entry). Intrabar stop+target: stop assumed first (conservative).
  - exit_reason: stop_hit | target_hit | time_expiry

Logs:
  models/realized_contract_trade_log_parallel.csv
  models/realized_contract_trade_log_cascade.csv
"""
from __future__ import annotations

import csv
import json
import logging
import sqlite3
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any, Optional

from chains import contract_fields
from market_state import recommend_option_expression
from math_levels import WallsRow, TotalsRow
from timeframe_config import CANONICAL_TIMEFRAME, SNAPSHOT_TABLE_1M

log = logging.getLogger(__name__)

OPTION_MULTIPLIER = 100
DEFAULT_CONTRACTS = 1

PRICING_ENTRY_RULE = "entry_price = ask (debit to open long option)"
PRICING_EXIT_RULE = "exit_price = bid (credit to close long option)"
EXIT_RULE_DOC = (
    "Underlying path vs snapshot rules_stop/rules_target on forward 1m OHLC; "
    "if neither hits within replay_max_hold_bars → time_expiry (bars from Call card via "
    "call_engine.replay_max_hold_bars_for_setup, stored in replay_context_json). "
    "Same-bar stop+target: candle_open/close body-direction ordering when available; "
    "else conservative stop-first. Option priced bid/ask at exit/entry bar."
)

# Skip-rate quality gates (evaluation trust)
SKIP_RATE_WARNING_THRESHOLD = 0.35
SKIP_RATE_FAIL_THRESHOLD = 0.55

APP_DIR = Path(__file__).resolve().parent
TRADE_LOG_PARALLEL = APP_DIR / "models" / "realized_contract_trade_log_parallel.csv"
TRADE_LOG_CASCADE = APP_DIR / "models" / "realized_contract_trade_log_cascade.csv"
TRADE_LOG_LEGACY = APP_DIR / "models" / "realized_contract_trade_log.csv"
CHAIN_DEBUG_JSON = APP_DIR / "models" / "option_chain_selection_debug.json"
CHAIN_QUALITY_JSON = APP_DIR / "models" / "chain_selection_quality_audit.json"
COVERAGE_REPORT_JSON = APP_DIR / "models" / "replay_coverage_report.json"
AGGREGATE_JSON = APP_DIR / "models" / "realized_contract_eval_aggregate.json"

TRADE_LOG_FIELDS = [
    "architecture_type",
    "ticker",
    "signal_time",
    "entry_time",
    "exit_time",
    "right",
    "strike",
    "expiry",
    "contract_symbol",
    "entry_price",
    "exit_price",
    "contracts",
    "multiplier",
    "pnl_dollars",
    "pnl_percent",
    "exit_reason",
    "hold_bars",
    "rules_entry",
    "rules_stop",
    "rules_target",
    "skipped_flag",
    "skipped_reason",
    "snapshot_id_entry",
    "snapshot_id_exit",
    "pricing_entry_rule",
    "pricing_exit_rule",
    "path_model_used",
    "same_bar_stop_target_conflict_flag",
    "same_bar_resolution_rule",
]

_COARSE_BUCKETS = (
    "no_option_chain_archive",
    "no_exit_snapshot",
    "missing_bid_ask",
    "no_contract_selected",
    "missing_replay_context",
    "other",
)


def replay_max_hold_bars_for_trade_type(trade_type: str | None) -> int:
    t = (trade_type or "").strip().lower()
    if t == "trend_continuation":
        return 60
    if t == "breakout":
        return 15
    if t == "reversal":
        return 20
    if t in ("fade", "mean_reversion"):
        return 30
    if t == "none":
        return 20
    return 30


def trade_log_path_for_architecture(architecture_type: str) -> Path:
    u = (architecture_type or "").strip().lower()
    if u == "cascade":
        return TRADE_LOG_CASCADE
    if u == "parallel":
        return TRADE_LOG_PARALLEL
    return TRADE_LOG_LEGACY


def trade_log_path(architecture_type: str = "parallel") -> Path:
    p = trade_log_path_for_architecture(architecture_type)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def aggregate_path() -> Path:
    AGGREGATE_JSON.parent.mkdir(parents=True, exist_ok=True)
    return AGGREGATE_JSON


def serialize_option_chain_for_eval(contracts: list, selected_exp: str | None) -> str | None:
    """Persist minimal contract rows for historical replay (same keys as scoring path)."""
    if not contracts or not selected_exp:
        return None
    exp_key = str(selected_exp)[:10]
    out: list[dict[str, Any]] = []
    for ct in contracts:
        normalized = _replay_contract_fields(ct)
        raw_exp = normalized.get("expirationDate") or ""
        if str(raw_exp)[:10] != exp_key:
            continue
        out.append(normalized)
    if not out:
        return None
    return json.dumps(out, default=str)


def build_replay_context_payload(
    *,
    walls: list,
    totals: list,
    option_chain_selection_proof: dict | None,
    regime_primary: str | None,
    regime_confidence: str | None,
    zone: str | None,
    vol_regime: str | None,
    trade_type: str | None,
    time_qualifier: str | None,
    replay_max_hold_bars_live: int | None = None,
    vwap: float | None,
    vwap_side: str | None,
) -> str:
    """Called from server when logging a snapshot (JSON string for DB)."""
    wall_dicts: list[dict[str, Any]] = []
    for w in walls or []:
        if isinstance(w, WallsRow):
            wall_dicts.append(asdict(w))
        elif isinstance(w, dict):
            wall_dicts.append(w)
    total_dicts: list[dict[str, Any]] = []
    for t in totals or []:
        if isinstance(t, TotalsRow):
            total_dicts.append(asdict(t))
        elif isinstance(t, dict):
            total_dicts.append(t)
    hold_fb = replay_max_hold_bars_for_trade_type(trade_type)
    try:
        live = int(replay_max_hold_bars_live) if replay_max_hold_bars_live is not None else None
    except (TypeError, ValueError):
        live = None
    if live is not None and live > 0:
        hold_resolved = live
        hold_src = "call_card"
    else:
        hold_resolved = hold_fb
        hold_src = "trade_type_fallback"
    payload = {
        "version": 1,
        "walls": wall_dicts,
        "totals": total_dicts,
        "regime_primary": regime_primary,
        "regime_confidence": regime_confidence,
        "zone": zone,
        "vol_regime": vol_regime,
        "call_trade_type": trade_type,
        "time_qualifier": time_qualifier,
        "replay_max_hold_bars": hold_resolved,
        "replay_max_hold_bars_source": hold_src,
        "replay_max_hold_bars_fallback": hold_fb,
        "replay_time_expiry_policy": (
            f"max_forward_1m_bars={hold_resolved}; source={hold_src}; "
            f"time_qualifier={time_qualifier!r}; trade_type={trade_type!r}; "
            f"fallback_bars_if_card_missing={hold_fb}"
        ),
        "replay_entry_policy": (
            "option_leg_long_at_signal_snapshot: entry_price=ask on chain row matching "
            "recommend_option_expression strike/side; underlying reference=spot at signal."
        ),
        "replay_exit_policy": (
            "underlying levels rules_stop/rules_target vs forward 1m bars; option leg exit_bid on "
            "exit_bar chain; same_bar_stop_target uses candle_open/close body direction when both "
            "OHLC present, else conservative_stop_first; time_expiry after max_forward bars."
        ),
        "vwap": vwap,
        "vwap_side": vwap_side,
        "option_chain_selection_proof": option_chain_selection_proof,
    }
    return json.dumps(payload, default=str)


def _f(v) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _walls_from_replay(obj: dict) -> list[WallsRow] | None:
    raw = obj.get("walls")
    if not isinstance(raw, list) or len(raw) == 0:
        return None
    out: list[WallsRow] = []
    for item in raw:
        if not isinstance(item, dict):
            return None
        try:
            out.append(WallsRow(**item))
        except (TypeError, ValueError):
            return None
    return out


def _forward_path_rows(
    conn: sqlite3.Connection,
    table: str,
    ticker: str,
    after_ts: float,
    limit: int,
) -> list[sqlite3.Row]:
    cur = conn.execute(
        f"""
        SELECT snapshot_id, ts_utc, ts_et, candle_open, candle_high, candle_low,
               candle_close, spot, option_chain_json
        FROM {table}
        WHERE ticker = ? AND timeframe = ? AND ts_utc > ?
        ORDER BY ts_utc ASC
        LIMIT ?
        """,
        (ticker, CANONICAL_TIMEFRAME, after_ts, limit),
    )
    return cur.fetchall()


def _find_contract_row(chain: list[dict], *, strike: float, put_call: str, symbol_hint: str | None) -> Optional[dict]:
    pc = put_call.upper().strip()
    if symbol_hint:
        for ct in chain:
            if str(ct.get("symbol") or "") == symbol_hint:
                return _replay_contract_fields(ct)
    for ct in chain:
        if str(ct.get("putCall") or "").upper().strip() != pc:
            continue
        sp = _f(ct.get("strikePrice"))
        if sp is not None and abs(sp - float(strike)) < 0.011:
            return _replay_contract_fields(ct)
    return None


def _replay_contract_fields(ct: dict) -> dict:
    """Normalize one contract for replay while excluding raw payload passthrough."""
    normalized = contract_fields(ct)
    normalized.pop("raw", None)
    return normalized


def _normalize_contract_chain(chain: list[dict]) -> list[dict]:
    """Normalize archived option-chain rows through the Schwab contract accessor."""
    return [_replay_contract_fields(ct) for ct in chain if isinstance(ct, dict)]


def _parse_expression(expr: str) -> Optional[tuple[float, str]]:
    parts = (expr or "").strip().split()
    if len(parts) < 2:
        return None
    try:
        return float(parts[0]), parts[1].upper()
    except (TypeError, ValueError):
        return None


def _expressions_match_live(replay_expr: str, proof: dict | None) -> bool:
    if not proof:
        return False
    win = proof.get("winner") or {}
    live_e = win.get("expression")
    if not live_e:
        return False
    a = _parse_expression(replay_expr)
    b = _parse_expression(str(live_e))
    if a and b:
        return abs(a[0] - b[0]) < 0.02 and a[1] == b[1]
    return (replay_expr or "").strip().upper() == str(live_e).strip().upper()


def _simulate_exit(
    *,
    call_signal: str,
    stop: float | None,
    target: float | None,
    bars: list[sqlite3.Row],
) -> dict[str, Any]:
    """
    Exit simulation with explicit path metadata. Uses OHLC body-direction ordering when
    open+close exist on the exit bar; otherwise conservative stop-first for same-bar conflicts.
    """
    out: dict[str, Any] = {
        "exit_reason": None,
        "exit_row": None,
        "hold_bars": None,
        "skip_reason": None,
        "path_model_used": "none",
        "same_bar_stop_target_conflict": False,
        "same_bar_resolution_rule": "",
    }
    sig = (call_signal or "").strip().lower()
    if not bars:
        out["skip_reason"] = "no_exit_snapshot"
        return out
    if sig not in ("long", "short"):
        out["skip_reason"] = "invalid_call_signal_for_path"
        return out
    if stop is None or target is None:
        out["skip_reason"] = "missing_stop_target_for_exit"
        return out

    for i, bar in enumerate(bars):
        hi = _f(bar["candle_high"])
        lo = _f(bar["candle_low"])
        if hi is None or lo is None:
            out["skip_reason"] = "missing_ohlc_forward_path"
            return out

        co = _f(bar["candle_open"]) if "candle_open" in bar.keys() else None
        cc = _f(bar["candle_close"]) if "candle_close" in bar.keys() else None

        if sig == "long":
            stop_hit = lo <= float(stop)
            tgt_hit = hi >= float(target)
            if stop_hit and tgt_hit:
                out["same_bar_stop_target_conflict"] = True
                if co is not None and cc is not None:
                    out["path_model_used"] = "ohlc_body_direction_intrabar_order"
                    if cc >= co:
                        out["same_bar_resolution_rule"] = (
                            "bull_bar_assume_extreme_low_before_high_stop_priority"
                        )
                        _reason = "stop_hit"
                    else:
                        out["same_bar_resolution_rule"] = (
                            "bear_bar_assume_extreme_high_before_low_target_priority"
                        )
                        _reason = "target_hit"
                else:
                    out["path_model_used"] = "ohlc_stop_priority_no_open_close"
                    out["same_bar_resolution_rule"] = "conservative_stop_first_missing_body"
                    _reason = "stop_hit"
                out["exit_reason"] = _reason
                out["exit_row"] = bar
                out["hold_bars"] = i + 1
                return out
            if stop_hit:
                out["path_model_used"] = "ohlc_first_touch_sequential_bars"
                out["exit_reason"] = "stop_hit"
                out["exit_row"] = bar
                out["hold_bars"] = i + 1
                return out
            if tgt_hit:
                out["path_model_used"] = "ohlc_first_touch_sequential_bars"
                out["exit_reason"] = "target_hit"
                out["exit_row"] = bar
                out["hold_bars"] = i + 1
                return out
        else:
            stop_hit = hi >= float(stop)
            tgt_hit = lo <= float(target)
            if stop_hit and tgt_hit:
                out["same_bar_stop_target_conflict"] = True
                if co is not None and cc is not None:
                    out["path_model_used"] = "ohlc_body_direction_intrabar_order"
                    if cc >= co:
                        out["same_bar_resolution_rule"] = (
                            "bull_bar_assume_low_before_high_short_target_before_stop"
                        )
                        _reason = "target_hit"
                    else:
                        out["same_bar_resolution_rule"] = (
                            "bear_bar_assume_high_before_low_short_stop_before_target"
                        )
                        _reason = "stop_hit"
                else:
                    out["path_model_used"] = "ohlc_stop_priority_no_open_close"
                    out["same_bar_resolution_rule"] = "conservative_stop_first_missing_body"
                    _reason = "stop_hit"
                out["exit_reason"] = _reason
                out["exit_row"] = bar
                out["hold_bars"] = i + 1
                return out
            if stop_hit:
                out["path_model_used"] = "ohlc_first_touch_sequential_bars"
                out["exit_reason"] = "stop_hit"
                out["exit_row"] = bar
                out["hold_bars"] = i + 1
                return out
            if tgt_hit:
                out["path_model_used"] = "ohlc_first_touch_sequential_bars"
                out["exit_reason"] = "target_hit"
                out["exit_row"] = bar
                out["hold_bars"] = i + 1
                return out

    out["path_model_used"] = "ohlc_time_expiry_max_hold"
    out["exit_reason"] = "time_expiry"
    out["exit_row"] = bars[-1]
    out["hold_bars"] = len(bars)
    return out


def _contract_pnl_at_horizon(
    *,
    strike: float,
    put_call: str,
    entry_chain: list[dict],
    exit_chain: list[dict],
    symbol_hint: str | None,
) -> float | None:
    en = _find_contract_row(entry_chain, strike=strike, put_call=put_call, symbol_hint=None)
    ex = _find_contract_row(
        exit_chain, strike=strike, put_call=put_call, symbol_hint=symbol_hint,
    )
    if not en or not ex:
        return None
    a = _f(en.get("ask"))
    b = _f(ex.get("bid"))
    if a is None or a <= 0 or b is None:
        return None
    return (b - a) * OPTION_MULTIPLIER * DEFAULT_CONTRACTS


def _chain_selection_quality_row(
    *,
    ticker: str,
    architecture_type: str,
    signal_time: Any,
    selected_strike: float,
    put_call: str,
    ranked_top5: list[dict] | None,
    selected_pnl: float,
    symbol_hint: str | None,
    entry_chain: list[dict],
    exit_chain: list[dict],
) -> dict[str, Any]:
    """Realized PnL audit for top-ranked strikes vs selected (same exit bar, alt entry asks)."""
    by_strike_pnl: dict[float, float | None] = {}
    by_strike_score: dict[float, Any] = {}
    seen_strikes: set[float] = set()
    for row in (ranked_top5 or [])[:5]:
        try:
            sk = float(row.get("strike", 0))
        except (TypeError, ValueError):
            continue
        if sk in seen_strikes:
            continue
        seen_strikes.add(sk)
        by_strike_score[sk] = row.get("composite_score")
        if abs(sk - float(selected_strike)) < 0.02:
            by_strike_pnl[sk] = float(selected_pnl)
        else:
            by_strike_pnl[sk] = _contract_pnl_at_horizon(
                strike=sk,
                put_call=put_call,
                entry_chain=entry_chain,
                exit_chain=exit_chain,
                symbol_hint=None,
            )

    if float(selected_strike) not in by_strike_pnl:
        by_strike_pnl[float(selected_strike)] = float(selected_pnl)

    valid_pnl = {k: v for k, v in by_strike_pnl.items() if v is not None}
    alts_out: list[dict[str, Any]] = []
    for sk, sc in sorted(by_strike_score.items(), key=lambda x: float(x[0])):
        if abs(sk - float(selected_strike)) < 0.02:
            continue
        alts_out.append(
            {
                "strike": sk,
                "composite_score": sc,
                "realized_pnl_dollars": valid_pnl.get(sk),
            }
        )

    global_best: float | None = None
    if valid_pnl:
        global_best = max(float(v) for v in valid_pnl.values())
    best_strike = None
    if valid_pnl:
        best_strike = max(valid_pnl.keys(), key=lambda k: float(valid_pnl[k]))

    ordered_by_pnl = sorted(
        valid_pnl.items(),
        key=lambda x: float(x[1]),
        reverse=True,
    )
    rank_idx = next(
        (i for i, x in enumerate(ordered_by_pnl) if abs(float(x[0]) - float(selected_strike)) < 0.02),
        99,
    )

    score_sorted = sorted(by_strike_score.items(), key=lambda x: float(x[1] or 0), reverse=True)
    best_score = float(score_sorted[0][1]) if score_sorted and score_sorted[0][1] is not None else None
    sel_score = None
    for sk, sc in by_strike_score.items():
        if abs(sk - float(selected_strike)) < 0.02:
            try:
                sel_score = float(sc) if sc is not None else None
            except (TypeError, ValueError):
                sel_score = None
            break

    n_alt_known = sum(1 for k in by_strike_pnl if abs(k - float(selected_strike)) >= 0.02 and by_strike_pnl[k] is not None)
    selected_was_best = (
        bool(valid_pnl and global_best is not None and float(selected_pnl) + 1e-6 >= global_best)
        if n_alt_known > 0
        else None
    )

    return {
        "ticker": ticker,
        "architecture_type": architecture_type,
        "signal_time": signal_time,
        "selected_strike": selected_strike,
        "put_call": put_call,
        "selected_realized_pnl_dollars": round(selected_pnl, 4),
        "alt_1": alts_out[0] if len(alts_out) > 0 else None,
        "alt_2": alts_out[1] if len(alts_out) > 1 else None,
        "alt_3": alts_out[2] if len(alts_out) > 2 else None,
        "best_strike_by_realized_pnl": best_strike,
        "best_realized_pnl_among_ranked": round(global_best, 4) if global_best is not None else None,
        "selected_was_best_among_scored_alternatives": selected_was_best,
        "selected_pnl_rank_among_known": rank_idx + 1 if ordered_by_pnl and rank_idx < 99 else None,
        "selected_was_top2_by_pnl": bool(ordered_by_pnl and rank_idx <= 1),
        "score_gap_vs_best": round(best_score - sel_score, 4)
        if best_score is not None and sel_score is not None
        else None,
        "pnl_gap_vs_best": round(global_best - float(selected_pnl), 4)
        if global_best is not None
        else None,
    }


def compute_replay_coverage_stats(
    conn: sqlite3.Connection, table: str, ticker: str | None = None
) -> dict[str, Any]:
    """Quantify replayable rows (RTH training-relevant filters not applied here — raw table stats)."""
    wh = "timeframe = ?"
    params: list[Any] = [CANONICAL_TIMEFRAME]
    if ticker:
        wh += " AND ticker = ?"
        params.append(ticker.upper())
    rows = conn.execute(
        f"""
        SELECT
          COUNT(*) AS n_all,
          SUM(CASE WHEN replay_context_json IS NOT NULL AND length(replay_context_json) > 10
              THEN 1 ELSE 0 END) AS n_replay_ctx,
          SUM(CASE WHEN option_chain_json IS NOT NULL AND length(option_chain_json) > 10
              THEN 1 ELSE 0 END) AS n_chain,
          SUM(CASE WHEN replay_context_json IS NOT NULL AND length(replay_context_json) > 10
               AND option_chain_json IS NOT NULL AND length(option_chain_json) > 10
              THEN 1 ELSE 0 END) AS n_full
        FROM {table}
        WHERE {wh}
        """,
        params,
    ).fetchone()
    n_all = int(rows["n_all"] or 0)
    n_rc = int(rows["n_replay_ctx"] or 0)
    n_oc = int(rows["n_chain"] or 0)
    n_full = int(rows["n_full"] or 0)
    return {
        "table": table,
        "ticker_filter": ticker,
        "total_rows": n_all,
        "rows_with_replay_context": n_rc,
        "rows_with_option_chain_json": n_oc,
        "rows_fully_replayable": n_full,
        "replay_coverage_rate": round(n_full / n_all, 6) if n_all else 0.0,
        "replay_context_rate": round(n_rc / n_all, 6) if n_all else 0.0,
        "option_chain_rate": round(n_oc / n_all, 6) if n_all else 0.0,
    }


def save_replay_coverage_report(db_path: str, table: str, *, ticker: str | None = None) -> None:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    by_ticker: dict[str, Any] = {}
    if ticker:
        by_ticker[ticker.upper()] = compute_replay_coverage_stats(conn, table, ticker)
    else:
        cur = conn.execute(
            f"SELECT DISTINCT ticker FROM {table} WHERE timeframe = ? ORDER BY ticker",
            (CANONICAL_TIMEFRAME,),
        )
        for r in cur.fetchall():
            tk = str(r[0])
            if tk.startswith("$"):
                continue
            by_ticker[tk] = compute_replay_coverage_stats(conn, table, tk)
    overall = compute_replay_coverage_stats(conn, table, None)
    conn.close()
    payload = {"updated_by": "realized_contract_eval.save_replay_coverage_report", "overall": overall, "by_ticker": by_ticker}
    COVERAGE_REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    COVERAGE_REPORT_JSON.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def _append_chain_quality_audit(entries: list[dict]) -> None:
    if not entries:
        return
    CHAIN_QUALITY_JSON.parent.mkdir(parents=True, exist_ok=True)
    cur: list[Any] = []
    if CHAIN_QUALITY_JSON.is_file():
        try:
            cur = json.loads(CHAIN_QUALITY_JSON.read_text(encoding="utf-8"))
        except Exception:
            cur = []
    if not isinstance(cur, list):
        cur = []
    cur.extend(entries)
    cur = cur[-5000:]
    CHAIN_QUALITY_JSON.write_text(json.dumps(cur, indent=2, default=str), encoding="utf-8")


def _coarse_skip(reason: str) -> str:
    if reason in (
        "no_option_chain_archive",
        "option_chain_json_invalid",
        "option_chain_empty",
    ):
        return "no_option_chain_archive"
    if reason in (
        "no_exit_snapshot",
        "no_forward_bars",
        "exit_contract_not_found",
    ):
        return "no_exit_snapshot"
    if reason in ("missing_entry_ask", "missing_exit_bid"):
        return "missing_bid_ask"
    if reason in (
        "call_no_trade_or_wait",
        "parse_expression_failed",
        "entry_contract_not_in_chain",
        "replay_selection_mismatch",
        "all_candidates_unscorable",
    ):
        return "no_contract_selected"
    if reason.startswith("missing_replay") or reason in (
        "missing_chain_selection_proof",
        "replay_context_invalid",
        "walls_deserialize_failed",
    ):
        return "missing_replay_context"
    if reason in _COARSE_BUCKETS:
        return reason
    return "other"


def _append_trade_csv(rows: list[dict], architecture_type: str) -> None:
    p = trade_log_path(architecture_type)
    write_header = not p.is_file() or p.stat().st_size == 0
    with p.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=TRADE_LOG_FIELDS, extrasaction="ignore")
        if write_header:
            w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k) for k in TRADE_LOG_FIELDS})


def _update_chain_debug_file(samples: list[dict]) -> None:
    if not samples:
        return
    CHAIN_DEBUG_JSON.parent.mkdir(parents=True, exist_ok=True)
    cur: list[Any] = []
    if CHAIN_DEBUG_JSON.is_file():
        try:
            cur = json.loads(CHAIN_DEBUG_JSON.read_text(encoding="utf-8"))
        except Exception:
            cur = []
    if not isinstance(cur, list):
        cur = []
    cur.extend(samples)
    cur = cur[-200:]
    CHAIN_DEBUG_JSON.write_text(json.dumps(cur, indent=2, default=str), encoding="utf-8")


def compare_parallel_cascade_trade_logs() -> dict[str, Any]:
    """Metrics proving independence / overlap between arch trade logs (valid trades)."""
    def _load_valid(path: Path) -> dict[str, dict]:
        if not path.is_file():
            return {}
        out: dict[str, dict] = {}
        with path.open(newline="", encoding="utf-8") as f:
            r = csv.DictReader(f)
            for row in r:
                if row.get("skipped_flag") != "0":
                    continue
                t = row.get("signal_time") or ""
                out[str(t)] = row
        return out

    par = _load_valid(TRADE_LOG_PARALLEL)
    cas = _load_valid(TRADE_LOG_CASCADE)
    t_par = set(par.keys())
    t_cas = set(cas.keys())
    inter = t_par & t_cas

    def _contract_key(d: dict) -> tuple:
        return (
            d.get("strike"),
            d.get("right"),
            d.get("expiry"),
            d.get("contract_symbol"),
        )

    same_contract = sum(1 for t in inter if _contract_key(par[t]) == _contract_key(cas[t]))
    pnl_rows: list[dict[str, Any]] = []
    for t in sorted(inter):
        try:
            pp = float(par[t].get("pnl_dollars") or 0)
            cp = float(cas[t].get("pnl_dollars") or 0)
            pnl_rows.append({"signal_time": t, "pnl_diff_parallel_minus_cascade": round(pp - cp, 6)})
        except (TypeError, ValueError):
            continue

    denom_sig = max(len(t_par | t_cas), 1)
    denom_trade = max(len(inter), 1)
    return {
        "signal_overlap_count": len(inter),
        "signal_union_count": len(t_par | t_cas),
        "signal_overlap_rate": round(len(inter) / denom_sig, 6),
        "trade_overlap_count": same_contract,
        "trade_overlap_rate": round(same_contract / denom_trade, 6),
        "pnl_difference_per_trade_sample": pnl_rows[:50],
        "pnl_difference_mean": round(
            sum(p["pnl_diff_parallel_minus_cascade"] for p in pnl_rows) / max(len(pnl_rows), 1),
            6,
        )
        if pnl_rows
        else None,
    }


def evaluate_realized_contract_trades_for_rows(
    db_path: str,
    ticker: str,
    architecture_type: str,
    rows_used: list[dict],
    *,
    snapshot_table: str | None = None,
) -> dict[str, Any]:
    """
    Build one trade row per evaluation row in rows_used.
    Appends to arch-specific realized_contract_trade_log_*.csv.
    """
    table = snapshot_table or SNAPSHOT_TABLE_1M
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    trades_out: list[dict] = []
    pnls: list[float] = []
    wins = 0
    losses = 0
    sum_win = 0.0
    sum_loss = 0.0
    skipped = 0
    valid = 0
    skip_reason_counts: Counter[str] = Counter()
    chain_debug_accum: list[dict] = []
    quality_entries: list[dict] = []
    total_signals = len(rows_used)
    same_bar_conflict_trades = 0

    for row in rows_used:
        snap_id = row.get("snapshot_id")
        ts_utc = row.get("ts_utc")
        ts_et = row.get("ts_et")
        expiry = row.get("expiry")
        spot = row.get("spot")
        call_sig = row.get("combined_signal")
        chain_raw = row.get("option_chain_json")
        r_stop = _f(row.get("rules_stop"))
        r_tgt = _f(row.get("rules_target"))
        r_entry = _f(row.get("rules_entry"))
        replay_raw = row.get("replay_context_json")

        base = {
            "architecture_type": architecture_type,
            "ticker": ticker,
            "signal_time": ts_et,
            "entry_time": ts_et,
            "exit_time": "",
            "right": "",
            "strike": "",
            "expiry": expiry or "",
            "contract_symbol": "",
            "entry_price": "",
            "exit_price": "",
            "contracts": DEFAULT_CONTRACTS,
            "multiplier": OPTION_MULTIPLIER,
            "pnl_dollars": "",
            "pnl_percent": "",
            "exit_reason": "",
            "hold_bars": "",
            "rules_entry": r_entry if r_entry is not None else "",
            "rules_stop": r_stop if r_stop is not None else "",
            "rules_target": r_tgt if r_tgt is not None else "",
            "skipped_flag": "1",
            "skipped_reason": "",
            "snapshot_id_entry": snap_id,
            "snapshot_id_exit": "",
            "pricing_entry_rule": PRICING_ENTRY_RULE,
            "pricing_exit_rule": PRICING_EXIT_RULE,
            "path_model_used": "",
            "same_bar_stop_target_conflict_flag": "",
            "same_bar_resolution_rule": "",
        }

        def skip(reason: str) -> None:
            nonlocal skipped
            skipped += 1
            skip_reason_counts[reason] += 1
            base["skipped_reason"] = reason
            trades_out.append(dict(base))

        if ts_utc is None or spot is None:
            skip("missing_ts_or_spot")
            continue
        if not replay_raw:
            skip("missing_replay_context")
            continue
        try:
            replay_obj = json.loads(replay_raw)
        except json.JSONDecodeError:
            skip("replay_context_invalid")
            continue
        if not isinstance(replay_obj, dict):
            skip("replay_context_invalid")
            continue

        walls_list = _walls_from_replay(replay_obj)
        if walls_list is None:
            skip("missing_replay_walls")
            continue

        proof_live = replay_obj.get("option_chain_selection_proof")
        if not isinstance(proof_live, dict) or not proof_live.get("winner"):
            skip("missing_chain_selection_proof")
            continue

        try:
            max_hold = int(replay_obj["replay_max_hold_bars"])
        except (KeyError, TypeError, ValueError):
            max_hold = 30
        if max_hold < 1:
            max_hold = 30
        max_hold = min(max_hold, 390)

        if not chain_raw:
            skip("no_option_chain_archive")
            continue
        try:
            chain = json.loads(chain_raw)
        except json.JSONDecodeError:
            skip("option_chain_json_invalid")
            continue
        if not isinstance(chain, list) or not chain:
            skip("option_chain_empty")
            continue
        chain = _normalize_contract_chain(chain)
        if not chain:
            skip("option_chain_empty")
            continue

        expr, _reasons, proof_replay = recommend_option_expression(
            contracts=chain,
            spot=float(spot),
            call_signal=call_sig,
            walls=walls_list,
            selected_expiry=expiry,
        )
        if not _expressions_match_live(expr or "", proof_live):
            skip("replay_selection_mismatch")
            continue

        if not expr or str(expr).upper().startswith("NO TRADE"):
            skip("call_no_trade_or_wait")
            continue

        parsed = _parse_expression(expr)
        if not parsed:
            skip("parse_expression_failed")
            continue
        strike_f, put_call = parsed

        entry_ct = _find_contract_row(chain, strike=strike_f, put_call=put_call, symbol_hint=None)
        if not entry_ct:
            skip("entry_contract_not_in_chain")
            continue
        entry_ask = _f(entry_ct.get("ask"))
        if entry_ask is None or entry_ask <= 0:
            skip("missing_entry_ask")
            continue

        bars = _forward_path_rows(conn, table, ticker, float(ts_utc), max_hold)
        if not bars:
            skip("no_exit_snapshot")
            continue

        path_r = _simulate_exit(
            call_signal=str(call_sig or ""),
            stop=r_stop,
            target=r_tgt,
            bars=list(bars),
        )
        if path_r.get("skip_reason"):
            skip(str(path_r["skip_reason"]))
            continue
        exit_reason = path_r["exit_reason"]
        exit_row = path_r["exit_row"]
        hold_bars = path_r["hold_bars"]
        path_model_used = path_r.get("path_model_used") or ""
        sb_conf = bool(path_r.get("same_bar_stop_target_conflict"))
        sb_rule = path_r.get("same_bar_resolution_rule") or ""
        if sb_conf:
            same_bar_conflict_trades += 1
        assert exit_row is not None and exit_reason and hold_bars is not None

        ex_raw = exit_row["option_chain_json"]
        if not ex_raw:
            skip("no_exit_snapshot")
            continue
        try:
            ex_chain = json.loads(ex_raw)
        except json.JSONDecodeError:
            skip("option_chain_json_invalid")
            continue
        if not isinstance(ex_chain, list):
            skip("option_chain_json_invalid")
            continue
        ex_chain = _normalize_contract_chain(ex_chain)
        if not ex_chain:
            skip("option_chain_empty")
            continue

        sym = entry_ct.get("symbol")
        exit_ct = _find_contract_row(
            ex_chain,
            strike=strike_f,
            put_call=put_call,
            symbol_hint=str(sym) if sym else None,
        )
        if not exit_ct:
            skip("exit_contract_not_found")
            continue
        exit_bid = _f(exit_ct.get("bid"))
        if exit_bid is None:
            skip("missing_exit_bid")
            continue

        pnl_per_contract = (exit_bid - entry_ask) * OPTION_MULTIPLIER * DEFAULT_CONTRACTS
        pnl_pct = ((exit_bid - entry_ask) / entry_ask) * 100.0 if entry_ask > 0 else None

        valid += 1
        pnls.append(pnl_per_contract)
        if pnl_per_contract > 0:
            wins += 1
            sum_win += pnl_per_contract
        elif pnl_per_contract < 0:
            losses += 1
            sum_loss += pnl_per_contract

        chain_debug_accum.append(
            {
                "ticker": ticker,
                "architecture_type": architecture_type,
                "signal_time": ts_et,
                "ranked_candidates_top5": proof_replay.get("ranked_candidates_top5"),
                "winner": proof_replay.get("winner"),
                "wall_ablation_winner": proof_replay.get("wall_ablation_winner"),
                "live_snapshot_proof": proof_live.get("winner"),
            }
        )

        quality_entries.append(
            _chain_selection_quality_row(
                ticker=ticker,
                architecture_type=architecture_type,
                signal_time=ts_et,
                selected_strike=float(strike_f),
                put_call=put_call,
                ranked_top5=proof_replay.get("ranked_candidates_top5"),
                selected_pnl=float(pnl_per_contract),
                symbol_hint=str(sym) if sym else None,
                entry_chain=chain,
                exit_chain=ex_chain,
            )
        )

        trades_out.append(
            {
                **base,
                "skipped_flag": "0",
                "skipped_reason": "",
                "exit_time": exit_row["ts_et"],
                "right": put_call,
                "strike": strike_f,
                "contract_symbol": sym or "",
                "entry_price": entry_ask,
                "exit_price": exit_bid,
                "pnl_dollars": round(pnl_per_contract, 4),
                "pnl_percent": round(pnl_pct, 4) if pnl_pct is not None else "",
                "exit_reason": exit_reason,
                "hold_bars": hold_bars,
                "snapshot_id_exit": exit_row["snapshot_id"],
                "path_model_used": path_model_used,
                "same_bar_stop_target_conflict_flag": "1" if sb_conf else "0",
                "same_bar_resolution_rule": sb_rule,
            }
        )

    conn.close()

    _append_trade_csv(trades_out, architecture_type)
    _update_chain_debug_file(chain_debug_accum[-25:])
    _append_chain_quality_audit(quality_entries)
    try:
        save_replay_coverage_report(db_path, table, ticker=ticker)
    except Exception as _cov_e:
        log.warning("replay coverage report: %s", _cov_e)

    total = sum(pnls)
    n_v = len(pnls)
    avg = (total / n_v) if n_v else None
    sorted_pnls = sorted(pnls)
    median = None
    if sorted_pnls:
        mid = len(sorted_pnls) // 2
        median = (
            sorted_pnls[mid]
            if len(sorted_pnls) % 2
            else (sorted_pnls[mid - 1] + sorted_pnls[mid]) / 2
        )

    win_rate = (wins / n_v) if n_v else None
    avg_win = (sum_win / wins) if wins else None
    avg_loss = (sum_loss / losses) if losses else None
    expectancy = avg

    coarse_counts: Counter[str] = Counter()
    for r, c in skip_reason_counts.items():
        coarse_counts[_coarse_skip(r)] += c

    skip_rate = (skipped / total_signals) if total_signals else 0.0

    skip_by_reason_rate = {
        k: round(v / total_signals, 6) for k, v in skip_reason_counts.items()
    } if total_signals else {}

    _q = quality_entries
    _best = sum(
        1
        for x in _q
        if x.get("selected_was_best_among_scored_alternatives") is True
    )
    _nqa = sum(
        1 for x in _q if x.get("selected_was_best_among_scored_alternatives") is not None
    )
    _top2 = sum(1 for x in _q if x.get("selected_was_top2_by_pnl") is True)
    _gaps = [
        float(x["pnl_gap_vs_best"])
        for x in _q
        if x.get("pnl_gap_vs_best") is not None
    ]
    _sgaps = [
        float(x["score_gap_vs_best"])
        for x in _q
        if x.get("score_gap_vs_best") is not None
    ]

    agg = {
        "eval_pnl_realized_contract": avg,
        "total_pnl_dollars": round(total, 4) if n_v else None,
        "avg_pnl_dollars": round(avg, 6) if avg is not None else None,
        "median_pnl_dollars": round(median, 6) if median is not None else None,
        "win_rate": round(win_rate, 6) if win_rate is not None else None,
        "avg_win": round(avg_win, 6) if avg_win is not None else None,
        "avg_loss": round(avg_loss, 6) if avg_loss is not None else None,
        "expectancy": round(expectancy, 6) if expectancy is not None else None,
        "total_signals": total_signals,
        "skipped_trade_count": skipped,
        "valid_trade_count": valid,
        "skip_rate": round(skip_rate, 6),
        "skip_reason_counts": dict(skip_reason_counts),
        "skip_reason_counts_coarse": dict(coarse_counts),
        "skip_rate_by_reason": skip_by_reason_rate,
        "skip_rate_warning_threshold": SKIP_RATE_WARNING_THRESHOLD,
        "skip_rate_fail_threshold": SKIP_RATE_FAIL_THRESHOLD,
        "skip_rate_warning_flag": bool(skip_rate >= SKIP_RATE_WARNING_THRESHOLD),
        "skip_rate_fail_flag": bool(skip_rate >= SKIP_RATE_FAIL_THRESHOLD),
        "evaluation_quality_degraded": bool(skip_rate >= SKIP_RATE_WARNING_THRESHOLD),
        "same_bar_conflict_trade_count": same_bar_conflict_trades,
        "same_bar_conflict_share_of_valid": round(same_bar_conflict_trades / n_v, 6) if n_v else 0.0,
        "chain_selection_quality": {
            "selected_was_best_rate": round(_best / _nqa, 6) if _nqa else None,
            "selected_was_top2_rate": round(_top2 / max(len(_q), 1), 6) if _q else None,
            "average_pnl_gap_vs_best": round(sum(_gaps) / len(_gaps), 6) if _gaps else None,
            "average_score_gap_vs_best": round(sum(_sgaps) / len(_sgaps), 6) if _sgaps else None,
            "audit_path": str(CHAIN_QUALITY_JSON.resolve()),
        },
        "replay_coverage_report_path": str(COVERAGE_REPORT_JSON.resolve()),
        "pricing_entry_rule": PRICING_ENTRY_RULE,
        "pricing_exit_rule": PRICING_EXIT_RULE,
        "exit_rule": EXIT_RULE_DOC,
        "trade_log_path": str(trade_log_path_for_architecture(architecture_type).resolve()),
        "chain_selection_debug_path": str(CHAIN_DEBUG_JSON.resolve()),
        "chain_selection_debug_sample": chain_debug_accum[:3],
    }
    log.info(
        "%s %s realized eval: valid=%d skipped=%d skip_rate=%s avg_pnl=%s",
        ticker,
        architecture_type,
        valid,
        skipped,
        agg.get("skip_rate"),
        agg.get("avg_pnl_dollars"),
    )
    return agg


def save_eval_aggregate_merge(ticker: str, architecture_type: str, agg: dict[str, Any], updated_at: str) -> None:
    p = aggregate_path()
    cur: dict[str, Any] = {}
    if p.is_file():
        try:
            cur = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            cur = {}
    by_t = cur.get("by_ticker")
    if not isinstance(by_t, dict):
        by_t = {}
    tku = ticker.upper()
    entry = by_t.get(tku) or {}
    entry[architecture_type] = agg
    by_t[tku] = entry
    cur["by_ticker"] = by_t
    cur["updated_at"] = updated_at

    _sr_par: list[float] = []
    _sr_cas: list[float] = []
    _any_fail = False
    _any_warn = False
    for _ent in by_t.values():
        if not isinstance(_ent, dict):
            continue
        for _arch, _lst in (("parallel", _sr_par), ("cascade", _sr_cas)):
            _m = _ent.get(_arch)
            if isinstance(_m, dict):
                _sr = _m.get("skip_rate")
                if _sr is not None:
                    _lst.append(float(_sr))
                if _m.get("skip_rate_fail_flag"):
                    _any_fail = True
                if _m.get("skip_rate_warning_flag"):
                    _any_warn = True
    cur["skip_rate_by_architecture"] = {
        "parallel": round(sum(_sr_par) / len(_sr_par), 6) if _sr_par else None,
        "cascade": round(sum(_sr_cas) / len(_sr_cas), 6) if _sr_cas else None,
    }
    cur["skip_rate_any_architecture_fail_flag"] = _any_fail
    cur["skip_rate_any_architecture_warning_flag"] = _any_warn

    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cur, indent=2, default=str), encoding="utf-8")
    tmp.replace(p)
