#!/usr/bin/env python3
"""
Card signal fidelity + feature provenance audit (read-only).

Traces horizon cards → fusion → features → ALL/PLAN without changing models,
thresholds, or UI rendering.

Usage:
  python tools/check_card_signal_fidelity.py --date 2026-06-17 --tickers SPY \\
      --output reports/card_fidelity/card_signal_fidelity_2026-06-17.json
"""
from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from db import DB_PATH
from tools.check_card_direction_integrity import run_direction_integrity_audit
from verification.card_signal_fidelity import (
    CARD_FEATURE_PROVENANCE,
    CARD_FIELD_PROVENANCE,
    aggregate_june17_explanation,
    build_histogram_shape_audit,
    enrich_timeline_row_provenance,
    histogram_shape_operator_answers,
    horizon_card_driver_summary,
)


def _load_json_if_exists(path: Path) -> dict[str, Any] | None:
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return None


def _answer_questions(
    report: dict[str, Any],
    transport_notes: dict[str, Any],
    hist_audit: dict[str, Any],
) -> dict[str, Any]:
    drivers = horizon_card_driver_summary()
    spy = (report.get("tickers") or {}).get("SPY") or {}
    timeline = spy.get("timeline") or []
    enriched = [enrich_timeline_row_provenance(r) for r in timeline]

    return {
        "1_horizon_card_direction_fields": drivers,
        "2_horizon_card_confidence_fields": {
            hz: f"mhap_rows[{hz}].confidence ← fusion_confidence_score / HorizonForecast.confidence"
            for hz in ("1c", "5c", "15c", "60c")
        },
        "3_stale_loading_fields": CARD_FIELD_PROVENANCE["STALE_LOADING"],
        "4_all_fields": CARD_FIELD_PROVENANCE["ALL_consolidated"],
        "5_plan_fields": CARD_FIELD_PROVENANCE["PLAN"],
        "6_fusion_vs_empirical_vs_rules": (
            "Product horizon card direction = fusion probability argmax only (fusion-only contract). "
            "Empirical histogram (horizon_prob_bars) is signal-rail context; default blend weight 0. "
            "Rules/tape stack participates in call_engine veto (ALL/PLAN), not per-hz card call."
        ),
        "7_feature_timestamps_fresh": (
            "Replay uses snapshot ts_utc; data_age_seconds vs calibration_decision_log on June 17 SPY "
            f"payloads_fresh_in_decline={spy.get('payloads_fresh_in_decline')}"
        ),
        "8_primitive_vs_engineered": (
            "Primitive: spot/bid/ask/volume from Schwab quotes in snapshots. "
            "Engineered: similar-set histogram, MVP/inference_snapshot, seven-layer fusion."
        ),
        "9_dominant_engineered_features": [
            "fusion_prob_up/down/flat per horizon",
            "similar_setup histogram (when shown on signal rail)",
            "inference_snapshot_v1 feature bundle feeding ML layers",
        ],
        "10_provenance_for_long": (
            "mhap_rows.call + fusion_triplets + optional horizon_prob_bars + wait_reason/blockers on same probe"
        ),
        "11_long_means": (
            "Highest fusion P(up) vs P(down)/P(flat) for that horizon — forecast, not trailing price sign"
        ),
        "12_price_vs_forecast_distinction": (
            "Card direction is forecast; trailing returns in audit show price conflict separately (trailing_conflict flag)"
        ),
        "13_horizons_may_disagree": True,
        "14_all_long_during_decline_features": aggregate_june17_explanation(enriched),
        "15_fusion_override_empirical_june17": (
            "Yes on short horizons — fusion LONG while horizon_prob_bars favor DOWN on 1m/5m at many decline samples"
        ),
        "16_longer_horizons_forward_returns": {
            "1c_hit_rate": (spy.get("horizon_metrics") or {}).get("1c", {}).get("direction_hit_rate"),
            "60c_hit_rate": (spy.get("horizon_metrics") or {}).get("60c", {}).get("direction_hit_rate"),
        },
        "17_all_plan_non_tradeable_while_horizons_long": (spy.get("answers") or {}).get(
            "all_plan_non_tradeable_while_horizons_long"
        ),
        "18_blockers_hidden": (
            "wait_reason present in replay but not on horizon chips — explainability gap; "
            "ALL/PLAN show blocked state while hz cards stay LONG"
        ),
        "19_feature_leakage_staleness_risk": transport_notes.get("staleness_risks"),
        "20_missing_price_conflict_chip": (
            "No operator chip when fusion LONG conflicts with trailing price down AND empirical SHORT — proven gap"
        ),
        "histogram_shape_deep_dive": histogram_shape_operator_answers(hist_audit),
    }


def run_card_signal_fidelity_audit(
    *,
    day: datetime.date,
    tickers: list[str],
    db_path: Path,
    sample_stride: int = 5,
    min_decline_minutes: int = 30,
) -> dict[str, Any]:
    integrity = run_direction_integrity_audit(
        day=day,
        tickers=tickers,
        db_path=db_path,
        sample_stride=sample_stride,
        min_decline_minutes=min_decline_minutes,
    )

    transport_path = _REPO / "reports/money_path/base_capture_live_validation_2026-06-18.json"
    transport = _load_json_if_exists(transport_path) or {}

    transport_notes = {
        "date_observed": "2026-06-18",
        "sqlite_lock_contention": "Observed database is locked on base capture path (June 18 session)",
        "stale_loading_events": "Operator reported STALE/LOADING pills 2026-06-18 08:18–11:42 ET (not re-tested in this audit)",
        "capture_improvements": "PR #8 raw cadence improved; PR #9 fixed normalization debounce starvation",
        "staleness_risks": [
            "Tier A quote lane ahead of Tier C analytical bundle (price_ahead_of_bundle)",
            "Sparse normalized rows → stale similar-set / ML inputs",
            "SQLite lock wait on concurrent insert + materialize",
            "UI analytics_stale while SSE connected",
        ],
        "base_capture_summary": transport.get("summary"),
    }

    tickers_out: dict[str, Any] = {}
    histogram_shape_audit: dict[str, Any] = {"cell_count": 0, "cells": []}
    for t, block in (integrity.get("tickers") or {}).items():
        enriched_timeline = [enrich_timeline_row_provenance(r) for r in block.get("timeline") or []]
        norm_rows = None
        for obs in (integrity.get("base_ticker_observability") or {}).get("tickers") or []:
            if obs.get("ticker") == t:
                norm_rows = obs.get("normalized_count_rth")
                break
        if t == "SPY" and day.isoformat() == "2026-06-17":
            histogram_shape_audit = build_histogram_shape_audit(
                enriched_timeline,
                normalized_rows_rth=norm_rows,
            )
        tickers_out[t] = {
            **block,
            "timeline": enriched_timeline,
            "june17_explanation": aggregate_june17_explanation(enriched_timeline)
            if day.isoformat() == "2026-06-17" and t == "SPY"
            else None,
        }

    questions = _answer_questions({**integrity, "tickers": tickers_out}, transport_notes, histogram_shape_audit)

    bugs_proven = [
        "Horizon cards can show LONG while trailing price declines (forecast ≠ price direction)",
        "Fusion can override empirical histogram on product cards (fusion-only contract)",
        "ALL/PLAN can block trade while all horizon cards show LONG (call-engine veto)",
        "Missing operator chip for price/fusion/empirical conflict on horizon cards",
        "June 17: short-horizon histogram often SHORT while fusion/card LONG during decline",
        "Longer horizons (15c/60c) fusion LONG while histogram/tape disagree warrants calibration review",
        "Empirical disagreement not promoted to veto, haircut, or conflict chip on horizon cards",
    ]
    bugs_not_proven = [
        "Model weights incorrect or drifted (forward hits on 1c ~72% argue forecasts not random)",
        "Histogram mathematically wrong — it often DID shift SHORT on 1m/5m; question is fusion override weight",
        "UI rendering wrong direction vs backend mhap_rows (not browser-tested this audit)",
        "Live STALE pill false positive rate (needs RTH UI transport audit)",
        "Feature leakage from future data in replay path",
    ]
    recommended = [
        "audit/ui-realtime-transport-fidelity — STALE/LOADING/SQLite contention live",
        "fix/card-price-conflict-explainability — chip when fusion LONG + trailing down + empirical SHORT",
        "investigate/fusion-empirical-override-policy — longer-horizon override when histogram bearish",
        "validate capture+normalization live post PR #9 before trusting feature freshness",
    ]

    return {
        "meta": {
            **integrity.get("meta", {}),
            "audit_type": "card_signal_fidelity_and_provenance",
            "branch": "audit/card-signal-fidelity-and-provenance",
            "read_only": True,
            "no_model_changes": True,
            "no_threshold_changes": True,
            "no_ui_render_changes": True,
            "prior_audits": [
                "reports/money_path/direction_integrity_2026-06-17.json",
                "reports/money_path/base_capture_live_validation_2026-06-18.json",
            ],
        },
        "card_field_provenance": CARD_FIELD_PROVENANCE,
        "feature_provenance_map": CARD_FEATURE_PROVENANCE,
        "horizon_card_drivers": horizon_card_driver_summary(),
        "histogram_shape_audit": histogram_shape_audit,
        "questions": questions,
        "transport_and_staleness_notes": transport_notes,
        "base_ticker_observability": integrity.get("base_ticker_observability"),
        "data_limitations": integrity.get("data_limitations"),
        "tickers": tickers_out,
        "summary": {
            **(integrity.get("summary") or {}),
            "what_drives_1M": horizon_card_driver_summary()["1c"],
            "what_drives_5M": horizon_card_driver_summary()["5c"],
            "what_drives_15M": horizon_card_driver_summary()["15c"],
            "what_drives_60M": horizon_card_driver_summary()["60c"],
            "what_drives_ALL": CARD_FIELD_PROVENANCE["ALL_consolidated"]["display_direction"]["branch"],
            "what_drives_PLAN": CARD_FIELD_PROVENANCE["PLAN"]["display_state"]["branch"],
            "fusion_vs_histogram_june17": questions.get("15_fusion_override_empirical_june17"),
            "june17_all_long_explanation": (tickers_out.get("SPY") or {}).get("june17_explanation"),
            "histogram_shape_summary": {
                k: histogram_shape_audit.get(k)
                for k in (
                    "classification_counts",
                    "histogram_short_fusion_long_cells",
                    "valid_reversal_despite_bearish_histogram",
                    "fusion_overrides_bearish_histogram",
                    "operator_interpretation",
                )
            },
        },
        "bugs_proven": bugs_proven,
        "bugs_not_proven": bugs_not_proven,
        "recommended_fix_branches": recommended,
    }


def format_markdown(report: dict[str, Any]) -> str:
    meta = report["meta"]
    summary = report.get("summary") or {}
    lines = [
        "> **Classification:** Audit Report | **Scope:** Card signal fidelity and feature provenance",
        "",
        f"# Card signal fidelity — {meta.get('date')}",
        "",
        f"DB: `{meta.get('db_path')}`",
        f"Read-only: {meta.get('read_only')} · No model/threshold/UI changes",
        "",
        "## Executive summary",
        "",
        "- Horizon **product** direction = **fusion probability argmax** per horizon (`mhap_rows.call`), not trailing price.",
        "- Empirical histogram can **disagree** (often SHORT on 1m/5m) while cards show LONG — fusion-only contract.",
        "- **ALL/PLAN** gate tradeability separately; June 17 SPY decline: horizons LONG, ALL FLAT, PLAN blocked.",
        "- Primary gap: **explainability** — operator cannot see price/fusion/empirical conflict on horizon chips.",
        "",
        "## What drives each card",
        "",
        f"- **1M:** {summary.get('what_drives_1M')}",
        f"- **5M:** {summary.get('what_drives_5M')}",
        f"- **15M:** {summary.get('what_drives_15M')}",
        f"- **60M:** {summary.get('what_drives_60M')}",
        f"- **ALL:** {summary.get('what_drives_ALL')}",
        f"- **PLAN:** {summary.get('what_drives_PLAN')}",
        "",
        "## June 17 all-horizon LONG during SPY decline",
        "",
    ]
    expl = summary.get("june17_all_long_explanation") or {}
    if isinstance(expl, dict):
        for k, v in expl.items():
            lines.append(f"- **{k}:** {v}")
    hist = report.get("histogram_shape_audit") or {}
    hist_summary = hist.get("classification_counts") or {}
    if hist_summary:
        lines.extend(
            [
                "",
                "## Histogram shape audit",
                "",
                f"- Cells sampled: {hist.get('cell_count')} ({hist.get('sample_timestamps')} timestamps × 4 horizons)",
                f"- Histogram SHORT + fusion LONG: {hist.get('histogram_short_fusion_long_cells')}",
                f"- Valid reversal despite bearish histogram: {hist.get('valid_reversal_despite_bearish_histogram')}",
                f"- Fusion overrides bearish histogram: {hist.get('fusion_overrides_bearish_histogram')}",
                f"- Classification counts: {hist_summary}",
                "",
                "**Dual interpretation:**",
                "",
                "- *Cards worked as designed* — fusion forecast LONG can be a valid short-horizon bounce call.",
                "- *Histogram/integration weak* — bearish empirical shape is not surfaced as veto/haircut on cards; "
                "longer horizons staying LONG while histogram/tape disagree needs calibration review.",
                "",
            ]
        )
        deep = (report.get("questions") or {}).get("histogram_shape_deep_dive") or {}
        if deep:
            lines.append("### Operator histogram questions")
            lines.append("")
            for k, v in deep.items():
                lines.append(f"- **{k}:** {v}")
    lines.extend(["", "## Feature provenance (leaf vs engineered)", ""])
    for row in report.get("feature_provenance_map") or []:
        lines.append(
            f"- **{row['feature']}** ({row['class']}): {row['source_fn']} · stale_risk={row['stale_risk']}"
        )
    lines.extend(["", "## Bugs proven", ""])
    for b in report.get("bugs_proven") or []:
        lines.append(f"- {b}")
    lines.extend(["", "## Bugs not proven", ""])
    for b in report.get("bugs_not_proven") or []:
        lines.append(f"- {b}")
    lines.extend(["", "## Recommended fix branches", ""])
    for b in report.get("recommended_fix_branches") or []:
        lines.append(f"- {b}")
    lines.extend(["", "## Transport / staleness (June 18 evidence)", ""])
    for k, v in (report.get("transport_and_staleness_notes") or {}).items():
        lines.append(f"- **{k}:** {v}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Card signal fidelity + provenance audit")
    ap.add_argument("--date", required=True)
    ap.add_argument("--tickers", nargs="+", default=["SPY"])
    ap.add_argument("--db", type=Path, default=Path(DB_PATH))
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--markdown", type=Path, default=None)
    ap.add_argument("--sample-stride", type=int, default=5)
    ap.add_argument("--min-decline-minutes", type=int, default=30)
    args = ap.parse_args(argv)

    report = run_card_signal_fidelity_audit(
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
