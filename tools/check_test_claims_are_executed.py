#!/usr/bin/env python3
"""RC-298 — a test that string-matches prose cannot detect a false claim.

WHAT WAS MEASURED (2026-08-07). `tests/test_charm_docstring_states_the_physics_v1.py`, as
written under RC-294, contained eight assertions and every one had the shape

    assert "<a sentence I wrote>" in DOC

It confirmed only that I had written what I had written. The claim it locked — "calls sell,
puts buy" — was FALSE, and the suite was green, because a string match cannot disagree with
the string. One line of execution refuted the entire file: `math_levels.bs_charm` takes no
call/put argument at all, and its sign tracks moneyness (+0.7654 at K=90, −1.5684 at K=105
for spot 100).

The identical shape produced RC-281 (three `# silent-zero-ok:` reasons) and RC-290 (both
`# caps-ok:` reasons). In each case my verification method for a CLAIM was reading, and
reading is what produced the claim. Cursor refuted all of them by execution.

THE RULE. Not "is this claim true" — no checker can know that. The rule is narrower and
mechanical: a test file that makes assertions about SOURCE TEXT must also assert on a value
obtained by CALLING something. A file that only reads text can never find out whether the
text is right, and the co-staged-test gate (RC-49) currently accepts it as a lock.

WHY NOT JUST BAN TEXT ASSERTIONS. They are legitimate and this repo needs them: proving an
exemption marker carries a reason, that a retired pattern has not returned, that a gate is
wired into a live path. The defect is a file made ENTIRELY of them while claiming to test
behaviour. So the rule is a mix requirement, not a prohibition.

    .venv/Scripts/python.exe tools/check_test_claims_are_executed.py
"""

from __future__ import annotations

import argparse
import ast
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

#: Reading source or docs — the shapes that produce a prose assertion.
_TEXT_SOURCES = (
    "getsource", "getdoc", "getcomments", "read_text", "__doc__", "readlines",
)

#: Files that are legitimately text-only: they audit the REPOSITORY as an artefact
#: (inventories, registers, wiring maps) rather than asserting how code behaves. Each is
#: listed with the reason, because an unexplained exemption is RC-276 all over again.
TEXT_ONLY_ALLOWED: tuple[tuple[str, str], ...] = (
    ("tests/test_operator_law_guard_repo_scope_v1.py",
     "audits guard source wiring, not a computed value"),
    ("tests/test_enforced_check_negative_controls_v1.py",
     "asserts every enforced check owns a negative control — a property of the check list"),
)


def _tracked_test_files() -> list[Path]:
    """RC-274/RC-286: scope is the git index, never a filesystem walk."""
    proc = subprocess.run(
        ["git", "ls-files", "-z", "--", "tests/*.py"],
        cwd=REPO, capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError("git ls-files failed, so the scan scope is unknown: "
                           + proc.stderr.strip())
    return [REPO / p for p in proc.stdout.split("\0") if p]


def _allowed(rel: str) -> bool:
    return any(rel == p for p, _ in TEXT_ONLY_ALLOWED)


#: Builtins and helpers whose presence does not mean the subject was exercised.
_NEUTRAL_CALLS = frozenset({
    "len", "str", "set", "sorted", "list", "any", "all", "int", "float", "dict",
    "tuple", "repr", "print", "open", "parse", "walk", "compile", "search",
    "findall", "match", "sub", "split", "join", "strip", "startswith", "endswith",
    "replace", "count", "index", "find", "lower", "upper", "splitlines", "format",
    "approx", "raises", "fixture", "mark", "param", "setattr", "getattr",
})


def analyse(tree: ast.AST) -> tuple[int, int]:
    """Return (prose_assertions, subject_calls) for one parsed test module.

    A PROSE assertion reads source or docstring text and compares it. A SUBJECT CALL is any
    invocation anywhere in the module that is neither a text reader nor a neutral builtin.

    Counted at MODULE scope on purpose. An earlier version required the call to appear
    inside the assert expression and produced a false positive on
    tests/test_pred_1c_horizon_persistence_v1.py, which calls `_build_snapshot_dict(...)`
    and then asserts on the returned dict — the ordinary shape of a good test. The question
    this checker asks is "does this file exercise the code at all", and where the call sits
    relative to the assertion is not part of that question.
    """
    prose_asserts = 0
    subject_calls = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Assert):
            for sub in ast.walk(node.test):
                if isinstance(sub, ast.Attribute) and sub.attr in _TEXT_SOURCES:
                    prose_asserts += 1
                    break
                if isinstance(sub, ast.Name) and sub.id in (
                        "DOC", "SRC", "src", "doc", "text", "html", "ui"):
                    prose_asserts += 1
                    break
        elif isinstance(node, ast.Call):
            name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
            if name and name not in _TEXT_SOURCES and name not in _NEUTRAL_CALLS:
                subject_calls += 1
    return prose_asserts, subject_calls


#: Calls whose RESULT is file text, for the per-function taint below.
_TEXT_READERS = frozenset({"read_text", "getsource", "getdoc", "getcomments", "readlines"})


def source_text_only_functions() -> list[str]:
    """Every test FUNCTION whose every assertion is about file text. The gate's blind spot.

    RC-311. `violations()` above judges at MODULE scope, so one executing test anywhere in a
    file satisfies the rule for every sibling. That was a deliberate widening — the
    per-function form produced five false positives on ordinary tests — and it is why the
    gate reported PASS on all six shadow-assertion tests RC-308 found the next day, each of
    them sitting beside a healthy test in the same file.

    This function measures what the widening gave up. It is NOT enforced: the count was 264
    when RC-308 opened and is 261 with its six repairs landed, and most of those functions are the inventory, register and wiring audits RC-298's own
    docstring defends, which have no value to compute. Enforcing at 264 exemptions would be
    the allowlist habit RC-276 removed. What the number does is make a future widening of
    this gate's scope visible as a moved figure rather than as continued silence — the same
    device RC-286 used for its filesystem-scanner sweep.

    WHAT THE NUMBER IS NOT (2026-08-17). It is not a count of bad tests, and lowering it is
    not by itself an improvement. Two different things are in it:

      INHERENTLY STRUCTURAL — the asserted property is about the REPOSITORY: that exactly
      one definition exists, that a formula is not independently re-encoded, that a
      forbidden literal is absent, that a governed artefact carries the keys a row claims.
      Uniqueness, duplication and absence have no faithful runtime call — a function that
      behaves correctly today says nothing about whether a second copy of it exists — so
      these belong here and are not defects.

      AVOIDABLE SOURCE-TEXT PROXY — the asserted property is BEHAVIOUR, restated as a
      spelling. `str.index` offsets standing in for call ordering, a matched call string
      standing in for what a producer publishes, the checker's own regexes restated
      instead of its verdict. These are the RC-308 class, and the repair is to assert the
      value, not to register an exemption.

    So a MOVE in this figure must be ACCOUNTED FOR, not merely re-baselined: each new
    entry is either shown to be inherently structural, or it is rewritten to assert the
    behaviour and leaves on its own. Note also that the measurement is coarser than the
    distinction — an assertion on a value COMPUTED from file text still counts as
    source-text here, because the taint follows the argument. Tightening that was tried
    and reverted 2026-08-17: every candidate rule that cleared such assertions also
    cleared `isinstance(...)`, `m.group(1)` and text-derived local helpers, i.e. widened
    the gate instead of sharpening it. A repaired test may therefore stay in the count;
    say so in the row rather than loosening the measurement to make the number move.
    """
    out: list[str] = []
    for path in _tracked_test_files():
        rel = path.relative_to(REPO).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not fn.name.startswith("test_"):
                continue
            tainted = _names_holding_file_text(fn)
            asserts = [a for a in ast.walk(fn) if isinstance(a, ast.Assert)]
            if len(asserts) < 2:
                continue
            if all(_asserts_on_text(a, tainted) for a in asserts):
                out.append(f"{rel}:{fn.lineno} {fn.name}")
    return out


def _names_holding_file_text(fn: ast.AST) -> set[str]:
    """Local names bound, transitively, from a file-text read inside this function."""
    tainted: set[str] = set()
    changed = True
    while changed:
        changed = False
        for node in ast.walk(fn):
            if not isinstance(node, ast.Assign) or not isinstance(node.targets[0], ast.Name):
                continue
            name = node.targets[0].id
            if name in tainted:
                continue
            hit = any(isinstance(s, ast.Attribute) and s.attr in _TEXT_READERS
                      for s in ast.walk(node.value))
            if not hit:
                hit = any(isinstance(s, ast.Name) and s.id in tainted
                          for s in ast.walk(node.value))
            if hit:
                tainted.add(name)
                changed = True
    return tainted


def _asserts_on_text(node: ast.Assert, tainted: set[str]) -> bool:
    for sub in ast.walk(node.test):
        if isinstance(sub, ast.Name) and sub.id in tainted:
            return True
        if isinstance(sub, ast.Attribute) and sub.attr in _TEXT_READERS:
            return True
    return False


def violations() -> list[str]:
    out: list[str] = []
    for path in _tracked_test_files():
        rel = path.relative_to(REPO).as_posix()
        if _allowed(rel):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        prose_n, exec_n = analyse(tree)
        if prose_n >= 3 and exec_n == 0:
            out.append(
                f"{rel}: {prose_n} assertion(s) match SOURCE TEXT and {exec_n} call(s) "
                f"exercise the subject. A string match cannot disagree with the string, "
                f"so this file "
                f"cannot detect a false claim — it only confirms the text was written "
                f"(RC-298; RC-294 shipped exactly this and locked 'calls sell, puts buy', "
                f"which one call to bs_charm refutes). Add at least one assertion on a "
                f"value returned by CALLING the subject, or register the file in "
                f"TEXT_ONLY_ALLOWED with the reason it audits an artefact rather than a "
                f"behaviour.")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--measure", action="store_true",
                    help="RC-311: also report the per-FUNCTION count this module-scope "
                         "gate does not see, so PASS cannot read as 'none in the repo'")
    args = ap.parse_args(argv)
    if args.measure:
        fns = source_text_only_functions()
        print(f"per-function source-text-only tests (MEASURED, not enforced): {len(fns)}")
        for f in fns:
            print("  " + f)
    v = violations()
    if v:
        print("check_test_claims_are_executed: FAIL — prose-only test files:")
        for line in v:
            print("  " + line)
        return 1
    if not args.quiet:
        print("check_test_claims_are_executed: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
