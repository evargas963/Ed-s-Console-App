"""RC-510: CODEOWNERS has no role or authority in Ed Console, and cannot acquire one.

WHAT WAS MEASURED (2026-09-02, and again 2026-09-03 before the fix). GitHub branch protection
on `main` carried `require_code_owner_reviews: true` while the repository contained NO
CODEOWNERS file: `git ls-tree -r origin/main` found none among 2,897 paths, and the contents
API returned 404 for all three locations GitHub accepts — `CODEOWNERS`, `.github/CODEOWNERS`
and `docs/CODEOWNERS`. A code-owner requirement with no CODEOWNERS file owns nothing, so it
required a review from nobody. Four rows in `governance/retired_checks.md` nevertheless cited
that setting as the surviving protection that justified retiring a real check.

On operator direction the requirement was DELETED rather than implemented: a protection that
protects nothing is a false entry in the authority map, not missing coverage. The real
protection was misnamed — the guard rosters are pinned mechanically in required CI, which
cannot be approved away.

THIS FILE IS A CONTROL, NOT A NEW MECHANISM. It adds no gate, hook or checker; it is a test in
the suite that already runs, asserting that the concept stays gone from the tree. The GitHub
setting itself lives outside the repository and cannot be asserted here — that is precisely
why it went unexamined for so long, and it is stated rather than papered over.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: The only three paths GitHub honours for a CODEOWNERS file.
CODEOWNERS_LOCATIONS = ("CODEOWNERS", ".github/CODEOWNERS", "docs/CODEOWNERS")

#: History records what was true when written and is not rewritten to match later decisions —
#: the same rule that restored the preregistration and the archive in this mission. The dated
#: root-cause rows and the RC-510 record itself narrate the removal; they confer no authority.
HISTORY = (
    "governance/root_cause_log.md",      # append-only defect ledger
    "governance/retired_checks.md",      # append-only manifest; carries the RC-510 record
    "governance/agent_error_log.md",
    "governance/OPERATOR_DECISION_REGISTER.md",
    "governance/archive/",
    "tests/archive/",
    "reports/",                          # dated evidence
    "tests/test_no_code_owner_authority_v1.py",   # this file
)

_MENTION = re.compile(r"(?i)code[_ -]?owner")


def _tracked() -> list[str]:
    out = subprocess.run(["git", "ls-files"], cwd=str(ROOT), capture_output=True,
                         text=True, encoding="utf-8", errors="replace").stdout.split()
    assert len(out) > 100, "tracked-file discovery returned too little to be a real check"
    return out


def test_no_codeowners_file_exists():
    """The file must not be created to satisfy a setting that no longer exists."""
    present = [p for p in CODEOWNERS_LOCATIONS if (ROOT / p).exists()]
    assert present == [], (
        f"a CODEOWNERS file was added at {present}. The code-owner requirement was REMOVED, "
        "not satisfied — adding the file re-creates the authority this mission eliminated.")
    tracked = [p for p in _tracked() if "CODEOWNERS" in p.upper()]
    assert tracked == [], f"CODEOWNERS is tracked at {tracked}"


def test_no_active_surface_claims_code_owner_authority():
    """No live specification, source or configuration may name it as a control.

    Scoped to ACTIVE surfaces: history and dated evidence are excluded by name above, because
    rewriting them to match a later decision is the error this mission made twice and undid
    twice (the preregistration, and 35 archive files).
    """
    offenders = []
    for rel in _tracked():
        if rel.startswith(HISTORY):
            continue
        p = ROOT / rel
        if not p.exists() or p.suffix.lower() not in (
                ".py", ".md", ".mdc", ".json", ".yaml", ".yml", ".toml", ".cfg", ".sh",
                ".ps1", ".bat", ".js", ".mjs", ".html"):
            continue
        if p.stat().st_size > 3_000_000:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for n, line in enumerate(text.splitlines(), 1):
            if _MENTION.search(line):
                offenders.append(f"{rel}:{n}")
    assert offenders == [], (
        "an active surface names code-owner review as a control; it has no role in this "
        "repository: " + ", ".join(offenders[:10]))


def test_the_retirement_rationales_name_a_mechanism_that_exists():
    """The four retirements must not be justified by the deleted requirement.

    This is the substance: a retirement row is the standing reason a real check is gone, so a
    rationale naming a control that does not exist is a live false claim, not a footnote.
    """
    manifest = (ROOT / "governance" / "retired_checks.md").read_text(encoding="utf-8")
    rows = {m.group(1): m.group(0) for m in
            re.finditer(r"^\| ([a-z][a-z0-9_]*) \| \d{4}-\d{2}-\d{2} \|[^\n]*", manifest, re.M)}
    for name in ("plus_player_cursor_hooks", "claude_cursor_guard_parity",
                 "honesty_guard_wired", "writer_no_drift"):
        assert name in rows, f"{name} row vanished from the manifest"
        assert "RATIONALE CORRECTED" in rows[name], (
            f"{name} still carries its original rationale — it cited a control that never "
            "existed and must say what actually survives")
        assert not re.search(r"(?i)CODEOWNERS-owned", rows[name]), (
            f"{name} still claims a CODEOWNERS-owned file as its protection")
    # ...and the two-step retirement contract must still be able to read every name.
    assert len(rows) >= 25, f"the manifest's machine-readable rows shrank to {len(rows)}"
