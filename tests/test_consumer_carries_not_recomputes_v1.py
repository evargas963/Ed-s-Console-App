"""A consumer CARRIES an already-produced semantic; it never recomputes it from an alias.

THE LAW, second half. governance/computation_registry.json "_law" says: "ONE and only ONE
producer for every field... Many consumers are expected and correct. A consumer CARRIES the
produced value; it never recomputes it." The ONE FAUCET lock proved only the FIRST half — that
a computation has one DEFINITION site. It could not see this:

    payload["strike_labels"]["call_wall"] = format_strike_for_display(payload["call_wall"])
    md["kl_call_gamma_wall"]              = _g("call_wall")        # an ALIAS of that value
    md["kl_strike_labels"]["kl_call_gamma_wall"] = format_strike_for_display(md["kl_call_gamma_wall"])

The third line reconstructs a display semantic the first line already produced, from an alias of
the same underlying value. Both are calls to the ONE canonical producer, so a lock that counts
definition sites passes them. MEASURED 2026-08-26 on the shipped key sets: 8 of the 18
strike-valued kl_ keys aliased a terrain key that was already labelled; the other 10 exist only
in the kl_ namespace and are legitimate FIRST production.

That 8-vs-10 split inside ONE dict is why "the producer may only be called once" is the WRONG
rule, and why these tests assert the DISTINCTION rather than a call count.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from instrument_identity import format_strike_for_display  # noqa: E402

SERVER = REPO / "server.py"


def _src() -> str:
    return SERVER.read_text(encoding="utf-8")


def _const(name: str):
    """Read a constant out of server.py without importing (and starting) the app.

    Walks the whole tree, not just module scope: KL_STRIKE_ALIAS_OF and KL_STRIKE_VALUED_KEYS
    live INSIDE `_terrain_kl_overlay`, beside the `md["kl_x"] = _g("y")` assignments they
    describe. That is deliberate — RC-128's single-writer lock treats an SSOT level key named
    anywhere else as a second writer, and the map cannot drift from assignments it sits on top of.
    """
    for node in ast.walk(ast.parse(_src())):
        tgt = (node.targets[0] if isinstance(node, ast.Assign)
               else getattr(node, "target", None) if isinstance(node, ast.AnnAssign) else None)
        if isinstance(tgt, ast.Name) and tgt.id == name:
            return ast.literal_eval(node.value)
    raise AssertionError(f"{name} is not declared in server.py")


def _alias_assignments() -> dict[str, str]:
    """The kl_ -> terrain aliases as the SHIPPED CODE actually assigns them.

    Read from `md["kl_x"] = _g("y")` so the declared map cannot drift away from the code it
    describes; test_the_declared_alias_map_matches_the_code below is the lock on that.
    """
    out: dict[str, str] = {}
    for line in _src().splitlines():
        s = line.strip()
        if s.startswith('md["kl_') and '= _g("' in s:
            out[s.split('"')[1]] = s.split('_g("')[1].split('"')[0]
    return out


# ── the distinction the rule must make ──────────────────────────────────────────────────────

def test_the_split_exists_so_call_counting_would_be_wrong():
    """Both classes live in ONE key set. A call-count rule cannot separate them."""
    kl_keys = _const("KL_STRIKE_VALUED_KEYS")
    alias_of = _const("KL_STRIKE_ALIAS_OF")
    terrain = set(_const("STRIKE_VALUED_PAYLOAD_KEYS"))

    aliased = [k for k in kl_keys if alias_of.get(k) in terrain]
    first = [k for k in kl_keys if alias_of.get(k) not in terrain]
    assert aliased, "no aliased keys — the fixture no longer exercises reconstruction"
    assert first, (
        "every kl_ key is an alias, so this suite could not tell a correct fix from "
        "'never call the producer here'")


def test_the_declared_alias_map_matches_the_code():
    """The map must describe the assignments that actually exist, or it silently rots."""
    declared = _const("KL_STRIKE_ALIAS_OF")
    actual = _alias_assignments()
    for kl_key, root in declared.items():
        assert kl_key in actual, (
            f"{kl_key} is declared as an alias of {root} but server.py never assigns it from "
            f"_g(...); the map has drifted from the code")
        assert actual[kl_key] == root, (
            f"{kl_key} is declared an alias of {root} but the code assigns it from "
            f"{actual[kl_key]}")


def test_every_aliased_strike_key_is_declared():
    """No silent gap: a kl_ strike key that aliases a LABELLED terrain key must be in the map.

    Without this, adding a new kl_ alias re-opens the hole one key at a time.
    """
    terrain = set(_const("STRIKE_VALUED_PAYLOAD_KEYS"))
    declared = _const("KL_STRIKE_ALIAS_OF")
    actual = _alias_assignments()
    for kl_key in _const("KL_STRIKE_VALUED_KEYS"):
        root = actual.get(kl_key)
        if root in terrain:
            assert kl_key in declared, (
                f"{kl_key} is assigned from _g({root!r}), and {root} is already labelled by "
                f"strike_labels — it must CARRY that label, not recompute it. Add it to "
                f"KL_STRIKE_ALIAS_OF.")


# ── behavioural negative controls: reproduce the bypass, prove it is closed ──────────────────

class _CountingProducer:
    """The canonical producer, instrumented. Counts INVOCATIONS, not definitions."""

    def __init__(self):
        self.calls: list[object] = []

    def __call__(self, v):
        self.calls.append(v)
        return format_strike_for_display(v)


def _terrain_payload():
    """A terrain payload with every labelled strike key populated."""
    keys = _const("STRIKE_VALUED_PAYLOAD_KEYS")
    # distinct fractional values so a carried label is distinguishable from a recomputed one
    return {k: 100.0 + 2.5 * i for i, k in enumerate(keys)}


def _build_kl_labels(terrain: dict, terrain_labels: dict, md: dict, produce) -> dict:
    """The SHIPPED carry-then-produce rule, expressed once for the controls to drive."""
    alias_of = _const("KL_STRIKE_ALIAS_OF")
    out: dict[str, str] = {}
    for kk in _const("KL_STRIKE_VALUED_KEYS"):
        root = alias_of.get(kk)
        if root is not None and terrain_labels.get(root) is not None:
            out[kk] = terrain_labels[root]
        elif md.get(kk) is not None:
            out[kk] = produce(md[kk])
    return out


def test_an_aliased_semantic_is_carried_not_reproduced():
    """THE DECISIVE CONTROL. The producer must not run again for an already-labelled value."""
    terrain = _terrain_payload()
    alias_of = _const("KL_STRIKE_ALIAS_OF")
    terrain_labels = {k: format_strike_for_display(v) for k, v in terrain.items()}
    md = {kk: terrain[root] for kk, root in alias_of.items() if root in terrain}

    producer = _CountingProducer()
    labels = _build_kl_labels(terrain, terrain_labels, md, producer)

    assert producer.calls == [], (
        f"the producer ran {len(producer.calls)} time(s) for values whose label already "
        f"existed — that is reconstruction from an alias, the exact bypass this closes")
    for kk, root in alias_of.items():
        if root in terrain:
            assert labels[kk] == terrain_labels[root], (
                f"{kk} did not carry the label produced for {root}")


def test_a_first_production_value_still_reaches_the_producer():
    """The other half. A value nothing upstream produced MUST be produced here.

    If this fails the "fix" is really "never call the producer", which would silently drop
    labels for the ten keys that exist only in this namespace.
    """
    terrain = _terrain_payload()
    terrain_labels = {k: format_strike_for_display(v) for k, v in terrain.items()}
    alias_of = _const("KL_STRIKE_ALIAS_OF")
    first_keys = [k for k in _const("KL_STRIKE_VALUED_KEYS") if k not in alias_of]
    assert first_keys, "no first-production keys in the fixture"
    md = {k: 187.5 for k in first_keys}

    producer = _CountingProducer()
    labels = _build_kl_labels(terrain, terrain_labels, md, producer)

    assert len(producer.calls) == len(first_keys), (
        f"expected the producer to run once per first-production key "
        f"({len(first_keys)}), it ran {len(producer.calls)}")
    for k in first_keys:
        assert labels[k] == "187.5", f"{k} lost its vendor-true label: {labels.get(k)!r}"


def test_carrying_and_reproducing_agree_on_the_text():
    """Carrying must not change what the operator reads — only how many times it is computed."""
    terrain = _terrain_payload()
    terrain_labels = {k: format_strike_for_display(v) for k, v in terrain.items()}
    alias_of = _const("KL_STRIKE_ALIAS_OF")
    md = {kk: terrain[root] for kk, root in alias_of.items() if root in terrain}

    carried = _build_kl_labels(terrain, terrain_labels, md, _CountingProducer())
    reconstructed = {kk: format_strike_for_display(v) for kk, v in md.items()}
    assert carried == reconstructed, (
        f"the carry changed the rendered text: "
        f"{ {k: (carried.get(k), reconstructed.get(k)) for k in carried if carried.get(k) != reconstructed.get(k)} }")


def test_an_unlabelled_root_falls_through_to_production():
    """If nothing upstream produced it, this IS first production — carry must not swallow it."""
    terrain = _terrain_payload()
    alias_of = _const("KL_STRIKE_ALIAS_OF")
    kk, root = next(iter(alias_of.items()))
    md = {kk: terrain[root]}
    producer = _CountingProducer()
    labels = _build_kl_labels(terrain, {}, md, producer)   # upstream produced NOTHING
    assert len(producer.calls) == 1, (
        "with no upstream label, the value was neither carried nor produced — it would render "
        "as absent even though the level is real")
    assert labels[kk] == format_strike_for_display(terrain[root])


# ── the shipped code really does this ───────────────────────────────────────────────────────

def test_the_shipped_assembler_carries(  # noqa: D103
):
    """Guard the real call site, not just the rule expressed in this file."""
    src = _src()
    i = src.find('md["kl_strike_labels"]')
    assert i > 0, "the kl_ label assembly is gone"
    block = src[i:i + 900]
    assert "_carried_labels" in block, (
        "the kl_ assembler no longer reads the already-produced labels — it is reconstructing")
    assert "KL_STRIKE_ALIAS_OF" in block, "the assembler does not consult the alias map"
    assert "format_strike_for_display" in block, (
        "the assembler cannot produce at all; the ten first-production keys would go dark")
