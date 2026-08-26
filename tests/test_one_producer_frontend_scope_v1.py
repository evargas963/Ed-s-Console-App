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
    build_frontend_corpus,
    build_scan_corpus,
    computing_sites,
    load_registry,
)

# The unit extractor lives in the DISCOVERY authority, not in the gate. Importing it from here
# is itself part of the contract: if it reappears inside check_one_producer, that is a second
# producer of "what are this repository's units" inside the machinery that forbids second
# producers, and test_discovery_has_exactly_one_authority below fails.
from tools.producer_inventory_v1 import js_function_units  # noqa: E402

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
    return [(rel, js, js_function_units(js))]


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


def test_discovery_has_exactly_one_authority():
    """THE ARCHITECTURE. One census, one decision path — enforced, not just intended.

    Repairing this gate the first time introduced a SECOND repository enumeration, a SECOND
    <script> extractor and a SECOND JS parser inside check_one_producer: a second producer of
    "what are this repository's units", living inside the machinery whose entire purpose is
    forbidding second producers. It was also NARROWER than the authority it duplicated —
    static/*.html, static/*.js and static/js/*.js only — so .sql, .ts, .jsx, .mjs and any
    JavaScript outside static/ stayed invisible while the gate claimed to be repo-wide.

    producer_inventory_v1 DISCOVERS (it enumerates every tracked file, buckets it by executable
    kind, and accounts for every exclusion with a reason). check_one_producer DECIDES.
    """
    import re

    tools = REPO / "tools"
    enumerations = {}
    for rel in ("check_one_producer.py", "deep_duplicate_probe_v1.py",
                "producer_inventory_v1.py"):
        src = (tools / rel).read_text(encoding="utf-8")
        enumerations[rel] = len(re.findall(r'"git"\s*,\s*"ls-files"', src))

    assert enumerations["producer_inventory_v1.py"] == 1, (
        "the discovery authority must be the one that enumerates the repository")
    assert enumerations["check_one_producer.py"] == 0, (
        "the enforced gate is enumerating the repository itself again — discovery belongs to "
        "producer_inventory_v1; this module decides")
    assert enumerations["deep_duplicate_probe_v1.py"] == 0, (
        "the clone probe is enumerating the repository itself again")

    # ...and the unit extractor lives with discovery, not with the decision.
    # Checked against CODE, not prose: a first version of this assertion matched "<script"
    # inside the comment that EXPLAINS the removal — the same prose-matching mistake the
    # detector itself had to be cured of, reproduced one layer up.
    from tools.check_one_producer import _code_only

    gate = _code_only((tools / "check_one_producer.py").read_text(encoding="utf-8"))
    assert "def js_function_units" not in gate and "def _function_blocks_js" not in gate, (
        "a JS parser is back inside the gate — that is a second unit extractor")
    assert "<script" not in gate, "a second <script> extractor is back inside the gate"


def test_the_scope_is_every_executable_kind_not_hand_picked_globs():
    """REPO-WIDE means the authority's executable set, not three static globs.

    The hand-picked version saw 10 files. The authority sees the .js/.html/.sql/.mjs/.jsx/.bat/
    .ps1 production surfaces the repository actually has.
    """
    import producer_inventory_v1 as inv

    fe = build_frontend_corpus()
    exts = {Path(rel).suffix.lower() for rel, _t, _u in fe}
    assert exts - {".html", ".js"}, (
        f"scope is still only static html/js ({sorted(exts)}) — the authority recognises "
        f"{sorted(inv._EXEC_EXT)} and the gate should cover the production ones")
    assert not any(rel.startswith(("tests/", "tools/", "research/")) for rel, _t, _u in fe), (
        "test/tool/research surfaces are in the enforcement scope; they legitimately recompute")


def test_every_tracked_file_is_accounted_for_by_the_authority():
    """No silent holes: executable, excluded-with-a-reason, or reported NOT_PROVEN."""
    import producer_inventory_v1 as inv

    rec = inv.reconcile(inv.tracked())
    counted = (sum(len(v) for v in rec["buckets"].values())
               + len(rec["excluded"]) + len(rec["unknown"]))
    assert counted == rec["repository_files_total"], (
        f"the census loses files: {counted} accounted vs {rec['repository_files_total']} tracked")
    assert rec["buckets"]["python"] and rec["buckets"]["html"], "buckets look empty"


def test_the_extractor_handles_the_form_the_real_duplicate_used():
    """A single-param arrow (`const f = k => {`) is the shape that slipped through."""
    blocks = js_function_units(DUPLICATE_JS)
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
