"""RC-293 — one input served two questions, and fixing one answer broke the other.

CURSOR v3. `planes/l1_operational.py` used `l1_build_total` TWICE:

    avg_ms         = l1_build_ms_sum / max(1, l1_build_total)     # latency
    builds_per_min = (l1_build_total / uptime_sec) * 60           # RATE

RC-291 fixed the latency average by passing the TIMED count as `l1_build_total`, which
silently fed the rate calculation a timed-build count. Cursor's probe: a true 500
builds/min reported as 100 and dropped a severity level.

WHY MY EIGHT RC-291 TESTS ALL PASSED: not one of them asserted the build rate. I wrote
tests from the FINDING — Cursor handed me a wrong average, I asserted the average — and a
suite shaped by a bug report inherits that report's blind spots. These tests assert the
OTHER consumer in each case, which is the discipline that was missing.

SECOND HALF, same root. RC-291 made `edge` an honest None and left `status="LIVE"`
unconditional, while static/index.html counts every LIVE model toward "N approved". So a
model nobody scored was still approved — which was the substance of the finding, not the
field's type. I fixed the value and not the verdict that reads it.
"""

from __future__ import annotations

import inspect
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


def _assess(total: int, timed: int | None, ms_sum: float, uptime: float = 60.0) -> str:
    from planes.l1_operational import build_l1_operational_assessment as B

    kw = {p: 0 for p in inspect.signature(B).parameters}
    kw["reasons"] = {}
    kw["uptime_sec"] = uptime
    kw["l1_build_total"] = total
    kw["timing_sample_count"] = timed
    kw["l1_build_ms_sum"] = ms_sum
    return json.dumps(B(**kw))


def _num(payload: str, key: str) -> float:
    m = re.search(rf'"{key}":\s*([0-9.]+)', payload)
    assert m, f"{key} is no longer published; re-derive this test"
    return float(m.group(1))


def test_the_build_rate_counts_every_build_not_just_the_timed_ones():
    """Cursor's probe, asserted to the opposite result."""
    p = _assess(total=500, timed=100, ms_sum=100 * 26.0)
    assert _num(p, "builds_per_minute") == 500.0, (
        "the rate alarm is reading timed builds again — a true 500/min under-reports")


def test_the_latency_average_still_divides_by_timed_builds():
    """The RC-291 fix must survive: the two answers are now independent."""
    p = _assess(total=500, timed=100, ms_sum=100 * 26.0)
    assert _num(p, "avg_build_ms") == 26.0


def test_fixing_the_average_no_longer_suppresses_the_rate_alarm():
    """The regression, stated as the property that failed.

    Passing the timed count as the total gave a correct average AND a wrong rate, and the
    severity dropped a level. Both must now be right at once.
    """
    fixed = _assess(total=500, timed=100, ms_sum=100 * 26.0)
    broken = _assess(total=100, timed=None, ms_sum=100 * 26.0)   # the RC-291 shape
    assert _num(fixed, "avg_build_ms") == _num(broken, "avg_build_ms") == 26.0
    assert _num(fixed, "builds_per_minute") > _num(broken, "builds_per_minute")
    order = {"healthy": 0, "unknown": 1, "warning": 2, "critical": 3}
    sev = lambda s: order.get(  # noqa: E731
        (re.search(r'"build_load":\s*\{"status":\s*"([a-z]+)"', s) or ["", "unknown"])[1], 1)
    assert sev(fixed) > sev(broken), (
        "the corrected rate must escalate the severity the diluted one suppressed")


def test_omitting_the_new_parameter_preserves_old_behaviour():
    """A default that changes existing callers silently is its own defect."""
    assert _num(_assess(total=100, timed=None, ms_sum=100 * 26.0), "avg_build_ms") == 26.0


def test_the_two_quantities_no_longer_share_one_input():
    src = (REPO / "planes" / "l1_operational.py").read_text(encoding="utf-8", errors="replace")
    assert "timing_sample_count" in src
    assert "avg_ms = float(l1_build_ms_sum) / max(1, l1_build_total)" not in src, (
        "the average divides by the build total again")
    assert "builds_per_min = (l1_build_total / max(uptime_sec, 1e-6)) * 60.0" in src, (
        "the RATE stopped counting every build")


def test_the_caller_passes_both_counts():
    src = (REPO / "server.py").read_text(encoding="utf-8", errors="replace")
    assert "l1_build_total=bt," in src, "the true build count is no longer sent"
    assert "timing_sample_count=bt_measured," in src, "the timed count is no longer sent"


# ──────────────────────────── a model nobody scored is not approved ────

def test_a_compliant_model_with_no_edge_is_not_reported_live():
    """RC-291 fixed the value and left the verdict that reads it."""
    src = (REPO / "server.py").read_text(encoding="utf-8", errors="replace")
    i = src.find('"status_reason": "Binary + metadata + provenance compliant, but no edge')
    assert i > 0, "the UNSCORED branch is gone — a model with no edge reads LIVE again"
    assert '"status": "UNSCORED"' in src[max(0, i - 400):i + 200]


def test_the_unscored_branch_is_reached_only_when_edge_is_absent():
    src = (REPO / "server.py").read_text(encoding="utf-8", errors="replace")
    i = src.find('"status": "UNSCORED"')
    assert i > 0
    assert "if edge is None:" in src[max(0, i - 500):i], (
        "UNSCORED is not gated on the edge being absent")


def test_a_scored_model_is_still_live():
    """Negative control: the honest verdict must not condemn real models."""
    src = (REPO / "server.py").read_text(encoding="utf-8", errors="replace")
    assert '"status": "LIVE", "status_reason": "Binary + metadata + provenance compliant"' in src
