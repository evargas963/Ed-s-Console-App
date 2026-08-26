"""ONE FAUCET must be enforceable in EVERY runtime, not only in Python (RC-325 scope repair).

WHAT FAILED, AND WHY IT COULD NOT HAVE BEEN CAUGHT. `check_one_producer.computing_sites` counts
definition sites inside `build_scan_corpus()`, and that corpus was built from
`git ls-files -- *.py` alone. So `len(sites)` counted PYTHON sites, and the gate's FAIL condition
`len(sites) > 1` was UNREACHABLE for any duplication living in the browser — not because a rule
was wrong, but because the corpus never contained the file. MEASURED 2026-08-26: 222 files
enumerated, 100% .py, while 19,224 tracked lines of production frontend were invisible.

That is how one semantic — how a strike is written as text — came to be implemented twice, in
Python and in JavaScript, with this gate reporting PASS the whole time.

The law is ONE COMPUTATION repo-wide. The lock was one computation per-Python.

These are BEHAVIORAL negative controls: they drive the real `computing_sites` with a real
injected duplicate and assert the gate now counts it. The decisive one is
`test_a_browser_duplicate_is_invisible_under_the_old_scope`, which pins the exact difference —
same input, old scope green, new scope FAIL.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools.check_one_producer import (  # noqa: E402
    _function_blocks_js,
    build_frontend_corpus,
    build_scan_corpus,
    computing_sites,
    load_registry,
)

#: The browser formatter that actually existed, verbatim in shape. Single-param arrow with no
#: parentheses — the form a first version of the extractor could not match at all.
DUPLICATE_JS = """
const fmtStrike = k => {
  if (k == null) return '-';
  const n = Number(k);
  if (!Number.isFinite(n)) return '-';
  const s = n.toFixed(4);
  return s.indexOf('.') < 0 ? s : s.replace(/0+$/, '').replace(/\\.$/, '');
};
"""

SPEC = {
    "producer": "instrument_identity.py:format_strike_for_display",
    "kind": "display_transform",
    "computation_inputs": ["strike"],
}


def _fake_frontend(js: str, rel: str = "static/injected.html"):
    return [(rel, js, _function_blocks_js(js))]


# ── the scope repair itself ─────────────────────────────────────────────────────────────────

def test_the_corpus_now_contains_the_production_browser_surfaces():
    """The root cause was scope. This is the scope."""
    fe = build_frontend_corpus()
    rels = {r for r, _s, _f in fe}
    assert rels, "no browser surface is enumerated — the gate is Python-only again"
    for required in ("static/chart.html", "static/exposure.html", "static/index.html"):
        assert required in rels, f"{required} is production and must be in scope"
    assert sum(len(f) for _r, _s, f in fe) > 100, (
        "almost no functions were extracted from the browser surfaces — the extractor is not "
        "actually parsing them, so the scope repair would be cosmetic")


def test_the_extractor_handles_the_form_the_real_duplicate_used():
    """A single-param arrow (`const f = k => {`) is the shape that slipped through."""
    blocks = _function_blocks_js(DUPLICATE_JS)
    names = [n for n, _b in blocks]
    assert "fmtStrike" in names, (
        f"the single-param arrow form was not extracted (got {names}) — the detector would be "
        f"blind to the exact construct it exists to catch")


# ── behavioral negative controls ────────────────────────────────────────────────────────────

def test_a_browser_duplicate_is_invisible_under_the_old_scope():
    """THE DECISIVE CONTROL. Same duplicate, two scopes, two verdicts.

    Old scope (Python only, modelled by passing an empty frontend corpus): ONE site -> green.
    New scope: TWO sites -> the gate's FAIL condition fires.
    """
    py = build_scan_corpus()
    old = computing_sites("strike_display_text", SPEC, py, [])
    new = computing_sites("strike_display_text", SPEC, py, _fake_frontend(DUPLICATE_JS))

    assert old == ["instrument_identity.py:format_strike_for_display"], (
        f"baseline changed: expected exactly the declared producer under the old scope, got {old}")
    assert len(old) == 1, "under the OLD scope a browser duplicate was invisible — that is the bug"
    assert len(new) == 2, (
        f"the browser duplicate is STILL not counted: {new}. len(sites) > 1 can never fire and "
        f"the law is unenforced in the browser.")
    assert any(s.startswith("static/") for s in new), "the duplicate was not attributed to a surface"


def test_a_python_duplicate_is_still_caught():
    """The repair must not weaken the runtime that already worked."""
    py = build_scan_corpus()
    fake_py_dupe = "def other_fmt(strike):\n    return f\"{float(strike):.4f}\".rstrip('0')\n"
    import ast as _ast

    tree = _ast.parse(fake_py_dupe)
    fns = [(n, fake_py_dupe) for n in _ast.walk(tree)
           if isinstance(n, (_ast.FunctionDef, _ast.AsyncFunctionDef))]
    sites = computing_sites("strike_display_text", SPEC,
                            py + [("other_module.py", fake_py_dupe, fns)], [])
    assert len(sites) == 2, f"a second PYTHON producer was not counted: {sites}"


def test_a_renamed_browser_duplicate_is_still_caught():
    """Renaming is the cheapest evasion; the bar is behaviour, not the identifier."""
    renamed = DUPLICATE_JS.replace("fmtStrike", "prettyStrikeText")
    sites = computing_sites("strike_display_text", SPEC, build_scan_corpus(),
                            _fake_frontend(renamed))
    assert len(sites) == 2, f"renaming defeated the detector: {sites}"


def test_a_consumer_is_not_mistaken_for_a_producer():
    """CARRYING a value is allowed and must stay allowed, or the gate blocks correct code."""
    consumer = """
    const render = row => {
      const label = row[3];
      el.textContent = 'Strike ' + label;
      return label;
    };
    """
    sites = computing_sites("strike_display_text", SPEC, build_scan_corpus(),
                            _fake_frontend(consumer))
    assert len(sites) == 1, (
        f"a pure consumer was counted as a producer: {sites}. Many consumers are the point; "
        f"blocking them would make the gate unusable and it would be switched off.")


def test_prose_about_a_field_is_not_a_computation():
    """Comment-only mentions must not count.

    Measured: `regime_engine._score_pinning` formats a pin WIDTH and mentions "strike" only in
    commentary; a first version of this detector named it a producer of strike display text.
    """
    commentary = """
    const draw = v => {
      // this strike ladder is drawn elsewhere; see the strike notes above
      return v.toFixed(2);
    };
    """
    sites = computing_sites("strike_display_text", SPEC, build_scan_corpus(),
                            _fake_frontend(commentary))
    assert len(sites) == 1, f"prose was counted as a computation: {sites}"


# ── the gate as shipped ─────────────────────────────────────────────────────────────────────

def test_the_shipped_registry_has_exactly_one_site_for_the_strike_text():
    """No false positives on the real repo — the whole point of tuning the bar empirically."""
    reg = load_registry()["fields"]["strike_display_text"]
    sites = computing_sites("strike_display_text", reg, build_scan_corpus(),
                            build_frontend_corpus())
    assert sites == ["instrument_identity.py:format_strike_for_display"], (
        f"expected exactly the declared producer, got {sites}")


def test_the_gate_still_passes_over_every_registered_field():
    """The widened scope must not have introduced noise on the fields that already passed."""
    from tools.check_one_producer import evaluate

    failures, _not_proven, registered = evaluate()
    assert registered >= 7, "the registry shrank"
    assert not failures, "the widened scope introduced failures:\n" + "\n".join(failures)
