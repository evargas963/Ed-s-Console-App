"""RC-256: the cold-start harness must refuse to measure a busy host, and must separate stages.

Why these exist. Every startup number this repo has argued about was taken while the live
console competed for CPU and disk — where ten runs of one identical command spanned
6.01-18.64s, wider than the effect being claimed. A harness that measures anyway, and reports
a tidy median, launders that noise into a decision. So the refusal is the load-bearing feature,
not a nicety.

These tests do NOT boot the server: that is the operator's quiet-host run. They lock the
harness's contract.
"""
from __future__ import annotations

import socket
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.measure_cold_start as M  # noqa: E402


def test_refuses_to_measure_when_something_is_already_listening() -> None:
    """The whole point: a busy host produces numbers that cannot rank anything."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind((M.HOST, 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    try:
        assert M.main(["--port", str(port), "-n", "1"]) == 2, (
            "harness measured a busy host — that is how the 6.61s/10.5s disagreement happened"
        )
    finally:
        srv.close()


def test_the_refusal_is_overridable_but_explicit() -> None:
    """An escape must exist for deliberate use, and must be impossible to hit by accident."""
    import inspect

    src = inspect.getsource(M.main)
    assert "--allow-busy-host" in inspect.getsource(M)
    assert "allow_busy_host" in src, "no explicit override; a hard block invites editing the tool"


def test_free_port_detection_is_honest_in_both_directions() -> None:
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind((M.HOST, 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    try:
        assert M._port_is_free(port) is False
    finally:
        srv.close()
    # A closed port must read free, or the harness would refuse to ever run.
    assert M._port_is_free(port) is True


def test_host_is_loopback_ip_not_localhost() -> None:
    """Repo law: probe 127.0.0.1, never 'localhost' — ::1 resolution burns ~2s per probe and
    would be silently added to every stage this tool measures."""
    assert M.HOST == "127.0.0.1"


def test_stages_are_reported_separately_including_post_bind() -> None:
    """import / bind / health / post_bind must be distinct. Timing them as one lump is the
    reason nobody can say which of the operator's two waits dominates."""
    import inspect

    src = inspect.getsource(M.main)
    for stage in ("baseline", "import", "bind", "health", "post_bind"):
        assert f'"{stage}"' in src, f"stage {stage} is not reported separately"


def test_spread_reports_min_median_max_not_a_bare_scalar() -> None:
    """A scalar hides the thing that invalidated every previous measurement."""
    s = M._spread([1.0, 5.0, 3.0])
    assert s == {"n": 3, "min": 1.0, "median": 3.0, "max": 5.0, "spread": 4.0}
    assert M._spread([])["n"] == 0


def test_spread_ignores_failed_runs_rather_than_scoring_them_as_zero() -> None:
    s = M._spread([2.0, None, 4.0])  # type: ignore[list-item]
    assert s["n"] == 2 and s["min"] == 2.0 and s["max"] == 4.0


def test_stage_timeout_is_bounded() -> None:
    """A harness that waits forever on a broken boot reads exactly like one still measuring."""
    assert 0 < M.STAGE_TIMEOUT_S <= 600


def test_harness_does_not_touch_the_default_console_port() -> None:
    """It must never bind 8000 by default — that is the operator's console."""
    assert M.DEFAULT_PORT != 8000


@pytest.mark.parametrize("stage", ["_time_baseline", "_time_import", "_time_bind_and_health"])
def test_each_stage_has_its_own_timer(stage: str) -> None:
    assert callable(getattr(M, stage))
