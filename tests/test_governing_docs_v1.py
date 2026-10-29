"""The governing documents name only paths that exist.

Failure this catches (2026-09-27): AGENTS.md named `decision_gate.py`, `call_engine.py` and
`config/decision_path_admissions.json` for months after they were deleted. Checked: a backticked
path whose first folder is tracked in git or that names a code, JSON or document file, and a bare
code or document file name. Runtime files,
branch names, folders outside the repository and not-yet-built target folders are not repository
paths and are not checked.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
#: the agents' rules for one area, the skills and the reviewers (loaded on demand)
AGENT_FILES = tuple(p.relative_to(ROOT).as_posix() for p in sorted(
    [*ROOT.glob(".claude/rules/*.md"), *ROOT.glob(".claude/skills/*/SKILL.md"), *ROOT.glob(".claude/agents/*.md")]))
DOCS = ("AGENTS.md", "CLAUDE.md", "docs/DATA_FLOW.md", "ACTIVE_PROGRAM.md", "docs/ARCHITECTURE.md", *AGENT_FILES)
FILE_EXT = (".py", ".js", ".mjs", ".html", ".bat", ".md")


def missing_paths(text: str, tracked: list[str]) -> list[str]:
    names = {Path(t).name for t in tracked}
    tops = {t.split("/")[0] for t in tracked if "/" in t}
    prefixes = {"/".join(t.split("/")[:i]) for t in tracked for i in range(1, t.count("/") + 2)}
    missing = []
    for tok in re.findall(r"`([^`\s]+)`", text):
        t = tok.rstrip("/")
        if "*" in t or ":" in t or t.startswith(("/", ".", "-")):
            continue
        if "/" in t:
            if (t.split("/")[0] in tops or t.endswith(FILE_EXT + (".json",))) and t not in prefixes:
                missing.append(tok)
        elif t.endswith(FILE_EXT) and t not in names:
            missing.append(tok)
    return missing


def test_every_path_the_governing_documents_name_exists(tracked_files):
    assert tracked_files, "git lists no tracked files"
    bad = {d: missing_paths((ROOT / d).read_text(encoding="utf-8"), tracked_files) for d in DOCS}
    assert not any(bad.values()), f"paths that do not exist: {bad}"


def test_the_check_catches_the_deleted_paths_the_old_charter_named():
    old = ("Enforced by `decision_gate.py` in `call_engine.compute_call`, per "
           "`config/decision_path_admissions.json`; `server.py` serves it.")
    tracked = ["server.py", "tools/hook_chain.py"]
    assert missing_paths(old, tracked) == ["decision_gate.py", "config/decision_path_admissions.json"]
