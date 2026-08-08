#!/usr/bin/env python3
"""Multi-faucet census (mission multi-faucet-census-v1, rehab spine RH-F1).

Repo-wide AUDIT of every named operator field with >=2 producers or clocks. Emits
reports/multi_faucet_census_latest.md + .json. CENSUS ONLY — this tool changes nothing;
kill missions follow one concept at a time (one authority; old path removed/hard-fail).

Each finding carries: concept, producers (with current line evidence re-scanned at run
time), severity P0/P1/P2, measured evidence + reproduce command, proposed kill.

Severity rubric (operator-facing):
  P0 - two different NUMBERS for one concept operator-visible at once (none open post
       levels-faucet-v1 Phase 1; the PDL split was the last measured P0)
  P1 - two producers/windows live in code on operator-reachable paths; divergence is
       structural (different window/basis/clock) even when today's tape hides it
  P2 - guarded residue: declared fallbacks, parity-locked grandfathers, display-layer
       splits, or single-producer concepts whose lock deserves a census pointer
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MD_OUT = REPO / "reports" / "multi_faucet_census_latest.md"
JSON_OUT = REPO / "reports" / "multi_faucet_census_latest.json"


def _sites(rel: str, pattern: str, limit: int = 6) -> list[str]:
    """Current line evidence for a producer site — re-scanned every run so the census
    can never cite a line that no longer exists (stale-evidence law)."""
    p = REPO / rel
    try:
        src = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return [f"{rel}: FILE MISSING"]
    out = []
    for n, line in enumerate(src.splitlines(), 1):
        if re.search(pattern, line):
            out.append(f"{rel}:{n}: {line.strip()[:110]}")
            if len(out) >= limit:
                break
    return out or [f"{rel}: pattern gone ({pattern[:40]}) — producer may be dead, re-verify"]


def build_findings() -> list[dict]:
    return [
        {
            "concept": "prior_day (PDH/PDL/PDC/PD_POC/PD_VAH/PD_VAL)",
            "status": "PHASE1_DONE + PHASE2A_DONE",
            "severity": "P2",
            "producers": {
                "liquidity_value_engine.get_previous_day_levels (AUTHORITY, RC-153/RC-213)":
                    _sites("liquidity_value_engine.py", r"def get_previous_day_levels"),
                "liquidity_value_engine.build_price_level_snapshot (SOLE INVOKER, Phase 2A)":
                    _sites("liquidity_value_engine.py", r"def build_price_level_snapshot"),
                "market_context.fetch_price_levels (CARRIES the snapshot; no compute, no fetch)":
                    _sites("market_context.py", r"carry_snapshot_levels"),
                "static/chart.html (CARRIES /api/levels rows; computeDaily prior-day derivation DELETED)":
                    _sites("static/chart.html", r"/api/levels\?ticker="),
            },
            "evidence": "PHASE2A: the client-side prior_day derivation in computeDaily is DELETED, not "
                        "fallback-patched, and market_context's private prior-session resolution is gone — "
                        "both now carry the materialized PriceLevelSnapshot keyed by "
                        "(ticker, level_id, semantic_scope, generation).",
            "reproduce": "curl /api/levels?ticker=SPY + /api/liquidity-snapshot?ticker=SPY&snapshot=live; "
                         "python -m pytest tests/test_phase2a_price_level_snapshot_v1.py -q",
            "proposed_kill": "PHASE2A_DONE — one computation in build_price_level_snapshot, one materialization "
                             "per generation, carried everywhere; absent stays absent (RC-68).",
        },
        {
            "concept": "vwap (+bands)",
            "severity": "P2",
            "status": "TIERB_DONE + PHASE2A_DONE",
            "producers": {
                "liquidity_value_engine.compute_session_vwap_series (AUTHORITY: one accumulation)":
                    _sites("liquidity_value_engine.py",
                           r"def compute_session_vwap_series|def compute_vwap_bands"),
                "liquidity_value_engine.build_price_level_snapshot (SOLE INVOKER; scalar = last point)":
                    _sites("liquidity_value_engine.py", r"vwap_series"),
                "market_context.fetch_price_levels (CARRIES the snapshot's VWAP)":
                    _sites("market_context.py", r"carry_snapshot_levels"),
                "static/chart.html + static/exposure.html (CARRY vwap_series; in-page accumulation DELETED)":
                    _sites("static/exposure.html", r"adoptVwapSeries|vwap_series"),
                "backfill_snapshot_derived eff_vwap (real/forward-fill only; typical-price SUBSTITUTION deleted)":
                    _sites("backfill_snapshot_derived.py", r"eff_vwap"),
            },
            "evidence": "PHASE2A: ONE accumulation (compute_session_vwap_series) feeds the scalar VWAP, the "
                        "±1σ/±2σ levels and the drawn curve, so the line ends on the served number. Both "
                        "browser reconstructions (chart computeDaily, exposure computeVwapSeries) are DELETED.",
            "reproduce": "curl /api/levels?ticker=SPY | jq '.levels[]|select(.family==\"vwap\")'; "
                         "python -m pytest tests/test_phase2a_price_level_snapshot_v1.py -q",
            "proposed_kill": "PHASE2A_DONE — residue is consumer migration off /api/price-levels (B6), not a second compute.",
        },
        {
            "concept": "opening_range (ORB H/L/mid)",
            "severity": "P2",
            "status": "TIERB_DONE + PHASE2A_DONE",
            "producers": {
                "liquidity_value_engine.compute_opening_range (AUTHORITY)":
                    _sites("liquidity_value_engine.py", r"def compute_opening_range"),
                "liquidity_value_engine.build_price_level_snapshot (SOLE INVOKER)":
                    _sites("liquidity_value_engine.py", r"ORB_HIGH"),
                "market_context.fetch_price_levels (CARRIES the snapshot's ORB)":
                    _sites("market_context.py", r"carry_snapshot_levels"),
            },
            "evidence": "PHASE2A: the inline ORB loop was already dead; now the second INVOCATION is too — "
                        "one materialization per generation, carried to every serve path.",
            "reproduce": "curl /api/levels?ticker=SPY | jq '.levels[]|select(.family==\"opening_range\")'",
            "proposed_kill": "PHASE2A_DONE — B6 retires /api/price-levels as a second HTTP surface, not a second formula.",
        },
        {
            "concept": "overnight (high/low)",
            "severity": "P2",
            "status": "TIERB_DONE + PHASE2A_DONE",
            "producers": {
                "liquidity_value_engine.get_overnight_levels (AUTHORITY, RC-153 window)":
                    _sites("liquidity_value_engine.py", r"def get_overnight_levels"),
                "liquidity_value_engine.build_price_level_snapshot (SOLE INVOKER)":
                    _sites("liquidity_value_engine.py", r"OVERNIGHT_HIGH"),
                "market_context.fetch_price_levels (CARRIES the snapshot's overnight)":
                    _sites("market_context.py", r"carry_snapshot_levels"),
            },
            "evidence": "PHASE2A, and this family is the measured defect: /api/levels served 773.3975/773.3975 "
                        "while /api/liquidity-snapshot served 773.40/772.55 for one ticker at one instant. Same "
                        "formula, DIFFERENT bar input — killed by one materialization plus a carrier contract "
                        "that raises when two carriers disagree.",
            "reproduce": "curl /api/levels?ticker=SPY + /api/liquidity-snapshot?ticker=SPY&snapshot=live, repeatedly",
            "proposed_kill": "PHASE2A_DONE.",
        },
        {
            "concept": "today value_area (POC/VAH/VAL) + today profile",
            "severity": "P2",
            "status": "TIERB_DONE + PHASE2A_DONE",
            "producers": {
                "liquidity_value_engine.compute_volume_profile_levels (AUTHORITY for today)":
                    _sites("liquidity_value_engine.py", r"def compute_volume_profile_levels"),
                "liquidity_value_engine.build_price_level_snapshot (SOLE INVOKER, today + prior VA)":
                    _sites("liquidity_value_engine.py", r"TODAY_POC"),
                "market_context.fetch_price_levels (CARRIES today AND prior value areas)":
                    _sites("market_context.py", r"carry_snapshot_levels"),
            },
            "evidence": "PHASE2A: today VA and the prior_day pd_* value area now come out of the same "
                        "materialization, which is what stopped PD_POC/PD_VAH/PD_VAL from disagreeing "
                        "intermittently between the two endpoints.",
            "reproduce": "read fetch_price_levels; curl /api/levels?ticker=SPY | jq '.levels[]|select(.family==\"value_area\")'",
            "proposed_kill": "TIERB_DONE for today VA; prior_day profile entry-point collapse is a later residue.",
        },
        {
            "concept": "charm / greeks formulas",
            "severity": "P1",
            "producers": {
                "math_levels bs_* faucet (AUTHORITY per registry greek_formula_faucet)":
                    _sites("math_levels.py", r"def bs_charm|def bs_gamma|def bs_vanna", 4),
                "math_exposure_core.compute_net_charm (DELEGATES to bs_charm; RC-224)":
                    _sites("math_exposure_core.py", r"bs_charm|def compute_net_charm", 2),
            },
            "evidence": "CHARM_DONE (RC-224 / charm-bs-faucet-migrate-v1): compute_net_charm calls "
                        "math_levels.bs_charm(rate=0); grandfathered_inline_greeks cleared; RC-179 "
                        "parity locks remain green.",
            "reproduce": "python -m pytest tests/test_charm_sign_finite_difference.py -q; "
                         "python -c \"import json; assert not json.load(open("
                         "'governance/level_faucets.json'))['grandfathered_inline_greeks']\"",
            "proposed_kill": "CHARM_DONE — migrate + delete inline + clear grandfather (RC-224).",
        },
        {
            "concept": "clocks (session date / display time)",
            "severity": "P1",
            "producers": {
                "time_et (ET market-logic authority) / America-Chicago display law":
                    _sites("time_et.py", r"def now_et|^ET = ", 2),
                "static/chart.html SESSION_TZ+DISPLAY_TZ (RC-223 killed ambient regroup)":
                    _sites("static/chart.html", r"SESSION_TZ|etDateKey|DISPLAY_TZ"),
                "tools/clocks_tz_lock.py bare toLocaleDateString ban":
                    _sites("tools/clocks_tz_lock.py", r"bare_locale_date_violations|SESSION_TZ"),
            },
            "evidence": "CLOCKS_DONE (RC-223 / clocks-tz-explicit-v1): session keys America/New_York, "
                        "display labels America/Chicago, bare toLocaleDateString banned by "
                        "tools/clocks_tz_lock.py + T1. Residue: untracked exposure.html axis times; "
                        "computeDaily prior_day B3 is a later mission.",
            "reproduce": "python -m pytest tests/test_clocks_tz_explicit_v1.py -q; "
                         "python -c \"from tools.clocks_tz_lock import scan_tracked_static; "
                         "assert scan_tracked_static()==[]\"",
            "proposed_kill": "CLOCKS_DONE — explicit timeZone binding + static ban (RC-223).",
        },
        {
            "concept": "spot",
            "severity": "P2",
            "status": "SPOT_DONE",
            "producers": {
                "server.resolve_spot (THE authority, RC-14; every payload carries spot_source)":
                    _sites("server.py", r"def resolve_spot", 1),
                "client /api/spot binding + as_of (RC-225; cycle fallback DELETED)":
                    _sites("static/chart.html", r"function currentSpot|spotBindingAgeLabel", 3),
                "tools/spot_binding_lock.py dual-age ban":
                    _sites("tools/spot_binding_lock.py", r"scan_tracked_static|chart_binding_violations"),
            },
            "evidence": "SPOT_DONE (RC-225 / spot-binding-single-payload-v1): chart+exposure bind ONLY "
                        "/api/spot with spot_as_of age visible (STALE >30s); consoleSpot drops "
                        "last_price/quote_mid fallback; _cycleSpot DELETED; T1 + spot_binding_lock. "
                        "Residue: desk.html dist.spot sample surface (OUT-OF-SCOPE this slice).",
            "reproduce": "python -m pytest tests/test_spot_binding_single_payload_v1.py -q; "
                         "python -c \"from tools.spot_binding_lock import scan_tracked_static; "
                         "assert scan_tracked_static()==[]\"",
            "proposed_kill": "SPOT_DONE — single per-screen binding + visible as_of (RC-225).",
        },
        {
            "concept": "walls / gamma flip",
            "severity": "P2",
            "producers": {
                "terrain_engine (single producer since RC-80)":
                    _sites("terrain_engine.py", r"call_wall=call_wall", 2),
                "math_levels gamma_flip_from_profile AND compute_gamma_flip_v2 (two flip formula generations)":
                    _sites("math_levels.py", r"def gamma_flip_from_profile|def compute_gamma_flip_v2"),
            },
            "evidence": "Wall/flip VALUES have one producer (RC-80 kill held). MEASURED this census: the two "
                        "flip functions are LAYERED, not parallel — compute_gamma_flip_v2 calls "
                        "gamma_flip_from_profile internally (math_levels.py:1054); production (server.py, "
                        "terrain_engine.py) enters ONLY via v2; research tools (flip_iv_sensitivity_v1, "
                        "study_flip_span_convergence_v1) enter at the primitive. One formula stack, two entry "
                        "depths — not a dual faucet.",
            "reproduce": "referrer trace of both names across *.py + tools/ (6 lines each; v1's non-tool referrer is v2 itself)",
            "proposed_kill": "none needed — layered single stack. Census pointer: research entries at the "
                             "primitive bypass v2's confidence gate BY DESIGN (they study the raw crossing).",
        },
        {
            "concept": "per-strike volume / strikes",
            "severity": "P2",
            "producers": {
                "/api/terrain/strikes (per-strike GEX$/volume payload)":
                    _sites("server.py", r'@app.get\("/api/terrain/strikes"\)', 1),
                "chart FORCES strip client-side rows (GEX/OV derived in-browser from the same payload)":
                    _sites("server.py", r"strip's GEX/OV rows come from the live strikes payload client-side", 1),
            },
            "evidence": "One data source, two aggregation sites (server payload vs in-browser derivation for the "
                        "strip). Binding-level duality: a payload change breaks the strip silently.",
            "reproduce": "read chart.html strip builder vs /api/terrain/strikes payload contract",
            "proposed_kill": "Strip consumes server-aggregated rows (or /api/levels gamma family) — no in-browser "
                             "re-derivation of served numbers.",
        },
        {
            "concept": "display precision (prior-day family)",
            "severity": "P2",
            "producers": {
                "state payload rounds (pdh 748.89)":
                    _sites("server.py", r'ms_dict\["pdh"\]', 1),
                "/api/levels + /api/price-levels serve raw (748.895)":
                    _sites("server.py", r'family": "prior_day"|_append_level', 1),
            },
            "evidence": "MEASURED same instant: state pdh=748.89 vs levels PDH=748.895 — same number, two "
                        "precisions on two surfaces. Not a producer split; a payload-rounding faucet.",
            "reproduce": "curl /api/analytics/state | jq .pdh; curl /api/levels | jq '.levels[] | select(.id==\"PDH\").price'",
            "proposed_kill": "Payloads carry RAW; rounding happens at render only (one display rule).",
        },
        {
            "concept": "expected_move (EM bands)",
            "severity": "P2",
            "producers": {
                "terrain sigma band (kl_em_upper/lower, E-34 locked to payload spot)":
                    _sites("server.py", r"kl_em_upper", 2),
            },
            "evidence": "Single producer, lock-tested (test_levels_single_producer_v1 E-34 assertions). Census "
                        "pointer only — no second producer found this run.",
            "reproduce": "pytest tests/test_levels_single_producer_v1.py -k em",
            "proposed_kill": "none needed — keep the lock.",
        },
    ]


def emit(findings: list[dict]) -> None:
    JSON_OUT.write_text(json.dumps({
        "mission": "multi-faucet-census-v1",
        "schema_version": 1,
        "findings": findings,
    }, indent=1) + "\n", encoding="utf-8")
    lines = [
        "# Multi-faucet census — latest (mission multi-faucet-census-v1, RH-F1)",
        "",
        "Census only: every named operator field with >=2 producers or clocks, ranked, with",
        "current-line evidence (re-scanned at generation) and the proposed kill. Kill missions",
        "run one concept end-to-end — one authority, old path REMOVED or hard-failing, never a",
        "fallback patch.",
        "",
        "| # | concept | severity | producers | proposed kill |",
        "|---|---------|----------|-----------|---------------|",
    ]
    for i, f in enumerate(findings, 1):
        lines.append(f"| {i} | {f['concept']} | {f['severity']} | {len(f['producers'])} | "
                     f"{f['proposed_kill'][:110]} |")
    lines.append("")
    for i, f in enumerate(findings, 1):
        lines.append(f"## {i}. {f['concept']} — {f['severity']}"
                     + (f" ({f['status']})" if f.get("status") else ""))
        lines.append("")
        for name, sites in f["producers"].items():
            lines.append(f"- **{name}**")
            for s in sites:
                lines.append(f"  - `{s}`")
        lines.append("")
        lines.append(f"**Evidence:** {f['evidence']}")
        lines.append(f"**Reproduce:** `{f['reproduce']}`")
        lines.append(f"**Proposed kill:** {f['proposed_kill']}")
        lines.append("")
    MD_OUT.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    findings = build_findings()
    emit(findings)
    multi = [f for f in findings if len(f["producers"]) >= 2]
    print(f"census: {len(findings)} concepts, {len(multi)} with >=2 producers/clocks; "
          f"wrote {MD_OUT.name} + {JSON_OUT.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
