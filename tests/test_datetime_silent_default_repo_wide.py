"""Fail-closed: production code must not use .get('datetime', 0) silent synthesis."""

from __future__ import annotations

import re

_DATETIME_DEFAULT_ZERO = re.compile(r"""\.get\(\s*["']datetime["']\s*,\s*0\s*\)""")

_SKIP_DIR_PARTS = frozenset(
    {
        ".git",
        ".claude",
        "__pycache__",
        ".venv",
        "venv",
        "node_modules",
        ".pytest_cache",
        "backups",
        "governance",
        "tests",
        "tools",
        "calibration",
        "verification",
        "arch_competition",
    }
)

# Explicit allowlist only if a documented exception is required (empty by default).
_DATETIME_DEFAULT_ZERO_ALLOWLIST: frozenset[str] = frozenset()


def test_no_datetime_default_zero_in_production_py(repo_index):
    """TEST_SYSTEM_REHAB_V2: was an independent ROOT.rglob("*.py") + per-file
    read_text -- now sources from the shared `repo_index` corpus. Filter semantics
    unchanged (same _SKIP_DIR_PARTS, incl. the deliberate calibration/verification/
    arch_competition exclusions)."""
    hits: list[str] = []
    for rel, text, _tree in repo_index.items():
        if any(part in _SKIP_DIR_PARTS for part in rel.parts):
            continue
        rel_posix = rel.as_posix()
        if rel_posix in _DATETIME_DEFAULT_ZERO_ALLOWLIST:
            continue
        for i, line in enumerate(text.splitlines(), start=1):
            if _DATETIME_DEFAULT_ZERO.search(line):
                hits.append(f"{rel_posix}:{i}:{line.strip()}")
    assert hits == [], f".get('datetime', 0) remains in production code: {hits}"




