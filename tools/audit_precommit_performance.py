#!/usr/bin/env python3
"""Audit pre-commit hook tiers and optional runtime — governance performance discipline."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT_JSON = REPO / "governance" / "artifacts" / "PRECOMMIT_PERFORMANCE_AUDIT.json"
OUT_MD = REPO / "governance" / "docs" / "PRECOMMIT_PERFORMANCE_AUDIT.md"

# Declared tier policy (authoritative for mechanical lock).
HOOK_TIER_POLICY: dict[str, dict] = {
    "governance-consolidation-tests": {
        "tier": 2,
        "scope": "repo-wide pytest consolidation suite",
        "keep_in_precommit": False,
        "proposed_location": "prepush",
        "recommendation": "Move to pre-push; full suite belongs in Tier 2, not every commit.",
    },
    "no-grep-subprocess": {
        "tier": 1,
        "scope": "staged Python only",
        "keep_in_precommit": True,
        "proposed_location": "precommit",
        "recommendation": "Keep — fast staged-file AST scan.",
    },
    "no-deferral-language-msg": {
        "tier": 1,
        "scope": "commit message",
        "keep_in_precommit": True,
        "proposed_location": "precommit",
        "recommendation": "Keep — commit-msg stage, negligible cost.",
    },
    "no-deferral-language-files": {
        "tier": 1,
        "scope": "staged text (allowlisted governance/tests excluded)",
        "keep_in_precommit": True,
        "proposed_location": "precommit",
        "recommendation": "Keep — staged-file regex scan.",
    },
    "fix-everything-we-touch-msg": {
        "tier": 1,
        "scope": "commit message",
        "keep_in_precommit": True,
        "proposed_location": "precommit",
        "recommendation": "Keep — commit-msg stage.",
    },
    "fix-everything-we-touch": {
        "tier": 1,
        "scope": "staged + conditional/cached repo-wide locks",
        "keep_in_precommit": True,
        "proposed_location": "precommit",
        "recommendation": "Fast path: staged checks + cache hit skips repo-wide; governance path expands.",
    },
    "fix-everything-we-touch-full-static": {
        "tier": 2,
        "scope": "full repo-wide static locks",
        "keep_in_precommit": False,
        "proposed_location": "prepush",
        "recommendation": "Pre-push runs all repo-wide locks; populates local cache for fast commits.",
    },
    "prepush-fast-gate": {
        "tier": 2,
        "scope": "clean working tree before expensive pre-push hooks",
        "keep_in_precommit": False,
        "proposed_location": "prepush",
        "recommendation": "Fail in under 5s when tree is dirty — must run before consolidation pytest.",
    },
    "generated-artifacts-clean-check": {
        "tier": 2,
        "scope": "check-only staleness for generated governance JSON",
        "keep_in_precommit": False,
        "proposed_location": "prepush",
        "recommendation": "Non-mutating compare vs sources — fail before long pytest when artifacts stale.",
    },
}

TIER_LABELS = {
    0: "Tier 0 — Upfront gate (enforce_all_rules --upfront-gate before staging production paths)",
    1: "Tier 1 — Pre-commit (staged + fast locks)",
    2: "Tier 2 — Pre-push / explicit local audit",
    3: "Tier 3 — CI objective-audit + reviewer audit",
    4: "Tier 4 — Full training/qualification — never pre-push",
}

# Phase 3K — measured pre-push bundle baseline (2026-06-11 profiling).
PHASE3K_BASELINE = {
    "pre_push_bundle_seconds_before": 1265.0,
    "pre_push_bundle_target_seconds": 600.0,
    "static_profile_seconds_before": 103.0,
    "dominant_subcheck_before": "check_ablation_seven_model_four_horizon_grid",
    "dominant_subcheck_seconds_before": 99.4,
    "test_file_share_before": {
        "tests/test_check_fix_everything_we_touch.py": 0.99,
        "tests/test_governance_consolidation.py": 3.0,
    },
    "top_slow_tests_before": [
        {"test": "test_objective_code_audit_situational_runtime_dispatch", "seconds": 240.7},
        {"test": "test_ablation_legacy_report_runnable_inference_and_target", "seconds": 180.8},
        {"test": "test_ablation_grid_requires_all_seven_models_and_four_horizons", "seconds": 126.8},
        {"test": "test_run_objective_code_audit_static_passes", "seconds": 124.4},
    ],
    "pre_push_bundle_seconds_after": 576.24,
    "test_check_fix_everything_seconds_after": 563.66,
    "static_profile_seconds_after": 94.0,
    "top_slow_tests_after": [
        {"test": "test_ablation_legacy_report_runnable_inference_and_target", "seconds": 161.9},
        {"test": "test_ablation_grid_requires_all_seven_models_and_four_horizons", "seconds": 110.5},
        {"test": "test_run_objective_code_audit_static_passes", "seconds": 57.2},
        {"test": "test_ablation_report_status_uses_runnable_denominator", "seconds": 55.2},
    ],
}


def _parse_precommit_hooks() -> list[dict]:
    cfg = REPO / ".pre-commit-config.yaml"
    if not cfg.is_file():
        return []
    text = cfg.read_text(encoding="utf-8", errors="replace")
    hooks: list[dict] = []
    current: dict | None = None
    for line in text.splitlines():
        m_id = re.match(r"\s*-\s*id:\s*(\S+)", line)
        if m_id:
            if current:
                hooks.append(current)
            current = {"id": m_id.group(1), "name": "", "entry": "", "stages": ["pre-commit"]}
            continue
        if current is None:
            continue
        m_name = re.match(r"\s*name:\s*(.+)", line)
        if m_name:
            current["name"] = m_name.group(1).strip()
            continue
        m_entry = re.match(r"\s*entry:\s*(.+)", line)
        if m_entry:
            current["entry"] = m_entry.group(1).strip()
            continue
        m_stages = re.match(r"\s*stages:\s*\[(.+)\]", line)
        if m_stages:
            current["stages"] = [s.strip() for s in m_stages.group(1).split(",")]
    if current:
        hooks.append(current)
    return hooks


def _measure_hook(entry: str, *, timeout_sec: int = 600) -> float | None:
    """Run hook entry command; return wall seconds or None on failure."""
    cmd = entry.split()
    if not cmd:
        return None
    start = time.perf_counter()
    try:
        proc = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, timeout=timeout_sec)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode not in (0, 1):
        return None
    return round(time.perf_counter() - start, 3)


def build_audit(*, measure: bool = False, measure_timeout_sec: int = 600) -> dict:
    hooks_raw = _parse_precommit_hooks()
    hook_rows: list[dict] = []
    total_measured = 0.0
    for h in hooks_raw:
        hid = h["id"]
        policy = HOOK_TIER_POLICY.get(hid, {})
        row = {
            "name": h.get("name") or hid,
            "id": hid,
            "command": h.get("entry", ""),
            "stages": h.get("stages") or ["pre-commit"],
            "runtime_seconds": None,
            "scope": policy.get("scope", "unspecified"),
            "tier": policy.get("tier", 1),
            "recommendation": policy.get(
                "recommendation", "Review — no tier policy entry in audit_precommit_performance.py"
            ),
            "keep_in_precommit": policy.get("keep_in_precommit", True),
            "proposed_location": policy.get("proposed_location", "precommit"),
        }
        if measure and row["command"]:
            rt = _measure_hook(row["command"], timeout_sec=measure_timeout_sec)
            row["runtime_seconds"] = rt
            if rt is not None:
                total_measured += rt
        hook_rows.append(row)

    slowest = None
    if measure:
        measured = [r for r in hook_rows if r.get("runtime_seconds") is not None]
        if measured:
            slowest = max(measured, key=lambda r: r["runtime_seconds"])

    return {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "measurement_mode": "live" if measure else "declared_policy_only",
        "total_measured_seconds": round(total_measured, 3) if measure else None,
        "slowest_hook": slowest,
        "tier_labels": TIER_LABELS,
        "phase3k_governance_pre_push_optimization": dict(PHASE3K_BASELINE),
        "hooks": hook_rows,
        "findings": _findings(hook_rows),
    }


def _findings(hook_rows: list[dict]) -> list[str]:
    findings: list[str] = []
    for row in hook_rows:
        hid = row["id"]
        stages = row.get("stages") or []
        if hid == "governance-consolidation-tests" and "pre-commit" in stages:
            findings.append(
                f"{hid}: runs on pre-commit — move to pre-push (Tier 2) to avoid 10–20min commit cycles"
            )
        if hid == "fix-everything-we-touch" and "pytest" in (row.get("command") or ""):
            findings.append(f"{hid}: must not invoke full pytest — use static locks only")
    if measure_rows := [r for r in hook_rows if r.get("runtime_seconds")]:
        slow = max(measure_rows, key=lambda r: r["runtime_seconds"])
        if slow["runtime_seconds"] and slow["runtime_seconds"] > 120:
            findings.append(
                f"{slow['id']}: measured {slow['runtime_seconds']}s — exceeds 120s pre-commit budget"
            )
    return findings


def write_markdown(audit: dict) -> str:
    lines = [
        "# Pre-commit performance audit",
        "",
        "**Scope:** Institutional governance — pre-commit tiering, profiling, and cache policy (Phase 3F-Perf1). Does not weaken objective-audit or repo-wide locks on pre-push/CI.",
        "",
        f"Generated: `{audit.get('generated_at_utc', '')}`",
        f"Mode: `{audit.get('measurement_mode', '')}`",
        "",
        "## Tier model",
        "",
    ]
    for tier, label in sorted(TIER_LABELS.items()):
        lines.append(f"- **{label}**")
    lines.append("")
    lines.append("## Hooks")
    lines.append("")
    lines.append("| Hook | Tier | Stages | Runtime (s) | Keep pre-commit | Location |")
    lines.append("|------|------|--------|---------------|-----------------|----------|")
    for row in audit.get("hooks") or []:
        rt = row.get("runtime_seconds")
        rt_s = f"{rt:.1f}" if isinstance(rt, (int, float)) else "—"
        stages = ", ".join(row.get("stages") or [])
        lines.append(
            f"| {row.get('id')} | {row.get('tier')} | {stages} | {rt_s} | "
            f"{row.get('keep_in_precommit')} | {row.get('proposed_location')} |"
        )
    findings = audit.get("findings") or []
    if findings:
        lines.append("")
        lines.append("## Findings")
        lines.append("")
        for f in findings:
            lines.append(f"- {f}")
    lines.append("")
    phase3k = audit.get("phase3k_governance_pre_push_optimization") or {}
    if phase3k:
        lines.append("## Phase 3K — governance pre-push optimization")
        lines.append("")
        lines.append(f"- Pre-push bundle before: **{phase3k.get('pre_push_bundle_seconds_before')}s**")
        after = phase3k.get("pre_push_bundle_seconds_after")
        if after is not None:
            lines.append(f"- Pre-push bundle after: **{after}s** (~{100 * (1 - after / phase3k.get('pre_push_bundle_seconds_before', after)):.0f}% vs before)")
        tcf_after = phase3k.get("test_check_fix_everything_seconds_after")
        if tcf_after is not None:
            lines.append(f"- `test_check_fix_everything_we_touch.py` after: **{tcf_after}s**")
        static_after = phase3k.get("static_profile_seconds_after")
        if static_after is not None:
            lines.append(f"- Static profile after: **{static_after}s** (grid check still ~90s once per process)")
        lines.append(f"- Target: **<{phase3k.get('pre_push_bundle_target_seconds', 600)}s**")
        lines.append(
            f"- Static profile before: **{phase3k.get('static_profile_seconds_before')}s** "
            f"(dominant: `{phase3k.get('dominant_subcheck_before')}` "
            f"~{phase3k.get('dominant_subcheck_seconds_before')}s once)"
        )
        lines.append("")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write", action="store_true", help="write JSON + MD artifacts")
    ap.add_argument("--measure", action="store_true", help="time each hook command (slow)")
    ap.add_argument("--measure-timeout", type=int, default=600)
    args = ap.parse_args(argv)
    audit = build_audit(measure=bool(args.measure), measure_timeout_sec=args.measure_timeout)
    if args.write:
        OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
        OUT_MD.parent.mkdir(parents=True, exist_ok=True)
        OUT_JSON.write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
        OUT_MD.write_text(write_markdown(audit), encoding="utf-8")
        print(f"wrote {OUT_JSON.relative_to(REPO)}")
        print(f"wrote {OUT_MD.relative_to(REPO)}")
    else:
        print(json.dumps(audit, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
