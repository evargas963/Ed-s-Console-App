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
            "status": "PHASE1_DONE + P2 residue",
            "severity": "P2",
            "producers": {
                "liquidity_value_engine.get_previous_day_levels (AUTHORITY, RC-153/RC-213)":
                    _sites("liquidity_value_engine.py", r"def get_previous_day_levels"),
                "market_context.fetch_price_levels (DELEGATES to authority since 91d38623)":
                    _sites("market_context.py", r"prior_trading_session_date"),
                "static/chart.html computeDaily (JS FALLBACK faucet — browser-local clock, buffer-group window)":
                    _sites("static/chart.html", r"function computeDaily|toLocaleDateString\(\)"),
            },
            "evidence": "LIVE 2026-08-03 18:0x CT PID 39720: /api/price-levels PDL 737.68 == /api/levels PDL 737.68 "
                        "(was 737.68 vs 734.59 at 09:41). Residue: computeDaily derives pdh/pdl/pdc client-side "
                        "when engine values absent — browser timezone, no RTH filter, days[length-2] window.",
            "reproduce": "curl /api/price-levels?ticker=SPY + /api/levels?ticker=SPY; read chart.html computeDaily",
            "proposed_kill": "B3 (design §7): chart.html consumes /api/levels prior_day ids; computeDaily DELETED "
                             "(not fallback-patched) — absent engine values render as absent (RC-68).",
        },
        {
            "concept": "vwap (+bands)",
            "severity": "P1",
            "producers": {
                "liquidity_value_engine.compute_session_vwap (session bars, cutoff-aware)":
                    _sites("liquidity_value_engine.py", r"def compute_session_vwap|def compute_vwap_bands"),
                "market_context.fetch_price_levels inline cum_tpv loop (vendor TWO_DAYS window)":
                    _sites("market_context.py", r"cum_tpv"),
                "backfill_snapshot_derived eff_vwap fallback chain (typical-price SUBSTITUTION)":
                    _sites("backfill_snapshot_derived.py", r"eff_vwap"),
            },
            "evidence": "MEASURED 2026-08-03 18:1x CT same instant: /api/analytics/state vwap=None while "
                        "/api/liquidity-snapshot raw_levels.vwap=755.8154 — one concept, one tab absent, one tab "
                        "valued. Structural: three computes, three windows/bases (session+cutoff vs vendor-2day "
                        "vs typical-price substitute).",
            "reproduce": "curl /api/analytics/state?ticker=SPY | jq .vwap; curl '/api/liquidity-snapshot?ticker=SPY&snapshot=live' | jq .raw_levels.vwap",
            "proposed_kill": "NEXT KILL SLICE (highest leverage): vwap family collapses onto "
                             "compute_session_vwap served via /api/levels Tier-B cache (design §5.4); "
                             "market_context inline compute DELETED; backfill typical-price substitution "
                             "HARD-FAILS to absent (a fabricated vwap is worse than no vwap).",
        },
        {
            "concept": "opening_range (ORB H/L/mid)",
            "severity": "P1",
            "producers": {
                "liquidity_value_engine ORB family (raw_levels.orb)":
                    _sites("liquidity_value_engine.py", r"orb", 3),
                "market_context.fetch_price_levels inline ORB loop":
                    _sites("market_context.py", r"orb_h = max|pl\.orb_high"),
            },
            "evidence": "MEASURED same instant: state orb_high=None while liquidity raw_levels.orb="
                        "{751.94/748.8/750.37} — same absence-vs-value split as vwap, same producers.",
            "reproduce": "curl /api/analytics/state?ticker=SPY | jq .orb_high; curl '/api/liquidity-snapshot?ticker=SPY&snapshot=live' | jq .raw_levels.orb",
            "proposed_kill": "Same slice as vwap: ORB collapses onto the engine via /api/levels; "
                             "market_context inline loop deleted with fetch_price_levels retirement (B6).",
        },
        {
            "concept": "overnight (high/low)",
            "severity": "P1",
            "producers": {
                "liquidity_value_engine.get_overnight_levels (RC-153-corrected interval window)":
                    _sites("liquidity_value_engine.py", r"def get_overnight_levels"),
                "market_context.fetch_price_levels overnight_bars (today-premarket only window)":
                    _sites("market_context.py", r"overnight_bars"),
            },
            "evidence": "Two windows for one name: engine = prior close -> today open interval (holiday-safe, "
                        "RC-153); market_context = today's premarket bars only (extended_hours flag). "
                        "Different answers whenever the overnight range formed before midnight.",
            "reproduce": "read both functions; compare on a Monday tape",
            "proposed_kill": "Same slice: overnight collapses onto get_overnight_levels via /api/levels.",
        },
        {
            "concept": "today value_area (POC/VAH/VAL) + today profile",
            "severity": "P1",
            "producers": {
                "liquidity_value_engine profile (raw_levels.poc/vah/val)":
                    _sites("liquidity_value_engine.py", r"_volume_profile_poc_vah_val", 3),
                "market_context._volume_profile_poc_vah_val (separate copy)":
                    _sites("market_context.py", r"_volume_profile_poc_vah_val", 3),
            },
            "evidence": "Two same-named profile implementations, one per module — value-area math forked at "
                        "module boundary; divergence follows bar-source/window differences exactly as prior_day did.",
            "reproduce": "read both _volume_profile_poc_vah_val implementations; diff parameters (value-area %, tick size)",
            "proposed_kill": "Same slice: ONE profile implementation (engine's, config-carrying) serves both; "
                             "market_context copy deleted.",
        },
        {
            "concept": "charm / greeks formulas",
            "severity": "P1",
            "producers": {
                "math_levels bs_* faucet (AUTHORITY per registry greek_formula_faucet)":
                    _sites("math_levels.py", r"def bs_charm|def bs_gamma|def bs_vanna", 4),
                "math_exposure_core.compute_net_charm inline formula (GRANDFATHERED, RC-179 parity-locked)":
                    _sites("math_exposure_core.py", r"def compute_net_charm", 2),
            },
            "evidence": "Registry names the grandfather explicitly; RC-179 parity locks pin sign/magnitude. "
                        "Structural residue: one concept, two formula sites — the vanna defect (RC-211) was "
                        "exactly this class before its kill.",
            "reproduce": "python tools/check_institutional_correctness.py (charm parity checks); read registry grandfathered_inline_greeks",
            "proposed_kill": "Migrate compute_net_charm onto bs_charm; delete the inline formula; registry "
                             "grandfather entry removed (its own stated destiny: 'migrate to the bs_* faucet').",
        },
        {
            "concept": "clocks (session date / display time)",
            "severity": "P1",
            "producers": {
                "time_et (ET market-logic authority) / America-Chicago display law":
                    _sites("time_et.py", r"def now_et|^ET = ", 2),
                "static/chart.html bare toLocaleDateString (BROWSER-LOCAL clock in bar grouping + axis)":
                    _sites("static/chart.html", r"toLocaleDateString"),
                "static/index.html toLocaleDateString('en-CA') date stamp (browser-local)":
                    _sites("static/index.html", r"toLocaleDateString\('en-CA'\)"),
            },
            "evidence": "chart.html groups daily bars by the BROWSER's timezone (computeDaily dkey + axis labels) "
                        "while every server window is ET and the display law is CT — a traveling operator's "
                        "chart would regroup sessions. index.html carries one browser-local date stamp beside "
                        "CT-explicit stamps.",
            "reproduce": "read chart.html L377/L396/L1362 + index.html L11710; compare with UI clock law (CT)",
            "proposed_kill": "All JS date grouping/labels take an explicit timeZone (America/Chicago display, "
                             "ET session logic served by the API, e.g. /api/levels provenance.window); bare "
                             "toLocaleDateString banned by a static check.",
        },
        {
            "concept": "spot",
            "severity": "P2",
            "producers": {
                "server.resolve_spot (THE authority, RC-14; every payload carries spot_source)":
                    _sites("server.py", r"def resolve_spot", 1),
                "client bindings (chart/exposure/index render spot from different payloads' spot fields)":
                    _sites("static/chart.html", r"\bspot\b", 3),
            },
            "evidence": "Compute side is single-faucet (RC-14). Residue is BINDING-level: each tab renders the "
                        "spot of whichever payload it last fetched, so tabs can show different ages of the one "
                        "authority. FORCES strip spot honesty is the PM-named instance.",
            "reproduce": "compare spot + spot_source + as_of across /api/terrain, /api/analytics/state, /api/levels",
            "proposed_kill": "Consumers render spot ONLY from a single shared payload field per screen with its "
                             "as_of age visible; stale spot renders as stale, not as current.",
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
                    _sites("server.py", r'"id": lid, "price": float\(val\)', 1),
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
