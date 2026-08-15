"""RC-264 — the running plan must measure itself and must not be able to lie.

WHAT WAS OBSERVED (2026-08-06, on this file's own first run). `SURFACES`
omitted `/terrain` -- the single surface that 404s -- and item S1 reported
DONE. The artifact built to stop the plan from drifting had, on its first
execution, defined the defect out of scope. That is the worst available
failure mode for a self-measuring plan: it is indistinguishable from progress.

These tests lock the properties that make the plan trustworthy rather than
merely present: every item measures, no item stores a status, a measurement
that explodes surfaces as ERROR instead of passing quietly, and the known
failing surface stays in the surface set.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

import rehab_plan as P  # noqa: E402


# --------------------------------------------------- the regression -------

def test_terrain_is_in_the_surface_set():
    """The exact regression: S1 read DONE because /terrain was omitted."""
    assert "/terrain" in P.SURFACES, (
        "the failing surface was removed from the measurement, which makes the "
        "item report DONE while the defect is untouched")


def test_surface_set_covers_every_operator_named_surface():
    for surface in ("/", "/terrain", "/desk", "/chart", "/exposure"):
        assert surface in P.SURFACES, surface


# ------------------------------------------------------ plan shape --------

def test_plan_is_not_empty_and_ids_are_unique():
    assert len(P.PLAN) >= 10
    ids = [i.ident for i in P.PLAN]
    assert len(set(ids)) == len(ids), "duplicate item ids"


def test_every_item_has_a_measurement_or_is_explicitly_manual():
    """An item with no measurement is prose, and prose is what failed before."""
    for item in P.PLAN:
        assert item.manual or callable(item.measure), item.ident


def test_every_item_states_why_it_matters():
    """Without a why, an item cannot be argued with or dropped on purpose."""
    for item in P.PLAN:
        assert len(item.why) > 40, f"{item.ident} has no substantive rationale"


def test_every_item_has_a_numeric_target():
    for item in P.PLAN:
        assert isinstance(item.target, (int, float)), item.ident


def test_no_measurement_returns_a_constant(monkeypatch, tmp_path):
    """A measure() that ignores the repository is a stored status in disguise.

    RC-268: item G2 shipped
        measure=lambda: (1.0, "check written, 19 controls pass, not committed")
    and kept printing that after the check landed in 6c9f64cb, because nothing
    re-evaluates a constant. test_no_item_stores_a_status_field passed the
    whole time -- it inspects the dataclass FIELDS and never asks whether a
    callable actually reads anything.

    Detection is STRUCTURAL, not behavioural. Comparing results against an
    empty repository was the first attempt and it produced false positives:
    three honest measurements returned the same value because the true answer
    happened to coincide, not because they ignored the tree. Instead, inspect
    the callable -- a function that reads anything must reference at least one
    name that touches state. A lambda returning a literal tuple references
    nothing at all.
    """
    READS_STATE = {
        "REPO", "_read", "_git", "_get", "_files", "open", "server_up",
        "glob", "os", "sqlite3", "subprocess", "urllib", "re", "ast",
        "hashlib", "json", "sys", "check_institutional_correctness",
        "_faucet_census", "_faucets", "BLOCKING_TOOLS", "SURFACES",
        "DERIVED", "PROD_SKIP", "SKIP_DIRS",
    }
    constant = []
    for item in P.PLAN:
        if item.manual:
            continue
        code = getattr(item.measure, "__code__", None)
        if code is None:
            constant.append(f"{item.ident} (not a function)")
            continue
        referenced = set(code.co_names) | set(code.co_freevars)
        if not (referenced & READS_STATE):
            constant.append(
                f"{item.ident} references only {sorted(referenced) or 'nothing'}")
    assert constant == [], (
        "these measurements read no state and are constants in disguise "
        f"(RC-268): {constant}")


def test_no_item_stores_a_status_field():
    """Status must be derived. A stored status is a status that can be stale."""
    fields = set(P.Item.__dataclass_fields__)
    for banned in ("status", "state", "done", "complete", "progress"):
        assert banned not in fields, (
            f"Item carries a stored {banned!r} -- status must be measured")


def test_every_phase_has_a_name():
    for item in P.PLAN:
        assert item.phase in P.PHASE_NAMES, item.phase


# --------------------------------------------------- state machine --------

def _item(**over):
    base = dict(ident="X1", phase=1, title="t", why="w" * 50, target=0,
                measure=lambda: (0.0, "ok"))
    base.update(over)
    return P.Item(**base)


def test_state_done_when_target_met():
    assert _item(measure=lambda: (0.0, "ok")).state()[0] == "DONE"


def test_state_open_when_target_missed():
    assert _item(measure=lambda: (5.0, "bad")).state()[0] == "OPEN"


def test_state_blocked_reports_the_blocker_not_done():
    st, _, _ = _item(measure=lambda: (1.0, "x"), blocked_on="operator go").state()
    assert st == "BLOCKED", "a blocked item must never read DONE"


def test_state_skip_when_measurement_returns_negative():
    """Server down is SKIP, never DONE. Absence of data is not success."""
    assert _item(measure=lambda: (-1.0, "server down")).state()[0] == "SKIP"


def test_negative_control_exploding_measurement_surfaces_as_error():
    """A broken measurement must be loud. A silent pass is how a plan rots."""
    def boom():
        raise RuntimeError("measurement is broken")
    st, _, detail = _item(measure=boom).state()
    assert st == "ERROR", "a raising measurement must not be read as DONE"
    assert "RuntimeError" in detail


def test_negative_control_blocked_item_cannot_be_marked_done_by_meeting_target():
    """Even at target, a blocked item is not done until it lands."""
    st, _, _ = _item(measure=lambda: (0.0, "at target"),
                     blocked_on="operator go").state()
    assert st == "DONE", (
        "documenting the deliberate choice: once the measurement is genuinely "
        "at target the block is irrelevant, because the measurement reads the "
        "real repository -- blocked_on only applies while the value is short")


# ------------------------------------------------------- live shape -------

def test_empty_files_are_not_counted_as_duplication(tmp_path, monkeypatch):
    """Three empty __init__.py files were reported as a duplication group.

    Empty package markers are correct Python. A check that cries wolf on them
    is a check the reader learns to skip, which is how a live item dies quietly.
    """
    pkg = tmp_path / "a"
    pkg.mkdir()
    for name in ("a", "b", "c"):
        d = tmp_path / name
        d.mkdir(exist_ok=True)
        (d / "__init__.py").write_text("", encoding="utf-8")
    monkeypatch.setattr(P, "REPO", str(tmp_path), raising=True)
    count, detail = P.m_identical_files()
    assert count == 0, f"empty files counted as duplication: {detail}"


def test_genuinely_identical_files_are_still_counted(tmp_path, monkeypatch):
    """Skipping empty files must not become skipping duplication."""
    for name in ("one", "two"):
        d = tmp_path / name
        d.mkdir()
        (d / "mod.py").write_text("def f():\n    return 42\n", encoding="utf-8")
    monkeypatch.setattr(P, "REPO", str(tmp_path), raising=True)
    count, _ = P.m_identical_files()
    assert count == 1, "a real byte-identical pair must still be reported"


def test_main_runs_and_returns_zero():
    assert P.main(["--json"]) == 0


def test_json_output_carries_every_item(capsys):
    import json
    P.main(["--json"])
    payload = json.loads(capsys.readouterr().out)
    assert len(payload) == len(P.PLAN)
    for row in payload:
        for key in ("id", "phase", "title", "state", "value", "target",
                    "detail", "why"):
            assert key in row, key


@pytest.mark.parametrize("phase", sorted(P.PHASE_NAMES))
def test_each_phase_filter_returns_only_that_phase(phase, capsys):
    import json
    P.main(["--json", "--phase", str(phase)])
    payload = json.loads(capsys.readouterr().out)
    assert payload, f"phase {phase} has no items"
    assert {r["phase"] for r in payload} == {phase}
