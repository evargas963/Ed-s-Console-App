"""Phase 1a governance consolidation guards."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Pin excerpt hashes only (not full AGENTS.md body).
BANNED_TOOLS_HASH = "0de266bec3a17c77af3180fa8fbdb10d03fa075cd6a34be01e306dc5761c1194"
NO_PERMISSION_ASKS_HASH = "1a1f2968debddd443f24595e4c4d4384585bde65c26a8e7a89e124a254a28d3f"


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _section(text: str, heading: str) -> str:
    m = re.search(rf"^## {re.escape(heading)}.*?(?=^## |\Z)", text, re.M | re.S)
    assert m, f"missing section {heading!r}"
    return m.group(0).strip()


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_agents_md_exists():
    assert (ROOT / "AGENTS.md").is_file()


def test_active_program_exists():
    assert (ROOT / "ACTIVE_PROGRAM.md").is_file()


def test_mdc_always_apply():
    mdc = _read(".cursor/rules/00-always.mdc")
    assert "alwaysApply: true" in mdc


def test_mdc_pointers_match_canonical_files():
    mdc = _read(".cursor/rules/00-always.mdc")
    for name in ("ACTIVE_PROGRAM.md", "AGENTS.md", "CLAUDE.md"):
        assert name in mdc
    assert "ACTIVE_PROGRAM.md" in _read("AGENTS.md")
    assert "AGENTS.md" in _read("ACTIVE_PROGRAM.md")


def test_agents_banned_tools_excerpt_hash():
    agents = _read("AGENTS.md")
    excerpt = _section(agents, "Banned tools")
    assert _sha(excerpt) == BANNED_TOOLS_HASH


def test_agents_no_permission_asks_excerpt_hash():
    agents = _read("AGENTS.md")
    excerpt = _section(agents, "No permission asks")
    assert _sha(excerpt) == NO_PERMISSION_ASKS_HASH


def test_agent_self_governance_no_grep_references():
    text = _read("docs/governance/AGENT_SELF_GOVERNANCE.md").lower()
    for banned in ("grep", "ripgrep", " re-grep", "re-greps"):
        assert banned not in text, f"AGENT_SELF_GOVERNANCE still references {banned!r}"


def test_memory_archive_has_all_source_files():
    archive = ROOT / "governance/archive/2026-Q2/memory_archive"
    assert archive.is_dir()
    archived = {p.name for p in archive.glob("*.md") if p.name != "README.md"}
    # Phase 0 classification counted 34 non-MEMORY.md memory files
    assert len(archived) == 34
    for name in (
        "feedback_no_grep_tool.md",
        "feedback_no_permission_asks.md",
        "feedback_fiduciary_duty.md",
        "project_gate_b_state_2026_05_21.md",
    ):
        assert name in archived
    assert (ROOT / "MEMORY.md").is_file()
    body = (ROOT / "MEMORY.md").read_text(encoding="utf-8")
    assert "AGENTS.md" in body and "OPERATOR-ONLY" in body


SCOPE_HEADER_RE = re.compile(
    r"\*\*(?:Classification|Scope|Historical|SUPERSEDED)",
    re.I,
)


def _iter_repo_md() -> list[Path]:
    skip = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache", "backups"}
    out: list[Path] = []
    for path in ROOT.rglob("*.md"):
        rel = path.relative_to(ROOT)
        if any(part in skip for part in rel.parts):
            continue
        if ".claude" in rel.parts and "worktrees" in rel.parts:
            continue
        out.append(path)
    return out


def test_phase2_md_classification_spreadsheet():
    csv_path = ROOT / "governance/consolidation/phase2/md_classification.csv"
    assert csv_path.is_file(), "run tools/build_phase2_md_classification.py"
    import csv

    with csv_path.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) >= 250
    categories = {r["category"] for r in rows}
    for cat in (
        "Active Rule Source",
        "Policy Specification",
        "Historical Record",
        "Operational Ledger",
        "Operator Runbook",
    ):
        assert cat in categories


def test_phase2_all_md_have_scope_headers():
    missing: list[str] = []
    for path in _iter_repo_md():
        head = "\n".join(path.read_text(encoding="utf-8").splitlines()[:15])
        if not SCOPE_HEADER_RE.search(head):
            missing.append(path.relative_to(ROOT).as_posix())
    assert not missing, f"missing scope headers: {missing[:20]}"


def test_phase3_cleanup_artifacts():
    phase3 = ROOT / "governance/consolidation/phase3"
    for name in (
        "baseline_delta.json",
        "duplicate_md_report.json",
        "protected_py_audit.json",
        "worktree_cleanup_notes.md",
    ):
        assert (phase3 / name).is_file(), f"missing {name}; run tools/build_phase3_repo_cleanup.py"


def test_phase4_pre_commit_config():
    assert (ROOT / ".pre-commit-config.yaml").is_file()
    assert (ROOT / "tools/check_no_grep_subprocess.py").is_file()
