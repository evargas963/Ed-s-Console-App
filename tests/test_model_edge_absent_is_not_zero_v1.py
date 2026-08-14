"""RC-285 — a model that was never scored has not scored zero.

``_model_status_from_artifact`` published ``{"status": "LIVE", "edge": 0}``
when metadata omitted the edge metric. Literal ``"edge": 0`` on the
NOT TRAINED / BINARY MISSING / NON-COMPLIANT / ERROR branches made
measured-zero and unmeasured the same type.

``static/index.html`` still renders only ``m.model`` and ``m.status``.
The field is kept and made optional rather than deleted.
"""

from __future__ import annotations

import json
from pathlib import Path

from verify_active_models import model_health_edge_from_meta

REPO = Path(__file__).resolve().parent.parent


def test_no_write_site_fabricates_a_zero_edge():
    src = (REPO / "server.py").read_text(encoding="utf-8")
    assert '"edge": 0' not in src


def test_the_metadata_read_has_no_zero_default():
    src = (REPO / "server.py").read_text(encoding="utf-8")
    assert '_m.get(edge_key, _m.get("val_accuracy", 0))' not in src
    assert "float(raw or 0)" not in src
    assert "model_health_edge_from_meta" in src


def test_absent_metric_reads_as_none_not_zero():
    assert model_health_edge_from_meta({"model_version": "v9"}, "edge_pp") is None


def test_a_real_metric_is_still_reported():
    assert model_health_edge_from_meta({"edge_pp": 3.5}, "edge_pp") == 3.5


def test_a_genuine_zero_edge_survives():
    assert model_health_edge_from_meta({"edge_pp": 0.0}, "edge_pp") == 0.0


def test_val_accuracy_is_still_scaled_to_percent():
    assert model_health_edge_from_meta({"val_accuracy": 0.62}, "val_accuracy") == 62.0


def test_the_field_still_has_no_consumer_and_that_is_recorded():
    ui = (REPO / "static" / "index.html").read_text(encoding="utf-8")
    i = ui.find("d.model_health")
    assert i > 0
    block = ui[i : i + 1400]
    assert "m.status" in block
    if "m.edge" in block:
        raise AssertionError(
            "a surface now renders m.edge — confirm None renders as unmeasured "
            "and update this test deliberately."
        )
