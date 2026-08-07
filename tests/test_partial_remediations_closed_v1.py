"""RC-291 — two of my remediations fixed the line and left the behaviour.

Cursor graded both PARTIAL rather than closed, and both times I had repaired the
expression the finding quoted instead of the QUANTITY the finding was about.

  L1 latency   RC-281 stopped an absent l1_pipeline_ms entering l1_build_ms_sum (the
               NUMERATOR) and left l1_build_total incrementing as the DENOMINATOR.
               Cursor: 19 builds at 26 ms plus one unmeasured published
               {'19_measured_avg': 26.0, 'published_avg': 24.7,
                'latency_status': 'healthy', 'warn_threshold': 25.0}
               — a real 26 ms average reported under the warn line.

  model edge   RC-285 removed the `, 0` default and then fell back to val_accuracy.
               Cursor: metadata with val_accuracy=0.55 and no edge_pp published
               {'status': 'LIVE', 'edge': 55.0}. Accuracy is not edge over a baseline,
               and static/index.html counts every LIVE model toward "N approved".

Excluding a value from a mean while counting it in the divisor is the fabricated zero
written a different way. Substituting a different metric is worse than reporting none,
because none is legible and a wrong number is not.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


# ────────────────────────────── L1: the mean divides by what it measured ────

def _assessment(build_total: int, ms_sum: float) -> dict:
    from planes.l1_operational import build_l1_operational_assessment as B

    kw = {p: 0 for p in inspect.signature(B).parameters}
    kw["reasons"] = {}
    kw["uptime_sec"] = 600.0
    kw["l1_build_total"] = build_total
    kw["l1_build_ms_sum"] = ms_sum
    return B(**kw)


def _avg(payload: dict) -> float:
    import json
    import re

    m = re.search(r'"avg_build_ms":\s*([0-9.]+)', json.dumps(payload))
    assert m, "avg_build_ms is no longer published; re-derive this test"
    return float(m.group(1))


def test_an_unmeasured_build_does_not_dilute_the_latency_average():
    """Cursor's probe, asserted to the opposite result."""
    measured = _avg(_assessment(build_total=19, ms_sum=19 * 26.0))
    diluted = _avg(_assessment(build_total=20, ms_sum=19 * 26.0))
    assert measured == 26.0, f"the measured average moved: {measured}"
    assert diluted < measured, "premise changed — the old denominator no longer dilutes"
    assert measured > 25.0 >= diluted, (
        "the whole point: 26.0 must cross the 25 ms warn line that 24.7 sits under")


def test_the_average_divides_by_the_measured_count_not_the_build_count():
    src = (REPO / "server.py").read_text(encoding="utf-8", errors="replace")
    assert 'l1_build_ms_measured' in src, "the measured-timing counter is gone"
    assert 'avg_ms = float(_l1_instrumentation["l1_build_ms_sum"]) / max(1, bt_measured)' in src
    assert 'avg_ms = float(_l1_instrumentation["l1_build_ms_sum"]) / max(1, bt)' not in src, (
        "the average divides by all builds again — an unmeasured build dilutes it")


def test_the_counter_only_advances_when_a_timing_is_credited():
    """Numerator and denominator must move together or the mean is wrong either way."""
    src = (REPO / "server.py").read_text(encoding="utf-8", errors="replace")
    i = src.find('_l1_instrumentation["l1_build_ms_sum"] = float(')
    assert i > 0
    window = src[i:i + 260]
    assert '_l1_instrumentation["l1_build_ms_measured"] += 1' in window, (
        "the measured counter no longer increments beside the sum")


def test_total_builds_is_still_counted_separately():
    """Builds-per-minute is a different and correct question; it must not lose its count."""
    src = (REPO / "server.py").read_text(encoding="utf-8", errors="replace")
    assert '_l1_instrumentation["l1_build_total"] += 1' in src


# ─────────────────────────── model edge: no substituted metric ────

def _edge(meta: dict, edge_key: str):
    """The reader as server.py now performs it."""
    from numeric_contract import float_finite_or_none as fin

    raw = fin(meta.get(edge_key))
    return None if raw is None else (raw * 100 if edge_key == "val_accuracy" else raw)


def test_missing_edge_is_not_replaced_by_accuracy():
    """Cursor's probe: val_accuracy=0.55 with no edge_pp published edge 55.0."""
    assert _edge({"val_accuracy": 0.55}, "edge_pp") is None, (
        "accuracy is being reported as edge over a baseline again")


def test_a_real_edge_is_still_reported():
    assert _edge({"edge_pp": 3.5}, "edge_pp") == 3.5


def test_val_accuracy_is_still_scaled_when_it_IS_the_requested_metric():
    """Removing the fallback must not break the models whose metric genuinely is accuracy."""
    assert _edge({"val_accuracy": 0.62}, "val_accuracy") == 62.0


def test_the_fallback_is_gone_from_the_source():
    src = (REPO / "server.py").read_text(encoding="utf-8", errors="replace")
    assert 'raw = _fin_edge(_m.get("val_accuracy"))' not in src, (
        "the val_accuracy fallback is back; a coin-flip model will read as 55 points of edge")
    assert '_m.get(edge_key, _m.get("val_accuracy", 0))' not in src
