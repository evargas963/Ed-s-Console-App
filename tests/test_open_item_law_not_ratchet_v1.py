"""RC-280 — the open-item check must be a LAW, not a ratchet.

WHAT WAS MEASURED (2026-08-07). `check_open_item_cap` stored a high-water mark in
`governance/open_item_ceiling.json` and blocked whenever the open count rose above it. Its
own docstring said "This is a RATCHET instead". It reported `39 open governance items >
ceiling of 37` and blocked the commit carrying the adversarial-audit request the operator
had already sent to Cursor, while 34 tests were red.

37 is a number the operator never named. The standing law is "WE DO NOT NEED RATCHETS. WE
NEED GREAT CODE. WE NEED TO REMOVE ALL RATCHETS", and this mission's done_criteria repeat
it: no ratchet, tolerance, ceiling or grandfather clause the operator did not name a number
for.

WHY A COUNT WAS THE WRONG INSTRUMENT. A count cannot tell honest new tracking from
deferral. The check's own history proves it: RC-65 re-scoped it because a session that FOUND
real defects failed the gate for RECORDING them. The remedy then was to count something
narrower. The remedy now is to stop counting and state the property: a dated item may not
rot.

These tests lock the removal so the ceiling cannot come back quietly.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

import check_institutional_correctness as C  # noqa: E402


def test_the_stored_ceiling_is_gone():
    """A baseline file is the ratchet. Its absence is the fix, not a side effect."""
    assert not (REPO / "governance" / "open_item_ceiling.json").exists(), (
        "the stored high-water mark is back — the check compares against a number "
        "nobody chose again")


def test_the_check_never_writes_a_baseline():
    """A ratchet re-arms by writing its own ceiling on a clean run.

    Judged on EXECUTABLE lines only. The comment block deliberately names the removed file
    so the next reader learns why it is gone; scanning raw text would make that explanation
    fail the test the explanation exists for — the same trap as RC-256's harness tests.
    """
    import ast
    import inspect

    src = inspect.getsource(C.check_open_item_cap)
    tree = ast.parse(src.lstrip())
    doc_spans: set[int] = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)):
            doc_spans.update(range(node.lineno, (node.end_lineno or node.lineno) + 1))
    body = "\n".join(ln for i, ln in enumerate(src.lstrip().splitlines(), 1)
                     if i not in doc_spans and not ln.strip().startswith("#"))

    assert "open_item_ceiling" not in body, "the check reads or writes a ceiling file again"
    assert "_ratchet_may_write" not in body, "the ratchet write path is back"
    assert "write_text" not in body, "the check writes a file — a gate that records its own"
    for token in ("ceiling", "baseline"):
        assert f"{token} =" not in body, f"a {token} value is being computed again"


def test_the_law_is_zero_overdue_not_a_tolerance():
    """The message must state the standard, so a reader cannot mistake it for a budget."""
    import inspect

    src = inspect.getsource(C.check_open_item_cap)
    assert "PAST their due date" in src
    assert "> ceiling of" not in src, "the tolerance wording survived the removal"


def test_an_overdue_item_still_fails(monkeypatch):
    """The negative control. Removing a ratchet must not remove the enforcement with it.

    Driven by feeding the real check a synthetic overdue item, because the repository's
    own ledger is (correctly) at zero overdue and a green check proves nothing on its own.
    """
    monkeypatch.setattr(C, "_overdue_governance_items",
                        lambda *a, **k: ["RC-999", "REG-001"], raising=True)
    out = C.check_open_item_cap()
    assert len(out) == 1, "an overdue item no longer fails the check"
    msg = out[0].msg
    assert "RC-999" in msg and "PAST their due date" in msg
    assert "2 governance item(s)" in msg


def test_zero_overdue_passes_without_consulting_any_stored_number(monkeypatch):
    monkeypatch.setattr(C, "_overdue_governance_items", lambda *a, **k: [], raising=True)
    assert C.check_open_item_cap() == []


def test_parking_lot_volume_is_no_longer_counted(monkeypatch):
    """OPEN_ITEMS.md rows carry no due date, so they were volume a law cannot judge.

    Dropping them is deliberate and is recorded in RC-280; this test states it so the
    omission reads as a decision rather than an oversight to be 'restored' later.
    """
    monkeypatch.setattr(C, "_overdue_governance_items", lambda *a, **k: [], raising=True)
    assert C.check_open_item_cap() == [], (
        "unchecked OPEN_ITEMS.md rows are being counted again; if they should be gated, "
        "give them due dates and let the overdue law judge them")
