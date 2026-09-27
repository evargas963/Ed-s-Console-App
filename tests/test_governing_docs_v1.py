"""The four governing documents name only paths that exist, and AGENTS.md stays loadable.

Failure this catches (2026-09-27): AGENTS.md named `decision_gate.py`, `call_engine.py` and
`config/decision_path_admissions.json` for months after they were deleted. Checked: a backticked
path whose first folder is tracked in git or that names a code, JSON or document file, and a bare
code or document file name. Runtime files,
branch names, folders outside the repository and not-yet-built target folders are not repository
paths and are not checked. Anthropic's CLAUDE.md guidance: under 200 lines, or rules are lost.
"""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ("AGENTS.md", "docs/DATA_FLOW.md", "ACTIVE_PROGRAM.md", "docs/ARCHITECTURE.md")
FILE_EXT = (".py", ".js", ".mjs", ".html", ".bat", ".md")


def _tracked() -> list[str]:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True)
    return out.stdout.split()


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


def _doc_texts() -> dict[str, str]:
    """The four documents only -- names come from `_tracked`, no source file is read."""
    return {d: (ROOT / d).read_text(encoding="utf-8") for d in DOCS}


def test_every_path_the_governing_documents_name_exists():
    texts = _doc_texts()
    tracked = _tracked()
    assert tracked, "git ls-files returned nothing"
    bad = {d: missing_paths(text, tracked) for d, text in texts.items()}
    assert not any(bad.values()), f"paths that do not exist: {bad}"


def test_the_check_catches_the_deleted_paths_the_old_charter_named():
    old = ("Enforced by `decision_gate.py` in `call_engine.compute_call`, per "
           "`config/decision_path_admissions.json`; `server.py` serves it.")
    assert missing_paths(old, _tracked()) == ["decision_gate.py", "config/decision_path_admissions.json"]


def test_agents_md_stays_under_200_lines():
    n = (ROOT / "AGENTS.md").read_text(encoding="utf-8").count("\n")
    assert n < 200, f"AGENTS.md is {n} lines"
