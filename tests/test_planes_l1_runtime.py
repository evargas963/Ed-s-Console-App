"""Unit tests for planes.l1_runtime materiality helpers."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_input_fingerprint_material_spot_move():
    from planes.l1_runtime import build_input_fingerprint, input_fingerprint_materially_changed

    row = {"spot": 100.0, "spread": 0.001, "fast_generation_id": 1.0}
    ent = {"analytics_version": 5}
    fp = build_input_fingerprint(row, ent)
    assert not input_fingerprint_materially_changed(fp, row, ent)
    row2 = dict(row)
    row2["spot"] = 100.05
    assert input_fingerprint_materially_changed(fp, row2, ent)


def test_l2_version_change_is_material():
    from planes.l1_runtime import input_fingerprint_materially_changed

    row = {"spot": 100.0, "spread": 0.001, "fast_generation_id": 1.0}
    fp = {"spot": 100.0, "spread_frac": 0.001, "l2_version": 1, "fast_gen": 1.0}
    ent2 = {"analytics_version": 2}
    assert input_fingerprint_materially_changed(fp, row, ent2)


def test_fast_gen_change_is_material():
    from planes.l1_runtime import input_fingerprint_materially_changed

    row = {"spot": 100.0, "spread": 0.001, "fast_generation_id": 2.0}
    fp = {"spot": 100.0, "spread_frac": 0.001, "l2_version": 1, "fast_gen": 1.0}
    ent = {"analytics_version": 1}
    assert input_fingerprint_materially_changed(fp, row, ent)
