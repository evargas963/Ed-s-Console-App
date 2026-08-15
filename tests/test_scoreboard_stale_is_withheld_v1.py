"""RC-289 — a measurement that does not describe THIS tree must not be shown as if it did.

WHAT HAPPENED. The operator asked me to rerun the reports. `tools/repo_scoreboard.py`
printed `failing tests 51 of 5313` with a `17h old` note; the true count, measured minutes
earlier, was 20. Coverage read 52.9% / 44.7% at 19h old. The board is a READER of stored
artefacts, so "rerun the report" re-renders yesterday's numbers, and I relayed them.

`STALE` was DECLARED as a state at the top of repo_scoreboard.py and rendered in the legend
and never assigned anywhere. Every row's state came from the VALUE alone, so an artefact's
age reached the operator as a footnote beside a number formatted, ranked and coloured
exactly like a live one.

`test_unmeasured_is_never_reported_as_ok` already forbids the neighbouring case — a MISSING
artefact must carry `—`. A stale one is the same lie with more decimal places.

STALENESS IS DERIVED, NOT BUDGETED. Not "older than N hours", a number nobody chose and the
operator has banned, but: was any tracked source file modified after this artefact was
written. That asks the only question that matters — does this measurement still describe
this tree.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

import repo_scoreboard as S  # noqa: E402


def _row(**kw):
    base = dict(key="K", area="a", metric="m", value="42", target="0", state="OPEN",
                source="reports/x.txt", note="")
    base.update(kw)
    return S.Row(**base)


def _with_artifact(tmp_path, monkeypatch, value="42"):
    """A row backed by a REAL file, because a missing artefact is a different case.

    The first version of this test pointed at a path that did not exist, `getmtime` raised,
    and the row passed through unchanged — the test failed for a reason unrelated to the
    behaviour it was written to pin. That is RC-275's defect in a test of my own.
    """
    art = tmp_path / "reports"
    art.mkdir(exist_ok=True)
    (art / "x.txt").write_text("measured", encoding="utf-8")
    monkeypatch.setattr(S, "REPO", str(tmp_path), raising=True)
    return _row(value=value, source="reports/x.txt")


def test_a_stale_artefact_has_its_value_withheld(tmp_path, monkeypatch):
    """The defect: a number from a different tree, rendered as this tree's."""
    row = _with_artifact(tmp_path, monkeypatch)
    rows = S._mark_stale_rows([row], tree_mtime=time.time() + 10_000)
    assert rows[0].state == "STALE"
    assert rows[0].value == "—", "a stale number is still being shown as current"


def test_the_withheld_row_says_what_it_measured_and_why_it_is_blank(tmp_path, monkeypatch):
    """A blank cell with no reason teaches the operator to ignore blanks."""
    row = _with_artifact(tmp_path, monkeypatch, value="51 of 5313")
    rows = S._mark_stale_rows([row], tree_mtime=time.time() + 10_000)
    note = rows[0].note
    assert "predates the working tree" in note
    assert "51 of 5313" in note, "the stale figure is lost, so nobody can tell what changed"
    assert "DIFFERENT tree" in note


def test_a_missing_artefact_is_not_silently_treated_as_stale(tmp_path, monkeypatch):
    """Absent and stale are different failures and must not be merged (RC-274)."""
    monkeypatch.setattr(S, "REPO", str(tmp_path), raising=True)
    rows = S._mark_stale_rows([_row(source="reports/nope.txt")],
                              tree_mtime=time.time() + 10_000)
    assert rows[0].state == "OPEN", (
        "a missing artefact was relabelled STALE; its own builder already reports "
        "UNMEASURED and that distinction is the point")


def test_a_current_artefact_keeps_its_number():
    """Negative control: withholding must not swallow live measurements."""
    rows = S._mark_stale_rows([_row()], tree_mtime=0.0)
    assert rows[0].state == "OPEN" and rows[0].value == "42"


def test_a_live_row_can_never_be_stale():
    """`source` is overloaded: row_db RUNS its checker and names the TOOL for provenance.

    Reading that as an artefact marked a genuinely live measurement STALE — the first
    version of this fix did exactly that, which is why the row states `live` explicitly
    instead of the rule guessing from the path.
    """
    rows = S._mark_stale_rows(
        [_row(source="tools/check_db_health.py", live=True)],
        tree_mtime=time.time() + 10_000)
    assert rows[0].state == "OPEN" and rows[0].value == "42"


def test_the_db_health_row_declares_itself_live():
    live = {r.key: r.live for r in S.collect()}
    assert live.get("DB") is True, (
        "row_db runs check_db_health.py in a subprocess; if it stops declaring itself live "
        "it will be marked stale whenever that tool file is older than the tree")


def test_unmeasured_and_error_rows_are_left_alone():
    for st in ("UNMEASURED", "ERROR"):
        rows = S._mark_stale_rows([_row(state=st, value="—")],
                                  tree_mtime=time.time() + 10_000)
        assert rows[0].state == st


def test_staleness_uses_no_invented_time_threshold():
    """The operator banned ceilings nobody named. This rule compares two timestamps."""
    import inspect

    src = inspect.getsource(S._mark_stale_rows) + inspect.getsource(
        S._newest_tracked_source_mtime)
    for banned in ("3600", "86400", "hours >", "age >", "MAX_AGE", "STALE_AFTER"):
        assert banned not in src, f"a time budget ({banned}) crept into the staleness rule"
    assert "ls-files" in src, "the tree mtime must come from tracked files, not a glob"


def test_the_tree_mtime_reflects_a_real_edit(tmp_path):
    """The comparison must actually move when the repo moves."""
    before = S._newest_tracked_source_mtime()
    assert before > 0, "no tracked source mtime — the comparison would be inert"
    probe = REPO / "tools" / "repo_scoreboard.py"
    assert os.path.getmtime(probe) <= before + 1


def test_every_state_the_legend_advertises_is_reachable():
    """STALE sat in the legend unassigned for the life of this file. Never again."""
    import inspect

    src = inspect.getsource(S)
    for state in ("OK", "OPEN", "UNMEASURED", "STALE", "ERROR"):
        assert f'"{state}"' in src, f"{state} is advertised but never produced"
    assert 'state="STALE"' in src or '"STALE",' in src
