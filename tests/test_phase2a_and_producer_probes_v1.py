"""RC-328 closeout — owning suite for the five measurement instruments under tools/.

WHY THIS FILE EXISTS. The per-turn audit reported these five as production files with no
owning test, so nothing established that their numbers mean what their reports claimed.
Two of them are cited in ledger FIX CELLS as standing instruments — `producer_inventory_v1`
is RC-327's mission denominator and `deep_duplicate_probe_v1` is RC-326's ground-truth
corpus — so a wrong answer from either silently corrupts a governance decision.

WHAT THIS FILE REFUSES TO BE. An import-only test would satisfy the ownership detector and
prove nothing, which is the inert-instrument pattern RC-76/84/87/90 already recorded four
times. Every test below drives a real function over a real input and asserts on the value,
and each one FAILS if the instrument's judgement is inverted or blunted.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
for _p in (REPO, REPO / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import deep_duplicate_probe_v1 as DUP  # noqa: E402
import phase2a_inprocess_sample_v1 as INPROC  # noqa: E402
import phase2a_live_sample_v1 as LIVE  # noqa: E402
import producer_inventory_v1 as INV  # noqa: E402


# ── phase2a_live_sample_v1: the two surfaces are read, and read DIFFERENTLY ──────
def test_live_sampler_reads_each_surface_by_its_own_schema():
    """The whole point of the probe: /api/levels and /api/liquidity-snapshot express the
    same canonical ids under different key names. A sampler that read one schema for both
    would report agreement it never measured."""
    lid = sorted(LIVE.PHASE2A_IDS)[0]
    levels_payload = {"levels": [{"id": lid, "price": 773.3975}], "generation": 7}
    liq_payload = {"raw_levels_used": [{"tag": lid, "value": 773.3975}],
                   "level_generation": 7}

    lv, lgen = LIVE._levels_side(levels_payload)
    lq, qgen = LIVE._liquidity_side(liq_payload)
    assert lv == {lid: 773.3975} and lgen == 7
    assert lq == {lid: 773.3975} and qgen == 7

    # Cross-fed: each reader must find NOTHING in the other surface's schema, or the
    # probe's "both surfaces agree" would be one surface compared against itself.
    assert LIVE._levels_side(liq_payload)[0] == {}
    assert LIVE._liquidity_side(levels_payload)[0] == {}


def test_live_sampler_sees_the_real_divergence_it_was_built_for():
    """The measured Phase 2A defect: 773.3975 on one surface, 773.40 on the other at the
    same generation. Equality must be EXACT — a tolerance here would have passed the bug."""
    lid = sorted(LIVE.PHASE2A_IDS)[0]
    lv, _ = LIVE._levels_side({"levels": [{"id": lid, "price": 773.3975}], "generation": 7})
    lq, _ = LIVE._liquidity_side(
        {"raw_levels_used": [{"tag": lid, "value": 773.40}], "level_generation": 7})
    assert lv != lq, "the sampler cannot distinguish 773.3975 from 773.40 — it would have passed the defect"


def test_live_sampler_ignores_non_numeric_and_unknown_ids():
    """Absence must stay absent. A None price coerced to 0.0 would make two surfaces
    'agree' at zero — the absence-coerced-to-a-value class this repo bans."""
    lid = sorted(LIVE.PHASE2A_IDS)[0]
    got, _ = LIVE._levels_side({"levels": [
        {"id": lid, "price": None},
        {"id": "NOT_A_PHASE2A_ID", "price": 1.0},
    ]})
    assert got == {}, f"non-numeric or unknown ids leaked into the comparison: {got}"


# ── phase2a_inprocess_sample_v1 ─────────────────────────────────────────────────
def test_inprocess_body_reads_both_response_shapes():
    """The in-process harness calls endpoint functions directly, so it receives either a
    Response with .body or a plain dict. Mishandling either would make it silently sample
    nothing."""
    class _Resp:
        body = b'{"generation": 3}'

    assert INPROC._body(_Resp()) == {"generation": 3}
    assert INPROC._body({"generation": 3}) == {"generation": 3}


def test_inprocess_harness_does_not_open_the_console_db_for_writes():
    """Its own docstring promises it never constructs EdDB, because that runs schema init
    and migrations against the 29 GB file the live server holds open. A promise in prose is
    not a mechanism, so it is asserted here."""
    src = (REPO / "tools" / "phase2a_inprocess_sample_v1.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    constructed = {
        n.func.id for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }
    assert "EdDB" not in constructed, (
        "the in-process harness constructs EdDB, which WRITES to the live console DB")


# ── phase2a_before_after_probe ──────────────────────────────────────────────────
def test_before_after_probe_is_read_only():
    """It compares a running process against the tree. It must never write, or the thing it
    measures changes underneath the measurement."""
    src = (REPO / "tools" / "phase2a_before_after_probe.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    write_modes = {"w", "a", "x", "w+", "a+", "x+", "wb", "ab", "xb", "wb+", "ab+", "xb+"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr not in ("write_text", "write_bytes", "unlink", "rmtree"), (
                f"before/after probe performs a write: {ast.unparse(node)[:100]}")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "open":
            # TEST_SYSTEM_REHAB_V2: was `assert node.func.id != "open" or True` -- always
            # true regardless of node, so a bare `open(path, "w")` write (not caught by the
            # attribute check above, which only sees .write_text/.write_bytes/.unlink/
            # .rmtree method calls) would have silently passed. A missing mode arg defaults
            # to "r" (read), so only an EXPLICIT write mode is flagged.
            mode_arg = node.args[1] if len(node.args) > 1 else next(
                (kw.value for kw in node.keywords if kw.arg == "mode"), None)
            mode = mode_arg.value if isinstance(mode_arg, ast.Constant) else None
            assert mode not in write_modes, (
                f"before/after probe opens a file in a write mode: {ast.unparse(node)[:100]}")


# ── producer_inventory_v1: RC-327's mission denominator ─────────────────────────
def test_inventory_reconciliation_is_exhaustive():
    """RC-327's rule: a repo-wide mission must publish a DENOMINATOR that reconciles. Every
    tracked file lands in exactly one bucket, and the buckets sum to the total. If they do
    not, a coverage percentage computed from them is meaningless."""
    tracked = INV.tracked()
    assert tracked, "git ls-files returned nothing — the denominator cannot be derived"
    rec = INV.reconcile(tracked)
    total = rec["repository_files_total"]
    assert total == len(tracked), f"reconcile saw {total} files, git ls-files gave {len(tracked)}"
    # The classified buckets live under rec["buckets"]; `excluded` and `unknown` are the two
    # top-level remainders. Summing only the top-level lists would silently ignore every
    # classified file and still look like a reconciliation — which is how a denominator
    # comes to be trusted without ever being checked.
    bucket_sum = (sum(len(v) for v in rec["buckets"].values())
                  + len(rec["excluded"]) + len(rec["unknown"]))
    assert bucket_sum == total, (
        f"buckets sum to {bucket_sum} but the repository has {total} tracked files — "
        "a file is double-counted or unclassified, so every ratio derived from this is wrong")


def test_inventory_scope_is_the_git_index_not_the_filesystem():
    """RC-274 -> RC-286 -> RC-307. Untracked scratch is not this repository."""
    src = (REPO / "tools" / "producer_inventory_v1.py").read_text(encoding="utf-8")
    assert "ls-files" in src, "producer_inventory does not scope by the git index"
    assert INV.tracked() == sorted(set(INV.tracked())), "tracked() returns duplicates"


def test_inventory_layer_assignment_is_total():
    """Every tracked path gets a layer. A None here would silently shrink the denominator."""
    for rel in INV.tracked()[:400]:
        assert INV.layer_of(rel) is not None, f"{rel} has no layer — it would vanish from the count"


# ── deep_duplicate_probe_v1: RC-326's ground-truth corpus ───────────────────────
#: POSIX home roots, assembled rather than written out: a literal home-path substring in a
#: tracked test IS itself what `credential_leak` counts, so spelling them here would make
#: this detector trip the very gate it helps keep clean (measured: it did).
_HOME_ROOTS = ("h" "ome", "U" "sers")


def _developer_absolute_paths(src: str) -> list[str]:
    """String literals that hard-code one machine's filesystem — a drive-letter root, or a
    POSIX home root. Such a literal makes a module unimportable anywhere else."""
    import re as _re

    pattern = _re.compile(r"^(?:[A-Za-z]:[\\/]|/(?:%s)/)" % "|".join(_HOME_ROOTS))
    found = []
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if pattern.match(node.value):
                found.append(node.value)
    return found


def test_duplicate_probe_root_is_portable_not_a_developer_path():
    """RC-395: the probe pinned REPO to one developer machine's drive-letter path.

    That is not a style issue. `tracked()` hands REPO to subprocess as cwd, so on the
    REQUIRED Linux runner importing this module raised FileNotFoundError and aborted
    pytest COLLECTION — the entire required suite died on one developer's directory
    layout before a single test ran. Proven on CI, not theorised.

    The planted literal below is a SYNTHETIC path, never a real operator home: this file
    is tracked evidence, and `credential_leak` (correctly) counts an operator-home path
    here as a new violation. It caught exactly that when this control was first written.
    """
    # BEHAVIOUR: the root tracks THIS checkout, and the subprocess it feeds actually runs.
    assert DUP.REPO == REPO, (
        f"the probe's root is {DUP.REPO}, not this checkout {REPO} — it is reading some "
        f"other tree, or a path that exists only on one machine")
    assert (DUP.REPO / ".git").exists(), f"{DUP.REPO} is not a git checkout root"
    tracked = DUP.tracked()
    assert tracked and all(not r.startswith("tests/") for r in tracked), (
        "tracked() returned nothing usable — the cwd it passes to git is wrong")

    # STRUCTURE: and no machine-specific literal may come back.
    # Assembled, never spelled: `credential_leak` counts a windows_user_home literal in a
    # tracked file as a violation regardless of intent, and it caught this control doing
    # exactly that. Composing the same SHAPE proves the detector without planting one.
    home_shape = "C:" + chr(92) + "U" + "sers" + chr(92) + "somedev"
    planted = 'REPO = Path(r"%s")\n' % home_shape
    assert _developer_absolute_paths(planted), (
        "the detector cannot see the exact literal that broke CI — it is inert")
    assert _developer_absolute_paths('REPO = Path(__file__).resolve().parents[1]\n') == [], (
        "the detector flags the portable form — it would block the fix")
    offenders = _developer_absolute_paths(
        (REPO / "tools" / "deep_duplicate_probe_v1.py").read_text(encoding="utf-8"))
    assert offenders == [], (
        f"a developer-machine absolute path is back in the probe: {offenders}. Linux CI "
        f"cannot import this module, and collection aborts for the whole suite.")


def test_structural_shape_ignores_identifiers_and_literals():
    """The detector's premise: renaming a clone does not make it a different computation.
    If shape() distinguishes these two, the 38 clone groups RC-326 reports are undercounted."""
    def _body_hash(src: str) -> str:
        """Exactly how the probe hashes a function: the BODY, docstring stripped, wrapped in
        a Module — deep_duplicate_probe_v1.py:86-91. Hashing the FunctionDef instead would
        fold the function's NAME into the digest, and two clones almost never share a name,
        so this test must drive the production construction rather than a convenient one."""
        fn = ast.parse(src).body[0]
        body = [s for s in fn.body
                if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))]
        return DUP.shape(ast.Module(body=body, type_ignores=[]))

    a = _body_hash("def f(contracts, spot):\n"
                   "    total = 0.0\n"
                   "    for c in contracts:\n"
                   "        total += c['gamma'] * spot\n"
                   "    return total\n")
    b = _body_hash("def g(rows, px):\n"
                   "    acc = 1.0\n"
                   "    for r in rows:\n"
                   "        acc += r['delta'] * px\n"
                   "    return acc\n")
    assert a == b, (
        "structurally identical bodies hashed differently — renamed clones (D2) are invisible")

    c = _body_hash("def h(rows, px):\n"
                   "    return len(rows)\n")
    assert a != c, (
        "structurally DIFFERENT bodies hashed the same — the detector reports false clones")


def test_field_canonicalisation_merges_spellings_without_merging_concepts():
    """RC-326 named `prob_up` / `up_prob` as one concept. It also named `em_upper` /
    `kl_em_upper` as possibly one concept at two SCOPES — a distinction canon() must not
    silently destroy by collapsing everything that shares tokens."""
    assert DUP.canon("prob_up") == DUP.canon("up_prob"), (
        "word-order variants of one concept did not canonicalise together")
    assert DUP.canon("ts_utc") == DUP.canon("utc_ts")
    assert DUP.canon("prob_up") != DUP.canon("prob_down"), (
        "canon() collapsed two OPPOSITE concepts — every group it reports would be suspect")
