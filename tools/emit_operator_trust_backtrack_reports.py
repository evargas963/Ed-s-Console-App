#!/usr/bin/env python3
"""Generate operator-trust backtrack reports."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from verification.operator_trust_backtrack import (
    build_pr_completion_audit,
    build_stabilization_decision,
)


def main() -> None:
    d = "2026-06-18"
    out = ROOT / "reports/operator_trust_backtrack"
    out.mkdir(parents=True, exist_ok=True)
    audit = build_pr_completion_audit(audit_date=d)
    (out / "pr_completion_audit_2026-06-18.json").write_text(
        json.dumps(audit, indent=2), encoding="utf-8"
    )
    lines = [
        "# PR completion audit",
        "",
        "> **Classification:** Historical Record | **Scope:** PR #11–#16 completion reconciliation",
        "",
        f"**Date:** {d}",
        "",
        "| PR | Claimed | Actual | Open risks | Correction |",
        "|---:|---|---|---|---|",
    ]
    for r in audit["rows"]:
        risks = ", ".join(r["open_risks_left_behind"]) or "-"
        corr = r.get("required_correction") or "-"
        lines.append(
            f"| {r['pr']} | {r['claimed_completion']} | {r['actual_completion_status']} | {risks} | {corr} |"
        )
    (out / "pr_completion_audit_2026-06-18.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    dec = build_stabilization_decision(audit_date=d, artifacts_gate_pass=True)
    (out / "stabilization_decision_2026-06-18.json").write_text(
        json.dumps(dec, indent=2), encoding="utf-8"
    )
    (out / "stabilization_decision_2026-06-18.md").write_text(
        "# Stabilization decision\n\n"
        "> **Classification:** Historical Record | **Scope:** Operator-trust backtrack gate decision\n\n"
        f"stabilization_artifacts_gate_pass: {dec['stabilization_artifacts_gate_pass']}\n"
        f"operator_readiness_gate_pass: {dec['operator_readiness_gate_pass']}\n"
        f"card_explainability_allowed: {dec['card_explainability_allowed']}\n\n"
        "## card_explainability_block_reason\n"
        + "\n".join(f"- {x}" for x in dec["card_explainability_block_reason"])
        + "\n\n## Blocking open items\n"
        + "\n".join(f"- {x}" for x in dec["blocking_items"])
        + "\n\n## Next allowed branch\n"
        + dec["next_allowed_branch"]
        + "\n\n## Operator note\n"
        + dec["operator_note"]
        + "\n",
        encoding="utf-8",
    )
    print("wrote", out)


if __name__ == "__main__":
    main()
