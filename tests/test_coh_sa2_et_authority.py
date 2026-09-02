"""COH-SA-2: America/New_York ZoneInfo authority lives only in time_et.py."""

from __future__ import annotations

import re
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


# TEST_SYSTEM_REHAB_V2 final remediation: `_iter_repo_py_files` was an independent
# `git ls-files` + per-file `.read_text()` re-scan, redundant with the shared
# `repo_index` fixture (tests/conftest.py) that already builds the identical
# git-index-scoped observation once per run -- structurally invisible to the
# original .rglob/.glob/os.walk-only recurrence lock (a `subprocess.run` call, not
# an `.rglob` call), caught only after the lock's git-ls-files extension. Migrated
# onto `repo_index` below; the original docstring's point (git index, not a
# filesystem walk with a hand-maintained skip list) is exactly what `repo_index`
# already does.


def test_only_time_et_defines_ny_zoneinfo_literal(repo_index):
    offenders: list[str] = []
    for relpath, text, _tree in repo_index.items():
        if relpath.parts and relpath.parts[0] == "tests":
            continue
        if relpath.name == "time_et.py":
            continue
        if _NY_LITERAL in text:
            offenders.append(relpath.as_posix())
    assert not offenders, offenders


def test_no_module_level_et_zoneinfo_assignment_outside_time_et(repo_index):
    offenders: list[str] = []
    for relpath, text, _tree in repo_index.items():
        if relpath.parts and relpath.parts[0] == "tests":
            continue
        if relpath.name == "time_et.py":
            continue
        if _ET_ASSIGN.search(text):
            offenders.append(relpath.as_posix())
    assert not offenders, offenders


def test_no_inline_datetime_now_ny_zoneinfo(repo_index):
    offenders: list[str] = []
    for relpath, text, _tree in repo_index.items():
        if relpath.parts and relpath.parts[0] == "tests":
            continue
        if relpath.name == "time_et.py":
            continue
        if _INLINE_NOW_NY.search(text):
            offenders.append(relpath.as_posix())
    assert not offenders, offenders


def test_coh_sa2_migrated_modules_use_canonical_et():
    """Spot-check COH-SA-2 production redirects."""
    from app.domain.time_et import ET as canonical, now_et

    import polling_adapter
    import live_decision_bundle
    import v2_decision.a2_session_calendar as asc

    assert polling_adapter.ET is canonical
    assert live_decision_bundle._ET is canonical
    assert asc.ET is canonical

    from event_risk import session_date_et

    assert session_date_et(now_et()) == now_et().date()
