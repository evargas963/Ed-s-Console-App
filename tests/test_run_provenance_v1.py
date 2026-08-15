"""Seams for run provenance stamping."""
from tools.run_provenance import build_run_provenance, stamp_report


def test_build_run_provenance_shape():
    p = build_run_provenance()
    assert set(p) >= {"git_commit", "git_dirty", "python_version", "timestamp_utc"}
    assert isinstance(p["git_dirty"], (bool, type(None)))
    assert "T" in p["timestamp_utc"]


def test_stamp_report_injects_block():
    out = stamp_report({"ok": True})
    assert out["ok"] is True
    assert "run_provenance" in out
    assert out["run_provenance"]["python_version"]
