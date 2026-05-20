"""COH-SA-2: America/New_York ZoneInfo authority lives only in time_et.py."""

from __future__ import annotations

import re
from pathlib import Path

_SKIP_PY_TREE_DIRS = frozenset(
    {".claude", ".git", ".venv", "venv", "node_modules", "__pycache__"}
)
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
    for path in root.rglob("*.py"):
        rel = path.relative_to(root)
        if rel.parts and rel.parts[0] == "tests":
            continue
        if any(part in _SKIP_PY_TREE_DIRS for part in rel.parts):
            continue
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
