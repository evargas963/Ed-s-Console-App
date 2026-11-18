"""The Experimental Trade Desk IIFE must bind orDash before todayCard uses it (#1154)."""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PAGE = (REPO / "static/js/ed-trade-desk.js").read_text(encoding="utf-8")


def test_the_experimental_iife_binds_ordash_before_todaycard_uses_it():
    """#1154 drew null gap_text via orDash but only the Right Now IIFE imported it.

    Under the Experimental IIFE's \"use strict\", that was ReferenceError on every paint.
    """
    start = PAGE.index('/* Trade Desk / "Experimental"')
    body = PAGE[start:]
    bind = body.index("orDash = window.EdShell.orDash")
    use = body.index("orDash(t.gap_text)")
    assert bind < use
