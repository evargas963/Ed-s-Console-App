#!/usr/bin/env python3
"""Build check-stack inventory + duplication/tier analysis (Phase 3I)."""
from __future__ import annotations

import argparse
import ast
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
OUT_JSON = REPO / "governance" / "artifacts" / "CHECK_STACK_INVENTORY.json"
OUT_MD = REPO / "governance" / "docs" / "CHECK_STACK_RIGHTSIZING.md"
PROFILE_JSON = REPO / "governance" / "artifacts" / "FIX_EVERYTHING_WE_TOUCH_PROFILE.json"
PRECOMMIT_AUDIT = REPO / "governance" / "artifacts" / "PRECOMMIT_PERFORMANCE_AUDIT.json"

SCHEMA_VERSION = 1

RUNTIME_BUDGETS_SEC = {
    "precommit_normal": 60,
    "precommit_governance": 180,
    "prepush_normal": 600,
    "prepush_governance": 1200,
    "ci_objective_audit": None,
    "reviewer_audit": None,
}

MEASURED_PREPUSH_SEC = 1440  # 24 min from PERF2-1 push observation


def _parse_precommit_hooks() -> list[dict[str, Any]]:
    cfg = REPO / ".pre-commit-config.yaml"
    if not cfg.is_file():
        return []
    text = cfg.read_text(encoding="utf-8", errors="replace")
    hooks: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line in text.splitlines():
        m_id = re.match(r"\s*-\s*id:\s*(\S+)", line)
        if m_id:
            if current:
                hooks.append(current)
            current = {"check_id": m_id.group(1), "command": "", "stages": ["pre-commit"]}
            continue
        if current is None:
            continue
        m_entry = re.match(r"\s*entry:\s*(.+)", line)
        if m_entry:
            current["command"] = m_entry.group(1).strip()
            continue
        m_stages = re.match(r"\s*stages:\s*\[(.+)\]", line)
        if m_stages:
            current["stages"] = [s.strip() for s in m_stages.group(1).split(",")]
    if current:
        hooks.append(current)
    return hooks


def _repo_wide_locks() -> list[str]:
    path = REPO / "tools" / "check_fix_everything_we_touch.py"
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"_REPO_WIDE_STATIC_CHECK_FUNCS:\s*tuple\[str,\s*\.\.\.\]\s*=\s*\((.*?)\)", text, re.S)
    if not m:
        return []
    return re.findall(r'"([^"]+)"', m.group(1))


def _enforce_all_rules_modes() -> list[dict[str, str]]:
    path = REPO / "tools" / "enforce_all_rules.py"
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8", errors="replace")
    modes: list[dict[str, str]] = []
    for flag in (
        "--upfront-gate",
        "--objective-audit",
        "--enforce-all",
        "--enforce-static",
        "--code-quality",
        "--ablation-bias",
        "--stop-hook",
    ):
        if flag in text:
            modes.append({"check_id": f"enforce_all_rules{flag}", "command": f"python tools/enforce_all_rules.py {flag}"})
    return modes


def _reviewer_steps() -> list[dict[str, str]]:
    path = REPO / "tools" / "run_reviewer_audit.py"
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8", errors="replace")
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "REVIEWER_STEPS":
                    if isinstance(node.value, ast.Tuple):
                        steps: list[dict[str, str]] = []
                        for elt in node.value.elts:
                            if isinstance(elt, ast.Tuple) and len(elt.elts) >= 2:
                                name = elt.elts[0]
                                cmd = elt.elts[1]
                                if isinstance(name, ast.Constant) and isinstance(cmd, ast.List):
                                    cmd_parts = [
                                        e.value for e in cmd.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)
                                    ]
                                    steps.append(
                                        {
                                            "check_id": f"reviewer_{name.value}",
                                            "command": " ".join(cmd_parts),
                                        }
                                    )
                        return steps
    return []


def _profile_seconds() -> dict[str, float]:
    if not PROFILE_JSON.is_file():
        return {}
    try:
        data = json.loads(PROFILE_JSON.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    out: dict[str, float] = {}
    for row in data.get("subchecks") or []:
        name = str(row.get("name") or "")
        sec = row.get("seconds")
        if name and isinstance(sec, (int, float)):
            out[name] = float(sec)
    return out


def _tier_for_hook(stages: list[str]) -> int:
    if "pre-push" in stages:
        return 2
    if "commit-msg" in stages:
        return 1
    return 1


def _overlap_kind(a: dict, b: dict) -> str | None:
    if a.get("check_id") == b.get("check_id"):
        return "unintentional_duplicate"
    ca = str(a.get("command") or "")
    cb = str(b.get("command") or "")
    if ca and ca == cb:
        return "unintentional_duplicate"
    ra = str(a.get("risk_addressed") or "")
    rb = str(b.get("risk_addressed") or "")
    if ra and ra == rb and a.get("tier") == b.get("tier"):
        return "candidate_for_merge"
    return None


def build_inventory() -> dict[str, Any]:
    profile = _profile_seconds()
    checks: list[dict[str, Any]] = []

    hook_ids = {str(h["check_id"]) for h in _parse_precommit_hooks()}
    for hook in _parse_precommit_hooks():
        cid = str(hook["check_id"])
        stages = hook.get("stages") or ["pre-commit"]
        tier = _tier_for_hook(stages)
        sec = None
        if cid == "fix-everything-we-touch-full-static":
            sec = profile.get("repo_wide_static_aggregate")
        checks.append(
            {
                "check_id": cid,
                "command": hook.get("command"),
                "tier": tier,
                "runtime_seconds": sec,
                "scope": "pre-commit hook",
                "files_or_modules_covered": "staged or repo per hook",
                "risk_addressed": "governance enforcement",
                "evidence_artifact": "governance/artifacts/PRECOMMIT_PERFORMANCE_AUDIT.json",
                "must_run_precommit": tier == 1 and "pre-commit" in stages,
                "must_run_prepush": "pre-push" in stages,
                "must_run_ci": False,
                "can_be_cached": cid == "fix-everything-we-touch",
                "can_be_incremental": cid == "fix-everything-we-touch",
                "can_be_parallelized": False,
                "can_be_removed": False,
                "removal_risk": "high",
                "recommendation": "keep_in_precommit" if tier == 1 else "move_to_prepush",
                "overlap_with_other_checks": [],
            }
        )

    if "fix-everything-we-touch-full-static" not in hook_ids:
        checks.append(
            {
                "check_id": "fix-everything-we-touch-full-static",
                "command": "python tools/check_fix_everything_we_touch.py --full-static",
                "tier": 3,
                "runtime_seconds": profile.get("repo_wide_static_aggregate"),
                "scope": "repo-wide static locks (CI objective-audit)",
                "files_or_modules_covered": "full repo",
                "risk_addressed": "governance enforcement",
                "evidence_artifact": ".github/workflows/objective-audit.yml",
                "must_run_precommit": False,
                "must_run_prepush": False,
                "must_run_ci": True,
                "can_be_cached": False,
                "can_be_incremental": False,
                "can_be_parallelized": False,
                "can_be_removed": False,
                "removal_risk": "critical",
                "recommendation": "keep_ci_only",
                "overlap_with_other_checks": ["enforce_all_rules_objective_audit"],
            }
        )

    for lock in _repo_wide_locks():
        checks.append(
            {
                "check_id": lock,
                "command": f"check_fix_everything_we_touch.py::{lock}",
                "tier": 2,
                "runtime_seconds": profile.get(lock),
                "scope": "repo-wide static",
                "files_or_modules_covered": "full repo",
                "risk_addressed": lock.replace("check_", "").replace("_", " "),
                "evidence_artifact": "governance/artifacts/FIX_EVERYTHING_WE_TOUCH_PROFILE.json",
                "must_run_precommit": False,
                "must_run_prepush": False,
                "must_run_ci": True,
                "can_be_cached": lock
                in {
                    "check_ablation_seven_model_four_horizon_grid",
                    "check_ablation_equal_layer_consumers",
                },
                "can_be_incremental": False,
                "can_be_parallelized": False,
                "can_be_removed": False,
                "removal_risk": "high",
                "recommendation": "keep_ci_only",
                "overlap_with_other_checks": [],
            }
        )

    checks.append(
        {
            "check_id": "enforce_all_rules_objective_audit",
            "command": "python tools/enforce_all_rules.py --objective-audit",
            "tier": 3,
            "runtime_seconds": profile.get("repo_wide_static_aggregate"),
            "scope": "repo-wide static + situational runtime",
            "files_or_modules_covered": "full repo",
            "risk_addressed": "objective code audit closure",
            "evidence_artifact": ".github/workflows/objective-audit.yml",
            "must_run_precommit": False,
            "must_run_prepush": False,
            "must_run_ci": True,
            "can_be_cached": False,
            "can_be_incremental": False,
            "can_be_parallelized": False,
            "can_be_removed": False,
            "removal_risk": "critical",
            "recommendation": "keep_ci_only",
            "overlap_with_other_checks": ["fix-everything-we-touch-full-static"],
        }
    )

    for step in _reviewer_steps():
        checks.append(
            {
                "check_id": step["check_id"],
                "command": step["command"],
                "tier": 4,
                "runtime_seconds": None,
                "scope": "reviewer reproduction",
                "files_or_modules_covered": "see command",
                "risk_addressed": "external reviewer proof",
                "evidence_artifact": "governance/REVIEWER_README.md",
                "must_run_precommit": False,
                "must_run_prepush": False,
                "must_run_ci": False,
                "can_be_cached": False,
                "can_be_incremental": False,
                "can_be_parallelized": True,
                "can_be_removed": False,
                "removal_risk": "medium",
                "recommendation": "keep_reviewer_only",
                "overlap_with_other_checks": [],
            }
        )

    dupes: list[dict[str, Any]] = []
    for i, a in enumerate(checks):
        for b in checks[i + 1 :]:
            kind = _overlap_kind(a, b)
            if kind:
                dupes.append(
                    {
                        "check_a": a["check_id"],
                        "check_b": b["check_id"],
                        "classification": kind,
                        "note": "Review before merge/remove — slowness alone is not removal grounds",
                    }
                )
                a.setdefault("overlap_with_other_checks", []).append(b["check_id"])

    ablation_grid = profile.get("check_ablation_seven_model_four_horizon_grid")
    ablation_layer = profile.get("check_ablation_equal_layer_consumers")

    over_budget: list[dict[str, Any]] = []
    if MEASURED_PREPUSH_SEC > RUNTIME_BUDGETS_SEC["prepush_governance"]:
        over_budget.append(
            {
                "path": "pre-push",
                "measured_seconds": MEASURED_PREPUSH_SEC,
                "budget_seconds": RUNTIME_BUDGETS_SEC["prepush_governance"],
                "documented_reason": (
                    "governance-consolidation-tests pytest suite dominates (~26 min); "
                    "ablation grid lock ~146s after PERF2-1 shared index"
                ),
                "recommendation": "candidate_for_retier and make_incremental — do not remove checks without risk proof",
            }
        )

    recommendations = {
        "keep_in_precommit": [c["check_id"] for c in checks if c.get("recommendation") == "keep_in_precommit"],
        "move_to_prepush": [c["check_id"] for c in checks if c.get("recommendation") == "move_to_prepush"],
        "move_to_ci_only": [c["check_id"] for c in checks if c.get("recommendation") == "keep_ci_only"],
        "merge_with_existing_check": [],
        "delete_obsolete_check": [],
        "make_incremental": [
            "governance-consolidation-tests",
            "check_ablation_seven_model_four_horizon_grid",
        ],
        "make_cached": ["fix-everything-we-touch", "check_ablation_equal_layer_consumers"],
        "make_parallel": ["reviewer audit pytest steps"],
        "manual_review": ["governance-consolidation-tests runtime split"],
    }

    return {
        "schema_version": SCHEMA_VERSION,
        "phase": "3I-CheckStack",
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "policy": "governance/docs/CHECK_STACK_RIGHTSIZING.md",
        "runtime_budgets_seconds": RUNTIME_BUDGETS_SEC,
        "measured": {
            "prepush_seconds": MEASURED_PREPUSH_SEC,
            "ablation_grid_seconds": ablation_grid,
            "ablation_equal_layer_seconds": ablation_layer,
        },
        "over_budget": over_budget,
        "check_count": len(checks),
        "duplication_analysis": dupes,
        "recommendations": recommendations,
        "checks": checks,
    }


def _render_md(inv: dict[str, Any]) -> str:
    lines = [
        "# Check stack right-sizing",
        "",
        "**Scope:** Phase 3I — inventory, tier policy, duplication analysis, runtime budgets. No check removal in this phase.",
        "",
        f"Generated: `{inv.get('generated_at_utc')}`",
        "",
        "## Runtime budget targets (seconds)",
        "",
        "| Path | Target | Measured / status |",
        "|------|--------|-------------------|",
        f"| Pre-commit normal | {RUNTIME_BUDGETS_SEC['precommit_normal']}s | under budget after Perf1 |",
        f"| Pre-commit governance | {RUNTIME_BUDGETS_SEC['precommit_governance']}s | scoped path |",
        f"| Pre-push governance | {RUNTIME_BUDGETS_SEC['prepush_governance']}s | **OVER** — {MEASURED_PREPUSH_SEC}s measured |",
        "",
        "## Tier model",
        "",
        "- **Tier 0** — upfront gate (`enforce_all_rules --upfront-gate`)",
        "- **Tier 1** — pre-commit (staged + fast)",
        "- **Tier 2** — pre-push (fast gates + consolidation pytest)",
        "- **Tier 3** — CI objective-audit (repo-wide full-static authority)",
        "- **Tier 4** — reviewer audit (`run_reviewer_audit.py`)",
        "",
        "## Over budget (recorded, not silently accepted)",
        "",
    ]
    for row in inv.get("over_budget") or []:
        lines.append(
            f"- **{row.get('path')}**: {row.get('measured_seconds')}s vs budget {row.get('budget_seconds')}s — "
            f"{row.get('documented_reason')}"
        )
    lines.extend(
        [
            "",
            "## Duplication analysis",
            "",
        ]
    )
    for d in inv.get("duplication_analysis") or []:
        lines.append(
            f"- `{d.get('check_a')}` ↔ `{d.get('check_b')}`: **{d.get('classification')}** — {d.get('note')}"
        )
    lines.extend(
        [
            "",
            "Regenerate: `python tools/build_check_stack_inventory.py`",
            "",
        ]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Build check stack inventory.")
    p.add_argument("--stdout", action="store_true")
    args = p.parse_args(argv)

    inv = build_inventory()
    if args.stdout:
        print(json.dumps(inv, indent=2))
        return 0

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(inv, indent=2) + "\n", encoding="utf-8")
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text(_render_md(inv), encoding="utf-8")
    print(
        f"wrote {OUT_JSON.relative_to(REPO)} ({inv['check_count']} checks; "
        f"{len(inv.get('duplication_analysis') or [])} duplication rows)"
    )
    print(f"wrote {OUT_MD.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
