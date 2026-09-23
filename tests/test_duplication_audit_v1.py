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

import json
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


# ------------------------------------------------ D-DBCOL false positives ---
# 2026-09-21: the flat STRUCTURAL name set only matched EXACT bare names (ts,
# created_at...), so this repo's own real timestamp convention (ts_utc, ts_et,
# ts_recv...) and identity/foreign-key columns (decision_id, git_sha...) fell
# straight through it. MEASURED on the live tree: 12 of 27 "active" D-DBCOL
# findings were exactly these two classes. A test using this repo's real
# column names would silently stop testing anything the day those names
# changed, so each control below plants its own synthetic table.

def _make_db_module(tmp_path, filename, table, columns):
    cols_sql = ",\n  ".join(f"{name} TEXT" for name in columns)
    (tmp_path / filename).write_text(
        f'SQL = """CREATE TABLE {table} (\n  {cols_sql}\n)"""\n', encoding="utf-8")


def test_db_columns_exempts_this_repos_timestamp_naming_convention(tmp_path, monkeypatch):
    """A column that is ONLY a timestamp, spelled the way this repo actually spells
    timestamps (_utc/_et/_recv suffixed, not bare 'ts'), must not read as duplication —
    every table legitimately has one."""
    monkeypatch.setattr(DA, "REPO", str(tmp_path), raising=True)
    for name, table, col in (
        ("a.py", "alpha_events", "event_ts_utc"),
        ("b.py", "beta_events", "event_ts_utc"),
    ):
        _make_db_module(tmp_path, name, table, [col])
    found = [f for f in DA.scan_db_columns() if f.ident == "D-DBCOL:event_ts_utc"]
    assert found == [], f"a repo-convention timestamp column was flagged: {found}"


def test_db_columns_exempts_identity_and_foreign_key_columns(tmp_path, monkeypatch):
    """An _id/_sha256 column linking two related tables is a foreign key, not a
    duplicated fact -- it is SUPPOSED to appear in both tables it joins."""
    monkeypatch.setattr(DA, "REPO", str(tmp_path), raising=True)
    _make_db_module(tmp_path, "a.py", "orders", ["order_id"])
    _make_db_module(tmp_path, "b.py", "order_fills", ["order_id"])
    found = [f for f in DA.scan_db_columns() if f.ident == "D-DBCOL:order_id"]
    assert found == [], f"a foreign-key column was flagged as duplication: {found}"


def test_db_columns_still_catches_a_real_planted_duplication(tmp_path, monkeypatch):
    """The point of the exemption widening: it must NOT swallow a genuine duplicated
    domain quantity. A column with no timestamp/identity shape, in two unrelated
    tables, must still be reported and must NOT be silently exempted."""
    monkeypatch.setattr(DA, "REPO", str(tmp_path), raising=True)
    _make_db_module(tmp_path, "a.py", "alpha_signals", ["signal_confidence_pct"])
    _make_db_module(tmp_path, "b.py", "beta_forecasts", ["signal_confidence_pct"])
    found = [f for f in DA.scan_db_columns() if f.ident == "D-DBCOL:signal_confidence_pct"]
    assert len(found) == 1, "a real duplicated domain column must still be caught"
    assert not found[0].accepted, "a real duplication must not be exempted"


def test_db_columns_mirror_exemption_still_fires(tmp_path, monkeypatch):
    """Pre-existing behavior, re-proven after the exemption-widening edit: a staging
    table sharing its parent's columns by lifecycle design stays exempted."""
    monkeypatch.setattr(DA, "REPO", str(tmp_path), raising=True)
    _make_db_module(tmp_path, "a.py", "widgets", ["widget_state"])
    _make_db_module(tmp_path, "b.py", "widgets_staging", ["widget_state"])
    found = [f for f in DA.scan_db_columns() if f.ident == "D-DBCOL:widget_state"]
    assert len(found) == 1
    assert found[0].accepted, "a staging-table mirror must still be exempted"


# --------------------------------------------- main() exemption merge bug ---
# 2026-09-21: `main()` used to do `f.accepted = ACCEPTED.get(f.ident, "")` --
# an unconditional REPLACE, not a fallback. MEASURED: this silently discarded
# scan_db_columns()'s own mirror-set exemption on every real CLI run (9 correct
# findings on this tree went from accepted to reported-as-active), an inert-
# instrument shape (RC-76/84/87/90) hiding behind a scanner that looks correct
# in isolation. This is a regression lock on `main()` itself, not on the
# scanner -- a fix that only tested scan_db_columns() directly would have
# missed this exact bug, the same way the original bug shipped invisibly.

def test_main_preserves_a_scanners_own_accepted_reason(tmp_path, monkeypatch, capsys):
    """A finding the SCANNER itself exempted (not via the global ACCEPTED dict) must
    still read as accepted after main()'s merge -- not silently replaced with none."""
    monkeypatch.setattr(DA, "REPO", str(tmp_path), raising=True)
    monkeypatch.setattr(DA, "server_up", lambda: True, raising=True)
    _make_db_module(tmp_path, "a.py", "widgets", ["widget_state"])
    _make_db_module(tmp_path, "b.py", "widgets_staging", ["widget_state"])
    rc = DA.main(["--json", "--kind", "D-DBCOL"])
    out = json.loads(capsys.readouterr().out)
    hit = [f for f in out if f["ident"] == "D-DBCOL:widget_state"]
    assert hit and hit[0]["accepted"], (
        "main() discarded the scanner's own exemption reason -- the exact "
        "silently-inert-instrument shape this repo has been bitten by before")
    assert rc == 0, "an exempted-only finding must not fail the gate"


def test_main_still_lets_the_global_accepted_dict_apply(tmp_path, monkeypatch, capsys):
    """The other half of the merge: a finding the scanner did NOT exempt must still
    pick up a reason from the global ACCEPTED dict when one is registered."""
    monkeypatch.setattr(DA, "REPO", str(tmp_path), raising=True)
    monkeypatch.setattr(DA, "server_up", lambda: True, raising=True)
    _make_db_module(tmp_path, "a.py", "alpha_signals", ["signal_confidence_pct"])
    _make_db_module(tmp_path, "b.py", "beta_forecasts", ["signal_confidence_pct"])
    monkeypatch.setitem(DA.ACCEPTED, "D-DBCOL:signal_confidence_pct",
                        "reviewed same session: coincidental name, unrelated producers")
    rc = DA.main(["--json", "--kind", "D-DBCOL"])
    out = json.loads(capsys.readouterr().out)
    hit = [f for f in out if f["ident"] == "D-DBCOL:signal_confidence_pct"]
    assert hit and hit[0]["accepted"], "a global ACCEPTED entry was not applied by main()"
    assert rc == 0


def test_validation_summary_exemption_is_real_not_a_guess():
    """The one D-DBCOL finding this session investigated by hand (not a pattern rule):
    validation_summary is carried, never recomputed, end to end from its one producer.
    Locks the exemption's presence and that it names the real producer, so a future
    edit can't silently turn this back into an unreviewed guess."""
    reason = DA.ACCEPTED.get("D-DBCOL:validation_summary", "")  # caps-ok: '' feeds the next line's assert reason with message 'the validation_summary exemption is missing', so absence fails with that named message
    assert reason, "the validation_summary exemption is missing"
    assert "call_engine.py" in reason, (
        "the exemption no longer names the traced producer -- re-verify before keeping it")


def test_dead_endpoint_scan_sees_router_modules_and_js_callers(tmp_path, monkeypatch):
    """RC-REHAB-1 (2026-09-23): the scan read `@app.` routes from server.py alone and looked
    for callers only in static/*.html, so once routes moved to app/api/routes (`@router.`)
    and the console's callers moved to static/js, it found 0 routes and reported 0 dead.
    A route defined in any module is in scope, a JS caller counts, and a route never
    counts as its own caller."""
    routes = tmp_path / "app" / "api" / "routes"
    routes.mkdir(parents=True)
    (routes / "x.py").write_text(
        '@router.get("/api/used")\ndef a():\n    pass\n\n'
        '@router.post("/api/orphan")\ndef b():\n    pass\n', encoding="utf-8")
    (tmp_path / "static" / "js").mkdir(parents=True)
    (tmp_path / "static" / "js" / "ed-x.js").write_text("fetch('/api/used')\n", encoding="utf-8")
    monkeypatch.setattr(DA, "REPO", str(tmp_path), raising=True)
    assert [f.ident for f in DA.scan_dead_endpoints()] == ["D-DEAD:/api/orphan"]
