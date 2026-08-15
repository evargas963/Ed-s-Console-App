"""COH-SA-2: America/New_York ZoneInfo authority lives only in time_et.py."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
_NY_LITERAL = 'ZoneInfo("America/New_York")'
_ET_ASSIGN = re.compile(
    r"^\s*(?:ET|_ET)\s*=\s*ZoneInfo\s*\(\s*[\"']America/New_York[\"']\s*\)",
    re.MULTILINE,
)
_INLINE_NOW_NY = re.compile(
    r"datetime\.now\s*\(\s*ZoneInfo\s*\(\s*[\"']America/New_York[\"']\s*\)\s*\)"
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _iter_repo_py_files(root: Path):
    """Repo-wide means the GIT INDEX (RC-274, RC-286, RC-307).

    This walked the filesystem with `rglob` behind a hand-written skip list of `.git`,
    `.venv`, `node_modules` and friends. `scratchpad/` was not on that list — it holds 93
    throwaway audit scripts, `git ls-files scratchpad` returns nothing, and `.gitignore:202`
    excludes it — so two tests here have been failing on code the repository does not
    contain. Every hand-maintained skip list is correct on the day it is written; the index
    cannot drift, because it is the definition.
    """
    out = subprocess.run(["git", "ls-files", "-z", "--", "*.py"],
                         cwd=root, capture_output=True, text=True, check=True).stdout
    for relstr in sorted(p for p in out.split("\0") if p):
        rel = Path(relstr)
        if rel.parts and rel.parts[0] == "tests":
            continue
        path = root / rel
        if path.exists():        # tracked-but-absent (a mid-rebase worktree) is not an offender
            yield path, rel


def test_only_time_et_defines_ny_zoneinfo_literal():
    root = _repo_root()
    offenders: list[str] = []
    for path, rel in _iter_repo_py_files(root):
        if rel.name == "time_et.py":
            continue
        if _NY_LITERAL in path.read_text(encoding="utf-8"):
            offenders.append(str(rel).replace("\\", "/"))
    assert not offenders, offenders


def test_no_module_level_et_zoneinfo_assignment_outside_time_et():
    root = _repo_root()
    offenders: list[str] = []
    for path, rel in _iter_repo_py_files(root):
        if rel.name == "time_et.py":
            continue
        src = path.read_text(encoding="utf-8")
        if _ET_ASSIGN.search(src):
            offenders.append(str(rel).replace("\\", "/"))
    assert not offenders, offenders


def test_no_inline_datetime_now_ny_zoneinfo():
    root = _repo_root()
    offenders: list[str] = []
    for path, rel in _iter_repo_py_files(root):
        if rel.name == "time_et.py":
            continue
        src = path.read_text(encoding="utf-8")
        if _INLINE_NOW_NY.search(src):
            offenders.append(str(rel).replace("\\", "/"))
    assert not offenders, offenders


def test_coh_sa2_migrated_modules_use_canonical_et():
    """Spot-check COH-SA-2 production redirects."""
    from time_et import ET as canonical, now_et

    import polling_adapter
    import live_decision_bundle
    import v2_decision.a2_session_calendar as asc

    assert polling_adapter.ET is canonical
    assert live_decision_bundle._ET is canonical
    assert asc.ET is canonical

    from event_risk import session_date_et

    assert session_date_et(now_et()) == now_et().date()
