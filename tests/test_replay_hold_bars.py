"""COH-I-K replay max-hold bars single authority (replay_hold_bars.py)."""

from __future__ import annotations

import re

from replay_hold_bars import (
    replay_max_hold_bars_from_context,
)
from time_et import RTH_SESSION_MINUTES

_SKIP_PY_TREE_DIRS = frozenset(
    {".claude", ".git", ".venv", "venv", "node_modules", "__pycache__"}
)
_REPLAY_HOLD_DEF = re.compile(r"""def\s+replay_max_hold_bars_""")


#: TEST_SYSTEM_REHAB_V2: was an independent root.rglob("*.py") + per-file read_text --
#: now sources from the shared tests/conftest.py `repo_index` corpus. Filter semantics
#: unchanged (skip tests/ and the same build-tool dirs).
def _iter_production_py(repo_index):
    for rel, text, _tree in repo_index.items():
        if rel.parts and rel.parts[0] == "tests":
            continue
        if any(part in _SKIP_PY_TREE_DIRS for part in rel.parts):
            continue
        yield rel, text


def test_replay_max_hold_bars_from_context_requires_explicit_value():
    assert replay_max_hold_bars_from_context({}) is None
    assert replay_max_hold_bars_from_context({"replay_max_hold_bars": None}) is None
    assert replay_max_hold_bars_from_context({"replay_max_hold_bars": 0}) is None
    assert replay_max_hold_bars_from_context({"replay_max_hold_bars": "bad"}) is None


def test_replay_max_hold_bars_from_context_accepts_valid_and_caps():
    assert replay_max_hold_bars_from_context({"replay_max_hold_bars": 15}) == 15
    assert replay_max_hold_bars_from_context({"replay_max_hold_bars": 500}) == RTH_SESSION_MINUTES








def test_no_replay_max_hold_bars_defs_outside_authority_module(repo_index):
    offenders: list[str] = []
    for rel, src in _iter_production_py(repo_index):
        if rel.name == "replay_hold_bars.py":
            continue
        if _REPLAY_HOLD_DEF.search(src):
            offenders.append(str(rel).replace("\\", "/"))
    assert not offenders, offenders
