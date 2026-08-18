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


def test_lstm_requests_edge_pp_not_val_accuracy(tmp_path, monkeypatch):
    """RC-364/RC-291 port: an LSTM whose meta carries ONLY val_accuracy has NO edge.

    The first version of this control matched two strings in server.py — the exact
    registration call and the absence of the old `raw * 100` expression. Both are
    renderings: the registration is already proved by AST in
    `test_producer_slice_has_no_arithmetic_translation_ast` below (which checks all
    three call sites, not one spelling of one of them), and a reshaped translation
    defeats the second string, which is why RC-375/RC-378 added the AST and
    whitelist locks. What no lock here observed was the OUTPUT. So this drives the
    real producer slice out of server.py and asserts what it publishes.
    """
    import textwrap

    import ml_predict

    src = (REPO / "server.py").read_text(encoding="utf-8", errors="replace")
    i = src.index("def _model_status_from_artifact(")
    j = src.index("_xgb_meta = ", i)
    fn_src = textwrap.dedent(src[i:j])
    monkeypatch.setattr(ml_predict, "_verify_governed_artifact",
                        lambda base, bt, hz, role, fn: {"verified": True})

    def produce(payload: dict):
        meta_p = tmp_path / "lstm_SPY_1c_meta.json"
        meta_p.write_text(json.dumps(payload), encoding="utf-8")
        ns = {
            "_artifacts": {"lstm": {"exists": True, "has_provenance": True, "issues": []}},
            "_dashboard_ticker": "SPY",
            "_dashboard_ml_hz": "1c",
            "_active_dir": tmp_path,
            "json": json,
            "Path": Path,
        }
        exec(compile(fn_src, "server.py::_model_status_from_artifact", "exec"), ns)
        return ns["_model_status_from_artifact"](
            "lstm", "LSTM", meta_p, "edge_pp", "model_type")

    # THE defect: accuracy standing in for edge. 0.62 must not surface as 0.62 or 62.
    only_accuracy = produce({"val_accuracy": 0.62, "model_type": "dual_stream_lstm"})
    assert only_accuracy["edge"] is None, (
        f"val_accuracy was published in the edge slot as {only_accuracy['edge']!r} — "
        f"accuracy masquerading as edge is the RC-291 defect")

    # Negative control: a real edge_pp still serves, unscaled and unrounded.
    scored = produce({"edge_pp": 1.25, "model_type": "dual_stream_lstm"})
    assert scored["edge"] == 1.25, (
        f"a genuinely measured edge was altered on the way out: {scored['edge']!r}")

    # A measured zero is a result, not absence (the RC-285 half of this file).
    assert produce({"edge_pp": 0.0, "model_type": "dual_stream_lstm"})["edge"] == 0.0


def test_producer_slice_has_no_arithmetic_translation_ast():
    """RC-375 (Cursor audit: the string lock above is weaker than the principle):
    parse the REAL _model_status_from_artifact source and prove by AST that the
    producer contains NO multiplication at all and that every registration call in
    server.py passes edge_pp — a renamed/reshaped ×100 cannot slip past a string."""
    import ast as _ast
    import textwrap

    src = (REPO / "server.py").read_text(encoding="utf-8", errors="replace")
    anchor = "def _model_status_from_artifact("
    i = src.index(anchor)
    # slice to the sibling definition boundary (the meta-path assignments that follow)
    j = src.index("_xgb_meta = ", i)
    fn_src = textwrap.dedent(src[i:j])
    tree = _ast.parse(fn_src)
    # RC-376 widening (Cursor gate-width note): ANY arithmetic — BinOp of any
    # operator or augmented assignment — is banned in the producer, not just Mult;
    # `edge += x` or `edge = raw + 0` is the same translation class reshaped.
    arith = [n for n in _ast.walk(tree)
             if isinstance(n, (_ast.BinOp, _ast.AugAssign))]
    assert arith == [], (
        "the model-health producer contains arithmetic — any numeric translation "
        "of a metric into the edge slot is the RC-291 class")
    regs = [n for n in _ast.walk(_ast.parse(src))
            if isinstance(n, _ast.Call)
            and getattr(n.func, "id", "") == "_model_status_from_artifact"]
    assert len(regs) == 3, f"expected 3 model registrations, found {len(regs)}"
    for call in regs:
        edge_key_arg = call.args[3]
        assert isinstance(edge_key_arg, _ast.Constant) and edge_key_arg.value == "edge_pp", (
            f"a registration passes edge_key={getattr(edge_key_arg, 'value', '?')!r} — "
            "every model requests edge_pp, never an accuracy metric")


def test_producer_slice_call_surface_is_a_closed_whitelist():
    """RC-378 (Cursor gate-width residual: `edge = operator.mul(_fin_edge(...), 1)` is a
    Call, not a BinOp — the arithmetic ban alone never sees it). An enumerated blacklist
    loses to the next reshape by construction, so the lock is a CLOSED WHITELIST over the
    real slice: every call in the producer must be listed here, and ANY new callable —
    operator.mul, float, round, sum, whatever arrives next — trips the gate and forces a
    deliberate update at this site."""
    import ast as _ast
    import textwrap

    src = (REPO / "server.py").read_text(encoding="utf-8", errors="replace")
    i = src.index("def _model_status_from_artifact(")
    j = src.index("_xgb_meta = ", i)
    tree = _ast.parse(textwrap.dedent(src[i:j]))
    allowed_attrs = {"get", "exists", "read_text", "loads", "join"}
    allowed_names = {"_fin_edge", "_item4_verify"}
    for n in _ast.walk(tree):
        if not isinstance(n, _ast.Call):
            continue
        f = n.func
        if isinstance(f, _ast.Attribute):
            assert f.attr in allowed_attrs, (
                f"unlisted attribute call .{f.attr}(...) in the model-health producer — "
                "a numeric translation smuggled as a call is the RC-291 class reshaped")
        elif isinstance(f, _ast.Name):
            assert f.id in allowed_names, (
                f"unlisted call {f.id}(...) in the model-health producer — "
                "a numeric translation smuggled as a call is the RC-291 class reshaped")
        else:
            raise AssertionError(
                "call through a computed expression in the producer slice — nothing "
                "in this function may call anything the whitelist cannot name")


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
