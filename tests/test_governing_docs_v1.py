"""The governing documents and instructions name only paths that exist, and no source file claims
a tool that does not exist.

Failures this catches: AGENTS.md named `decision_gate.py`, `call_engine.py` and
`config/decision_path_admissions.json` for months after they were deleted; guards, a workflow and
code comments claimed enforcement by `tools/` scripts that do not exist. Checked: a backticked
path whose first folder is tracked in git or that names a code, config or document file, and a
bare file name of those kinds. Runtime files, branch names, folders outside the repository and
not-yet-built target folders are not repository paths and are not checked.
"""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ("AGENTS.md", "CLAUDE.md", "README.md", "ACTIVE_PROGRAM.md", "docs/DATA_FLOW.md",
        "docs/ARCHITECTURE.md", "docs/playwright.md", "docs/host/README.md",
        "docs/host/BACKUP_AND_MIRROR.md", ".github/pull_request_template.md",
        ".claude/skills/drift-audit/SKILL.md", ".cursor/rules/00-always.mdc")
FILE_EXT = (".py", ".js", ".mjs", ".html", ".bat", ".md", ".yml", ".yaml", ".toml", ".mdc")


def missing_paths(text: str, tracked: list[str]) -> list[str]:
    names = {Path(t).name for t in tracked}
    tops = {t.split("/")[0] for t in tracked if "/" in t}
    prefixes = {"/".join(t.split("/")[:i]) for t in tracked for i in range(1, t.count("/") + 2)}
    missing = []
    for tok in re.findall(r"`([^`\s]+)`", text):
        t = tok.rstrip("/")
        if "*" in t or ":" in t or t.startswith(("/", "-", "./", "../")):
            continue
        if "/" in t:
            if (t.split("/")[0] in tops or t.endswith(FILE_EXT + (".json",))) and t not in prefixes:
                missing.append(tok)
        elif t.endswith(FILE_EXT) and t not in names:
            missing.append(tok)
    return missing


def _ignored(path: str) -> bool:
    """A runtime file the documents name as never in git (`.gitignore`)."""
    return subprocess.run(["git", "check-ignore", "-q", path], cwd=ROOT).returncode == 0


def test_every_path_the_governing_documents_name_exists(tracked_files):
    assert tracked_files, "git lists no tracked files"
    bad = {d: [p for p in missing_paths((ROOT / d).read_text(encoding="utf-8"), tracked_files)
               if not _ignored(p)] for d in DOCS}
    assert not any(bad.values()), f"paths that do not exist: {bad}"


def test_the_check_catches_the_deleted_paths_the_old_charter_named():
    old = ("Enforced by `decision_gate.py` in `call_engine.compute_call`, per "
           "`config/decision_path_admissions.json`; `server.py` serves it.")
    tracked = ["server.py", "tools/hook_chain.py"]
    assert missing_paths(old, tracked) == ["decision_gate.py", "config/decision_path_admissions.json"]


def test_a_dot_path_is_checked_too():
    tracked = [".pre-commit-config.yaml", ".claude/settings.json"]
    assert missing_paths("`.pre-commit-config.yaml` and `.claude/settings.json`", tracked) == []
    assert missing_paths("`.claude/hooks.json`", tracked) == [".claude/hooks.json"]


def test_no_source_file_names_a_tools_script_that_does_not_exist():
    """A comment or config that cites `tools/<x>.py` as its enforcer names a real file. Tests are
    left out: they build scratch tools and name retired ones on purpose."""
    listed = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True,
                            check=True).stdout.split()
    files = [p for p in listed if not p.startswith("tests/")
             and p.endswith((".py", ".js", ".md", ".yml", ".yaml", ".json", ".bat", ".mdc"))]
    assert files
    named = {(p, m) for p in files for m in re.findall(
        r"\btools/[A-Za-z0-9_]+\.py\b", (ROOT / p).read_text(encoding="utf-8", errors="replace"))}
    assert not {(p, m) for p, m in named if m not in listed}, "tools that do not exist are named"
