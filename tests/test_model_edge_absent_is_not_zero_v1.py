"""RC-285 — a model that was never scored has not scored zero.

CURSOR'S [P2]. `server.py` returned `{"status": "LIVE", ..., "edge": 0}` for a
provenance-compliant model whose metadata omits the edge metric:

    raw  = _m.get(edge_key, _m.get("val_accuracy", 0))
    edge = ... float(raw or 0)

I had annotated that line `# silent-zero-ok: RC-276 residual, dashboard-only, edge=0 is
this endpoint's existing missing convention`. Cursor's verdict on that defence: an existing
convention DOCUMENTS the defect, it does not justify it. Correct — and the "convention" was
four more literal `"edge": 0` writes in the same endpoint, so the field carried "measured
zero" and "no measurement" in one type with nothing to separate them.

THE SECOND FINDING, from tracing the consumer instead of the producer:
`static/index.html:8840-8848` filters `d.model_health` and renders only `m.model` and
`m.status`. NOTHING in this repository reads `edge`. An unread field cannot be wrong in a
way anyone notices, so its type drifts to whatever is convenient at each write site — which
is what happened, and it leaves a trap primed for the first reader who arrives. The field
is kept and made correct rather than deleted: `status_reason` already reaches the operator
through the tooltip and an edge figure is its natural companion, so deleting a correct
field stays cheap later while un-deleting a wrong one after a reader appears does not.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


def test_no_write_site_fabricates_a_zero_edge():
    """All five placeholder writes plus the computed one must agree on absence."""
    src = (REPO / "server.py").read_text(encoding="utf-8", errors="replace")
    assert '"edge": 0' not in src, (
        "a branch writes a literal zero edge again — 'measured zero' and 'not measured' "
        "become the same value the moment it leaves the function")


def test_the_metadata_read_has_no_zero_default():
    """`.get(key, 0)` is the same fabrication one layer earlier."""
    src = (REPO / "server.py").read_text(encoding="utf-8", errors="replace")
    assert '_m.get(edge_key, _m.get("val_accuracy", 0))' not in src, (
        "the zero default is back in the metadata read")
    assert 'float(raw or 0)' not in src


def test_the_retired_justification_is_not_reinstated():
    """The specific defence Cursor overturned must not return as a live exemption."""
    src = (REPO / "server.py").read_text(encoding="utf-8", errors="replace")
    live = [ln.strip() for ln in src.splitlines()
            if "silent-zero-ok:" in ln and "existing missing convention" in ln]
    assert not live, f"the overturned exemption is active again: {live}"


def _meta(tmp_path: Path, payload: dict) -> Path:
    p = tmp_path / "m_meta.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def test_absent_metric_reads_as_none_not_zero(tmp_path, monkeypatch):
    """The defect, driven through the real reader."""
    from numeric_contract import float_finite_or_none

    meta = json.loads(_meta(tmp_path, {"model_version": "v9"}).read_text(encoding="utf-8"))
    raw = float_finite_or_none(meta.get("edge_pp"))
    if raw is None:
        raw = float_finite_or_none(meta.get("val_accuracy"))
        edge = None if raw is None else raw * 100
    else:
        edge = raw
    assert edge is None, "a model with no recorded edge reports a measured zero"


def test_a_real_metric_is_still_reported(tmp_path):
    """Negative control: absence handling must not blank out real measurements."""
    from numeric_contract import float_finite_or_none

    meta = json.loads(_meta(tmp_path, {"edge_pp": 3.5}).read_text(encoding="utf-8"))
    assert float_finite_or_none(meta.get("edge_pp")) == 3.5


def test_a_genuine_zero_edge_survives(tmp_path):
    """A model MEASURED at zero edge is a real result and must not be erased as absence."""
    from numeric_contract import float_finite_or_none

    meta = json.loads(_meta(tmp_path, {"edge_pp": 0.0}).read_text(encoding="utf-8"))
    assert float_finite_or_none(meta.get("edge_pp")) == 0.0, (
        "a measured zero was swallowed with the fabricated ones — float_finite_or_none "
        "accepts zero, float_positive_or_none would not, and this site needs the former")


def test_val_accuracy_is_never_published_as_edge(tmp_path):
    """RC-364/RC-291 port: accuracy is not edge. A meta with only val_accuracy has NO
    edge (None → UNSCORED); val_accuracy is stamped under its own name, unscaled."""
    from numeric_contract import float_finite_or_none

    meta = json.loads(_meta(tmp_path, {"val_accuracy": 0.62}).read_text(encoding="utf-8"))
    edge = float_finite_or_none(meta.get("edge_pp"))
    assert edge is None, "val_accuracy must not fill the edge slot"
    val_accuracy = float_finite_or_none(meta.get("val_accuracy"))
    assert val_accuracy == 0.62


def test_lstm_requests_edge_pp_not_val_accuracy():
    """RC-364/RC-291 port: the LSTM registration passes edge_key='edge_pp' like every
    other model, and the ×100 accuracy-as-edge translation is gone from the producer."""
    src = (REPO / "server.py").read_text(encoding="utf-8", errors="replace")
    assert '_model_status_from_artifact("lstm", "LSTM", _lstm_meta, "edge_pp"' in src, (
        "LSTM model-health registration no longer requests edge_pp — val_accuracy "
        "masquerading as edge is the RC-291 defect")
    assert 'raw * 100 if edge_key == "val_accuracy"' not in src, (
        "the accuracy-as-edge ×100 translation is back in the producer")


def test_the_field_still_has_no_consumer_and_that_is_recorded():
    """If a surface starts reading `edge`, this test should be the thing that notices.

    It is not a demand that the field stay unread — it is a tripwire so the day a reader
    appears is a deliberate moment rather than a discovery during an audit.
    """
    ui = (REPO / "static" / "index.html").read_text(encoding="utf-8", errors="replace")
    i = ui.find("d.model_health")
    assert i > 0, "the model_health consumer moved; re-derive what it renders"
    block = ui[i:i + 1400]
    assert "m.status" in block
    if "m.edge" in block:
        raise AssertionError(
            "a surface now renders m.edge — RC-285 recorded that nothing did. Confirm the "
            "None case renders as 'not measured' and update this test deliberately.")
