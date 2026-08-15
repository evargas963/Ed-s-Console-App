"""RC-265 — the duplication register must count real duplication, not noise.

WHAT WAS MEASURED (2026-08-06, at the market open). Two identical runs of the
naive value scan, seconds apart, reported 105 findings and then 6. Polling
nineteen endpoints takes seconds; during market hours spot moves between the
first call and the last, so every field derived from it "disagrees" purely
because it was sampled at different instants. A register that reads 105 or 6
for the same repository is noise, and it is noisiest exactly when the operator
is trading.

Separately the module scan reported 401 near-duplicate pairs, because
`quick_ratio()` compares character multisets and is only an UPPER BOUND: two
files score high for both being written in Python.

Both defects inflate the total, and an inflated total is worse than no total —
it makes real progress invisible and trains the reader to discount the number.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

import duplication_audit as DA  # noqa: E402


# ------------------------------------------------------------- shape ------

def test_every_scanner_has_a_plain_english_blurb():
    """A kind nobody can explain is a kind nobody will act on."""
    for kind in DA.SCANNERS:
        assert kind in DA.BLURB and len(DA.BLURB[kind]) > 10, kind


def test_exemptions_carry_a_reason_and_stay_visible():
    """A silent exemption is how a register quietly stops covering things."""
    for ident, reason in DA.ACCEPTED.items():
        assert ident.startswith("D-"), ident
        assert len(reason) > 20, f"{ident} exempted without a real reason"


def test_findings_are_identifiable():
    """Every finding needs a stable id so it can be argued with or deferred."""
    f = DA.Finding("D-FUNC", "D-FUNC:x", "detail", ["a", "b"])
    assert f.ident and f.kind and f.members and not f.accepted


# ------------------------------------------------- empty-file handling ----

def test_empty_files_are_not_duplication(tmp_path, monkeypatch):
    for name in ("a", "b", "c"):
        d = tmp_path / name
        d.mkdir()
        (d / "__init__.py").write_text("", encoding="utf-8")
    monkeypatch.setattr(DA, "REPO", str(tmp_path), raising=True)
    assert DA.scan_files() == []


def test_real_identical_files_are_still_found(tmp_path, monkeypatch):
    for name in ("a", "b"):
        d = tmp_path / name
        d.mkdir()
        (d / "m.py").write_text("def f():\n    return 42\n", encoding="utf-8")
    monkeypatch.setattr(DA, "REPO", str(tmp_path), raising=True)
    found = DA.scan_files()
    assert len(found) == 1 and len(found[0].members) == 2


# ------------------------------------------- the market-hours defect ------

def _faucet_stub(first, second):
    calls = {"n": 0}

    def fake():
        calls["n"] += 1
        return first if calls["n"] == 1 else second
    return fake


def test_negative_control_a_moving_price_is_not_a_disagreement(monkeypatch):
    """Spot ticks 770.10 -> 770.40 while nineteen endpoints are polled.

    Endpoints sampled early report the old price, endpoints sampled late the
    new one. That is one faucet observed at two instants, not two faucets.
    """
    monkeypatch.setattr(DA, "server_up", lambda: True, raising=True)
    first = {"spot": {"/api/a": 770.10, "/api/b": 770.40}}
    second = {"spot": {"/api/a": 770.55, "/api/b": 770.80}}   # drift 0.45 > spread 0.30
    monkeypatch.setattr(DA, "_faucets", _faucet_stub(first, second), raising=True)
    assert DA.scan_values() == [], "a moving price must not be reported"


def test_negative_control_a_structural_disagreement_survives(monkeypatch):
    """A banked spot served beside a live one does not cancel out.

    The endpoints disagree by far more than either moves, and they disagree in
    the same direction on both passes.
    """
    monkeypatch.setattr(DA, "server_up", lambda: True, raising=True)
    first = {"spot": {"/api/live": 770.10, "/api/banked": 775.40}}
    second = {"spot": {"/api/live": 770.12, "/api/banked": 775.42}}
    monkeypatch.setattr(DA, "_faucets", _faucet_stub(first, second), raising=True)
    found = DA.scan_values()
    assert len(found) == 1, "a real 5-point disagreement must survive drift correction"
    assert "spot" in found[0].ident


def test_negative_control_disagreement_that_vanishes_is_dropped(monkeypatch):
    """If the second pass agrees, the first was a sampling artifact."""
    monkeypatch.setattr(DA, "server_up", lambda: True, raising=True)
    first = {"x": {"/api/a": 1.0, "/api/b": 2.0}}
    second = {"x": {"/api/a": 2.0, "/api/b": 2.0}}
    monkeypatch.setattr(DA, "_faucets", _faucet_stub(first, second), raising=True)
    assert DA.scan_values() == []


def test_no_drift_measurement_fails_toward_reporting(monkeypatch):
    """When the second pass cannot measure the field, report rather than excuse."""
    monkeypatch.setattr(DA, "server_up", lambda: True, raising=True)
    first = {"x": {"/api/a": 1.0, "/api/b": 9.0}}
    monkeypatch.setattr(DA, "_faucets", _faucet_stub(first, {}), raising=True)
    assert len(DA.scan_values()) == 1, "unmeasurable drift must not silence a finding"


def test_server_down_reports_nothing_rather_than_zero_duplication(monkeypatch):
    """Absence of data is not absence of duplication."""
    monkeypatch.setattr(DA, "server_up", lambda: False, raising=True)
    assert DA.scan_values() == [] and DA.scan_fields() == []


# ------------------------------------------ the quick_ratio upper bound ---

def test_module_scan_confirms_with_real_ratio_not_quick_ratio(tmp_path, monkeypatch):
    """quick_ratio compares character multisets and overcounts badly.

    These two modules use an almost identical alphabet and share no structure.
    quick_ratio scores them high; ratio does not.
    """
    a = tmp_path / "a.py"
    b = tmp_path / "b.py"
    a.write_text("def alpha():\n" + "    x = 1\n" * 400, encoding="utf-8")
    b.write_text("def alpha():\n" + "    1 = x\n" * 400, encoding="utf-8")
    monkeypatch.setattr(DA, "REPO", str(tmp_path), raising=True)
    import difflib
    quick = difflib.SequenceMatcher(None, a.read_text(), b.read_text()).quick_ratio()
    assert quick >= 0.85, "fixture must actually trip the cheap prefilter"
    for finding in DA.scan_modules():
        assert float(finding.detail.split("%")[0]) >= 85.0, (
            "a reported pair must meet the threshold on the REAL ratio")
