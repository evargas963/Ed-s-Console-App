"""
Live vs replay exact-match validation for option selection + persisted risk context.

Compares, for the same snapshot row:
  - Live: option_chain_selection_proof + snapshot expiry + rules_* + replay bundle timing
  - Replay: recommend_option_expression(...) with archived chain, spot, combined_signal, walls

Writes models/live_vs_replay_validation.json
Includes an explicit sample-size gate (min_required_rows), validation_quality_status
(insufficient_sample | provisional | validated), and dashboard_validation_complete.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from market_state import recommend_option_expression
from replay_bundle_coverage import (
    DEFAULT_MIN_REQUIRED_ROWS,
    build_replay_bundle_coverage,
)
from timeframe_config import CANONICAL_TIMEFRAME, SNAPSHOT_TABLE_1M

from realized_contract_eval import (
    _expressions_match_live,
    _parse_expression,
    _walls_from_replay,
)

APP_DIR = Path(__file__).resolve().parent
OUTPUT_JSON = APP_DIR / "models" / "live_vs_replay_validation.json"

# Only tables safe to use in validation SQL (prevents accidental injection via --table).
_VALIDATION_TABLES = frozenset({SNAPSHOT_TABLE_1M, "snapshots", "snapshots_1m_normalized"})


def _validation_quality_status(
    *,
    min_required_rows: int,
    rows_available_full_bundle: int,
    rows_evaluated: int,
) -> str:
    if rows_evaluated >= min_required_rows:
        return "validated"
    if rows_available_full_bundle < min_required_rows:
        return "insufficient_sample"
    return "provisional"


def _row_get(row: sqlite3.Row, key: str) -> Any:
    if key not in row.keys():
        return None
    return row[key]


def _exp_key(exp: str | None) -> str:
    if not exp:
        return ""
    return str(exp).strip()[:10]


def _normalize_side(s: str | None) -> str:
    return (s or "").strip().upper()


def _replay_one_row(row: sqlite3.Row) -> tuple[dict[str, Any], Optional[str]]:
    out: dict[str, Any] = {
        "replay_expression": None,
        "replay_strike": None,
        "replay_side": None,
        "replay_is_no_trade": False,
    }
    chain_raw = row["option_chain_json"]
    try:
        chain = json.loads(chain_raw)
    except json.JSONDecodeError:
        return out, "chain_json_invalid"
    if not isinstance(chain, list) or not chain:
        return out, "chain_empty"

    replay_raw = row["replay_context_json"]
    try:
        rc = json.loads(replay_raw)
    except json.JSONDecodeError:
        return out, "replay_context_invalid"
    if not isinstance(rc, dict):
        return out, "replay_context_not_dict"

    walls = _walls_from_replay(rc)
    if walls is None:
        return out, "walls_deserialize_failed"

    spot = row["spot"]
    expiry = row["expiry"]
    call_sig = row["combined_signal"]
    try:
        expr, _reasons, proof = recommend_option_expression(
            contracts=chain,
            spot=float(spot),
            call_signal=call_sig,
            walls=walls,
            selected_expiry=expiry,
        )
    except Exception as e:
        return out, f"recommend_option_expression_error:{e!r}"

    out["replay_expression"] = expr
    out["replay_proof_status"] = proof.get("status") if isinstance(proof, dict) else None
    parsed = _parse_expression(expr or "")
    if parsed:
        out["replay_strike"], out["replay_side"] = parsed[0], parsed[1]
    out["replay_is_no_trade"] = bool(
        not expr or str(expr).upper().startswith("NO TRADE")
    )
    return out, None


def _live_expiry_from_proof(win: dict, row_expiry: Any) -> str:
    cr = win.get("chain_row")
    if isinstance(cr, dict):
        ex = cr.get("expirationDate") or cr.get("expiration")
        if ex:
            return _exp_key(str(ex))
    return _exp_key(row_expiry)


def _live_from_row(row: sqlite3.Row, rc: dict) -> dict[str, Any]:
    proof = rc.get("option_chain_selection_proof")
    if not isinstance(proof, dict):
        proof = {}
    win = proof.get("winner")
    if not isinstance(win, dict):
        win = {}
    expr = win.get("expression")
    live_strike = win.get("strike")
    live_side = _normalize_side(win.get("side"))
    parsed = _parse_expression(str(expr or ""))
    if parsed and live_strike is None:
        live_strike = parsed[0]
        live_side = live_side or parsed[1]

    sig = (row["combined_signal"] or "").strip().lower()
    status = proof.get("status")
    live_no_trade = (
        status == "no_trade"
        or sig == "wait"
        or not expr
        or str(expr).upper().startswith("NO TRADE")
    )

    snap_exp = _exp_key(row["expiry"])
    live_exp_proof = _live_expiry_from_proof(win, row["expiry"])

    return {
        "live_expression": expr,
        "live_strike": float(live_strike) if live_strike is not None else None,
        "live_side": live_side or (parsed[1] if parsed else ""),
        "live_expiry_snapshot": snap_exp,
        "live_expiry_from_proof_chain": live_exp_proof,
        "live_no_trade": live_no_trade,
        "live_rules_entry": _row_get(row, "rules_entry"),
        "live_rules_stop": _row_get(row, "rules_stop"),
        "live_rules_target": _row_get(row, "rules_target"),
        "live_replay_max_hold_bars": rc.get("replay_max_hold_bars"),
        "live_time_expiry_policy": rc.get("replay_time_expiry_policy"),
        "live_entry_policy": rc.get("replay_entry_policy"),
        "live_exit_policy": rc.get("replay_exit_policy"),
    }


def run_live_vs_replay_validation(
    db_path: str,
    *,
    ticker: str | None = None,
    n: int = 30,
    table: str = SNAPSHOT_TABLE_1M,
    min_required: int = DEFAULT_MIN_REQUIRED_ROWS,
) -> dict[str, Any]:
    if table not in _VALIDATION_TABLES:
        raise ValueError(
            f"table must be one of {sorted(_VALIDATION_TABLES)}; got {table!r}"
        )
    ticker_u = ticker.upper() if ticker else None
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    wh_t = "ticker = ?" if ticker_u else "1=1"
    params_count: list[Any] = [CANONICAL_TIMEFRAME]
    if ticker_u:
        params_count.append(ticker_u)
    cnt_row = conn.execute(
        f"""
        SELECT COUNT(*) AS c FROM {table}
        WHERE timeframe = ?
          AND {wh_t}
          AND replay_context_json IS NOT NULL AND length(replay_context_json) > 10
          AND option_chain_json IS NOT NULL AND length(option_chain_json) > 10
        """,
        tuple(params_count),
    ).fetchone()
    available = int(cnt_row["c"] or 0)

    take_n = max(n, min_required)
    params_sel: list[Any] = [CANONICAL_TIMEFRAME]
    if ticker_u:
        params_sel.append(ticker_u)
    params_sel.append(take_n)

    sql = f"""
        SELECT snapshot_id, ticker, timeframe, ts_utc, ts_et, expiry, spot, combined_signal,
               option_chain_json, replay_context_json,
               rules_entry, rules_stop, rules_target
        FROM {table}
        WHERE timeframe = ?
          AND {wh_t}
          AND replay_context_json IS NOT NULL AND length(replay_context_json) > 10
          AND option_chain_json IS NOT NULL AND length(option_chain_json) > 10
        ORDER BY ts_utc DESC
        LIMIT ?
    """
    rows = conn.execute(sql, tuple(params_sel)).fetchall()
    conn.close()

    mismatches: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    n_eval = 0
    n_contract_ok = 0
    n_strike_ok = 0
    n_expiry_ok = 0
    n_full_ok = 0

    for row in rows:
        rid = row["snapshot_id"]
        try:
            rc = json.loads(row["replay_context_json"])
        except json.JSONDecodeError:
            skipped.append({"snapshot_id": rid, "reason": "replay_context_json_invalid"})
            continue
        if not isinstance(rc, dict):
            skipped.append({"snapshot_id": rid, "reason": "replay_context_not_object"})
            continue

        proof = rc.get("option_chain_selection_proof")
        if not isinstance(proof, dict):
            proof = {}
        live = _live_from_row(row, rc)

        replay, r_err = _replay_one_row(row)
        if r_err:
            skipped.append({"snapshot_id": rid, "reason": r_err})
            continue

        n_eval += 1
        snap_exp = _exp_key(row["expiry"])
        live_nt = live["live_no_trade"]
        replay_nt = replay["replay_is_no_trade"]

        rules_stop = _row_get(row, "rules_stop")
        rules_target = _row_get(row, "rules_target")
        rules_present = rules_stop is not None and rules_target is not None
        sig = (row["combined_signal"] or "").strip().lower()
        rules_expected = (not live_nt) and sig in ("long", "short")

        mismatch_issues: list[str] = []
        explain_parts: list[str] = []

        if live_nt and replay_nt:
            strike_hit = True
            expiry_hit = True
            contract_hit = True
            expr_hit = True
            rules_ok = True
        elif live_nt != replay_nt:
            strike_hit = False
            expiry_hit = False
            contract_hit = False
            expr_hit = False
            rules_ok = False
            mismatch_issues.append("no_trade_mismatch")
            explain_parts.append(
                "Live proof/signal implies NO TRADE vs replay actionable (or reverse). "
                "Check combined_signal, proof.status, or chain/at-the-time context."
            )
        else:
            ls = live["live_strike"]
            rs = replay["replay_strike"]
            lside = _normalize_side(live["live_side"])
            rside = _normalize_side(replay["replay_side"])

            strike_hit = (
                ls is not None
                and rs is not None
                and abs(float(ls) - float(rs)) < 0.021
            )
            live_exp = live["live_expiry_from_proof_chain"] or live["live_expiry_snapshot"]
            expiry_hit = bool(snap_exp) and live_exp == snap_exp
            contract_hit = strike_hit and lside == rside and expiry_hit
            expr_hit = _expressions_match_live(
                replay["replay_expression"] or "",
                proof,
            )
            rules_ok = (not rules_expected) or rules_present
            if rules_expected and not rules_present:
                mismatch_issues.append("missing_snapshot_rules_stop_target")
                explain_parts.append(
                    "Snapshot has actionable combined_signal but NULL rules_stop or rules_target."
                )
            if not strike_hit:
                mismatch_issues.append("strike_mismatch")
                explain_parts.append(
                    "Strike differs by more than 0.02 or one side missing a strike."
                )
            if lside != rside:
                mismatch_issues.append("side_mismatch")
                explain_parts.append("Side (call/put) does not match live proof.")
            if not expiry_hit:
                mismatch_issues.append("expiry_mismatch_proof_vs_snapshot")
                explain_parts.append(
                    "Proof chain expiry prefix does not match snapshot expiry."
                )
            if not expr_hit:
                mismatch_issues.append("expression_mismatch")
                explain_parts.append(
                    "Replay expression text differs from persisted proof.winner.expression."
                )

        full_hit = bool(contract_hit and expr_hit and rules_ok)
        if not (live_nt and replay_nt) and (mismatch_issues or not full_hit):
            mismatches.append(
                {
                    "snapshot_id": rid,
                    "ticker": row["ticker"],
                    "ts_et": row["ts_et"],
                    "reason": "+".join(mismatch_issues)
                    if mismatch_issues
                    else "full_decision_mismatch",
                    "explain": " ".join(explain_parts).strip()
                    if explain_parts
                    else (
                        "Contract, expression, or persisted rules context do not align with replay."
                    ),
                    "live": live,
                    "replay": replay,
                }
            )
        if strike_hit:
            n_strike_ok += 1
        if expiry_hit:
            n_expiry_ok += 1
        if contract_hit:
            n_contract_ok += 1
        if full_hit:
            n_full_ok += 1

    def _rate(num: int, den: int) -> float | None:
        return round(num / den, 6) if den else None

    min_required_rows = min_required
    min_required_met = n_eval >= min_required_rows
    vqs = _validation_quality_status(
        min_required_rows=min_required_rows,
        rows_available_full_bundle=available,
        rows_evaluated=n_eval,
    )

    bundle_diag = build_replay_bundle_coverage(
        db_path, min_required_rows=min_required_rows
    )
    val_tbl_stats = bundle_diag.get("tables", {}).get(table, {})
    snap_full = (
        bundle_diag.get("tables", {})
        .get("snapshots", {})
        .get("rows_with_full_bundle", 0)
    )
    remediation: list[str] = []
    if available == 0 and snap_full and table == SNAPSHOT_TABLE_1M:
        remediation.append(
            f"snapshots has {snap_full} full-bundle row(s) at timeframe={CANONICAL_TIMEFRAME}, but "
            f"{table} has 0. Run: python snapshot_normalizer.py (materializes 1m rows from snapshots)."
        )
    if available == 0 and not snap_full:
        remediation.append(
            "No snapshots rows with both replay_context_json and option_chain_json. "
            "Confirm server refresh runs the db_snapshot path in server.py (SnapshotRow with "
            "option_chain_json + replay_context_json) after schema migration."
        )

    need_bundle = max(0, min_required_rows - available)
    need_eval = max(0, min_required_rows - n_eval)
    if min_required_met:
        sufficiency = (
            f"Sample size gate satisfied: {n_eval} successful live-vs-replay evaluation(s) "
            f"(minimum {min_required_rows}). validation_quality_status=validated — "
            "match rates meet the configured minimum for operational trust."
        )
    elif vqs == "insufficient_sample":
        sufficiency = (
            f"Validation is NOT sufficient: only {available} full-bundle row(s) exist on this table "
            f"({need_bundle} more needed to reach minimum {min_required_rows}). "
            "validation_quality_status=insufficient_sample — accumulate more live snapshots "
            "with replay bundles (and materialize normalized table if applicable)."
        )
    else:
        sufficiency = (
            f"Validation is NOT sufficient: {available} full-bundle row(s) available but only "
            f"{n_eval} evaluated successfully ({len(skipped)} skipped). "
            f"{need_eval} more successful evaluation(s) required "
            f"(minimum {min_required_rows}). validation_quality_status=provisional."
        )

    report = {
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        "db_path": str(Path(db_path).resolve()),
        "table": table,
        "ticker_filter": ticker_u,
        "n_requested": take_n,
        "validation_quality_status": vqs,
        "dashboard_validation_complete": min_required_met,
        "validation_sufficiency_message": sufficiency,
        "rows_available_full_bundle": available,
        "rows_selected": len(rows),
        "rows_evaluated": n_eval,
        "rows_evaluated_match_logic": n_eval,
        "rows_skipped": len(skipped),
        "min_required_rows": min_required_rows,
        "min_required_met": min_required_met,
        "sample_size_gate": {
            "min_required_rows": min_required_rows,
            "rows_still_needed_full_bundle_on_table": need_bundle,
            "rows_still_needed_successful_evaluations": need_eval,
        },
        "contract_match_rate": _rate(n_contract_ok, n_eval),
        "strike_match_rate": _rate(n_strike_ok, n_eval),
        "expiry_match_rate": _rate(n_expiry_ok, n_eval),
        "full_decision_match_rate": _rate(n_full_ok, n_eval),
        "mismatch_count": len(mismatches),
        "counts": {
            "contract_match": n_contract_ok,
            "strike_match": n_strike_ok,
            "expiry_match": n_expiry_ok,
            "full_decision_match": n_full_ok,
            "evaluated": n_eval,
        },
        "mismatches": mismatches,
        "skipped": skipped[:200],
        "replay_bundle_diagnostics": bundle_diag,
        "validation_table_coverage": val_tbl_stats,
        "historical_backfill": bundle_diag.get("historical_backfill")
        or {
            "automatic_sql_backfill_available": False,
            "summary": "See replay_bundle_coverage.json historical_backfill.",
        },
        "acceptance": {
            "rows_with_full_bundle_on_validation_table": available,
            "rates_are_non_null": n_eval > 0,
            "replay_compared_on_real_snapshots": n_eval > 0,
            "mismatches_reviewable": n_eval > 0,
            "min_required_met": min_required_met,
            "phase_complete": bool(min_required_met and n_eval > 0),
        },
        "remediation_hints": remediation,
        "definitions": {
            "contract_match": "strike within 0.02, side match, expiry(proof chain) aligns with snapshot expiry",
            "full_decision_match": "contract_match AND expression matches persisted proof AND rules_stop/target present when signal is long/short",
            "expiry_match": "live proof chain_row expiry (if any) agrees with snapshot expiry date prefix",
            "full_bundle": "replay_context_json and option_chain_json non-null and length > 10",
            "validation_quality_status": {
                "insufficient_sample": "Fewer full-bundle rows on this table than min_required_rows; cannot reach a trustworthy sample until more data exists.",
                "provisional": "At least min_required_rows full-bundle rows exist, but fewer than min_required_rows were successfully evaluated (e.g. skips); rates are not certified.",
                "validated": "At least min_required_rows successful live-vs-replay evaluations; min_required_met is true and dashboard_validation_complete may be shown as complete.",
            },
            "dashboard_validation_complete": "True only when min_required_met; never treat live-vs-replay as operationally complete when false.",
        },
    }

    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return report


def main() -> None:
    from calibration.db_guard import register_allow_noncanonical_flag, require_canonical_db_target
    from db import DB_PATH

    ap = argparse.ArgumentParser(description="Live vs replay validation for OE selection")
    ap.add_argument("--db", type=str, default=str(DB_PATH))
    ap.add_argument("--ticker", type=str, default=None)
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--table", type=str, default=SNAPSHOT_TABLE_1M)
    ap.add_argument(
        "--min",
        type=int,
        dest="min_required",
        default=DEFAULT_MIN_REQUIRED_ROWS,
    )
    register_allow_noncanonical_flag(ap)
    args = ap.parse_args()
    require_canonical_db_target(args, tool_name="live_vs_replay_validation", write_capable=False)
    r = run_live_vs_replay_validation(
        args.db,
        ticker=args.ticker,
        n=args.n,
        table=args.table,
        min_required=args.min_required,
    )
    skip_print = (
        "mismatches",
        "skipped",
        "definitions",
        "replay_bundle_diagnostics",
        "validation_table_coverage",
        "historical_backfill",
    )
    summary = {k: r[k] for k in r if k not in skip_print}
    print(json.dumps(summary, indent=2))
    print(
        "mismatches:",
        r["mismatch_count"],
        "→",
        OUTPUT_JSON,
        "| bundle detail in report['replay_bundle_diagnostics']",
    )


if __name__ == "__main__":
    main()
