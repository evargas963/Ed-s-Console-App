"""RC-304 — the chart labelled three FORCES rows with one provenance string.

/api/forces differences open interest across TWO banked captures for ΔOI and sums DEX and
CHARM on the NEWER capture alone, yet chart.html handed all three the same
`banked <older>→<newer>` label — a two-date span printed behind two single-date numbers. It
also never read `charm_book_scope` (RC-288 derived it so a one-expiry charm could not be
mistaken for a whole-book charm beside whole-book GEX) or `charm_error` (so a FAILED charm
rendered as an em-dash under a confident banked label).

The label logic now lives in `static/js/forces_provenance.js` and these tests EXECUTE it
(RC-298): string-matching chart.html could only ever prove a field is mentioned, never that
the sentence it builds is true.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def test_the_provenance_function_runs_under_node():
    """Every assertion about the built label, executed against the real function."""
    node = shutil.which("node")
    if not node:
        pytest.fail(
            "Node.js is required on PATH for this test (runs tests/forces_provenance_node.mjs). "
            "Same prerequisite as the L1 SSE guard assertions — see docs/playwright.md."
        )
    r = subprocess.run(
        [node, str(ROOT / "tests" / "forces_provenance_node.mjs")],
        cwd=str(ROOT), capture_output=True, text=True, timeout=60,
    )
    assert r.returncode == 0, r.stdout + "\n" + r.stderr


def test_the_chart_loads_the_module_and_stops_hand_writing_the_label():
    """Negative control on the wiring: a correct module nobody loads fixes nothing."""
    csrc = (ROOT / "static" / "chart.html").read_text(encoding="utf-8", errors="replace")
    assert "/static/js/forces_provenance.js" in csrc, "the chart does not load the module"
    assert "EdForcesProvenance" in csrc, "the chart never calls the provenance function"
    assert "const bankSrc" not in csrc, (
        "the one-label-for-three-rows constant is back — that IS the RC-304 defect")


def test_the_server_still_serves_what_the_label_reads():
    """The other half of the seam. A label reading fields nobody serves renders nothing."""
    ssrc = (ROOT / "server.py").read_text(encoding="utf-8", errors="replace")
    for key in ('"charm_book_scope"', '"charm_error"', '"newer_et_date"', '"older_et_date"'):
        assert key in ssrc, f"/api/forces no longer serves {key}"


def test_the_book_scope_is_derived_and_not_asserted():
    """RC-288's function, called — a scope the server hardcodes cannot detect a book change."""
    import sys

    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from server import _charm_book_scope

    one = [{"expirationDate": "2026-08-14"}, {"expirationDate": "2026-08-14"}]
    many = [{"expirationDate": "2026-08-14"}, {"expirationDate": "2026-08-21"}]
    assert _charm_book_scope(one) == "single_expiry_banked:2026-08-14"
    assert _charm_book_scope(many) == "full_chain_banked"
    assert _charm_book_scope([]) == "unknown", "an unlooked-at book claims a scope"
    assert _charm_book_scope(None) == "unknown"
