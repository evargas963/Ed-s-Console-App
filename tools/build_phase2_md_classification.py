"""Phase 2: classify all repo Markdown and insert scope headers where missing."""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "governance/consolidation/phase2"
OUT_CSV = OUT_DIR / "md_classification.csv"

SKIP_DIR_NAMES = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        ".pytest_cache",
        "backups",
    }
)

HEADER_RE = re.compile(
    r"^\s*>\s*\*\*(?:Classification|Scope|Historical|SUPERSEDED)",
    re.I | re.M,
)
INLINE_SCOPE_RE = re.compile(r"^\*\*Scope:\*\*", re.I | re.M)

ACTIVE_RULE_SOURCES: dict[str, str] = {
    "AGENTS.md": "Always-on agent behavior rules (Cursor + Claude Code).",
    "ACTIVE_PROGRAM.md": "Current epic, conflicts, open work, known risks.",
    "CLAUDE.md": "Schwab program law; Read-not-scan methodology.",
    "MEMORY.md": "Thin pointer to AGENTS/ACTIVE_PROGRAM and [OPERATOR-ONLY] archive prefs.",
    "docs/governance/AGENT_SELF_GOVERNANCE.md": (
        "Process alternation, sign-off contract, verification matrix."
    ),
}

ROOT_HISTORICAL_AUDITS = frozenset(
    {
        "CALL_CARD_SEMANTICS_FIX_AUDIT.md",
        "CARD_STUCK_FIX_AUDIT.md",
        "FUSION_MC_AUDIT.md",
        "LSTM_INACTIVE_FIX_AUDIT.md",
        "MODEL_STATUS_HARDENING_AUDIT.md",
        "SCHWAB_AUTH_AUDIT.md",
        "SNAPSHOT_DATA_AUDIT.md",
    }
)

ROOT_HISTORICAL_OTHER = frozenset(
    {
        "MIGRATION_1M_CANONICAL.md",
        "PIPELINE_QUALITY.md",
        "PROMOTION_POLICY.md",
    }
)


@dataclass(frozen=True)
class Row:
    rel_path: str
    category: str
    scope: str
    header_added: bool


def iter_md_files() -> list[Path]:
    out: list[Path] = []
    for path in ROOT.rglob("*.md"):
        rel = path.relative_to(ROOT)
        if any(part in SKIP_DIR_NAMES for part in rel.parts):
            continue
        if ".claude" in rel.parts and "worktrees" in rel.parts:
            continue
        out.append(path)
    return sorted(out, key=lambda p: str(p).lower())


def has_scope_header(text: str) -> bool:
    head = "\n".join(text.splitlines()[:15])
    return bool(HEADER_RE.search(head) or INLINE_SCOPE_RE.search(head))


def classify(rel_posix: str, text: str) -> tuple[str, str]:
    name = Path(rel_posix).name
    head = text[:800]

    if rel_posix in ACTIVE_RULE_SOURCES:
        return "Active Rule Source", ACTIVE_RULE_SOURCES[rel_posix]

    if rel_posix == "OPEN_ITEMS.md":
        return "Operational Ledger", "Canonical open-work registry; closes require SHA."

    if rel_posix == "MODEL_RESTORE_LOG.md" or rel_posix.endswith("/MODEL_RESTORE_LOG.md"):
        return "Operational Ledger", "Model restore/promotion event log."

    if "governance/archive/" in rel_posix:
        return "Historical Record", "Archived consolidation or memory artifact."

    if re.search(r"SUPERSEDED|FORWARDING", head, re.I):
        return "Superseded", f"Superseded index or forwarding stub for `{name}`."

    if rel_posix.startswith("docs/host/"):
        return "Operator Runbook", "Host-local secrets, backup, and environment guidance."

    if name in ("TRAINING_AND_MAINTENANCE.md", "DATA_STEWARDSHIP.md"):
        return "Operator Runbook", "Training, maintenance, and data stewardship procedures."

    if name == "README.md" and rel_posix == "README.md":
        return "Operator Runbook", "Project entrypoint and developer onboarding."

    if name in ROOT_HISTORICAL_AUDITS:
        return (
            "Historical Record",
            f"Root point-in-time audit `{name}`; not binding unless ACTIVE_PROGRAM cites.",
        )

    if name in ROOT_HISTORICAL_OTHER:
        return "Historical Record", f"Root historical reference `{name}`."

    if name.endswith("_AUDIT.md") or "/audits/" in rel_posix:
        return "Historical Record", f"Point-in-time audit artifact `{rel_posix}`."

    if rel_posix.startswith("docs/plans/"):
        return (
            "Policy Specification",
            "Execution plan; binding when ACTIVE_PROGRAM points here.",
        )

    if rel_posix.startswith("schwab_field_inventory/"):
        return (
            "Policy Specification",
            "Schwab field inventory reference; refresh on CHANGELOG or quarterly.",
        )

    if rel_posix.startswith("governance/"):
        upper = name.upper()
        if any(k in upper for k in ("REGISTER", "INVENTORY", "MAP", "LEDGER")):
            return "Operational Ledger", f"Governance register/inventory `{name}`."
        if any(k in upper for k in ("CONTRACT", "PROGRAM", "STANDARD", "PHASE_PLAN", "POLICY")):
            return "Policy Specification", f"Governance policy/contract `{name}`."
        if "AUDIT" in upper or "MEMO" in upper:
            return "Historical Record", f"Governance audit/memo `{name}`."
        return "Policy Specification", f"Governance documentation `{name}`."

    if rel_posix.startswith("docs/"):
        lower = name.lower()
        if any(k in lower for k in ("audit", "report", "proof", "validation", "closure")):
            return "Historical Record", f"Completed analysis or validation `{rel_posix}`."
        return "Policy Specification", f"Technical documentation `{rel_posix}`."

    if name == "EdWebConsole_DesignSystem.md":
        return "Policy Specification", "UI design system reference."

    return "Policy Specification", f"Repository documentation `{rel_posix}`."


def make_header(category: str, scope: str) -> str:
    if category == "Historical Record":
        return (
            f"> **Classification:** Historical Record | **Scope:** {scope}\n\n"
        )
    if category == "Superseded":
        return f"> **Classification:** Superseded | **Scope:** {scope}\n\n"
    return f"> **Classification:** {category} | **Scope:** {scope}\n\n"


def process_file(path: Path, *, apply: bool) -> Row:
    rel = path.relative_to(ROOT).as_posix()
    text = path.read_text(encoding="utf-8")
    category, scope = classify(rel, text)
    added = False
    if apply and not has_scope_header(text):
        path.write_text(make_header(category, scope) + text, encoding="utf-8")
        added = True
    return Row(rel_path=rel, category=category, scope=scope, header_added=added)


def write_csv(rows: list[Row]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["rel_path", "category", "scope", "header_added"],
        )
        w.writeheader()
        for row in rows:
            w.writerow(
                {
                    "rel_path": row.rel_path,
                    "category": row.category,
                    "scope": row.scope,
                    "header_added": "yes" if row.header_added else "no",
                }
            )
    summary = OUT_DIR / "phase2_summary.json"
    summary.write_text(
        __import__("json").dumps(
            {
                "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                "md_files": len(rows),
                "headers_added": sum(1 for r in rows if r.header_added),
                "categories": {
                    cat: sum(1 for r in rows if r.category == cat)
                    for cat in sorted({r.category for r in rows})
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def main() -> None:
    rows = [process_file(p, apply=True) for p in iter_md_files()]
    write_csv(rows)
    added = sum(1 for r in rows if r.header_added)
    print(f"classified {len(rows)} markdown files; headers added to {added}")
    print(f"wrote {OUT_CSV}")


if __name__ == "__main__":
    main()
