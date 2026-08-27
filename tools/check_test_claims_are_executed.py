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

    RC-317 (audit reopen 2026-08-25): the original form keyed prose detection on a FIXED
    name list, so `blob = _norm(inspect.getdoc(x)); assert 'claim' in blob` scored
    (0 prose, 1 subject) — the gate's own founding file passed it. Both counters now follow
    the taint that `_names_holding_file_text` already computed for the RC-311 lane: an
    assert on any name bound (transitively) from a text reader is prose, and a call whose
    arguments carry that taint is a text transform, not subject execution. MEASURED before
    landing: zero additional files flagged on the whole tracked test corpus, and the RC-317
    probe flips from (0, 1)-pass to (3, 0)-caught.
    """
    tainted = _names_holding_file_text(tree)
    prose_asserts = 0
    subject_calls = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Assert):
            for sub in ast.walk(node.test):
                if isinstance(sub, ast.Attribute) and sub.attr in _TEXT_SOURCES:
                    prose_asserts += 1
                    break
                if isinstance(sub, ast.Name) and (
                        sub.id in tainted or sub.id in (
                            "DOC", "SRC", "src", "doc", "text", "html", "ui")):
                    prose_asserts += 1
                    break
        elif isinstance(node, ast.Call):
            name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
            if not name or name in _TEXT_SOURCES or name in _NEUTRAL_CALLS:
                continue
            carries_taint = any(
                (isinstance(s, ast.Name) and s.id in tainted)
                or (isinstance(s, ast.Attribute) and s.attr in _TEXT_READERS)
                for a in list(node.args) + [k.value for k in node.keywords]
                for s in ast.walk(a))
            if not carries_taint:
                subject_calls += 1
    return prose_asserts, subject_calls


#: Calls whose RESULT is file text — the taint that analyse() and _names_holding_file_text follow.
_TEXT_READERS = frozenset({"read_text", "getsource", "getdoc", "getcomments", "readlines"})


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
    args = ap.parse_args(argv)
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
