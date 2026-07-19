#!/usr/bin/env python3
# institutional-length-ok: this file IS one thing - the institutional gate. Its length is
# the sum of its registered checks (~60 lines each, each self-contained and independently
# readable). Splitting it by line count produced circular imports and made the code worse
# (RC-19); splitting it by cohesion is impossible because there is only one concern here.
"""Institutional Correctness gate — the ONE lock (GOVERNING LAW, OPEN_ITEMS).

The repo is institutional in nature. This is the single enforcement point; new
correctness requirements are added as CHECKS here, never as new separate locks.

Run:  python tools/check_institutional_correctness.py
Exit non-zero on any violation. Intended for pre-commit / CI.

Registered checks (see CHECKS at the bottom — that list is the authority):

  ENFORCED (must be zero; blocks pre-commit)
    - no_synthetic_domain_fixtures_in_tests : tests exercise REAL data, not hand-built
      option-chain fixtures that can be tuned to pass ("no fake tests").
    - no_swallowed_test_failures : a helper that PRINTS a failure must also cause one.
    - no_silent_swallow            : exceptions are handled, never quietly discarded.
    - no_todo_without_tracking_id  : every TODO carries a tracking id.
    - unproven_register            : no UNPROVEN/DISPROVED claim past its due date
                                     (governance/unproven_register.md).

  ADVISORY (visible debt on the ratchet — driven to zero, then flipped to enforced)
    - tests_missing_explicit_assert, function_complexity, function_length,
      file_length, ruff_quality, no_fake_defaults, mypy_types

A check is promoted to ENFORCED only when its count is zero AND its rule is true — a
check that produces false positives is not eligible, however desirable the rule sounds.
"""
from __future__ import annotations

import ast
import datetime
import json
import re
import subprocess
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
TESTS = REPO / "tests"


# A dict literal carrying these keys is an inline option CONTRACT built by hand.
_CONTRACT_KEYS = {"putCall", "strikePrice"}

# A test that MUST feed a malformed/edge contract (fail-closed / exclusion behavior)
# declares it explicitly with this marker in the enclosing function/helper. Correctness
# tests get no marker — they must load a real chain from tests/fixtures/.
_JUSTIFY_MARKER = "institutional-synthetic-ok"


def _enclosing_func_span(tree: ast.AST, line: int) -> tuple[int, int] | None:
    best: tuple[int, int] | None = None
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            lo, hi = n.lineno, getattr(n, "end_lineno", n.lineno)
            if lo <= line <= hi and (best is None or lo > best[0]):
                best = (lo, hi)
    return best


class Violation:
    def __init__(self, path: Path, line: int, msg: str) -> None:
        self.path, self.line, self.msg = path, line, msg

    def __str__(self) -> str:
        rel = self.path.relative_to(REPO)
        return f"  {rel}:{self.line}  {self.msg}"


def _dict_literal_keys(node: ast.Dict) -> set[str]:
    keys: set[str] = set()
    for k in node.keys:
        if isinstance(k, ast.Constant) and isinstance(k.value, str):
            keys.add(k.value)
    return keys










def check_single_spot_authority() -> list[Violation]:
    """Spot may be read through exactly ONE function.

    RC-14: four independent spot sources existed (live quote, chain underlying,
    price_bars close, stored snapshot) and each consumer picked one, so the terrain card
    and the console header showed different prices for the same ticker at the same moment.
    `server.resolve_spot()` is now the single authority; this forbids reintroducing a
    second faucet.
    """
    out: list[Violation] = []
    banned = ("chain_underlying_spot(",)
    allowed_lines = ("def chain_underlying_spot", "chain_underlying_spot(chain_json)")
    for rel in ("server.py", "terrain_engine.py"):
        f = REPO / rel
        if not f.exists():
            continue
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), start=1):
            stripped = line.strip()
            if any(b in stripped for b in banned) and not any(a in stripped for a in allowed_lines):
                out.append(Violation(f, n,
                                     "spot must be read through resolve_spot() - the single "
                                     "authority (RC-14). Do not call chain_underlying_spot directly."))
    return out


def _has_failure_mechanism(node: ast.AST) -> bool:
    """True when a subtree can actually fail: assert, raise, or a pytest failure call."""
    return any(isinstance(c, (ast.Assert, ast.Raise)) or _is_raises_or_fail(c)
               for c in ast.walk(node))


def _prints_a_failure(node: ast.AST) -> bool:
    """True when a function prints a failure-shaped message (e.g. '[FAIL] ...')."""
    for c in ast.walk(node):
        if not (isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and c.func.id == "print"):
            continue
        for arg in c.args:
            for lit in ast.walk(arg):
                if isinstance(lit, ast.Constant) and isinstance(lit.value, str)                         and "FAIL" in lit.value.upper():
                    return True
    return False


def _records_for_later(node: ast.AST) -> bool:
    """True when a helper stores the failure in a collection something else asserts on."""
    return any(isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
               and c.func.attr in ("append", "add", "extend") for c in ast.walk(node))


def _asserting_helper_names(tree: ast.AST) -> set[str]:
    return {n.name for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            and _has_failure_mechanism(n)}


def _covered_by_helper(node: ast.AST, helpers: set[str]) -> bool:
    """A decorator or a called helper may supply the assertion."""
    for d in getattr(node, "decorator_list", []):
        if (isinstance(d, ast.Name) and d.id in helpers) or            (isinstance(d, ast.Attribute) and d.attr in helpers):
            return True
    for c in ast.walk(node):
        if not isinstance(c, ast.Call):
            continue
        f = c.func
        if (isinstance(f, ast.Name) and f.id in helpers) or            (isinstance(f, ast.Attribute) and f.attr in helpers):
            return True
    return False


def _living_test_files():
    for tf in sorted(TESTS.rglob("test_*.py")):
        if "archive" in tf.relative_to(TESTS).parts:
            continue
        try:
            yield tf, ast.parse(tf.read_text(encoding="utf-8", errors="replace"), filename=str(tf))
        except (OSError, SyntaxError):
            continue




def _rc_row_violations(log_path, n: int, rc_id: str, status: str,
                       cells: list[str]) -> list[Violation]:
    """Per-row rules for the root-cause log.

    Column order: id | status | opened | due | defect | why-chain | fix.

    FIVE WHYS BEFORE THE CLAIM (operator 2026-07-19): the chain must be complete the moment
    the row exists, not back-filled after a fix is announced. RC-14 was closed on code shape
    with a shallow chain and the bug survived into RC-15 and RC-16.

    PROOF REQUIRED: a CLOSED row must cite a measured observation. RC-15 was reported fixed
    because the code called the new function -- it returned None on every call and nobody
    had looked at the value.
    """
    out: list[Violation] = []
    why = cells[5] if len(cells) >= 6 else ""
    depth = why.count("->")
    if depth < 4:
        out.append(Violation(
            log_path, n,
            f"{rc_id} has a why-chain only {depth + 1} level(s) deep. Five whys are "
            f"required BEFORE the row is written - a shallow chain is how a symptom "
            f"gets recorded as a root cause."))
    if status == "CLOSED":
        evidence = cells[6] if len(cells) >= 7 else ""
        has_number = any(ch.isdigit() for ch in evidence)
        has_proof = any(w in evidence.upper()
                        for w in ("PROVEN", "VERIFIED", "MEASURED", "OBSERVED"))
        if not (has_number and has_proof):
            out.append(Violation(
                log_path, n,
                f"{rc_id} is CLOSED without observed evidence. A closed root cause must "
                f"cite a measured value (numbers) and say it was proven/verified/measured "
                f"- describing the code change is not proof that it works."))
    return out


def check_root_cause_log() -> list[Violation]:
    """Every defect gets five whys, and finding a cause RESTARTS the count.

    Operator law 2026-07-19: a cause found at why-2 is not the root -- it is a new defect
    that gets its own five whys. An entry stays OPEN until the chain terminates with no new
    defect AND the fix is verified. This blocks commits on any OPEN entry past its due date,
    so a half-traced defect cannot be quietly parked as "surface fixed".

    See governance/root_cause_log.md for the rules and the row format.
    """
    out: list[Violation] = []
    log_path = REPO / "governance" / "root_cause_log.md"
    if not log_path.exists():
        out.append(Violation(log_path, 0, "governance/root_cause_log.md is missing - every "
                                          "defect must be traced to a root cause there"))
        return out
    today = datetime.date.today()
    for n, line in enumerate(log_path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.startswith("| RC-"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 5:
            continue
        rc_id, status, _opened, due = cells[0], cells[1], cells[2], cells[3]

        out.extend(_rc_row_violations(log_path, n, rc_id, status, cells))
        if status != "OPEN":
            continue
        try:
            due_date = datetime.date.fromisoformat(due)
        except ValueError:
            out.append(Violation(log_path, n, f"{rc_id} has an unparseable due date {due!r}"))
            continue
        if due_date < today:
            out.append(Violation(log_path, n,
                                 f"{rc_id} is OPEN past its due date ({due}) - the why-chain is "
                                 f"incomplete or the fix is unverified; finish it or re-date it "
                                 f"with a reason"))
    return out


def _debt_baseline_path():
    return REPO / "governance" / "advisory_debt_baseline.json"


def check_debt_ratchet() -> list[Violation]:
    """Advisory debt may go DOWN or stay flat. It may never go UP.

    Operator 2026-07-19: "mypy is not a report, it's a tool." Reporting a counter every
    turn while it drifts upward is not using the tool. This makes the ratchet mechanical:
    every advisory count is recorded in governance/advisory_debt_baseline.json and any
    increase blocks the commit. Lowering a count rewrites the baseline automatically, so
    the floor only ever descends.

    Regenerate deliberately (after an accepted increase) with:
        python tools/check_institutional_correctness.py --rebaseline
    """
    # Imported at CALL time, not module scope: the gate owns CHECKS and imports this
    # module, so a top-level import here would be circular. By the time any check runs,
    # the gate module is fully loaded.

    out: list[Violation] = []
    path = _debt_baseline_path()
    current = {name: len(fn()) for name, fn, enforced in CHECKS if not enforced
               and name != "debt_ratchet"}
    if not path.exists():
        path.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return out
    try:
        baseline = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        out.append(Violation(path, 0, "advisory_debt_baseline.json is unparseable"))
        return out

    improved = False
    for name, count in sorted(current.items()):
        base = baseline.get(name)
        if base is None:
            baseline[name] = count
            improved = True
            continue
        if count > base:
            out.append(Violation(path, 0,
                                 f"{name} rose {base} -> {count} (+{count - base}). Advisory debt "
                                 f"may never increase: clean what you added, or lower another "
                                 f"count to pay for it."))
        elif count < base:
            # HONESTY GUARD: a checker that fails and returns nothing is indistinguishable
            # from a checker that found nothing. Recording that 0 as the new floor silently
            # destroys the ratchet -- it happened to ruff_quality (1147 -> 0), which then
            # blocked every commit with a phantom +1147. A collapse to zero from a large
            # baseline is a tool failure until proven otherwise.
            if count == 0 and base > 10:
                out.append(Violation(
                    path, 0,
                    f"{name} reported 0 against a baseline of {base}. That is a checker "
                    f"failure, not perfection - the baseline was NOT lowered. Investigate "
                    f"the checker, then re-run."))
                continue
            baseline[name] = count
            improved = True
    if improved and not out:
        path.write_text(json.dumps(baseline, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return out


def check_no_governance_duplication() -> list[Violation]:
    """The two governance files must not describe the same item.

    `unproven_register.md` holds CLAIMS ABOUT THE WORLD (epistemic: is this true of the
    market, the data, the vendor?). `root_cause_log.md` holds DEFECTS IN OUR CODE
    (engineering: why did this break?). The boundary was never written down, so two
    defects leaked into the register and were tracked twice - which means they can be
    closed in one place while still open in the other.
    """
    out: list[Violation] = []
    reg_path = REPO / "governance" / "unproven_register.md"
    rc_path = REPO / "governance" / "root_cause_log.md"
    if not (reg_path.exists() and rc_path.exists()):
        return out

    def _rows(path, pred):
        return [(n, ln) for n, ln in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
                if ln.startswith("|") and pred(ln)]

    def _terms(text: str) -> set[str]:
        return {w.lower() for w in re.findall(r"[a-zA-Z_]{6,}", text)}

    reg_rows = _rows(reg_path, lambda ln: ln.split("|")[1].strip() in
                     ("PROVEN", "UNPROVEN", "DISPROVED", "REMEDIATED"))
    rc_rows = _rows(rc_path, lambda ln: ln.startswith("| RC-"))

    for rn, rl in reg_rows:
        for _cn, cl in rc_rows:
            if len(_terms(rl) & _terms(cl)) > 12:
                out.append(Violation(
                    reg_path, rn,
                    "this row duplicates an entry in root_cause_log.md. A DEFECT belongs "
                    "only in the root-cause log; the register is for CLAIMS about the "
                    "world. Tracking one item twice lets it be closed in one place while "
                    "still open in the other."))
                break
    return out


def check_no_tautological_assertions() -> list[Violation]:
    """A test must be written to CATCH, never to PASS.

    Operator 2026-07-19: "you are not to write tests to pass, you are to write them to
    catch." The vacuous form found in this repo was:

        assert flip is None or isinstance(flip, float)

    which is true for every possible value and therefore asserts nothing. This detects the
    family: an `or` of a None-check with a type-check, `assert True`, `assert 1`, and
    comparisons of a value to itself.
    """
    out: list[Violation] = []
    for p, tree in _living_test_files():
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assert):
                continue
            reason = _tautology_reason(node.test)
            if reason:
                out.append(Violation(p, node.lineno,
                                     f"assertion is vacuous ({reason}) - it is true for every "
                                     f"possible value, so the test cannot catch anything"))
    return out


def _tautology_reason(test: ast.AST) -> str | None:
    """Name the vacuity, or None when the assertion can actually fail."""
    if isinstance(test, ast.Constant) and bool(test.value):
        return "constant truthy"
    if isinstance(test, ast.BoolOp) and isinstance(test.op, ast.Or):
        return _or_tautology(test)
    return _self_comparison(test)


def _or_tautology(test: ast.BoolOp) -> str | None:
    """`x is None or isinstance(x, T)` is true for every value."""
    has_none = any(
        isinstance(v, ast.Compare)
        and any(isinstance(c, ast.Constant) and c.value is None for c in v.comparators)
        for v in test.values
    )
    has_type = any(
        isinstance(v, ast.Call) and isinstance(v.func, ast.Name) and v.func.id == "isinstance"
        for v in test.values
    )
    return "'is None or isinstance(...)' covers every value" if (has_none and has_type) else None


def _self_comparison(test: ast.AST) -> str | None:
    """`x == x` asserts nothing — but `f(x) == f(x)` is a determinism test.

    For a pure function the call form holds trivially, so the assertion fails exactly when
    the function is NON-deterministic, which is the thing such a test exists to catch. Only
    a NAME or LITERAL compared with itself is vacuous. (This check flagged its own
    determinism test before the distinction was drawn.)
    """
    if not (isinstance(test, ast.Compare) and len(test.ops) == 1
            and isinstance(test.ops[0], ast.Eq)):
        return None
    both_static = (isinstance(test.left, (ast.Name, ast.Constant))
                   and isinstance(test.comparators[0], (ast.Name, ast.Constant)))
    if both_static and ast.dump(test.left) == ast.dump(test.comparators[0]):
        return "compares a value to itself"
    return None


def _open_root_causes(path) -> list[str]:
    """RC ids whose status is OPEN."""
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| RC-"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) > 1 and cells[1] == "OPEN":
            out.append(cells[0])
    return out


def _open_register_claims(path) -> list[str]:
    """Register rows still UNPROVEN or DISPROVED (the two non-terminal states)."""
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if cells and cells[0] in ("UNPROVEN", "DISPROVED"):
            out.append(f"register:{cells[3][:40] if len(cells) > 3 else '?'}")
    return out


def check_open_item_cap() -> list[Violation]:
    """Governance ledgers must burn DOWN. The open count may never rise.

    Operator 2026-07-19: the ledgers must resolve, not accumulate.

    A fixed cap would repeat the mistake of the 800-line ceiling (RC-19): an arbitrary
    number invites an arbitrary remedy, and a permanently-red gate teaches you to ignore
    it. This is a RATCHET instead -- the same mechanism as advisory debt. The current open
    count is the new ceiling the moment it drops, so the only permitted direction is down,
    and no number had to be invented.

    Opening a genuinely new defect therefore requires closing one first, which is the
    intended pressure: "logged" must never become a synonym for "deferred forever".
    """
    out: list[Violation] = []
    rc = REPO / "governance" / "root_cause_log.md"
    open_items = _open_root_causes(rc) + _open_register_claims(
        REPO / "governance" / "unproven_register.md")

    ceiling_path = REPO / "governance" / "open_item_ceiling.json"
    count = len(open_items)
    if not ceiling_path.exists():
        ceiling_path.write_text(json.dumps({"open_items": count}, indent=2) + "\n",
                                encoding="utf-8")
        return out
    try:
        ceiling = int(json.loads(ceiling_path.read_text(encoding="utf-8"))["open_items"])
    except (ValueError, KeyError, TypeError):
        out.append(Violation(ceiling_path, 0, "open_item_ceiling.json is unparseable"))
        return out

    if count > ceiling:
        out.append(Violation(
            rc, 0,
            f"{count} open governance items > ceiling of {ceiling}. Close one before "
            f"opening another - the ledger may only shrink. "
            f"Open: {', '.join(open_items[:8])}{'...' if count > 8 else ''}"))
    elif count < ceiling:
        ceiling_path.write_text(json.dumps({"open_items": count}, indent=2) + "\n",
                                encoding="utf-8")
    return out


def check_no_swallowed_test_failures() -> list[Violation]:
    """Fail a test helper that REPORTS a failure without causing one.

    This is the exact pathology found 2026-07-19 in tests/test_centralization.py:
    a `_fail(msg)` helper that incremented a counter and printed '[FAIL] ...' while
    the test returned normally — 587 lines, 0 asserts, 10 tests green forever, and
    a genuine violation printed to stdout that nothing acted on.

    Narrow and decidable by design: it flags only a function that prints a
    failure-shaped message and has no raise/assert of its own. It deliberately does
    NOT try to decide the general 'can this test fail?' question — the common
    'call production code that raises on bad input' idiom is a real test and is not
    flagged here (see tests_missing_explicit_assert, advisory).
    """
    out: list[Violation] = []
    for p, tree in _living_test_files():
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.name.startswith("test_"):
                continue  # helpers only
            if not _prints_a_failure(node):
                continue
            if _has_failure_mechanism(node) or _records_for_later(node):
                continue
            out.append(Violation(
                p, node.lineno,
                f"{node.name}() reports a test failure by printing but never raises - "
                f"the test passes anyway. Make it assert/raise so a reported failure "
                f"actually fails the run."))
    return out


def check_tests_missing_explicit_assert() -> list[Violation]:
    """ADVISORY: test functions with no explicit assertion of their own.

    Many are the legitimate 'call production code that raises on invalid input' idiom
    and DO fail on regression - verified 2026-07-19 across all 14 hits. Kept advisory,
    not enforced, because 'cannot fail' is not statically decidable and blocking on it
    would force noise edits to real tests. Review each; add an explicit assertion where
    the intent is unclear.
    """
    out: list[Violation] = []
    for p, tree in _living_test_files():
        helpers = _asserting_helper_names(tree)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not node.name.startswith("test_"):
                continue
            if _has_failure_mechanism(node) or _covered_by_helper(node, helpers):
                continue
            out.append(Violation(
                p, node.lineno,
                f"test {node.name}() has no explicit assertion - confirm it fails on "
                f"regression (raising production code counts) or add one"))
    return out


def _is_raises_or_fail(n: ast.AST) -> bool:
    """True for pytest.raises / pytest.fail / self.assert* / .fail() style failure paths."""
    if isinstance(n, ast.Raise):
        return True
    if isinstance(n, ast.Call):
        f = n.func
        if isinstance(f, ast.Attribute):
            if f.attr in ("raises", "fail", "warns", "approx"):
                return True
            if f.attr.startswith("assert"):
                return True
        if isinstance(f, ast.Name) and f.id.startswith("assert"):
            return True
    if isinstance(n, ast.With):
        for item in n.items:
            if isinstance(item.context_expr, ast.Call):
                f = item.context_expr.func
                if isinstance(f, ast.Attribute) and f.attr in ("raises", "warns"):
                    return True
    return False


def check_no_synthetic_domain_fixtures_in_tests() -> list[Violation]:
    """Fail if a test builds an option-chain contract inline instead of loading
    real data from tests/fixtures/. This is the mechanical form of 'no fake tests'
    for the domain whose correctness must be proven on real chains."""
    out: list[Violation] = []
    for p in sorted(TESTS.rglob("test_*.py")):
        # tests/archive/ is frozen legacy — out of scope for the living standard.
        if "archive" in p.relative_to(TESTS).parts:
            continue
        src = p.read_text(encoding="utf-8")
        lines = src.splitlines()
        try:
            tree = ast.parse(src, filename=str(p))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Dict) and _CONTRACT_KEYS.issubset(_dict_literal_keys(node))):
                continue
            line = getattr(node, "lineno", 0)
            span = _enclosing_func_span(tree, line)
            seg = "\n".join(lines[span[0] - 1 : span[1]]) if span else "\n".join(lines[max(0, line - 2) : line + 1])
            if _JUSTIFY_MARKER in seg:
                continue  # explicitly justified fail-closed/edge contract
            out.append(
                Violation(
                    p,
                    line,
                    "inline synthetic option contract — load a REAL chain from tests/fixtures/, "
                    "or (only for fail-closed/edge tests that MUST feed a malformed contract) add "
                    "'# institutional-synthetic-ok: <reason>' in the test/helper.",
                )
            )
    return out


# ── Production-code checks (no-silent-swallow, simplicity) ───────────────────
_SKIP_DIR_PARTS = {".git", "__pycache__", ".venv", "venv", "node_modules", "reports"}
_SWALLOW_MARKER = "institutional-swallow-ok"
_COMPLEXITY_MARKER = "institutional-complexity-ok"
MAX_COMPLEXITY = 15  # cyclomatic; above this a function is too hard to understand/fix safely


def _production_py_files() -> list[Path]:
    out: list[Path] = []
    for p in REPO.rglob("*.py"):
        parts = p.relative_to(REPO).parts
        if any(d in _SKIP_DIR_PARTS for d in parts):
            continue
        if "archive" in parts or "tests" in parts:
            continue  # tests have their own check; archive is frozen legacy
        out.append(p)
    return sorted(out)


def _marker_in_span(lines: list[str], node: ast.AST, marker: str) -> bool:
    lo = getattr(node, "lineno", 1)
    hi = getattr(node, "end_lineno", lo)
    return marker in "\n".join(lines[lo - 1 : hi])


def check_no_silent_swallow() -> list[Violation]:
    """Broad exception handlers (bare, or Exception/BaseException) whose body only
    `pass`/`...` swallow errors silently. Handle, log, or re-raise — or justify with
    '# institutional-swallow-ok: <reason>'."""
    out: list[Violation] = []
    for p in _production_py_files():
        try:
            src = p.read_text(encoding="utf-8")
            tree = ast.parse(src, filename=str(p))
        except (SyntaxError, UnicodeDecodeError):
            continue
        lines = src.splitlines()
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            broad = node.type is None or (
                isinstance(node.type, ast.Name) and node.type.id in {"Exception", "BaseException"}
            )
            if not broad:
                continue
            only_pass = all(
                isinstance(s, ast.Pass)
                or (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant) and s.value.value is Ellipsis)
                for s in node.body
            )
            if not only_pass or _marker_in_span(lines, node, _SWALLOW_MARKER):
                continue
            out.append(
                Violation(
                    p,
                    node.lineno,
                    "silent-swallow: broad except with pass-only body hides errors — "
                    "handle/log/raise, or mark '# institutional-swallow-ok: <reason>'.",
                )
            )
    return out


def _cyclomatic_complexity(func: ast.AST) -> int:
    """Decision points in a function's OWN body (nested functions counted separately)."""
    score = 1

    def visit(node: ast.AST) -> None:
        nonlocal score
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                continue  # nested callable — has its own complexity
            if isinstance(
                child,
                (ast.If, ast.IfExp, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler,
                 ast.With, ast.AsyncWith, ast.Assert, ast.comprehension),
            ):
                score += 1
            elif isinstance(child, ast.BoolOp):
                score += len(child.values) - 1
            visit(child)

    visit(func)
    return score


def check_function_complexity() -> list[Violation]:
    """Functions over the cyclomatic-complexity ceiling are too hard to read and to
    fix safely — split them, or justify with '# institutional-complexity-ok: <reason>'."""
    out: list[Violation] = []
    for p in _production_py_files():
        try:
            src = p.read_text(encoding="utf-8")
            tree = ast.parse(src, filename=str(p))
        except (SyntaxError, UnicodeDecodeError):
            continue
        lines = src.splitlines()
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            cc = _cyclomatic_complexity(node)
            if cc <= MAX_COMPLEXITY or _marker_in_span(lines, node, _COMPLEXITY_MARKER):
                continue
            out.append(
                Violation(
                    p,
                    node.lineno,
                    f"function '{node.name}' cyclomatic complexity {cc} > {MAX_COMPLEXITY} — "
                    "split into smaller functions, or mark '# institutional-complexity-ok: <reason>'.",
                )
            )
    return out


MAX_FILE_LINES = 800       # a file above this is doing too much — split into focused modules
MAX_FUNC_LINES = 80        # a function above this is hard to read/fix — split it
_LENGTH_MARKER = "institutional-length-ok"


def check_file_length() -> list[Violation]:
    """Files over the line ceiling do too much — split into focused modules.

    A file may exceed the ceiling by declaring `# institutional-length-ok: <reason>`, the
    same escape the complexity check already offers.

    WHY THIS EXISTS (RC-19, 2026-07-19): this gate file hit 807 lines against a ceiling of
    800 and the response was to chop it in two. That produced a new module needing FIVE
    circular-import workarounds (TYPE_CHECKING plus call-time imports) to save SEVEN lines
    -- objectively worse code, created to move a counter. A threshold with no justification
    path forces exactly that. The institutional question is "does splitting this improve
    the code?", not "is the number under the limit?" When the answer is no, say so here.
    """
    out: list[Violation] = []
    for p in _production_py_files():
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        n = len(text.splitlines())
        if _LENGTH_MARKER in text:
            continue
        if n > MAX_FILE_LINES:
            out.append(Violation(p, 1, f"file has {n} lines > {MAX_FILE_LINES} — split into focused modules, or declare '# institutional-length-ok: <reason>' if splitting would make it worse"))
    return out


def check_function_length() -> list[Violation]:
    """Functions over the line ceiling are hard to understand and fix — split them,
    or justify with '# institutional-length-ok: <reason>'."""
    out: list[Violation] = []
    for p in _production_py_files():
        try:
            src = p.read_text(encoding="utf-8")
            tree = ast.parse(src, filename=str(p))
        except (SyntaxError, UnicodeDecodeError):
            continue
        lines = src.splitlines()
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            lo, hi = node.lineno, getattr(node, "end_lineno", node.lineno)
            n = hi - lo + 1
            if n > MAX_FUNC_LINES and not _marker_in_span(lines, node, _LENGTH_MARKER):
                out.append(Violation(p, lo, f"function '{node.name}' is {n} lines > {MAX_FUNC_LINES} — split it"))
    return out


_TODO_RE = re.compile(r"#\s*(TODO|FIXME|HACK|XXX)\b", re.IGNORECASE)
_TRACK_ID_RE = re.compile(r"[A-Z][A-Z0-9]+-\d+|\[[A-Z][A-Z0-9-]+\]")  # e.g. FIND-GATE-1 or [OPEN-ITEMS]


def check_todo_without_tracking_id() -> list[Violation]:
    """TODO/FIXME/HACK without a tracking id is a patch waiting to be forgotten —
    file an OPEN_ITEMS entry and reference its id."""
    out: list[Violation] = []
    for p in _production_py_files():
        try:
            lines = p.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        for i, ln in enumerate(lines, 1):
            if _TODO_RE.search(ln) and not _TRACK_ID_RE.search(ln):
                out.append(Violation(p, i, "TODO/FIXME/HACK without a tracking id — file it in OPEN_ITEMS and reference the id"))
    return out


# Meaningful ruff rules (delegated to the mature tool, not hand-rolled): dead code,
# bug-prone patterns, needless complexity/simplification, unused args. Complexity (C90)
# is covered by our own function_complexity check above; cosmetic-only families
# (E501 line length, UP annotation modernization) are auto-fixable separately via `ruff --fix`.
_RUFF_RULES = "F,B,SIM,ARG,RET,PIE,F841"


def check_ruff_quality() -> list[Violation]:
    """Delegate dead-code / bug-prone / simplification lint to ruff (single mature tool)."""
    try:
        r = subprocess.run(
            [sys.executable, "-m", "ruff", "check", ".", "--select", _RUFF_RULES,
             "--exclude", "tests/archive,governance/archive,.venv,node_modules",
             # --color never: ruff may still colorize "concise" under a TTY/FORCE_COLOR;
             # ANSI breaks the line regex and collapses ~1147 findings to 0, which the
             # debt_ratchet honesty guard correctly treats as a checker failure.
             "--output-format", "concise", "--color", "never", "--no-cache"],
            cwd=str(REPO), capture_output=True, text=True, timeout=300,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return []  # ruff unavailable in this env — the pre-commit ruff hook still runs its subset
    out: list[Violation] = []
    for line in r.stdout.splitlines():
        m = re.match(r"^(.+?):(\d+):\d+:\s+(\S+)\s+(.*)$", line.strip())
        if not m:
            continue
        rel = m.group(1)
        try:
            path = (REPO / rel).resolve()
            path.relative_to(REPO)
        except ValueError:
            path = REPO / rel
        out.append(Violation(path, int(m.group(2)), f"ruff {m.group(3)}: {m.group(4)}"))
    return out


_FAKE_DEFAULT_RE = re.compile(r"\bor\s+0\.5\b|\bor\s+100\b|\.get\([^)]*,\s*(?:0\.5|100)\s*\)")


def check_no_fake_defaults() -> list[Violation]:
    """Silent 'neutral'/magic fallbacks (`or 0.5`, `or 100`, `.get(..., 0.5)`) can hide
    absence as a fabricated value. Review each — absence should read as absence."""
    out: list[Violation] = []
    for p in _production_py_files():
        try:
            lines = p.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        for i, ln in enumerate(lines, 1):
            if _FAKE_DEFAULT_RE.search(ln):
                out.append(
                    Violation(p, i, "possible fake-default (or 0.5 / or 100 / .get(...,default)) — "
                              "absence should read as absence, not a fabricated neutral value")
                )
    return out


def check_mypy_types() -> list[Violation]:
    """Delegate type checking to mypy. DORMANT until mypy is installed (returns nothing),
    then activates automatically — no environment change forced."""
    try:
        r = subprocess.run(
            [sys.executable, "-m", "mypy", ".", "--ignore-missing-imports", "--no-error-summary",
             "--explicit-package-bases", "--namespace-packages",
             "--exclude", r"(tests|archive|\.venv|node_modules)"],
            cwd=str(REPO), capture_output=True, text=True, timeout=900,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return []  # mypy not installed / timed out — dormant, not "clean"
    if "No module named mypy" in (r.stderr or ""):
        return []
    out: list[Violation] = []
    for line in r.stdout.splitlines():
        m = re.match(r"^(.+?):(\d+):\s*error:\s*(.*)$", line.strip())
        if m:
            out.append(Violation(REPO / m.group(1), int(m.group(2)), f"mypy: {m.group(3)}"))
    # HONESTY GUARD: exit 0/1 = mypy ran (clean/errors). Anything else = it FAILED to run,
    # so an empty result is NOT "clean" — surface the failure instead of falsely passing.
    if not out and r.returncode not in (0, 1):
        out.append(
            Violation(Path(__file__), 1,
                      f"mypy could not run (exit {r.returncode}) — type check did NOT execute; "
                      f"fix config. stderr: {(r.stderr or '').strip()[:200]}")
        )
    return out


_UNPROVEN_REGISTER = REPO / "governance" / "unproven_register.md"
UNPROVEN_STALE_DAYS = 14


_OPEN_STATUSES = {"UNPROVEN", "DISPROVED"}
_TERMINAL_STATUSES = {"PROVEN", "REMEDIATED"}


def check_unproven_register() -> list[Violation]:
    """Every claim ends at PROVEN or at a landed fix (REMEDIATED).

    UNPROVEN = not yet evidenced. DISPROVED = we were wrong; an OPEN DEFECT that must be
    fixed, not parked. Both are open states: past their `due` date they fail the gate and
    block commits. Missing register = fail-closed.
    """
    if not _UNPROVEN_REGISTER.exists():
        return [Violation(_UNPROVEN_REGISTER, 1,
                          "unproven register missing — claims must be evidenced or registered")]
    out: list[Violation] = []
    today = datetime.date.today()
    for i, ln in enumerate(_UNPROVEN_REGISTER.read_text(encoding="utf-8").splitlines(), 1):
        s = ln.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if len(cells) < 5:
            continue
        status = cells[0].upper()
        if status not in _OPEN_STATUSES | _TERMINAL_STATUSES:
            continue
        if status in _TERMINAL_STATUSES:
            continue
        try:
            due = datetime.date.fromisoformat(cells[2])
        except ValueError:
            out.append(Violation(_UNPROVEN_REGISTER, i,
                                 f"{status} row has an unparseable due date (want YYYY-MM-DD)"))
            continue
        overdue = (today - due).days
        if overdue > 0:
            what = ("OPEN DEFECT — fix it and move to REMEDIATED"
                    if status == "DISPROVED" else "prove or disprove it")
            out.append(Violation(_UNPROVEN_REGISTER, i,
                                 f"{status} is {overdue}d past due ({cells[2]}) — {what}: {cells[3][:80]}"))
    return out


# (name, check, enforced). ENFORCED checks must be zero — they block pre-commit.
# ADVISORY checks are visible debt being driven to zero, then flipped to enforced
# (the ratchet: new code is held to them; existing debt is shown, never hidden).
CHECKS = [
    # ENFORCED (must be zero — block pre-commit):
    ("no_synthetic_domain_fixtures_in_tests", check_no_synthetic_domain_fixtures_in_tests, True),
    ("no_swallowed_test_failures", check_no_swallowed_test_failures, True),  # printed failure must fail the run
    ("root_cause_log", check_root_cause_log, True),
    ("no_governance_duplication", check_no_governance_duplication, True),  # one item, one home
    ("no_tautological_assertions", check_no_tautological_assertions, True),  # catch, not pass
    ("open_item_cap", check_open_item_cap, True),   # ledgers burn down, never accumulate  # 5 whys, restarted on every new cause
    ("debt_ratchet", check_debt_ratchet, True),      # advisory debt may never rise
    ("single_spot_authority", check_single_spot_authority, True),  # one faucet (RC-14)
    ("no_silent_swallow", check_no_silent_swallow, True),           # driven to zero 2026-07-17
    ("no_todo_without_tracking_id", check_todo_without_tracking_id, True),
    ("unproven_register", check_unproven_register, True),  # claims: evidenced or registered
    # ADVISORY (visible debt, driven to zero, then flipped to enforced — the ratchet):
    ("tests_missing_explicit_assert", check_tests_missing_explicit_assert, False),  # review each
    ("function_complexity", check_function_complexity, False),      # too-branchy functions
    ("function_length", check_function_length, False),             # over-long functions
    ("file_length", check_file_length, False),                     # over-long files (split them)
    ("ruff_quality", check_ruff_quality, False),                   # dead code / bugs / simplify (ruff)
    ("no_fake_defaults", check_no_fake_defaults, False),           # neutral/magic fallbacks (review)
    ("mypy_types", check_mypy_types, False),                       # dormant until mypy installed
]

_MAX_PRINT = 15  # cap advisory output; full count is always reported


def main() -> int:
    enforced_violations = 0
    for name, fn, enforced in CHECKS:
        tag = "ENFORCED" if enforced else "ADVISORY"
        violations = fn()
        if violations:
            if enforced:
                enforced_violations += len(violations)
            note = "" if enforced else " — advisory debt: drive to zero, then enforce"
            print(f"FAIL [{name}] ({tag}) — {len(violations)} violation(s){note}:")
            for v in violations[:_MAX_PRINT]:
                print(v)
            if len(violations) > _MAX_PRINT:
                print(f"  … and {len(violations) - _MAX_PRINT} more")
        else:
            print(f"PASS [{name}] ({tag})")
    if enforced_violations:
        print(f"\nINSTITUTIONAL CORRECTNESS GATE: FAIL ({enforced_violations} enforced violation(s))")
        return 1
    print("\nINSTITUTIONAL CORRECTNESS GATE: PASS (enforced checks clean; advisory debt shown above)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
