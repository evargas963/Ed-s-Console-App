"""tools/check_no_grep_subprocess.py had zero pytest coverage and its CI invocation
(.github/workflows/hardening.yml, no file arguments) hit `if not paths: return 0` --
a "BLOCKING" gate that structurally could never fail. Fixed at the root: no arguments
now means "scan the real tracked-file population" (tools/anti_pattern_sweep.py::
iter_py_files, the git-index authority). These tests prove the fix, not just the
isolated AST visitor."""
from __future__ import annotations

from pathlib import Path

from tools.check_no_grep_subprocess import check_file, main


def _write(tmp_path: Path, src: str) -> Path:
    p = tmp_path / "probe.py"
    p.write_text(src, encoding="utf-8")
    return p


def test_negative_control_banned_grep_via_subprocess_run_is_blocked(tmp_path):
    p = _write(tmp_path, 'import subprocess\nsubprocess.run(["grep", "-n", "x", "y.py"])\n')
    assert check_file(p), "a real grep-via-subprocess call must be detected"
    assert main([str(p)]) == 1


def test_negative_control_banned_rg_via_subprocess_run_is_blocked(tmp_path):
    p = _write(tmp_path, 'import subprocess\nsubprocess.run(["rg", "-n", "x"])\n')
    assert check_file(p)
    assert main([str(p)]) == 1


def test_positive_control_ordinary_subprocess_call_passes(tmp_path):
    p = _write(tmp_path, 'import subprocess\nsubprocess.run(["git", "status"])\n')
    assert check_file(p) == []
    assert main([str(p)]) == 0


def test_positive_control_file_with_no_subprocess_calls_passes(tmp_path):
    p = _write(tmp_path, 'def f():\n    return 1\n')
    assert check_file(p) == []
    assert main([str(p)]) == 0


def test_no_arguments_scans_the_real_tracked_population_not_nothing():
    """THE actual defect: main() with argv=[] used to return 0 unconditionally
    (`if not paths: return 0`) without looking at a single file -- the exact shape
    .github/workflows/hardening.yml invokes it with. Prove it now derives a real,
    non-empty population instead of silently skipping the scan."""
    from tools.anti_pattern_sweep import iter_py_files

    population = iter_py_files(production_only=False)
    assert len(population) > 500, (
        f"canonical tracked-file population collapsed to {len(population)} -- "
        "the no-argument CI invocation would scan almost nothing")
    # The real invocation must actually run to completion over that population and
    # return a real verdict (0 on this clean tree), not skip the work.
    assert main([]) == 0


def test_ci_invocation_shape_reintroducing_the_bypass_would_fail_this_test(tmp_path, monkeypatch):
    """NEGATIVE CONTROL on the CI-invocation defect itself: if a future edit
    reintroduces `if not paths: return 0` (or any equivalent early-exit before the
    population is derived), this test must fail. Point the canonical population at a
    tmp_path containing one real violation and confirm the no-argument path still
    finds it -- proves the fallback isn't a second, narrower scan that happens to
    miss real violations."""
    bad = _write(tmp_path, 'import subprocess\nsubprocess.run(["grep", "x"])\n')
    monkeypatch.setattr(
        "tools.anti_pattern_sweep.iter_py_files", lambda **_: [bad])
    assert main([]) == 1, "the no-argument path must scan whatever the canonical population is and fail on a real violation in it"
