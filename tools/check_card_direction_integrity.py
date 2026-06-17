#!/usr/bin/env python3
"""
Read-only card direction integrity audit — base tickers SPY / QQQ / IWM.

Compares horizon card directions (mhap_rows) against trailing and forward
realized price returns. Does not change models, thresholds, or UI rendering.

Usage:
  python tools/check_card_direction_integrity.py --date 2026-06-16 --tickers SPY QQQ IWM \\
      --output reports/money_path/direction_integrity_2026-06-16.json
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any, Optional

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from db import DB_PATH
from money_path_ticker_tiers import BASE_MONEY_PATH_TICKERS, is_base_money_path_ticker
from verification.base_ticker_observability import base_ticker_observability_report
from verification.card_direction_integrity import (
    CLASS_FROZEN_BACKEND,
    CLASS_INSUFFICIENT,
    CLASS_MISSING_GUARD,
    CLASS_MODEL_DRIFT,
    CLASS_STALE_PAYLOAD,
    CLASS_VALID_HTF_LONG,
    CLASS_VALID_MEAN_REVERSION,
    CLASS_VALID_REVERSAL,
    DEFAULT_ALLOWED_DATA_AGE_SECONDS,
    DEFAULT_MIN_DECLINE_MINUTES,
    HORIZON_FORWARD_BARS,
    HORIZON_SLUGS,
    aggregate_horizon_metrics,
    classify_long_during_decline,
    direction_hit,
    direction_sign,
    drawdown_from_session_high,
    find_decline_intervals,
    forward_return_at_index,
    fusion_direction_from_probs,
    mhap_direction_map,
    stale_conflict,
    trailing_conflict,
    trailing_return_at_index,
    ts_et_label,
    ui_card_state_from_probe,
)
from tools.replay_money_path_probe import probe_snapshot_row, rth_window_utc


def _connect_ro(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def load_price_series(
    conn: sqlite3.Connection,
    ticker: str,
    rth_start: float,
    rth_end: float,
) -> tuple[list[float], list[float], list[dict[str, Any]]]:
    tu = ticker.upper()
    rows = conn.execute(
        """
        SELECT ts_utc, spot FROM snapshots_1m_normalized
        WHERE ticker=? AND ts_utc BETWEEN ? AND ? AND spot IS NOT NULL
        ORDER BY ts_utc
        """,
        (tu, rth_start, rth_end),
    ).fetchall()
    ts_list = [float(r["ts_utc"]) for r in rows]
    prices = [float(r["spot"]) for r in rows]
    return ts_list, prices, [{"ts_utc": t, "spot": p} for t, p in zip(ts_list, prices)]


def _nearest_snapshot_row(
    norm_rows: list[dict[str, Any]],
    ts: float,
    *,
    max_delta_sec: float = 90.0,
) -> Optional[dict[str, Any]]:
    if not norm_rows:
        return None
    best = min(norm_rows, key=lambda r: abs(float(r["ts_utc"]) - ts))
    if abs(float(best["ts_utc"]) - ts) > max_delta_sec:
        return None
    return best


def _cal_row_at_ts(
    conn: sqlite3.Connection,
    ticker: str,
    ts: float,
    *,
    max_delta_sec: float = 90.0,
) -> Optional[sqlite3.Row]:
    return conn.execute(
        """
        SELECT decision_ts_utc, multi_horizon_json, fusion_json, model_outputs_json,
               outcome_1c_pts, outcome_5c_pts, outcome_15c_pts, outcome_60c_pts,
               entry_price, final_signal
        FROM calibration_decision_log
        WHERE ticker=? AND ABS(decision_ts_utc - ?) <= ?
        ORDER BY ABS(decision_ts_utc - ?) ASC
        LIMIT 1
        """,
        (ticker.upper(), ts, max_delta_sec, ts),
    ).fetchone()


def _fusion_triplets_from_cal(cal_row: Optional[sqlite3.Row]) -> dict[str, dict[str, Optional[float]]]:
    if cal_row is None:
        return {}
    try:
        mo = json.loads(cal_row["model_outputs_json"] or "{}")
        by_hz = (mo.get("stack_probs_bundle") or {}).get("multi_horizon_ml_fusion_bundle", {}).get(
            "by_horizon", {}
        )
    except (json.JSONDecodeError, TypeError):
        return {}
    out: dict[str, dict[str, Optional[float]]] = {}
    for hz in HORIZON_SLUGS:
        block = by_hz.get(hz) or {}
        out[hz] = {
            "up": block.get("prob_up"),
            "down": block.get("prob_down"),
            "flat": block.get("flat") if "flat" in block else block.get("prob_flat"),
            "dominant_direction": block.get("dominant_direction"),
        }
    return out


def _histogram_direction(probe: dict[str, Any], hz_label: str) -> str:
    b = (probe.get("horizon_prob_bars") or {}).get(hz_label) or {}
    return fusion_direction_from_probs(b.get("up"), b.get("down"), b.get("flat"))


def _payload_frozen(
    probe: dict[str, Any],
    prev_probe: Optional[dict[str, Any]],
    data_age: Optional[float],
) -> bool:
    if prev_probe is None or data_age is None or data_age > DEFAULT_ALLOWED_DATA_AGE_SECONDS:
        return False
    return (
        probe.get("mhap_rows") == prev_probe.get("mhap_rows")
        and probe.get("fusion_triplets") == prev_probe.get("fusion_triplets")
        and probe.get("final_bias") == prev_probe.get("final_bias")
    )


def _build_timeline_row(
    *,
    index: int,
    ts_list: list[float],
    prices: list[float],
    probe: dict[str, Any],
    cal_row: Optional[sqlite3.Row],
    prev_probe: Optional[dict[str, Any]],
    allowed_age_seconds: float,
) -> dict[str, Any]:
    ts = float(ts_list[index])
    spot = prices[index]
    cal_ts = float(cal_row["decision_ts_utc"]) if cal_row is not None else None
    data_age = abs(ts - cal_ts) if cal_ts is not None else None

    mhap = mhap_direction_map(probe.get("mhap_rows") or [])
    fusion_triplets = probe.get("fusion_triplets") or _fusion_triplets_from_cal(cal_row)
    ui = ui_card_state_from_probe(probe)

    row: dict[str, Any] = {
        "ts_utc": ts,
        "ts_et": ts_et_label(ts),
        "ticker": probe.get("ticker"),
        "spot": spot,
        "trailing_return_1m": trailing_return_at_index(prices, index, 1),
        "trailing_return_5m": trailing_return_at_index(prices, index, 5),
        "trailing_return_15m": trailing_return_at_index(prices, index, 15),
        "trailing_return_60m": trailing_return_at_index(prices, index, 60),
        "drawdown_from_session_high": drawdown_from_session_high(prices, index),
        "card_direction_1M": mhap.get("1c"),
        "card_direction_5M": mhap.get("5c"),
        "card_direction_15M": mhap.get("15c"),
        "card_direction_60M": mhap.get("60c"),
        "ALL_direction": ui.get("ALL_direction"),
        "PLAN_state": ui.get("PLAN_state"),
        "mhap_rows": probe.get("mhap_rows"),
        "fusion_triplets": fusion_triplets,
        "horizon_prob_bars": probe.get("horizon_prob_bars"),
        "final_bias": probe.get("final_bias"),
        "final_tradeable": probe.get("final_tradeable"),
        "call_signal": probe.get("call_signal"),
        "wait_reason": probe.get("wait_reason"),
        "fusion_available": probe.get("fusion_available"),
        "cal_decision_ts_utc": cal_ts,
        "data_age_seconds": round(data_age, 3) if data_age is not None else None,
        "payload_frozen": _payload_frozen(probe, prev_probe, data_age),
        "ui_card_state": ui,
        "classifications": [],
    }

    hist_map = {"1c": "1m", "5c": "5m", "15c": "15m", "60c": "60m"}
    trailing_by_hz = {
        "1c": row["trailing_return_1m"],
        "5c": row["trailing_return_5m"],
        "15c": row["trailing_return_15m"],
        "60c": row["trailing_return_60m"],
    }
    for hz in HORIZON_SLUGS:
        bars_fwd = HORIZON_FORWARD_BARS[hz]
        fwd = forward_return_at_index(prices, index, bars_fwd)
        if cal_row is not None and cal_row[f"outcome_{hz}_pts"] is not None and spot:
            fwd_pts = float(cal_row[f"outcome_{hz}_pts"]) / float(spot)
            fwd = fwd if fwd is not None else fwd_pts
        displayed = mhap.get(hz)
        tr_hz = trailing_by_hz[hz]
        tr1 = row["trailing_return_1m"]
        tr60 = row["trailing_return_60m"]
        ft = fusion_triplets.get(hz) or {}
        fus_dir = fusion_direction_from_probs(ft.get("up"), ft.get("down"), ft.get("flat"))
        hist_dir = _histogram_direction(probe, hist_map[hz])
        tr_conf = trailing_conflict(displayed, tr_hz)
        row[f"horizon_{hz}"] = {
            "displayed_direction": displayed,
            "forward_realized_return": fwd,
            "trailing_realized_return": tr_hz,
            "trailing_realized_return_1m": tr1,
            "forecast_probability_up": ft.get("up"),
            "forecast_probability_down": ft.get("down"),
            "forecast_probability_flat": ft.get("flat"),
            "fusion_direction": fus_dir,
            "histogram_direction": hist_dir,
            "direction_hit": direction_hit(displayed, fwd),
            "trailing_conflict": tr_conf,
            "stale_conflict": stale_conflict(
                trailing_conflict_flag=tr_conf,
                data_age_seconds=data_age,
                allowed_age_seconds=allowed_age_seconds,
            ),
        }

    fwd1 = (row.get("horizon_1c") or {}).get("forward_realized_return")
    fwd60 = (row.get("horizon_60c") or {}).get("forward_realized_return")
    for hz in HORIZON_SLUGS:
        block = row.get(f"horizon_{hz}") or {}
        displayed = block.get("displayed_direction")
        if direction_sign(displayed) != 1 or not block.get("trailing_conflict"):
            continue
        row["classifications"].extend(
            classify_long_during_decline(
                displayed_direction=displayed or "",
                trailing_return_1m=row["trailing_return_1m"],
                trailing_return_60m=row["trailing_return_60m"],
                forward_return_1m=fwd1,
                forward_return_60m=fwd60,
                data_age_seconds=data_age,
                payload_frozen=row["payload_frozen"],
                fusion_stayed_long=(block.get("fusion_direction") or "").upper() == "LONG",
                histogram_stayed_long=(block.get("histogram_direction") or "").upper() == "LONG",
                final_tradeable=probe.get("final_tradeable"),
                allowed_age_seconds=allowed_age_seconds,
            )
        )

    row["classifications"] = sorted(set(row["classifications"]))
    return row


def audit_ticker(
    *,
    ticker: str,
    day: datetime.date,
    db_path: Path,
    sample_stride: int = 1,
    allowed_age_seconds: float = DEFAULT_ALLOWED_DATA_AGE_SECONDS,
    min_decline_minutes: int = DEFAULT_MIN_DECLINE_MINUTES,
) -> dict[str, Any]:
    from db import EdDB

    rth_start, rth_end = rth_window_utc(day)
    conn = _connect_ro(db_path)
    ts_list, prices, _ = load_price_series(conn, ticker, rth_start, rth_end)
    norm_rows = [
        {k: r[k] for k in r.keys()}
        for r in conn.execute(
            "SELECT * FROM snapshots_1m_normalized WHERE ticker=? AND ts_utc BETWEEN ? AND ? ORDER BY ts_utc",
            (ticker.upper(), rth_start, rth_end),
        ).fetchall()
    ]

    decline_intervals = find_decline_intervals(ts_list, prices, min_decline_minutes=min_decline_minutes)
    db = EdDB(str(db_path))
    timeline: list[dict[str, Any]] = []
    prev_probe: Optional[dict[str, Any]] = None

    for interval in decline_intervals:
        for idx in range(int(interval["start_idx"]), int(interval["end_idx"]) + 1, max(1, sample_stride)):
            snap = _nearest_snapshot_row(norm_rows, ts_list[idx])
            if snap is None:
                continue
            try:
                probe = probe_snapshot_row(db, snap)
            except Exception as e:
                probe = {"ticker": ticker.upper(), "ts_utc": ts_list[idx], "stack_error": repr(e)}
            cal_row = _cal_row_at_ts(conn, ticker, ts_list[idx])
            timeline.append(
                _build_timeline_row(
                    index=idx,
                    ts_list=ts_list,
                    prices=prices,
                    probe=probe,
                    cal_row=cal_row,
                    prev_probe=prev_probe,
                    allowed_age_seconds=allowed_age_seconds,
                )
            )
            prev_probe = probe

    conn.close()
    horizon_metrics = {hz: aggregate_horizon_metrics(timeline, hz) for hz in HORIZON_SLUGS}
    class_counts: dict[str, int] = {}
    for row in timeline:
        for tag in row.get("classifications") or []:
            class_counts[tag] = class_counts.get(tag, 0) + 1

    long_during_decline = [
        r
        for r in timeline
        if any(
            (r.get(f"horizon_{hz}") or {}).get("trailing_conflict")
            and direction_sign((r.get(f"horizon_{hz}") or {}).get("displayed_direction")) == 1
            for hz in HORIZON_SLUGS
        )
    ]

    return {
        "ticker": ticker.upper(),
        "price_rows_rth": len(prices),
        "decline_intervals": decline_intervals,
        "timeline_sample_count": len(timeline),
        "timeline": timeline,
        "horizon_metrics": horizon_metrics,
        "classification_counts": class_counts,
        "long_during_decline_samples": len(long_during_decline),
        "payloads_fresh_in_decline": (
            all((r.get("data_age_seconds") or 999) <= allowed_age_seconds for r in timeline)
            if timeline
            else None
        ),
        "answers": _answer_block(timeline, long_during_decline, class_counts),
    }


def _pct(rows: list[dict[str, Any]], pred) -> Optional[float]:
    if not rows:
        return None
    return round(sum(1 for r in rows if pred(r)) / len(rows), 4)


def _horizon_miss_rate(timeline: list[dict[str, Any]], hz: str) -> Optional[float]:
    hits = [
        (r.get(f"horizon_{hz}") or {}).get("direction_hit")
        for r in timeline
        if (r.get(f"horizon_{hz}") or {}).get("direction_hit") is not None
    ]
    return round(sum(1 for h in hits if h is False) / len(hits), 4) if hits else None


def _horizon_hit_rate(timeline: list[dict[str, Any]], hz: str) -> Optional[float]:
    hits = [
        (r.get(f"horizon_{hz}") or {}).get("direction_hit")
        for r in timeline
        if (r.get(f"horizon_{hz}") or {}).get("direction_hit") is not None
    ]
    return round(sum(1 for h in hits if h is True) / len(hits), 4) if hits else None


def _primary_classification(
    class_counts: dict[str, int],
    frozen_n: int,
    stale_n: int,
    valid_n: int,
    drift_n: int,
) -> str:
    if frozen_n or stale_n:
        return "stale_data_or_frozen_backend"
    if valid_n > drift_n:
        return "valid_forecast_explainability_gap"
    if drift_n:
        return "model_direction_drift"
    if class_counts.get(CLASS_INSUFFICIENT):
        return "insufficient_evidence"
    return "mixed_or_inconclusive"


def _answer_block(
    timeline: list[dict[str, Any]],
    long_during_decline: list[dict[str, Any]],
    class_counts: dict[str, int],
) -> dict[str, Any]:
    if not timeline:
        return {"cards_updating": None, "note": "no timeline samples in decline intervals"}

    frozen_n = class_counts.get(CLASS_FROZEN_BACKEND, 0)
    stale_n = class_counts.get(CLASS_STALE_PAYLOAD, 0)
    valid_n = sum(
        class_counts.get(k, 0)
        for k in (CLASS_VALID_REVERSAL, CLASS_VALID_MEAN_REVERSION, CLASS_VALID_HTF_LONG)
    )
    drift_n = class_counts.get(CLASS_MODEL_DRIFT, 0)
    guard_n = class_counts.get(CLASS_MISSING_GUARD, 0)

    return {
        "cards_updating_during_decline": frozen_n == 0
        and len({json.dumps(r.get("mhap_rows"), sort_keys=True) for r in timeline}) > 1,
        "mhap_timestamps_stale": stale_n > 0,
        "fusion_stayed_long_pct": _pct(
            timeline,
            lambda r: ((r.get("horizon_1c") or {}).get("fusion_direction") or "").upper() == "LONG",
        ),
        "histogram_stayed_long_pct": _pct(
            timeline,
            lambda r: ((r.get("horizon_1c") or {}).get("histogram_direction") or "").upper() == "LONG",
        ),
        "shorter_horizons_forward_miss": _horizon_miss_rate(timeline, "1c"),
        "longer_horizons_forward_hit": _horizon_hit_rate(timeline, "60c"),
        "all_plan_non_tradeable_while_horizons_long": _pct(
            long_during_decline,
            lambda r: r.get("final_tradeable") is False and r.get("ALL_direction") in ("FLAT", "WAIT"),
        ),
        "missing_price_integrity_warning": guard_n > 0,
        "primary_classification": _primary_classification(
            class_counts, frozen_n, stale_n, valid_n, drift_n
        ),
    }


def run_direction_integrity_audit(
    *,
    day: datetime.date,
    tickers: list[str],
    db_path: Path,
    sample_stride: int = 1,
    min_decline_minutes: int = DEFAULT_MIN_DECLINE_MINUTES,
) -> dict[str, Any]:
    if not db_path.is_file():
        raise FileNotFoundError(f"DB not found: {db_path}")

    os.environ.setdefault("SCHWAB_API_KEY", "ci-placeholder-key")
    os.environ.setdefault("SCHWAB_APP_SECRET", "ci-placeholder-secret")
    os.environ.setdefault("SCHWAB_CALLBACK_URL", "https://127.0.0.1:8182")

    obs = base_ticker_observability_report(day=day, tickers=tickers, db_path=db_path)
    ticker_blocks = {
        t.upper(): audit_ticker(
            ticker=t.upper(),
            day=day,
            db_path=db_path,
            sample_stride=sample_stride,
            min_decline_minutes=min_decline_minutes,
        )
        for t in tickers
    }

    all_intervals = []
    for t, block in ticker_blocks.items():
        for iv in block.get("decline_intervals") or []:
            tagged = dict(iv)
            tagged["ticker"] = t
            all_intervals.append(tagged)

    return {
        "meta": {
            "date": day.isoformat(),
            "rth_et": "09:30-16:00 ET",
            "db_path": str(db_path.resolve()),
            "read_only": True,
            "audit_type": "card_direction_integrity",
            "tickers": [t.upper() for t in tickers],
            "base_universe_observability_ready": obs["meta"]["base_universe_ready"],
            "method_note": (
                "Card direction from replayed mhap_rows; forward returns from price series "
                "and calibration outcome_*_pts when present. Trailing decline != automatic miss."
            ),
            "min_decline_minutes": min_decline_minutes,
        },
        "base_ticker_observability": obs,
        "tickers": ticker_blocks,
        "summary": {
            "decline_intervals_found": len(all_intervals),
            "tickers_with_decline": sorted({iv["ticker"] for iv in all_intervals}),
            "long_during_decline_total_samples": sum(
                block.get("long_during_decline_samples") or 0 for block in ticker_blocks.values()
            ),
        },
    }


def format_markdown(report: dict[str, Any]) -> str:
    lines = [
        "> **Classification:** Audit Report | **Scope:** Card direction integrity vs price movement (SPY/QQQ/IWM)",
        "",
        f"# Card direction integrity — {report['meta']['date']}",
        "",
        f"DB: `{report['meta']['db_path']}`",
        f"Min decline window: {report['meta'].get('min_decline_minutes', '—')} minutes",
        "",
        "## Summary",
        "",
        f"- Decline intervals: {report['summary']['decline_intervals_found']}",
        f"- Tickers with decline: {', '.join(report['summary']['tickers_with_decline']) or '—'}",
        f"- LONG-during-decline samples (any horizon): {report['summary']['long_during_decline_total_samples']}",
        "",
        "## Base ticker observability",
        "",
    ]
    for row in report.get("base_ticker_observability", {}).get("tickers") or []:
        lines.append(
            f"- **{row['ticker']}**: {row.get('coverage_status')} — "
            f"norm_rows={row.get('normalized_count_rth')} cal_rows={row.get('calibration_decision_count_rth')} "
            f"({row.get('reason')})"
        )
    lines.append("")
    for t, block in report["tickers"].items():
        lines.append(f"## {t}")
        for iv in block.get("decline_intervals") or []:
            lines.append(
                f"- Decline {iv['start_ts_et']} → {iv['end_ts_et']} "
                f"({iv['duration_minutes']} min, seg_ret={iv.get('segment_return')})"
            )
        ans = block.get("answers") or {}
        lines.append(f"- Primary: **{ans.get('primary_classification')}**")
        lines.append(f"- Payloads fresh in decline: {block.get('payloads_fresh_in_decline')}")
        lines.append(f"- LONG-during-decline samples: {block.get('long_during_decline_samples')}")
        lines.append(f"- Horizon 1c hit rate: {(block.get('horizon_metrics') or {}).get('1c', {}).get('direction_hit_rate')}")
        lines.append(f"- Classifications: {block.get('classification_counts')}")
        if ans.get("note"):
            lines.append(f"- Note: {ans.get('note')}")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Card direction integrity audit (base tickers)")
    ap.add_argument("--date", required=True)
    ap.add_argument("--tickers", nargs="+", default=list(BASE_MONEY_PATH_TICKERS))
    ap.add_argument("--db", type=Path, default=Path(DB_PATH))
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--markdown", type=Path, default=None)
    ap.add_argument("--sample-stride", type=int, default=5)
    ap.add_argument("--min-decline-minutes", type=int, default=DEFAULT_MIN_DECLINE_MINUTES)
    args = ap.parse_args(argv)

    for t in args.tickers:
        if not is_base_money_path_ticker(t):
            print(f"WARN: {t} is not a base money-path ticker", file=sys.stderr)

    report = run_direction_integrity_audit(
        day=datetime.date.fromisoformat(args.date.strip()),
        tickers=[t.upper() for t in args.tickers],
        db_path=args.db,
        sample_stride=max(1, args.sample_stride),
        min_decline_minutes=max(15, args.min_decline_minutes),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    md_path = args.markdown or args.output.with_suffix(".md")
    md_path.write_text(format_markdown(report), encoding="utf-8")
    print("Wrote", args.output)
    print("Wrote", md_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
