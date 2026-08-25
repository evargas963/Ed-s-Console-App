#!/usr/bin/env python3
"""
UI real-time transport fidelity audit (read-only).

Traces SSE/REST/hybrid transport, STALE/LOADING semantics, ownership guards,
and SQLite contention evidence. Does not change models or card meaning.

Usage:
  python tools/check_ui_realtime_transport_audit.py \\
      --output reports/ui_transport/ui_realtime_transport_audit_2026-06-18.json
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

from verification.ui_realtime_transport_audit import (
    TransportMetricsAccumulator,
    answer_audit_questions,
    audit_core_vs_guest_ticker_switching,
    bugs_proven_and_unproven,
    ingest_transport_event,
    parse_sqlite_contention_from_text,
    recommended_fix_branches,
    scan_static_surfaces,
    static_transport_mechanisms,
    summarize_metrics,
)

DEFAULT_JSON = _REPO / "reports/ui_transport/ui_realtime_transport_audit_2026-06-18.json"


def _load_switch_diag_events() -> list[dict[str, Any]]:
    try:
        from ticker_switch_diagnostics import get_recent_events

        return get_recent_events(limit=100)
    except Exception:
        return []


def _scrape_log_files() -> tuple[str, list[str]]:
    """Collect server log text from known locations."""
    texts: list[str] = []
    paths_scanned: list[str] = []
    candidates = [
        _REPO / "logs",
        _REPO / "enforce_all_out.txt",
    ]
    for base in candidates:
        if base.is_file():
            try:
                texts.append(base.read_text(encoding="utf-8", errors="replace"))
                paths_scanned.append(str(base))
            except OSError:
                pass
        elif base.is_dir():
            for p in sorted(base.glob("*.log"))[:20]:
                try:
                    texts.append(p.read_text(encoding="utf-8", errors="replace"))
                    paths_scanned.append(str(p))
                except OSError:
                    pass
            for p in sorted(base.glob("*.err"))[:10]:
                try:
                    texts.append(p.read_text(encoding="utf-8", errors="replace"))
                    paths_scanned.append(str(p))
                except OSError:
                    pass
    return "\n".join(texts), paths_scanned


def run_ui_transport_audit(
    *,
    audit_date: datetime.date,
    output_json: Path,
    market_session: str = "offline_static",
) -> dict[str, Any]:
    mechanisms = static_transport_mechanisms()
    static_scan = scan_static_surfaces()
    core_vs_guest = audit_core_vs_guest_ticker_switching()
    log_text, log_paths = _scrape_log_files()
    sqlite_log = parse_sqlite_contention_from_text(log_text)

    acc = TransportMetricsAccumulator(
        sqlite_lock_wait_count=sqlite_log.get("sqlite_lock_wait_count", 0),
        sqlite_database_locked_count=sqlite_log.get("sqlite_database_locked_count", 0),
    )
    switch_events = _load_switch_diag_events()
    for ev in switch_events:
        ingest_transport_event(acc, ev)

    metrics = summarize_metrics(acc)
    questions = answer_audit_questions(
        mechanisms,
        metrics,
        sqlite_log,
        static_scan,
        market_session=market_session,
    )
    bugs = bugs_proven_and_unproven(sqlite_log, metrics)

    report: dict[str, Any] = {
        "schema_version": 1,
        "classification": "Audit Report",
        "scope": "UI real-time transport fidelity",
        "audit_date": audit_date.isoformat(),
        "branch": "audit/ui-realtime-transport-fidelity",
        "market_session": market_session,
        "transport_mechanisms": mechanisms,
        "metrics": metrics,
        "sqlite_log_scan": {
            "paths": log_paths,
            **sqlite_log,
        },
        "switch_diag_events_in_memory": len(switch_events),
        "switch_diag_sample": switch_events[:5],
        "audit_questions": questions,
        "core_vs_guest_ticker_switching": core_vs_guest,
        "bugs": bugs,
        "recommended_fix_branches": recommended_fix_branches(),
        "acceptance_standards": {
            "ui_loading_on_switch_ms": 100,
            "warm_first_payload_ms": 2000,
            "warm_full_card_render_ms": 3000,
            "no_old_ticker_overwrite": True,
            "payload_must_include_ticker_timestamp": True,
        },
        "instrumentation_gaps": mechanisms.get("instrumentation_gaps", []),
        "static_surface_scan": static_scan,
        "live_validation_required": [
            "Warm ticker switch latency under RTH with ED_SWITCH_TIMING=1",
            "STALE pill timeline correlation with feed state + lane stale chip",
            "SQLite lock wait impact on Tier C refresh during concurrent base capture",
        ],
    }
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def _render_markdown(report: dict[str, Any], md_path: Path) -> None:
    m = report.get("metrics") or {}
    mech = report.get("transport_mechanisms") or {}
    bugs = report.get("bugs") or {}
    lines = [
        "> **Classification:** Audit Report | **Scope:** UI real-time transport fidelity",
        "",
        f"**Branch:** `{report.get('branch', '')}`",
        f"**Date/session audited:** {report.get('audit_date', '')} ({report.get('market_session', '')})",
        "",
        "## Transport mechanisms found",
        "",
        f"**Classification:** {mech.get('classification', 'hybrid')}",
        "",
        "### What drives cards",
        "",
    ]
    for item in (mech.get("card_drivers") or {}).get("tier_c_full_cards", []):
        lines.append(f"- {item}")
    lines.extend(
        [
            "",
            "### What drives price/header",
            "",
        ]
    )
    for item in mech.get("price_header_drivers") or []:
        lines.append(f"- {item}")
    lines.extend(["", "### What drives FEED LIVE", ""])
    for k, v in (mech.get("feed_live_ui_active") or {}).items():
        lines.append(f"- **{k}:** {v}")
    lines.extend(["", "### What drives STALE", ""])
    for k, v in (mech.get("stale_drivers") or {}).items():
        lines.append(f"- **{k}:** {v}")
    lines.extend(["", "### What drives LOADING", ""])
    for k, v in (mech.get("loading_drivers") or {}).items():
        lines.append(f"- **{k}:** {v}")
    lines.extend(
        [
            "",
            "## Startup critical path",
            "",
            "1. `static/index.html` shell load",
            "2. Initial `fetchState` → Tier A `/api/live/state` concurrent with async Tier C",
            "3. `runTickerLiveAcquisition` → SSE `/api/stream` + L1 `/api/analytics/light/stream` + `/api/fast-quote`",
            "4. First card paint when Tier C payload with `mhap_rows` passes `_renderCoherenceGuards`",
            "",
            "## Ticker-switch critical path",
            "",
            "1. `setActiveTicker` → `requestGeneration++`, optional cache restore",
            "2. `runTickerLiveAcquisition` (SSE force reconnect + fast quote)",
            "3. Tier A/B concurrent REST; Tier C `_fetchTierCRestAndApply` **not awaited** on switch",
            "4. Guards discard superseded generation / wrong ticker",
            "",
            "## Measured startup latency",
            "",
            f"- startup_time_to_shell_ms: {m.get('startup_time_to_shell_ms')}",
            f"- startup_time_to_first_payload_ms: {m.get('startup_time_to_first_payload_ms')}",
            f"- startup_time_to_first_card_render_ms: {m.get('startup_time_to_first_card_render_ms')}",
            "",
            "## Measured ticker-switch latency",
            "",
            f"- click_to_loading p50: {m.get('ticker_switch_click_to_loading_ms_p50')} ms",
            f"- click_to_card_render p50: {m.get('ticker_switch_click_to_card_render_ms_p50')} ms",
            f"- switch_diag samples: {(m.get('sample_counts') or {}).get('switch_events', 0)}",
            "",
            "## Backend bottleneck",
            "",
            "Tier C `_fetch_state` (Schwab chain + DB + seven-layer stack). Non-blocking on switch but poll/SSE still compete with snapshot writes.",
            "",
            "## Frontend bottleneck",
            "",
            "Full `render()` DOM work on Tier C; lane stale chip when quote lane leads analytical bundle.",
            "",
            "## SQLite contention evidence",
            "",
            json.dumps(report.get("sqlite_log_scan") or {}, indent=2),
            "",
            "## Stale/out-of-order risk",
            "",
            "- Quote lane can lead bundle → LANE STALE — QUOTE AHEAD (expected during refresh)",
            "- Superseded REST responses discarded by `requestGeneration` guard",
            "",
            "## Old ticker overwrite risk",
            "",
            str((report.get("audit_questions") or {}).get("7_old_ticker_overwrite_risk", "")),
            "",
            "## Missing metadata",
            "",
        ]
    )
    for gap in report.get("instrumentation_gaps") or []:
        lines.append(f"- {gap}")
    lines.extend(["", "## Bugs proven", ""])
    for b in bugs.get("bugs_proven") or []:
        lines.append(f"- {b}")
    lines.extend(["", "## Bugs not proven", ""])
    for b in bugs.get("bugs_not_proven") or []:
        lines.append(f"- {b}")
    lines.extend(["", "## Tests added", ""])
    lines.append("- `tests/test_live_ui_integrity_v1.py` — transport guard + feed state + sqlite parse helpers")
    lines.extend(["", "## Files changed", ""])
    lines.append("- `verification/ui_realtime_transport_audit.py`")
    lines.append("- `tools/check_ui_realtime_transport_audit.py`")
    lines.append("- `tests/test_live_ui_integrity_v1.py`")
    lines.append(f"- `{md_path.name}`")
    lines.extend(["", "## Objective audit", ""])
    # enforce_all_rules.py retired 2026-07-16; the live catalog is the objective audit.
    lines.append("Run: `python tools/check_institutional_correctness.py`")
    lines.extend(["", "## Recommended fix branches", ""])
    for row in report.get("recommended_fix_branches") or []:
        lines.append(f"- `{row.get('branch')}` — {row.get('reason')}")
    lines.extend(["", "## Live validation still required", ""])
    for item in report.get("live_validation_required") or []:
        lines.append(f"- {item}")
    cvg = report.get("core_vs_guest_ticker_switching") or {}
    lines.extend(
        [
            "",
            "## Core vs guest ticker switching",
            "",
            f"**Operator requirement:** {cvg.get('operator_requirement', '')}",
            "",
            f"- **Transport guards tier-agnostic:** {cvg.get('transport_guards_tier_agnostic')}",
            f"- **activeTicker ownership guest-safe:** {cvg.get('active_ticker_ownership_guest_safe')}",
            f"- **Wrong-ticker discarded (matrix):** {cvg.get('wrong_ticker_discarded_all_pairs')}",
            f"- **Cache restore marks stale (matrix):** {cvg.get('cache_restore_stale_all_pairs')}",
            f"- **Guest payload metadata same contract as core:** {cvg.get('guest_payload_metadata_required_same_as_core')}",
            f"- **Guest missing data visibly explained:** {cvg.get('guest_missing_data_visible')}",
            f"- **Core cards persist after guest switch risk:** {cvg.get('core_cards_can_persist_after_guest_switch_risk')}",
            "",
            "### Question 21",
            "",
            str((report.get('audit_questions') or {}).get('21_core_and_guest_ticker_switch_safe', '')),
            "",
            "### Guest live validation still required",
            "",
        ]
    )
    for item in cvg.get("live_validation_required_guest") or []:
        lines.append(f"- {item}")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="UI real-time transport fidelity audit")
    parser.add_argument(
        "--date",
        default="2026-06-18",
        help="Audit date label (default: 2026-06-18)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_JSON,
        help="JSON report path",
    )
    parser.add_argument(
        "--market-session",
        default="offline_static",
        choices=("offline_static", "closed_market", "rth_live"),
        help="Session context for findings",
    )
    args = parser.parse_args(argv)
    day = datetime.date.fromisoformat(args.date)
    report = run_ui_transport_audit(
        audit_date=day,
        output_json=args.output,
        market_session=args.market_session,
    )
    md_path = args.output.with_suffix(".md")
    _render_markdown(report, md_path)
    print(f"Wrote {args.output}")
    print(f"Wrote {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
