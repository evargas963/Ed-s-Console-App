"""The enforced seam blocks carry -> recompute, and does not block legitimate production.

THE LAW HAS TWO HALVES. governance/computation_registry.json: "ONE and only ONE producer for
every field... Many consumers are expected and correct. A consumer CARRIES the produced value;
it never recomputes it." `computing_sites` proves the first half by counting DEFINITION sites.
The second half was unenforced, and the operator named the exact bypass:

    payload["strike_labels"]["call_wall"] = P(payload["call_wall"])
    md["kl_call_gamma_wall"]              = _g("call_wall")           # an ALIAS
    md["kl_strike_labels"][...]           = P(md["kl_call_gamma_wall"])   # rebuilt from it

Both lines call the ONE canonical producer, so definition-counting sees nothing.

WHAT THE RULE IS NOT. It is never "the producer may be called once". Measured on this repo, a
single dict held 8 aliased keys that must CARRY beside 10 that must PRODUCE, and one loop
labels 200 distinct strikes through a single site. Invocation counts are not consulted at all:
sites are grouped by the ALIAS ROOT of their argument, and only a root reached by two or more
UNGUARDED sites is a failure.

WHY THE FLOW-SENSITIVITY IS LOAD-BEARING. Three independently designed detectors were built for
this and all three were refuted on measured evidence: each FAILED this repository's own correct
HEAD by reading an if/elif flow-insensitively. Driving the shipped assembler with an
instrumented producer shows 3 invocations, all first-production, and ZERO for the 8 aliased
keys. A gate that fails correct code gets switched off, so the legitimate shapes below are
asserted with the same weight as the bypasses.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools.check_one_producer import (  # noqa: E402
    alias_edges,
    alias_map_names,
    literal_domains,
    load_registry,
    reconstruction_sites,
)

SPEC = {"producer": "instrument_identity.py:format_strike_for_display",
        "kind": "display_transform", "computation_inputs": ["strike"]}

#: The shape every fixture shares: one upstream production, one alias, one downstream use.
UPSTREAM = '''
KEYS = ("call_wall", "put_wall")

def refresh(payload):
    payload["strike_labels"] = {
        k: format_strike_for_display(payload.get(k)) for k in KEYS
        if payload.get(k) is not None
    }
    return payload
'''


def _corpus(*sources: str):
    """(rel, src, [(fn_node, fn_text)]) — the shape build_scan_corpus() produces."""
    out = []
    for i, src in enumerate(sources):
        tree = ast.parse(src)
        fns = [(n, ast.get_source_segment(src, n) or "")
               for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        out.append((f"fixture_{i}.py", src, fns))
    return out


def _verdict(downstream: str):
    fails, unresolved = reconstruction_sites(
        "strike_display_text", SPEC, _corpus(UPSTREAM + downstream))
    return fails, unresolved


# ── the bypass class, in every shape it can take ────────────────────────────────────────────

def test_the_operators_exact_bypass_is_blocked():
    """Alias the produced value, then rebuild it with the same producer."""
    fails, _ = _verdict('''
ALIAS_OF = {"kl_call_wall": "call_wall"}
DOWN = ("kl_call_wall",)

def overlay(md, payload):
    md["kl_call_wall"] = payload["call_wall"]
    md["labels"] = {k: format_strike_for_display(md.get(k)) for k in DOWN
                    if md.get(k) is not None}
''')
    assert fails, "the alias reconstruction was not detected"
    assert "call_wall" in fails[0], f"the failure does not name the shared root: {fails[0]}"


def test_the_bypass_is_blocked_when_unrolled_to_an_explicit_key():
    """No loop to expand — the plainest form must still be caught."""
    fails, _ = _verdict('''
def overlay(md, payload):
    md["kl_call_wall"] = payload["call_wall"]
    md["labels"] = {}
    md["labels"]["kl_call_wall"] = format_strike_for_display(md["kl_call_wall"])
''')
    assert fails, "an explicit-key reconstruction went undetected"


def test_renaming_the_producer_on_import_does_not_hide_it():
    """`import P as _p` is the cheapest evasion of a name-matched rule."""
    fails, _ = _verdict('''
from instrument_identity import format_strike_for_display as _fsd
DOWN = ("kl_call_wall",)

def overlay(md, payload):
    md["kl_call_wall"] = payload["call_wall"]
    md["labels"] = {k: _fsd(md.get(k)) for k in DOWN if md.get(k) is not None}
''')
    assert fails, "an import-aliased producer hid the reconstruction"


def test_a_bypass_inside_the_carry_arm_is_blocked():
    """THE ARM MATTERS. The `if` body is the arm where the label ALREADY EXISTS.

    A first version treated any carry-guard as proof of absence, so moving the rebuild INTO the
    carry arm passed the enforced seam — the guard that proves the value is available was being
    read as proof that it was not.
    """
    fails, _ = _verdict('''
ALIAS_OF = {"kl_call_wall": "call_wall"}
DOWN = ("kl_call_wall",)

def overlay(md, payload, carried_labels):
    md["kl_call_wall"] = payload["call_wall"]
    md["labels"] = {}
    for k in DOWN:
        root = ALIAS_OF.get(k)
        if root is not None and carried_labels.get(root) is not None:
            md["labels"][k] = format_strike_for_display(md[k])
        elif md.get(k) is not None:
            md["labels"][k] = format_strike_for_display(md[k])
''')
    assert fails, "a rebuild placed in the carry arm was treated as first production"


def _chain(hops: int) -> str:
    """A -> B -> ... -> tail, then rebuild the semantic from the tail."""
    links = ['    md["kl_0"] = payload["call_wall"]']
    for i in range(1, hops):
        links.append(f'    md["kl_{i}"] = md["kl_{i - 1}"]')
    tail = f"kl_{hops - 1}"
    return (f'\nDOWN = ("{tail}",)\ndef overlay(md, payload):\n' + "\n".join(links) +
            '\n    md["labels"] = {k: format_strike_for_display(md.get(k)) for k in DOWN '
            'if md.get(k) is not None}\n')


def test_a_chained_alias_is_followed_to_its_origin():
    """ONE HOP IS NOT ENOUGH. Stopping after a single edge asks for one more assignment.

    Measured before the repair: the 1-hop shape was blocked and the 2-hop shape escaped.
    """
    for hops in (1, 2, 4, 8):
        fails, _ = _verdict(_chain(hops))
        assert fails, f"a {hops}-hop alias chain escaped the reconstruction check"


def test_the_alias_resolution_terminates_on_a_cycle():
    """A key that carries from itself must not spin the gate."""
    from tools.check_one_producer import resolve_alias_root

    assert resolve_alias_root("a", {"a": "b", "b": "a"}) in {"a", "b"}
    assert resolve_alias_root("a", {"a": "a"}) == "a"
    assert resolve_alias_root("x", {}) == "x"


def test_every_registered_field_is_asked_the_question():
    """NOT ONLY display_transform. The law says a consumer carries — for every field.

    This was gated to `kind == "display_transform"`, so six of the seven registered fields
    returned ([], []) immediately and were never checked at all.
    """
    from tools.check_one_producer import build_scan_corpus

    reg = load_registry()["fields"]
    corpus = build_scan_corpus()
    unchecked = []
    for name, spec in reg.items():
        fails, unresolved = reconstruction_sites(name, spec, corpus)
        if not fails and not unresolved:
            unchecked.append(f"{name} (kind={spec.get('kind')})")
    assert len(unchecked) < len(reg), (
        f"no registered field produced a verdict — the check is inert: {unchecked}")
    assert not [u for u in unchecked if "display_transform" not in u and "derived" in u], (
        f"a derived field is still never asked the question: {unchecked}")


# ── legitimate production must NOT be blocked ───────────────────────────────────────────────

def test_carry_then_produce_passes():
    """The shipped shape: carry where a label exists, produce only where none does."""
    fails, _ = _verdict('''
ALIAS_OF = {"kl_call_wall": "call_wall"}
DOWN = ("kl_call_wall", "kl_local_only")

def overlay(md, payload, carried_labels):
    md["kl_call_wall"] = payload["call_wall"]
    md["labels"] = {}
    for k in DOWN:
        root = ALIAS_OF.get(k)
        if root is not None and carried_labels.get(root) is not None:
            md["labels"][k] = carried_labels[root]
        elif md.get(k) is not None:
            md["labels"][k] = format_strike_for_display(md[k])
''')
    assert not fails, f"the correct carry-then-produce shape was blocked: {fails}"


def test_producing_only_the_non_aliased_keys_passes():
    """A `continue` guard is a PRECEDING SIBLING, not an ancestor — it must still count."""
    fails, _ = _verdict('''
ALIAS_OF = {"kl_call_wall": "call_wall"}
DOWN = ("kl_call_wall", "kl_local_only")

def overlay(md, payload):
    md["kl_call_wall"] = payload["call_wall"]
    md["labels"] = {}
    for k in DOWN:
        if ALIAS_OF.get(k) is not None:
            continue
        if md.get(k) is not None:
            md["labels"][k] = format_strike_for_display(md[k])
''')
    assert not fails, f"a produce-only loop with a continue guard was blocked: {fails}"


def test_many_independent_values_through_one_site_pass():
    """200 distinct strikes, one lexical site. The rule must never become 'call once'."""
    fails, _ = _verdict('''
def ladder(rows):
    return [[r[0], format_strike_for_display(r[0])] for r in rows]
''')
    assert not fails, f"labelling many independent values was treated as reconstruction: {fails}"


def test_a_transformed_value_is_a_different_value():
    """Arithmetic on the way is not carriage — the result may be produced in its own right."""
    fails, _ = _verdict('''
def overlay(md, payload):
    md["kl_shifted"] = payload["call_wall"] + 5.0
    md["labels"] = {}
    md["labels"]["kl_shifted"] = format_strike_for_display(md["kl_shifted"])
''')
    assert not fails, f"a shifted value was treated as an alias of its source: {fails}"


# ── the resolution primitives ───────────────────────────────────────────────────────────────

def test_unresolvable_arguments_are_reported_not_failed():
    """NOT_PROVEN, never FAIL — the discipline computing_sites already applies (RC-290/RC-323)."""
    fails, unresolved = _verdict('''
def overlay(md, key_from_somewhere):
    md["labels"] = {}
    md["labels"]["x"] = format_strike_for_display(md[key_from_somewhere])
''')
    assert not fails, "an unresolvable argument was failed instead of reported"
    assert unresolved, "an unresolvable argument produced no NOT_PROVEN note"


def test_the_primitives_resolve_what_they_claim():
    src = ('A = ("x", "y")\nM = {"kl_a": "a"}\n'
           'def f(d):\n    d["kl_a"] = d["a"]\n')
    tree = ast.parse(src)
    assert literal_domains(tree)["A"] == ("x", "y")
    assert alias_map_names(tree) == {"M"}
    assert alias_edges(tree)["kl_a"] == "a"


def test_the_shipped_tree_is_clean():
    """HEAD must PASS. A gate whose first act is to fail correct code gets switched off."""
    from tools.check_one_producer import build_scan_corpus
    spec = load_registry()["fields"]["strike_display_text"]
    fails, _unresolved = reconstruction_sites("strike_display_text", spec, build_scan_corpus())
    assert not fails, (
        "the shipped tree reports a reconstruction; if it is real, fix it — if it is not, this "
        f"is the false-positive class that got three prior designs refuted: {fails}")
