"""FIND-CAL-TS-RDERIVE — et_clock_from_ts_utc authority and training RTH filter."""

from __future__ import annotations

from datetime import datetime, timezone


from time_et import (
    et_clock_from_ts_utc,
)


def test_et_clock_from_ts_utc_dst_summer_vs_winter():
    winter = datetime(2026, 1, 15, 15, 0, tzinfo=timezone.utc)  # 10:00 ET
    summer = datetime(2026, 7, 15, 14, 0, tzinfo=timezone.utc)  # 10:00 ET
    hw, mw, _ = et_clock_from_ts_utc(winter.timestamp())
    hs, ms, _ = et_clock_from_ts_utc(summer.timestamp())
    assert (hw, mw) == (10, 0)
    assert (hs, ms) == (10, 0)


















def test_ml_train_load_data_where_has_no_rth_where_clause():
    import inspect

    from ml_train import load_data

    src = inspect.getsource(load_data)
    assert "rth_where_clause()" not in src


_SKIP_PY_TREE_DIRS = frozenset(
    {".claude", ".git", ".venv", "venv", "node_modules", "__pycache__"}
)


def test_no_rth_where_clause_callers_repo_wide(repo_index):
    """Regression: rth_where_clause() must not appear outside ml_data_common
    (definition). TEST_SYSTEM_REHAB_V2: sources from the shared `repo_index` corpus
    instead of an independent root.rglob("*.py")."""
    offenders: list[str] = []
    for rel, src, _tree in repo_index.items():
        if rel.parts and rel.parts[0] == "tests":
            continue
        if rel.name == "ml_data_common.py":
            continue
        if any(part in _SKIP_PY_TREE_DIRS for part in rel.parts):
            continue
        if "rth_where_clause()" in src:
            offenders.append(str(rel).replace("\\", "/"))
    assert not offenders, f"rth_where_clause() callers: {offenders}"


