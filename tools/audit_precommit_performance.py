#!/usr/bin/env python3
"""Audit pre-commit hook tiers and optional runtime — governance performance discipline."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
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
        "scope": "staged paths + repo-wide static locks (no full pytest)",
        "keep_in_precommit": True,
        "proposed_location": "precommit",
        "recommendation": "Keep — institutional locks; pytest suites must not duplicate here.",
    },
}

TIER_LABELS = {
    0: "Tier 0 — Upfront gate (enforce_all_rules --upfront-gate before staging production paths)",
    1: "Tier 1 — Pre-commit (staged + fast locks)",
    2: "Tier 2 — Pre-push / explicit local audit",
    3: "Tier 3 — CI objective-audit + reviewer audit",
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
