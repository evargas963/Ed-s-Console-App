"""RC-256 — the cold-start harness must measure the three stages SEPARATELY, or it repeats
the mistake that left the question open.

WHY THIS FILE EXISTS. RC-247 timed `import server` alone and the PM's audit timed
launch-to-ready as one number. Neither could rank the operator's two waits ("15-20s
hesitation before logs, then long wait before app"), because a single aggregate cannot say
which stage holds the time. A harness that silently collapses the stages, or that reports a
mean, or that measures `localhost` instead of `127.0.0.1`, would produce a number that looks
like an answer and is not one.

These tests drive the harness's own arithmetic with known inputs. They do not spawn a
server: that is the measurement, and asserting on real timings would make this file a
flake generator that reports the host's load as a defect.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

import measure_cold_start_stages_v1 as M  # noqa: E402


def test_stats_reports_min_median_max_not_a_mean():
    """A mean over a cold start is a number about the outlier (RC-167's lesson, reused).

    The first round pays for a cold filesystem cache; averaging it in describes that round,
    not the startup.
    """
    s = M._stats([1.0, 2.0, 30.0])
    assert s == {"n": 3, "min": 1.0, "median": 2.0, "max": 30.0}
    assert "mean" not in s and "avg" not in s


def test_stats_reads_absence_as_absence():
    """A round that timed out must not be silently counted as a fast one (RC-274)."""
    assert M._stats([]) is None
    assert M._stats([None, None]) is None
    partial = M._stats([None, 2.0, 4.0])
    assert partial is not None and partial["n"] == 2, (
        "a None round was folded into the sample instead of being excluded")


def test_the_three_stages_are_reported_separately():
    """The whole point of the row: one aggregate cannot rank two waits."""
    import inspect

    src = inspect.getsource(M.main)
    for key in ("import_minus_baseline_s", "accept_s", "http200_s", "readiness_tail_s"):
        assert key in src, f"{key} is no longer reported — the stages have been collapsed"


def test_import_timing_is_net_of_interpreter_start():
    """Otherwise ~0.2s of interpreter start-up is charged to `import server` every round."""
    import inspect

    src = inspect.getsource(M.main)
    assert "_baseline_interpreter_s()" in src
    assert "import_minus_baseline_s" in src, (
        "the baseline is measured but never subtracted, so it is decoration")


def test_readiness_tail_comes_from_one_spawn_not_two():
    """(c)-(b) is only meaningful when both are timed inside the SAME launch."""
    import inspect

    src = inspect.getsource(M._spawn_and_time)
    assert src.count("Popen") == 1, "the tail would compare two different launches"
    assert "accept_s" in src and "http_s" in src


def _executable_lines() -> list[str]:
    """Source with comments and the module docstring removed.

    Both must be excluded: the docstring EXPLAINS why localhost is refused and why the
    launcher is untouched, so scanning raw text makes the explanation fail the test that
    the explanation exists for.
    """
    import ast

    src = (REPO / "tools" / "measure_cold_start_stages_v1.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    doc_spans = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)):
            doc_spans.update(range(node.lineno, (node.end_lineno or node.lineno) + 1))
    return [ln for i, ln in enumerate(src.splitlines(), 1)
            if i not in doc_spans and not ln.strip().startswith("#")]


def test_probe_uses_127_0_0_1_and_never_localhost():
    """`localhost` burns ~2.05s on the ::1 attempt, which would land inside the measurement."""
    body = "\n".join(_executable_lines())
    assert "127.0.0.1" in body
    assert "localhost" not in body, (
        "a localhost probe pays the IPv6 fallback and reports it as startup cost")


def test_the_operator_locked_launcher_is_not_touched():
    """start_ed_console.bat output is FROZEN by operator instruction; this harness only reads."""
    body = "\n".join(_executable_lines())
    assert "start_ed_console" not in body, (
        "the harness touches the operator-locked launcher in executable code")


def test_a_dead_process_is_reported_not_counted_as_a_timeout():
    """A server that exits must be distinguishable from one that is merely slow."""
    import inspect

    src = inspect.getsource(M._spawn_and_time)
    assert "proc.poll() is not None" in src and "process exited rc=" in src
