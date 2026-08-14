"""RC-285 — a model that was never scored has not scored zero.

``_model_status_from_artifact`` published ``{"status": "LIVE", "edge": 0}``
when metadata omitted the edge metric. Literal ``"edge": 0`` on the
NOT TRAINED / BINARY MISSING / NON-COMPLIANT / ERROR branches made
measured-zero and unmeasured the same type.

Unmeasured edge is ``None``, never ``val_accuracy * 100`` mislabeled as edge.
The model-health row renders ``edge === null`` as ``—``.
"""

from __future__ import annotations

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


def test_absent_edge_pp_is_none_even_when_val_accuracy_is_present():
    """RC-285 bedrock: accuracy is not an edge. No fallback when edge_key is absent."""
    assert model_health_edge_from_meta({"val_accuracy": 0.55}, "edge_pp") is None


def test_model_health_edge_null_renders_em_dash():
    """DOM contract: formatModelHealthEdge(null) is — , not 0 / NaN / throw."""
    import re
    import subprocess

    ui = (REPO / "static" / "index.html").read_text(encoding="utf-8")
    i = ui.find("d.model_health")
    assert i > 0
    block = ui[i : i + 1800]
    assert "m.edge" in block
    assert "formatModelHealthEdge" in block
    match = re.search(
        r"function formatModelHealthEdge\(edge\) \{.*?\n  \}",
        ui,
        flags=re.S,
    )
    assert match, "formatModelHealthEdge must be extractable from index.html"
    fn = match.group(0)
    script = (
        fn
        + "\n"
        + "const fail = (m) => { console.error(m); process.exit(1); };\n"
        + "if (formatModelHealthEdge(null) !== '—') fail('null');\n"
        + "if (formatModelHealthEdge(undefined) !== '—') fail('undefined');\n"
        + "if (formatModelHealthEdge(Number.NaN) !== '—') fail('NaN');\n"
        + "if (formatModelHealthEdge(0) !== '0') fail('genuine zero');\n"
        + "if (formatModelHealthEdge(3.5) !== '3.5') fail('value');\n"
        + "console.log('ok');\n"
    )
    proc = subprocess.run(
        ["node", "-e", script],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    assert "ok" in proc.stdout
