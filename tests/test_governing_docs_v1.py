"""The four governing documents name only paths that exist, and AGENTS.md stays loadable.

Failure this catches (2026-09-27): AGENTS.md named `decision_gate.py`, `call_engine.py` and
`config/decision_path_admissions.json` for months after they were deleted. Checked: a backticked
path whose first folder is tracked in git or that names a code, JSON or document file, and a bare
code or document file name. Runtime files,
branch names, folders outside the repository and not-yet-built target folders are not repository
paths and are not checked. Anthropic's CLAUDE.md guidance: under 200 lines, or rules are lost.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ("AGENTS.md", "docs/DATA_FLOW.md", "ACTIVE_PROGRAM.md", "docs/ARCHITECTURE.md")
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


#: the documents whose sections marked "(enforced)" hold requirements
ENFORCED_DOCS = ("AGENTS.md", "docs/DATA_FLOW.md")
ENFORCEMENT_ID = re.compile(r"\bENF-\d+\b")
DATA_RULE_ID = re.compile(r"\bD\d\b")


def requirements(text: str) -> list[str]:
    """Each requirement in a section whose heading says "(enforced)": a numbered or bulleted item,
    or a paragraph, with its continuation lines. Code blocks are not requirements."""
    items: list[str] = []
    enforced = fence = False
    for line in text.splitlines():
        if line.startswith("```"):
            fence = not fence
            continue
        if fence:
            continue
        if line.startswith("#"):
            enforced = "(enforced)" in line
            if items and items[-1]:
                items.append("")
            continue
        if not enforced or not line.strip():
            if items and items[-1]:
                items.append("")                       # a blank line ends an item
            continue
        if re.match(r"(\d+\.|-) ", line) or not items or items[-1] == "":
            items.append(line.strip())
        else:
            items[-1] += " " + line.strip()
    return [i for i in items if i]


def enforcement_gaps(doc_text: str, tracked: list[str], program: str) -> list[str]:
    """Each requirement that does not say how it is enforced: no "Enforced by:", or one that names
    no tracked file, no ENF item listed in ACTIVE_PROGRAM.md and no data rule (D1–D6)."""
    listed = set(re.findall(r"^\| (ENF-\d+) \|", program, flags=re.M))
    files = set(tracked)
    gaps = []
    for item in requirements(doc_text):
        if "Enforced by:" not in item:
            gaps.append(f"no 'Enforced by:': {item[:80]}")
            continue
        how = item.split("Enforced by:", 1)[1]
        cites_file = any(t.rstrip(".,;") in files for t in re.findall(r"`([^`\s]+)`", how))
        ids = ENFORCEMENT_ID.findall(how)
        unlisted = [i for i in ids if i not in listed]
        if unlisted:
            gaps.append(f"names {unlisted}, not in ACTIVE_PROGRAM.md: {item[:80]}")
        elif not (cites_file or ids or DATA_RULE_ID.search(how)):
            gaps.append(f"names no test, hook, check or ENF item: {item[:80]}")
    return gaps


def test_every_requirement_says_how_it_is_enforced(tracked_files):
    program = (ROOT / "ACTIVE_PROGRAM.md").read_text(encoding="utf-8")
    texts = {d: (ROOT / d).read_text(encoding="utf-8") for d in ENFORCED_DOCS}
    assert all(requirements(t) for t in texts.values()), "a document has no (enforced) section"
    gaps = {d: enforcement_gaps(t, tracked_files, program) for d, t in texts.items()}
    assert not any(gaps.values()), f"requirements without enforcement: {gaps}"


def test_the_check_catches_a_requirement_with_no_enforcement():
    doc = ("## Rules (enforced)\n\n1. **Kept.** Enforced by: `tests/test_a.py`.\n"
           "2. **Prose only.** Nobody checks this.\n"
           "3. **Tracked.** Enforced by: no machine check — ENF-01.\n"
           "4. **Untracked.** Enforced by: no machine check — ENF-99.\n"
           "5. **Vague.** Enforced by: review.\n\n## Running it\n\nNot a requirement.\n")
    gaps = enforcement_gaps(doc, ["tests/test_a.py"], "| ENF-01 | QUEUED | x |\n")
    assert [g.split(":")[0] for g in gaps] == [
        "no 'Enforced by", "names ['ENF-99'], not in ACTIVE_PROGRAM.md",
        "names no test, hook, check or ENF item"]


def test_agents_md_stays_under_200_lines():
    n = (ROOT / "AGENTS.md").read_text(encoding="utf-8").count("\n")
    assert n < 200, f"AGENTS.md is {n} lines"
