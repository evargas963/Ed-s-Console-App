"""Tests for PERF2-1 shared in-process ablation static-lock index."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
TOOLS = REPO / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import ablation_integrity as fe  # noqa: E402
from tools.ablation_static_lock_index import (  # noqa: E402
    AblationStaticLockIndex,
    get_ablation_static_lock_index,
    get_ablation_static_lock_index_build_count,
)


@pytest.fixture
def _reset_index(fresh_ablation_static_lock_index):
    """Backward-compatible alias — opt-in reset only (no autouse per Phase 3K)."""
    yield


def test_shared_index_built_once_per_process():
    first = get_ablation_static_lock_index()
    second = get_ablation_static_lock_index()
    assert first is second
    assert get_ablation_static_lock_index_build_count() == 1
    assert first.build_count == 1


def test_both_ablation_checks_use_same_index_object():
    idx_before = get_ablation_static_lock_index()
    fe.check_ablation_seven_model_four_horizon_grid()
    idx_mid = get_ablation_static_lock_index()
    fe.check_ablation_equal_layer_consumers()
    idx_after = get_ablation_static_lock_index()
    assert idx_before is idx_mid is idx_after
    assert get_ablation_static_lock_index_build_count() == 1


def test_check_results_match_direct_index_materialization():
    idx = get_ablation_static_lock_index()
    grid_errors = fe.check_ablation_seven_model_four_horizon_grid()
    layer_errors = fe.check_ablation_equal_layer_consumers()
    assert get_ablation_static_lock_index_build_count() == 1
    assert isinstance(grid_errors, list)
    assert isinstance(layer_errors, list)
    if idx.manifest is not None:
        assert isinstance(idx.specs, list)
        assert len(idx.specs) > 0 or idx.spec_build_error is not None


def test_index_does_not_persist_across_processes():
    repo = str(REPO).replace("\\", "\\\\")
    script = f"""
import sys
from pathlib import Path
repo = Path("{repo}")
sys.path.insert(0, str(repo))
from tools.ablation_static_lock_index import (
    get_ablation_static_lock_index,
    get_ablation_static_lock_index_build_count,
    reset_ablation_static_lock_index_for_tests,
)
reset_ablation_static_lock_index_for_tests()
get_ablation_static_lock_index()
print(get_ablation_static_lock_index_build_count())
"""
    proc = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "1"


def test_failure_in_one_check_does_not_hide_failure_in_the_other(monkeypatch, fresh_ablation_static_lock_index):
    bad = AblationStaticLockIndex(
        manifest_path=REPO / "governance" / "artifacts" / "feature_ablation_manifest_leaf.json",
        db_path=None,
        gate_import_error=None,
        manifest=None,
        manifest_load_error="synthetic manifest failure for test",
        enriched=None,
        specs=[],
        spec_build_error=None,
        runnable_target=0,
        build_count=1,
    )

    def fake_build(**kwargs):
        return bad

    monkeypatch.setattr("tools.ablation_static_lock_index._build_index", fake_build)

    grid_errors = fe.check_ablation_seven_model_four_horizon_grid()
    layer_errors = fe.check_ablation_equal_layer_consumers()
    assert any("manifest unreadable" in e for e in grid_errors)
    assert any("manifest/spec build failed" in e for e in layer_errors)


def test_expensive_materialization_not_repeated_between_checks():
    fe.check_ablation_seven_model_four_horizon_grid()
    builds_after_first = get_ablation_static_lock_index_build_count()
    assert builds_after_first == 1
    fe.check_ablation_equal_layer_consumers()
    assert get_ablation_static_lock_index_build_count() == 1
