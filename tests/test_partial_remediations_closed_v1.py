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

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


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
