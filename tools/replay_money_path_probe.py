#!/usr/bin/env python3
"""
Read-only money-path replay probe for training anchor tickers (SPY / QQQ / IWM).

Traces: snapshot → empirical histogram → fusion triplets → mhap_rows → ALL →
call_engine → PLAN fields → UI render contract (derived, no browser).

Usage:
  python tools/replay_money_path_probe.py --date 2026-06-16 --tickers SPY QQQ IWM --read-only \\
      --output reports/money_path/replay_2026-06-16.json

No DB mutation, no threshold changes, no live Schwab required.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from db import DB_PATH
from money_path_ticker_tiers import (
    BASE_MONEY_PATH_TICKERS,
    TRUST_BASE,
    is_base_money_path_ticker,
    ticker_trust_class,
)
from verification.base_ticker_observability import base_ticker_observability_report

CLASS_SIGNAL_EXPOSED = "SIGNAL_EXPOSED"
CLASS_SIGNAL_SUPPRESSED_BY_POLICY = "SIGNAL_SUPPRESSED_BY_POLICY"
CLASS_SIGNAL_MISSING_DUE_TO_DATA = "SIGNAL_MISSING_DUE_TO_DATA"
CLASS_SIGNAL_MISSING_DUE_TO_FUSION = "SIGNAL_MISSING_DUE_TO_FUSION"
CLASS_SIGNAL_MISSING_DUE_TO_CALL_ENGINE_VETO = "SIGNAL_MISSING_DUE_TO_CALL_ENGINE_VETO"
CLASS_INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
CLASS_REPLAY_DRIFT_FROM_LIVE_POLICY = "REPLAY_DRIFT_FROM_LIVE_POLICY"

ET = datetime.timezone(datetime.timedelta(hours=-4))


def parse_date(s: str) -> datetime.date:
    return datetime.date.fromisoformat(s.strip())


def rth_window_utc(day: datetime.date) -> tuple[float, float]:
    start_et = datetime.datetime(day.year, day.month, day.day, 9, 30, tzinfo=ET)
    end_et = datetime.datetime(day.year, day.month, day.day, 16, 0, tzinfo=ET)
    return start_et.timestamp(), end_et.timestamp()


def ts_et_label(ts: float) -> str:
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).astimezone(ET).strftime(
        "%Y-%m-%d %H:%M:%S ET"
    )


def _connect_ro(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def data_coverage_row(
    conn: sqlite3.Connection,
    ticker: str,
    rth_start: float,
    rth_end: float,
) -> dict[str, Any]:
    t = ticker.upper()
    snap = conn.execute(
        "SELECT COUNT(*), MIN(ts_utc), MAX(ts_utc) FROM snapshots WHERE ticker=? AND ts_utc BETWEEN ? AND ?",
        (t, rth_start, rth_end),
    ).fetchone()
    norm = conn.execute(
        "SELECT COUNT(*), MIN(ts_utc), MAX(ts_utc) FROM snapshots_1m_normalized WHERE ticker=? AND ts_utc BETWEEN ? AND ?",
        (t, rth_start, rth_end),
    ).fetchone()
    cal = conn.execute(
        "SELECT COUNT(*), MIN(decision_ts_utc), MAX(decision_ts_utc) FROM calibration_decision_log WHERE ticker=? AND decision_ts_utc BETWEEN ? AND ?",
        (t, rth_start, rth_end),
    ).fetchone()
    notes: list[str] = []
    n_rows = int(norm[0] or 0)
    if n_rows == 0:
        notes.append("no normalized snapshots in RTH window")
    elif n_rows < 100:
        notes.append(f"sparse snapshot coverage ({n_rows} rows; SPY baseline ~360+ for full session)")
    gaps: list[float] = []
    if n_rows > 1:
        ts_list = [
            r[0]
            for r in conn.execute(
                "SELECT ts_utc FROM snapshots_1m_normalized WHERE ticker=? AND ts_utc BETWEEN ? AND ? ORDER BY ts_utc",
                (t, rth_start, rth_end),
            ).fetchall()
        ]
        gaps = [ts_list[i + 1] - ts_list[i] for i in range(len(ts_list) - 1)]
        if gaps:
            med = sorted(gaps)[len(gaps) // 2]
            if med > 300:
                notes.append(f"median inter-row gap {med:.0f}s (~{med/60:.1f} min) — not 1m continuity")
    return {
        "ticker": t,
        "snapshot_rows_rth": int(snap[0] or 0),
        "normalized_rows_rth": n_rows,
        "calibration_decision_log_rows_rth": int(cal[0] or 0),
        "first_ts_et": ts_et_label(float(norm[1])) if norm[1] is not None else None,
        "last_ts_et": ts_et_label(float(norm[2])) if norm[2] is not None else None,
        "median_gap_seconds": sorted(gaps)[len(gaps) // 2] if gaps else None,
        "data_quality_notes": notes,
    }


def cal_signal_summary(conn: sqlite3.Connection, ticker: str, rth_start: float, rth_end: float) -> dict[str, Any]:
    t = ticker.upper()
    counts = {}
    for sig in ("wait", "long", "short"):
        counts[sig] = int(
            conn.execute(
                "SELECT COUNT(*) FROM calibration_decision_log WHERE ticker=? AND decision_ts_utc BETWEEN ? AND ? AND final_signal=?",
                (t, rth_start, rth_end, sig),
            ).fetchone()[0]
        )
    tradeable_true = 0
    windows: list[dict[str, Any]] = []
    rows = conn.execute(
        """SELECT decision_ts_utc, final_signal, call_conviction, entry_price, stop_price, target_price,
                  validation_summary, multi_horizon_json, wait_blocker_json
           FROM calibration_decision_log
           WHERE ticker=? AND decision_ts_utc BETWEEN ? AND ?
           ORDER BY decision_ts_utc""",
        (t, rth_start, rth_end),
    ).fetchall()
    for r in rows:
        mh = json.loads(r["multi_horizon_json"] or "{}")
        if mh.get("final_tradeable") is True:
            tradeable_true += 1
        if r["final_signal"] in ("long", "short"):
            windows.append(
                {
                    "ts_et": ts_et_label(float(r["decision_ts_utc"])),
                    "ts_utc": float(r["decision_ts_utc"]),
                    "final_signal": r["final_signal"],
                    "final_tradeable": mh.get("final_tradeable"),
                    "final_bias": mh.get("final_bias"),
                    "final_confidence": mh.get("final_confidence"),
                    "primary_horizon": mh.get("primary_horizon"),
                    "call_conviction": r["call_conviction"],
                    "entry_price": r["entry_price"],
                    "stop_price": r["stop_price"],
                    "target_price": r["target_price"],
                    "validation_summary": r["validation_summary"],
                    "wait_reason": mh.get("wait_reason"),
                }
            )
    return {
        "final_signal_counts": counts,
        "final_tradeable_true_count": tradeable_true,
        "tradeable_windows": windows,
    }


def classify_suppression_layer(probe: dict[str, Any]) -> str:
    if probe.get("stack_error") or probe.get("empirical_error"):
        return "stack_error"
    if probe.get("fusion_available") is False:
        return "fusion_unavailable"
    wr = str(probe.get("wait_reason") or "").lower()
    wb = probe.get("call_readiness", {}).get("wait_blocker") or probe.get("wait_blocker") or {}
    if isinstance(wb, dict):
        reason = str(wb.get("reason") or "").lower()
        if reason == "time":
            return "time_gate"
        if reason == "stack":
            return "stack_vote_tie"
        if reason == "gates":
            return "validation_gate"
        if reason == "vol_regime":
            return "vol_regime_gate"
        if reason == "multi_horizon_policy":
            return "multi_horizon_alignment"
    if "call engine veto" in wr or "disagrees with tape stack" in wr:
        return "call_engine_veto"
    if "fewer than 2 tradeable horizons" in wr or "all synthesis withheld" in wr:
        return "multi_horizon_alignment"
    if probe.get("final_tradeable"):
        return "none_exposed"
    return "policy_other"


def ui_card_derivation(final_bias: str, final_tradeable: bool, entry_state: str) -> dict[str, str]:
    bias = str(final_bias or "WAIT").upper()
    tradeable = bool(final_tradeable) and bias in ("LONG", "SHORT")
    all_dir = bias if tradeable else "FLAT"
    plan_state = str(entry_state or "no_setup") if tradeable else "no_setup"
    return {
        "ALL_pill_direction": all_dir,
        "ALL_pill_visual_state": "directional" if tradeable else "dim/neutral",
        "PLAN_pill_state": plan_state.upper().replace("_", " "),
    }


def probe_snapshot_row(db, row: dict) -> dict[str, Any]:
    from features.fusion_model_input import similar_setup_filters_from_db_snapshot_row
    from features.replay_signal_input_v1 import signal_input_from_snapshot_row_dict
    from prediction_engine import _build_horizon_prob_bars, _literal_empirical_horizon
    from signals import compute_signals
    from verification.similar_set_trace import PRODUCT_EMPIRICAL, full_similar_and_empirical_trace

    ts = float(row["ts_utc"])
    ticker = str(row["ticker"]).upper()
    out: dict[str, Any] = {
        "ticker": ticker,
        "ts_utc": ts,
        "ts_et": ts_et_label(ts),
        "spot": row.get("spot"),
        "zone": row.get("zone"),
    }
    try:
        filt = similar_setup_filters_from_db_snapshot_row(row)
        trace = full_similar_and_empirical_trace(
            db,
            ticker=ticker,
            timeframe="1m",
            zone=filt["zone"],
            vwap_side=filt["vwap_side"],
            nearest_above_dist=filt["nearest_above_dist"],
            nearest_below_dist=filt["nearest_below_dist"],
            as_of_ts_utc=ts,
            include_similar=True,
        )
        similar = trace.get("similar") or []
        lit = {hz: _literal_empirical_horizon(similar, col, br) for hz, col, br in PRODUCT_EMPIRICAL}
        hp = _build_horizon_prob_bars(lit["1c"], lit["5c"], lit["15c"], lit["60c"])
        out["horizon_prob_bars"] = {
            k: {"up": v.get("up"), "down": v.get("down"), "flat": v.get("flat")}
            for k, v in hp.items()
        }
    except Exception as e:
        out["empirical_error"] = repr(e)

    try:
        inp = signal_input_from_snapshot_row_dict(row)
        sig = compute_signals(inp, db=db)
        pred = sig.predictive
        call = sig.call
        fd = sig.multi_horizon_bundle.final_decision if sig.multi_horizon_bundle else None
        plan = getattr(fd, "final_trade_plan", None) if fd else None

        out["fusion_available"] = bool(getattr(sig.fusion, "available", False)) if sig.fusion else False
        out["fusion_triplets"] = {
            hz: {
                "up": getattr(pred, f"up_prob_{hz}", None),
                "down": getattr(pred, f"down_prob_{hz}", None),
                "flat": getattr(pred, f"flat_prob_{hz}", None),
            }
            for hz in ("1c", "5c", "15c", "60c")
        }
        mhap = []
        if fd:
            for a in getattr(fd, "supporting_assessments", []) or []:
                mhap.append(
                    {
                        "horizon": getattr(a, "horizon", None),
                        "call": getattr(a, "call", None),
                        "confidence": getattr(a, "confidence", None),
                    }
                )
        out["mhap_rows"] = mhap
        out["final_bias"] = getattr(fd, "final_bias", None) if fd else None
        out["final_confidence"] = getattr(fd, "final_confidence", None) if fd else None
        out["final_tradeable"] = getattr(fd, "final_tradeable", None) if fd else None
        out["wait_reason"] = getattr(fd, "wait_reason", None) if fd else None
        out["call_signal"] = getattr(call, "signal", None)
        out["call_readiness"] = {"wait_blocker": getattr(call, "wait_blocker", None)}
        out["entry_state"] = getattr(fd, "entry_state", None) if fd else None
        out["entry_display_text"] = getattr(plan, "entry_display_text", None) if plan else None
        out["stop_display_text"] = getattr(plan, "stop_display_text", None) if plan else None
        out["targets_display"] = getattr(plan, "targets_display", None) if plan else None
        out["entry_price"] = getattr(plan, "entry", None) if plan else getattr(call, "entry", None)
        out["stop_price"] = getattr(plan, "stop", None) if plan else getattr(call, "stop", None)
        out["suppression_layer"] = classify_suppression_layer(out)
        out["ui_cards"] = ui_card_derivation(
            out.get("final_bias") or "WAIT",
            bool(out.get("final_tradeable")),
            str(out.get("entry_state") or "no_setup"),
        )
    except Exception as e:
        out["stack_error"] = repr(e)
        out["suppression_layer"] = "stack_error"

    return out


def classify_ticker_evidence(
    coverage: dict[str, Any],
    cal: dict[str, Any],
    replays: list[dict[str, Any]],
) -> list[str]:
    tags: list[str] = []
    n_norm = coverage.get("normalized_rows_rth") or 0
    if n_norm == 0 or n_norm < 100:
        tags.append(CLASS_SIGNAL_MISSING_DUE_TO_DATA)

    live_windows = cal.get("tradeable_windows") or []
    replay_tradeable = [p for p in replays if p.get("final_tradeable") is True]
    drift_rows = [p for p in replays if p.get("replay_drift")]
    if drift_rows or (live_windows and not replay_tradeable):
        tags.append(CLASS_REPLAY_DRIFT_FROM_LIVE_POLICY)
    if live_windows or replay_tradeable:
        tags.append(CLASS_SIGNAL_EXPOSED)
    elif replays:
        tags.append(CLASS_SIGNAL_SUPPRESSED_BY_POLICY)
    if any(p.get("suppression_layer") == "fusion_unavailable" for p in replays):
        tags.append(CLASS_SIGNAL_MISSING_DUE_TO_FUSION)
    if any(p.get("suppression_layer") == "call_engine_veto" for p in replays):
        tags.append(CLASS_SIGNAL_MISSING_DUE_TO_CALL_ENGINE_VETO)
    if not tags:
        tags.append(CLASS_INSUFFICIENT_EVIDENCE)
    tags.append(CLASS_INSUFFICIENT_EVIDENCE + "_UI_LAYER_NOT_RUNTIME_TESTED")
    return sorted(set(tags))


def _pick_sample_indices(n: int) -> list[tuple[str, int]]:
    if n <= 0:
        return []
    picks = [("open", 0), ("midday", n // 2), ("near_close", n - 1)]
    out: list[tuple[str, int]] = []
    seen: set[int] = set()
    for label, idx in picks:
        if idx not in seen:
            seen.add(idx)
            out.append((label, idx))
    return out


def run_probe(*, day: datetime.date, tickers: list[str], db_path: Path) -> dict[str, Any]:
    if not db_path.is_file():
        raise FileNotFoundError(f"DB not found: {db_path}")

    rth_start, rth_end = rth_window_utc(day)
    conn = _connect_ro(db_path)
    coverage_table = [data_coverage_row(conn, t, rth_start, rth_end) for t in tickers]
    cal_by_ticker = {t.upper(): cal_signal_summary(conn, t, rth_start, rth_end) for t in tickers}

    rows_by_ticker: dict[str, list[dict]] = {}
    for t in tickers:
        tu = t.upper()
        cur = conn.execute(
            "SELECT * FROM snapshots_1m_normalized WHERE ticker=? AND ts_utc BETWEEN ? AND ? ORDER BY ts_utc",
            (tu, rth_start, rth_end),
        )
        rows_by_ticker[tu] = [{k: r[k] for k in r.keys()} for r in cur.fetchall()]
    conn.close()

    os.environ.setdefault("SCHWAB_API_KEY", "ci-placeholder-key")
    os.environ.setdefault("SCHWAB_APP_SECRET", "ci-placeholder-secret")
    os.environ.setdefault("SCHWAB_CALLBACK_URL", "https://127.0.0.1:8182")

    from db import EdDB

    db = EdDB(str(db_path))
    ticker_results: dict[str, Any] = {}
    obs_report = base_ticker_observability_report(day=day, tickers=tickers, db_path=db_path)
    obs_by_ticker = {r["ticker"]: r for r in obs_report["tickers"]}

    for t in tickers:
        tu = t.upper()
        trows = rows_by_ticker.get(tu, [])
        replays: list[dict[str, Any]] = []
        seen_ts: set[float] = set()

        for label, idx in _pick_sample_indices(len(trows)):
            row = trows[idx]
            ts = float(row["ts_utc"])
            if ts in seen_ts:
                continue
            seen_ts.add(ts)
            pr = probe_snapshot_row(db, row)
            pr["sample_label"] = label
            replays.append(pr)

        for w in cal_by_ticker[tu].get("tradeable_windows") or []:
            ts = float(w["ts_utc"])
            nearest = min(trows, key=lambda r: abs(float(r["ts_utc"]) - ts), default=None)
            if nearest is None:
                continue
            nts = float(nearest["ts_utc"])
            if nts in seen_ts:
                continue
            seen_ts.add(nts)
            pr = probe_snapshot_row(db, nearest)
            pr["sample_label"] = "live_tradeable_window"
            pr["live_log"] = w
            pr["replay_drift"] = bool(
                w.get("final_tradeable") is True
                and pr.get("final_tradeable") is not True
            )
            replays.append(pr)

        cov = next(c for c in coverage_table if c["ticker"] == tu)
        ticker_results[tu] = {
            "ticker_tier": TRUST_BASE if is_base_money_path_ticker(tu) else ticker_trust_class(tu),
            "observability": obs_by_ticker.get(tu),
            "coverage": cov,
            "calibration_log": cal_by_ticker[tu],
            "replays": replays,
            "evidence_classification": classify_ticker_evidence(cov, cal_by_ticker[tu], replays),
        }

    return {
        "meta": {
            "date": day.isoformat(),
            "rth_et": "09:30-16:00 ET",
            "db_path": str(db_path.resolve()),
            "read_only": True,
            "tickers": [t.upper() for t in tickers],
            "base_universe_observability_ready": obs_report["meta"]["base_universe_ready"],
            "ticker_tier_policy": "reports/artifacts/base_ticker_money_path_contract.json",
        },
        "base_ticker_observability": obs_report,
        "data_coverage_table": coverage_table,
        "tickers": ticker_results,
        "ui_render_contract": {
            "ALL_pill": "static/index.html renderTimeframeSignalRow + engineTradeableSetup",
            "PLAN_pill": "static/index.html paintTradePlanCard + engineTradeableSetup",
            "horizon_pills": "mhap_rows; deriveSourceForHorizon (fusion chip, not horizon_prob_bars)",
            "histogram": "market_state.horizon_prob_bars — context rail only",
            "api_fields": "market_state.py — final_tradeable, final_bias, mhap_rows, entry_display_text",
        },
        "contract_tests_proposed": _contract_test_plan(),
    }


def _contract_test_plan() -> list[dict[str, str]]:
    return [
        {"id": "all_directional_when_tradeable", "owner": "tests/test_issue18_ui_contract.py"},
        {"id": "all_plan_wait_when_not_tradeable", "owner": "tests/test_issue18_ui_contract.py"},
        {"id": "plan_same_gate_as_all", "owner": "tests/test_issue18_ui_contract.py (exists)"},
        {"id": "horizon_pills_mhap_not_histogram", "owner": "tests/test_issue18_ui_contract.py (exists)"},
        {"id": "histogram_context_only", "owner": "tests/test_issue18_ui_contract.py deriveSourceForHorizon"},
        {"id": "call_engine_veto_wait", "owner": "multi_horizon_decision finalize_multi_horizon_bundle"},
    ]


def markdown_summary(report: dict[str, Any]) -> str:
    lines = [
        f"# Money-path replay — {report['meta']['date']}",
        "",
        f"DB: `{report['meta']['db_path']}`",
        "",
        "## Data coverage",
        "",
        "| Ticker | Norm rows | Cal rows | First ET | Last ET | Notes |",
        "|--------|-----------|----------|----------|---------|-------|",
    ]
    for row in report["data_coverage_table"]:
        notes = "; ".join(row.get("data_quality_notes") or []) or "—"
        lines.append(
            f"| {row['ticker']} | {row['normalized_rows_rth']} | {row['calibration_decision_log_rows_rth']} | "
            f"{row.get('first_ts_et') or '—'} | {row.get('last_ts_et') or '—'} | {notes} |"
        )
    for t, block in report["tickers"].items():
        cal = block["calibration_log"]
        c = cal["final_signal_counts"]
        lines.extend(["", f"## {t}", "", f"Cal: wait={c['wait']} long={c['long']} short={c['short']}"])
        for w in cal.get("tradeable_windows") or []:
            lines.append(f"- LIVE {w['ts_et']}: {w['final_signal']} entry={w.get('entry_price')}")
        lines.append(f"Evidence: {', '.join(block['evidence_classification'])}")
        for p in block["replays"]:
            drift = " REPLAY_DRIFT" if p.get("replay_drift") else ""
            lines.append(
                f"- {p.get('sample_label')} {p.get('ts_et')}: tradeable={p.get('final_tradeable')} "
                f"call={p.get('call_signal')} layer={p.get('suppression_layer')}{drift}"
            )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Read-only money-path replay for SPY/QQQ/IWM")
    ap.add_argument("--date", required=True)
    ap.add_argument("--tickers", nargs="+", default=list(BASE_MONEY_PATH_TICKERS))
    ap.add_argument("--db", type=Path, default=Path(DB_PATH))
    ap.add_argument("--read-only", action="store_true", default=True)
    ap.add_argument("--direction-integrity", action="store_true", help="Run card direction integrity audit")
    ap.add_argument("--sample-stride", type=int, default=5, help="Decline-interval sample stride (direction audit)")
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--markdown", type=Path, default=None)
    args = ap.parse_args(argv)

    if args.direction_integrity:
        from tools.check_card_direction_integrity import format_markdown, run_direction_integrity_audit

        report = run_direction_integrity_audit(
            day=parse_date(args.date),
            tickers=[t.upper() for t in args.tickers],
            db_path=args.db,
            sample_stride=max(1, args.sample_stride),
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        md_path = args.markdown or args.output.with_suffix(".md")
        md_path.write_text(format_markdown(report), encoding="utf-8")
        print("Wrote", args.output)
        print("Wrote", md_path)
        return 0

    report = run_probe(day=parse_date(args.date), tickers=[t.upper() for t in args.tickers], db_path=args.db)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    md_path = args.markdown or args.output.with_suffix(".md")
    md_path.write_text(markdown_summary(report), encoding="utf-8")
    print("Wrote", args.output)
    print("Wrote", md_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
