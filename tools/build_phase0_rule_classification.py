"""Phase 0.5: lightweight rule-bearing source classification CSV."""
from __future__ import annotations

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MEMORY_DIR = Path.home() / ".claude/projects/C--Users-evarg-Documents-Trading-EdWebConsole/memory"


def _topic_from_name(name: str) -> str:
    if name.startswith("feedback_"):
        return name.removeprefix("feedback_").replace("_", " ")
    if name.startswith("project_"):
        return name.removeprefix("project_").replace("_", " ")
    return name


def main() -> None:
    rows: list[dict[str, str]] = []

    rows.append(
        {
            "source_id": "AGENT_SELF_GOVERNANCE",
            "path": "docs/governance/AGENT_SELF_GOVERNANCE.md",
            "topic": "alternation ledger sign-off verification matrix",
            "proposed_disposition": "split: behavior→AGENTS process→keep slim",
            "notes": "Phase 1b slim to ~60 lines with stubs",
        }
    )
    rows.append(
        {
            "source_id": "CLAUDE",
            "path": "CLAUDE.md",
            "topic": "Schwab full repo directive",
            "proposed_disposition": "keep CLAUDE.md add scope header",
            "notes": "Resolve V4 CSV authority contradiction Phase 1b",
        }
    )

    memory_files = sorted(MEMORY_DIR.glob("*.md")) if MEMORY_DIR.is_dir() else []
    for idx, p in enumerate(memory_files, start=1):
        name = p.name
        if name == "MEMORY.md":
            disp = "Phase 1c thin pointer"
        elif name.startswith("feedback_no_grep") or name.startswith("feedback_no_permission"):
            disp = "PROMOTED→AGENTS + .mdc verbatim"
        elif name.startswith("feedback_"):
            disp = "PROMOTED or CONSOLIDATED→AGENTS"
        elif name.startswith("project_gate_b") or "gate_b" in name:
            disp = "OPERATOR-ONLY→MEMORY pointer"
        elif name.startswith("project_"):
            disp = "STALE or archive memory"
        else:
            disp = "TBD Phase 1a review"
        rows.append(
            {
                "source_id": f"memory_{idx:02d}",
                "path": str(p),
                "topic": _topic_from_name(p.stem),
                "proposed_disposition": disp,
                "notes": "archive Phase 1c unless OPERATOR-ONLY",
            }
        )

    rows.append(
        {
            "source_id": "cursor_user_rules",
            "path": "governance/consolidation/phase0/cursor_user_rules_snapshot.txt",
            "topic": "Cursor IDE user rules",
            "proposed_disposition": "Phase 1a explicit per-rule disposition",
            "notes": "promote / OPERATOR-ONLY / superseded by .mdc",
        }
    )

    out = ROOT / "governance/consolidation/phase0/rule_source_classification.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["source_id", "path", "topic", "proposed_disposition", "notes"],
        )
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {out} ({len(rows)} rows, {len(memory_files)} memory files)")


if __name__ == "__main__":
    main()
