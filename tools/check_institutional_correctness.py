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


# ── Five-why recursive lock (operator law 2026-07-24) ─────────────────────────
# "You must do a mechanical lock on a 5-why layer recursive regime... that which
# is uncovered at the 5-why layer regime we must then fix end to end. No patches
# ever." Rows opened before the cutover are grandfathered for the two NEW
# closure rules only (retro-scan 2026-07-24: 32 rows, one historical fix cell
# legitimately DESCRIBES removing workarounds - RC-19); ROOT-terminality and
# reference integrity were already clean across all 32 rows and enforce globally.
FIVE_WHY_LOCK_CUTOVER = "2026-07-24"
_PATCH_BANNED_PHRASES = (
    "workaround", "band-aid", "bandaid", "stopgap", "quick fix",
    "temporary fix", "papered over", "route around the",
)


def _five_why_lock_violations(lines: list[str], log_path) -> list[Violation]:
    """Pure row validator for the recursive 5-why lock (unit-testable)."""
    import re as _re

    parsed: list[tuple[int, list[str]]] = []
    ids: set[str] = set()
    for n, line in enumerate(lines, start=1):
        if not line.startswith("| RC-"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 7:
            continue
        parsed.append((n, cells))
        ids.add(cells[0])
    out: list[Violation] = []
    for n, cells in parsed:
        rc_id, status, opened = cells[0], cells[1], cells[2]
        why, fix = cells[5], cells[6]
        if "ROOT" not in why.upper():
            out.append(Violation(
                log_path, n,
                f"{rc_id}: why-chain never terminates in a named ROOT. A chain without "
                f"a ROOT is a symptom list - keep asking why until the root is named."))
        for ref in _re.findall(r"RC-\d+", f"{why} {fix}"):
            if ref not in ids:
                out.append(Violation(
                    log_path, n,
                    f"{rc_id}: references {ref} which has no row. A why that names a new "
                    f"defect SPAWNS that defect's own five-why entry - dangling children "
                    f"break the recursive regime."))
        if opened < FIVE_WHY_LOCK_CUTOVER:
            continue
        low_fix = fix.lower()
        for phrase in _PATCH_BANNED_PHRASES:
            if phrase in low_fix:
                out.append(Violation(
                    log_path, n,
                    f"{rc_id}: fix cell contains banned patch vocabulary ({phrase!r}). "
                    f"No patches ever - fix the architectural cause end to end. There is "
                    f"deliberately NO escape marker for this rule."))
        if status == "CLOSED" and "END-TO-END" not in fix.upper():
            out.append(Violation(
                log_path, n,
                f"{rc_id}: CLOSED without an END-TO-END declaration. Closure requires the "
                f"fix cell to state 'END-TO-END: <producer -> consumer scope>' proving the "
                f"repair reached the root's full blast radius, not the symptom site."))
    return out


# Operator law 2026-07-24 (second clause of the lock): "There is no terminal
# state of 'no solutions exist' - there is only engineering depth yet to be
# unlocked." Mechanized as: a wall may be stated only by naming the door.
_SURRENDER_PHRASES = (
    "no solution", "unsolvable", "impossible to fix", "cannot be fixed",
    "dead end", "abandon this", "give up",
)
NEXT_DEPTH_CUTOVER = "2026-07-25"


def _surrender_violations(lines: list[str], log_path) -> list[Violation]:
    """RC rows (post 5-why cutover): surrender vocabulary in why/fix cells is
    legal ONLY alongside a NEXT-DEPTH: declaration naming the unlock."""
    out: list[Violation] = []
    for n, line in enumerate(lines, start=1):
        if not line.startswith("| RC-"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 7 or cells[2] < FIVE_WHY_LOCK_CUTOVER:
            continue
        text = f"{cells[5]} {cells[6]}".lower()
        for phrase in _SURRENDER_PHRASES:
            if phrase in text and "NEXT-DEPTH:" not in f"{cells[5]} {cells[6]}".upper().replace(" ", ""):
                out.append(Violation(
                    log_path, n,
                    f"{cells[0]}: declares a dead end ({phrase!r}) without NEXT-DEPTH:. "
                    f"There is no terminal state of 'no solutions exist' - only "
                    f"engineering depth yet to be unlocked. Name the door: "
                    f"'NEXT-DEPTH: <the unlock>'."))
    return out


def _terminal_null_violations(report_dicts: list) -> list[Violation]:
    """Study reports born after the cutover with a zero-survivor / null verdict
    must carry a non-empty top-level 'next_depth' naming the successor bet."""
    out: list[Violation] = []
    for path, rep in report_dicts:
        if not isinstance(rep, dict):
            continue
        generated = str(rep.get("generated_utc", ""))
        if generated[:10] < NEXT_DEPTH_CUTOVER:
            continue
        verdictish = f"{rep.get('verdict', '')} {rep.get('status', '')}".upper()
        is_null = (
            rep.get("n_survivors") == 0
            or "NO_SIGNAL" in verdictish
            or "NULL" in verdictish
        )
        if not is_null:
            continue
        nd = rep.get("next_depth")
        if not (isinstance(nd, str) and nd.strip()):
            out.append(Violation(
                path, 0,
                "null-verdict study report without 'next_depth'. A null is never "
                "terminal - only engineering depth yet to be unlocked. Add "
                "next_depth: <the successor bet, data unlock, or generator>."))
    return out


def check_no_terminal_null() -> list[Violation]:
    """No terminal nulls: every dead end must name the next engineering depth.

    Operator law 2026-07-24. OBSERVED basis: four consecutive clean nulls this
    week (F2 grid, meta-XGB v1, and the gamma-conditioned study twice over its
    controls) each pointed at a concrete successor in prose - the reversion
    generator, the greeks channel, the external-data unlock. Prose is goodwill
    and goodwill fails; this makes the pointer mechanical. VALIDATED 2026-07-24:
    the three live null reports carry next_depth; RC rows carry no surrender
    vocabulary; both rules are cutover-dated so history is not retro-flagged.
    """
    out: list[Violation] = []
    log_path = REPO / "governance" / "root_cause_log.md"
    if log_path.exists():
        out.extend(_surrender_violations(
            log_path.read_text(encoding="utf-8").splitlines(), log_path))
    reports: list = []
    rdir = REPO / "reports"
    if rdir.exists():
        for p in sorted(rdir.glob("*.json")):
            try:
                reports.append((p, json.loads(p.read_text(encoding="utf-8"))))
            except (ValueError, OSError):
                continue
    out.extend(_terminal_null_violations(reports))
    return out


def check_five_why_recursive_lock() -> list[Violation]:
    """Mechanical lock: recursive 5-why regime + end-to-end fixes, no patches ever.

    Operator law 2026-07-24, machine-forced per the standing rule that goodwill fails.
    OBSERVED need: RC-14 was closed on code shape and the live bug survived into RC-15
    and RC-16 (three rows, one defect); the same week, mechanical verification (the P1
    parity machine) found in 8.5s an undocumented production convention that two days
    of code reading missed - checks catch what narrative cannot. VALIDATED against the
    live log 2026-07-24: 32 rows, ROOT-terminality and RC-reference integrity clean on
    all of them (enforced globally); the two closure rules (patch-vocabulary ban,
    END-TO-END declaration) bind rows opened on/after the cutover so one historical fix
    cell that legitimately DESCRIBES removing workarounds (RC-19) is not retro-flagged.
    """
    log_path = REPO / "governance" / "root_cause_log.md"
    if not log_path.exists():
        return [Violation(log_path, 0, "governance/root_cause_log.md is missing")]
    lines = log_path.read_text(encoding="utf-8").splitlines()
    return _five_why_lock_violations(lines, log_path)


def check_root_cause_log() -> list[Violation]:
    """Every defect gets five whys, and finding a cause RESTARTS the count.

    OBSERVED: RC-14 was closed on code shape with a shallow chain and the underlying bug
    survived into RC-15 and RC-16 -- three rows for one defect. VALIDATED by prototype
    against the log: the depth rule flagged RC-6 (4 levels) and RC-7 (2 levels), both
    genuinely half-traced, and no complete chain was falsely flagged.

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


# Correctness-shaped advisory debt — the ONLY metrics whose rise fails the commit.
# Shape/style volume (file/function length, complexity, ruff SIM/ARG/etc.) is reported
# but never blocks: elite institutional craft is judged by correctness and architecture,
# not by shaving counters (RC-19: a file-length ceiling forced five circular imports to
# save seven lines). Hard correctness already lives elsewhere (ENFORCED checks, pre-commit
# ruff F401/F821/E9, market-correctness, 5-why). New advisory checks default to
# track-only unless added here deliberately.
_RATCHET_BLOCKS_ON_RISE = frozenset({
    "no_fake_defaults",              # fabricated neutrals hide absence
    "orphan_dict_keys",              # silent None / misspelled keys (RC-15/RC-20)
    "tests_missing_explicit_assert", # tests that cannot fail on regression
    # mypy_types intentionally excluded: checker is dormant until mypy is installed;
    # a 0-vs-baseline honesty trip would brick every bare/.venv without mypy.
})


def check_debt_ratchet() -> list[Violation]:
    """Correctness advisory debt may go DOWN or stay flat. It may never go UP.

    Operator 2026-07-19: "mypy is not a report, it's a tool." Operator 2026-07-24/25:
    the ratchet exists to stop CRUFT (fake defaults, orphan keys, assertion-free tests,
    type holes) — not to police line counts, cyclomatic complexity, or stylistic ruff
    volume. Those shape/style counters remain visible as ADVISORY checks and may float
    with the codebase; they do not fail the gate. Allowlist = `_RATCHET_BLOCKS_ON_RISE`.

    Baseline floor for blocked metrics still only descends (auto-rewrite on improvement).
    Regenerate deliberately (after an accepted correctness-debt increase) with:
        python tools/check_institutional_correctness.py --rebaseline
    """
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
            if name not in _RATCHET_BLOCKS_ON_RISE:
                # Shape/style volume (or any future advisory not on the allowlist):
                # track the new floor; never block a correct professional change.
                baseline[name] = count
                improved = True
                continue
            out.append(Violation(path, 0,
                                 f"{name} rose {base} -> {count} (+{count - base}). Correctness "
                                 f"advisory debt may never increase: clean what you added, or "
                                 f"lower another correctness count to pay for it."))
        elif count < base:
            # HONESTY GUARD: a checker that fails and returns nothing is indistinguishable
            # from a checker that found nothing. Recording that 0 as the new floor silently
            # destroys the ratchet -- it happened to ruff_quality (1147 -> 0), which then
            # blocked every commit with a phantom +1147. A collapse to zero from a large
            # baseline is a tool failure until proven otherwise.
            if count == 0 and base > 10 and name in _RATCHET_BLOCKS_ON_RISE:
                out.append(Violation(
                    path, 0,
                    f"{name} reported 0 against a baseline of {base}. That is a checker "
                    f"failure, not perfection - the baseline was NOT lowered. Investigate "
                    f"the checker, then re-run."))
                continue
            if count == 0 and base > 10 and name not in _RATCHET_BLOCKS_ON_RISE:
                # Track-only metrics: do not collapse a large baseline to 0 on checker flake,
                # and do not fail the commit either — leave baseline unchanged.
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
    # OPEN_ITEMS.md joined the ratchet 2026-07-20. WHAT WAS OBSERVED: the cap covered
    # only the two governance ledgers, so OPEN_ITEMS.md was an UNGATED parking lot --
    # a "flagged, not fixed" disposition could sit there forever, which is exactly the
    # banned third state (operator: Fixed / Allowlisted-with-reason / Registered-with-
    # due-date, nothing else). Counting its unchecked rows puts the same only-down
    # pressure on it. VALIDATED BY PROTOTYPE: 39 unchecked rows at adoption (33 pre-existing + 6
    # registered from the 2026-07-20 audit remainder); the ceiling was re-baselined
    # 10 -> 49 IN THE SAME CHANGE (scope expansion, not backsliding) and
    # may only fall from there.
    open_items += [
        f"OPEN_ITEMS:{m.group(1)[:60]}"
        for m in re.finditer(r"^- \[ \] \*\*([^*]+)\*\*",
                             (REPO / "OPEN_ITEMS.md").read_text(encoding="utf-8"),
                             re.M)
    ] if (REPO / "OPEN_ITEMS.md").exists() else []

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


#: Receivers whose .get() is not a dict read we can reason about (routes, env, vendor libs).
_ORPHAN_KEY_SKIP_RECEIVERS = frozenset({
    "app", "router", "api", "client", "session", "requests", "httpx", "self",
    "environ", "os", "sys", "kwargs", "headers", "params", "cookies", "query",
})


def check_no_orphan_dict_keys() -> list[Violation]:
    """A string key read from a dict that NOTHING in this repo ever writes.

    WHY THIS EXISTS — two production defects in one session, same failure:
      RC-15  `parsed.get("spot_f")` -- the producer emits "spot". Returned None on every
             call, so the spot authority silently served a stale snapshot and the terrain
             card disagreed with the console header.
      RC-20  `p.get("artifact_sha256")` -- the verifier emits "actual_sha256". Every
             VERIFIED artifact reported a null digest, so provenance claimed
             VERIFIED_AGAINST_BUNDLE_MANIFEST while exposing nothing verified.

    Neither was caught by mypy (dict[str, Any] accepts any key), by ruff, or by tests
    (both were guarded by assertions that could not fail). A misspelled or stale key is
    not an error in Python -- it is a silent None. This is the only check that sees it.

    ADVISORY, deliberately: keys arriving in VENDOR payloads (Schwab quote/chain nodes,
    news APIs) are legitimately never written by us, so a zero-tolerance rule would be
    false. It is a ratcheted lead list -- every entry is a candidate silent-None.
    """
    reads: dict[str, tuple] = {}
    writes: set[str] = set()

    for path in _production_py_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        decorated = {
            id(d) for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            for d in n.decorator_list if isinstance(d, ast.Call)
        }
        for n in ast.walk(tree):
            _collect_dict_writes(n, writes)
            if not isinstance(n, ast.Call):
                continue
            key = _dict_read_key(n, decorated)
            if key is not None and key not in reads:
                reads[key] = (path, n.lineno)

    return [
        Violation(path, line,
                  f"key {key!r} is read from a dict but never written anywhere in the repo "
                  f"- a stale or misspelled key is a silent None, not an error (RC-15/RC-20). "
                  f"Confirm it comes from a vendor payload, or fix the name.")
        for key, (path, line) in sorted(reads.items()) if key not in writes
    ]


def _collect_dict_writes(node: ast.AST, writes: set[str]) -> None:
    if isinstance(node, ast.Dict):
        writes.update(k.value for k in node.keys
                      if isinstance(k, ast.Constant) and isinstance(k.value, str))
    elif isinstance(node, ast.Assign):
        for t in node.targets:
            if isinstance(t, ast.Subscript) and isinstance(t.slice, ast.Constant)                     and isinstance(t.slice.value, str):
                writes.add(t.slice.value)
    elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)             and node.func.attr in ("setdefault", "pop") and node.args:
        a0 = node.args[0]
        if isinstance(a0, ast.Constant) and isinstance(a0.value, str):
            writes.add(a0.value)


def _dict_read_key(node: ast.Call, decorated: set[int]) -> str | None:
    """The literal key of a `something.get("k")` dict read, or None if not one."""
    if not isinstance(node.func, ast.Attribute):
        return None
    if node.func.attr != "get" or not node.args or id(node) in decorated:
        return None
    recv = node.func.value
    name = recv.id if isinstance(recv, ast.Name) else (
        recv.attr if isinstance(recv, ast.Attribute) else None)
    if name in _ORPHAN_KEY_SKIP_RECEIVERS:
        return None
    a0 = node.args[0]
    if not (isinstance(a0, ast.Constant) and isinstance(a0.value, str)):
        return None
    key = a0.value
    if key.startswith(("/", "http")) or key.isupper():
        return None                      # routes and environment variables
    return key


#: Checks that predate the justification rule. Their warrant is that they delegate to an
#: industry-standard tool or encode a self-evident quality bar (ruff, mypy, complexity,
#: file/function length, TODO tracking). FROZEN -- nothing may be added to this set; a new
#: check must justify itself in its docstring instead.
_GRANDFATHERED_CHECKS = frozenset({
    "check_no_synthetic_domain_fixtures_in_tests", "check_no_silent_swallow",
    "check_function_complexity", "check_function_length", "check_file_length",
    "check_todo_without_tracking_id", "check_ruff_quality", "check_no_fake_defaults",
    "check_mypy_types", "check_unproven_register", "check_single_spot_authority",
    "check_debt_ratchet", "check_no_governance_duplication",
    "check_no_tautological_assertions",
})

_CAUSE_RE = re.compile(r"(RC-\d+|observed|measured|found \d)", re.I)
_VALIDATION_RE = re.compile(r"(prototyp|validated|proven|deliberately|ADVISORY)", re.I)


def check_checks_are_justified() -> list[Violation]:
    """Every NEW gate check must state what was observed and how the rule was validated.

    OBSERVED (this repo, 2026-07-19): two checks were shipped on plausibility alone and
    both were wrong. `tests_must_assert` flagged 14 legitimate tests because "a test needs
    an assertion" sounds right but ignores the call-production-code-that-raises idiom. An
    invented 800-line ceiling with no justification path caused a split that added five
    circular imports to save seven lines (RC-19). A rule that sounds correct is not a rule
    that IS correct.

    So a new check must answer two questions in its docstring:
      1. WHAT WAS OBSERVED that makes it necessary -- an RC id, or measured evidence.
      2. HOW THE RULE WAS VALIDATED -- prototyped against the repo before enforcing, or
         explicitly shipped ADVISORY because the rule cannot be zero-tolerance.

    VALIDATED BY PROTOTYPE before shipping: run against all 19 existing checks, 14 would
    have failed -- all of them pre-existing tool-delegating checks. Enforcing retroactively
    would have forced invented justifications onto ruff and mypy, which is the exact
    failure this rule exists to stop. Hence the frozen grandfather set above: the rule
    binds new checks only.
    """
    out: list[Violation] = []
    me = Path(__file__)
    try:
        tree = ast.parse(me.read_text(encoding="utf-8"))
    except SyntaxError:
        return out
    for node in ast.walk(tree):
        if not (isinstance(node, ast.FunctionDef) and node.name.startswith("check_")):
            continue
        if node.name in _GRANDFATHERED_CHECKS:
            continue
        doc = ast.get_docstring(node) or ""
        missing = []
        if not _CAUSE_RE.search(doc):
            missing.append("what was OBSERVED (cite an RC id or measured evidence)")
        if not _VALIDATION_RE.search(doc):
            missing.append("how the rule was VALIDATED (prototyped, or ADVISORY by design)")
        if missing:
            out.append(Violation(
                me, node.lineno,
                f"{node.name} is not justified: missing {' and '.join(missing)}. "
                f"A rule that sounds correct is not a rule that is correct."))
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

    OBSERVED: shipped first as an ENFORCED rule and it flagged 14 tests; reading all 14
    showed every one was the legitimate call-production-code-that-raises idiom. Demoted to
    ADVISORY rather than forcing noise edits into working tests.

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
# ".claude" (2026-07-22): agent worktrees (.claude/worktrees/<name>/) are full
# ISOLATED COPIES of the repo — scanning one as production doubled every AST-walked
# debt count (file_length 37->75, complexity 455->881) and hard-blocked all commits
# the moment a task chip existed. Gitignored tooling state is never production code.
_SKIP_DIR_PARTS = {".git", "__pycache__", ".venv", "venv", "node_modules", "reports",
                   ".claude"}
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
    """Silent neutral/magic fallbacks (a 0.5/100 default or a two-arg .get) can hide absence
    as a fabricated value. Review each — absence should read as absence. Annotate a
    proven-legitimate config/parameter default with a '# fake-default-ok: <reason>' marker.

    (This description is worded to avoid matching its own detector — the earlier docstring/
    message literally contained the flagged patterns and the check flagged ITSELF, RC-47.)"""
    out: list[Violation] = []
    for p in _production_py_files():
        try:
            lines = p.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        for i, ln in enumerate(lines, 1):
            if _FAKE_DEFAULT_RE.search(ln) and "fake-default-ok" not in ln:
                out.append(
                    Violation(p, i, "possible fabricated neutral (a 0.5/100 default or a two-arg "
                              ".get) — absence should read as absence, not a fabricated value; "
                              "annotate a legitimate one with '# fake-default-ok: <reason>'")
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


#: RC rows that predate the citation rule. Frozen, exactly like the CHECKS grandfather set:
#: PROTOTYPED against the log before shipping — 20 of 29 rows carry 3+ numeric claims and
#: ZERO reproducible citations, so enforcing retroactively would block every commit and
#: force fabricated citations onto numbers whose commands are long gone. The rule binds
#: rows opened from here forward.
_RC_CITATION_GRANDFATHERED = frozenset(f"RC-{i}" for i in range(1, 30))

#: A citation is a backticked fragment that could be RE-RUN to reproduce the number.
_RC_CITATION_RE = re.compile(
    r"`[^`]*(SELECT |COUNT\(|SUM\(|PRAGMA |pytest|python |node |tools/|\.py)[^`]*`", re.I
)
#: A numeric CLAIM — a bare digit run, optionally with a unit. Dates and RC ids are excluded
#: by the callers stripping them, so "2026-07-20" does not read as three claims.
_RC_NUMBER_RE = re.compile(r"\b\d[\d,.]*\s*(?:GB|MB|KB|s|ms|%|x|rows|files|strikes|tests)?\b")
_RC_CITATION_MIN_NUMBERS = 3


def check_rc_numeric_claims_cite_a_command() -> list[Violation]:
    """A row that asserts numbers must say how to reproduce them.

    WHAT WAS OBSERVED (2026-07-20): RC-6's why-chain quoted 5.96 / 5.78 / 1.03 / 0.92 GB
    and a "~7.7 GB second copy" as MEASURED. They were SAMPLED — 1,500 rows per table,
    extrapolated — and every one was wrong; exact SUM(LENGTH(...)) gives 5.10 / 4.88 /
    1.38 / 1.34 and a 6.22 GB second copy. Cursor's audit refuted all four.

    WHY THE EXISTING LOCK DID NOT FIRE. `_rc_row_violations` already demands "observed
    evidence", but (a) only `if status == "CLOSED"`, and RC-6 is OPEN, and (b) its test is
    `has_number = any(ch.isdigit())` AND the text containing the WORD "MEASURED". The RC-6
    entry opened with "MEASURED:" beside extrapolated figures, so it satisfied both. The
    check verified that the word was typed, not that a measurement happened — the RC-3
    failure class (a comment accepted in place of an assertion) rebuilt as governance.

    Sampling cannot be detected by reading prose: an extrapolated number and an exact one
    are the same characters. What IS checkable is provenance. Requiring the command means
    re-running it exposes the shortcut — the sampled query carried `LIMIT 1500` in plain
    sight — and it turns "trust the word MEASURED" into something the operator or Cursor
    can independently reproduce.

    HOW THE RULE WAS VALIDATED: prototyped against the log BEFORE enforcing. 20 of 29 rows
    would fail, which is why the grandfather set above is frozen and the rule binds only
    new rows — the same design already used for `checks_are_justified`.
    """
    out: list[Violation] = []
    log_path = REPO / "governance" / "root_cause_log.md"
    if not log_path.exists():
        return out
    for n, line in enumerate(log_path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.startswith("| RC-"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 7:
            continue
        rc_id = cells[0]
        if rc_id in _RC_CITATION_GRANDFATHERED:
            continue
        body = " ".join(cells[5:])
        if _RC_CITATION_RE.search(body):
            continue
        # strip ISO dates and RC ids so they are not counted as numeric claims
        stripped = re.sub(r"\d{4}-\d{2}-\d{2}|RC-\d+", "", body)
        if len(_RC_NUMBER_RE.findall(stripped)) >= _RC_CITATION_MIN_NUMBERS:
            out.append(Violation(
                log_path, n,
                f"{rc_id} asserts numbers but cites no reproducible command. Put the query "
                f"or command in backticks so the figure can be re-run — a sampled number "
                f"and an exact one read identically, and only the command tells them apart."))
    return out


#: A snapshots read that orders by ts_utc must name `timeframe`. Frozen grandfather set of
#: OFFLINE sites (tools / verification / research / the normalizer's full-history rebuild).
#: PROTOTYPED before shipping: 9 sites match, 7 of them here. The severity of this defect
#: is a function of whether it sits on the request path, which is why server.py is NOT
#: grandfathered -- a regression there blocks the commit.
_SNAPSHOT_TF_GRANDFATHERED = frozenset({
    "snapshot_normalizer.py",                      # deliberate full-history rebuild
    "research/gex_r1_screen_v1/signal.py",
    "tools/check_card_direction_integrity.py",
    "verification/base_ticker_observability.py",
    "tools/legacy/horizon_7/backfill_fusion_policy_columns_v1.py",   # frozen legacy backfill
})
_SNAPSHOTS_ORDER_RE = re.compile(
    r"FROM\s+snapshots\b(?:(?!;|\"\"\"|').){0,400}?ORDER\s+BY\s+ts_utc",
    re.I | re.S,
)


def check_snapshots_read_names_the_timeframe() -> list[Violation]:
    """A snapshots read ordered by ts_utc must filter `timeframe`, or it scans the table.

    WHAT WAS OBSERVED (2026-07-20, operator-reported: "the entire terrain tab is slow",
    then the console would not respond to Ctrl+C). The only index able to order these
    reads is idx_snap_ticker_tf_ts (ticker, timeframe, ts_utc). `_latest_chain_and_spot`
    and `_spot_from_stored` filtered ticker and ordered by ts_utc while SKIPPING timeframe
    -- the middle column -- so the ordering could not be index-served:

        SEARCH snapshots USING INDEX idx_snap_ticker_tf_ts (ticker=?)
        USE TEMP B-TREE FOR ORDER BY

    SQLite read every row for the ticker (70,556 for SPY, each carrying a ~50 KB inline
    option_chain_json) into a temp B-tree to return ONE row. MEASURED: did not complete
    inside a 300 s timeout. Naming the timeframe removes the sort entirely -- 0.002 s.
    That wedged a request worker, which froze the price lane and blocked shutdown.

    Neither the test suite nor any existing gate check could see it: every test passed,
    ruff and mypy were clean, and the defect lives in a query PLAN, not in code shape.

    HOW THE RULE WAS VALIDATED: prototyped against the repo before enforcing. 9 sites
    match; 7 are offline (grandfathered above), 1 is a deliberate negative control in
    tests/, and server.py -- the request path -- is clean. Tests are excluded because a
    test that PROVES the bad plan must contain the bad query.
    """
    out: list[Violation] = []
    for p in _production_py_files():
        rel = p.relative_to(REPO).as_posix()
        if rel in _SNAPSHOT_TF_GRANDFATHERED:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in _SNAPSHOTS_ORDER_RE.finditer(text):
            frag = " ".join(m.group(0).split())
            low = frag.lower()
            if "ticker" not in low or "timeframe" in low:
                continue
            out.append(Violation(
                p, text[: m.start()].count("\n") + 1,
                "snapshots read orders by ts_utc without naming `timeframe` — "
                "idx_snap_ticker_tf_ts cannot serve the ordering, so this degrades to a "
                "full read of every row for the ticker (MEASURED >300s vs 0.002s)"))
    return out


def check_shutdown_is_bounded() -> list[Violation]:
    """A shutdown path that joins workers must be bounded by the watchdog.

    WHAT WAS OBSERVED (operator, 2026-07-20): "when i press control plus c the console
    doesn't shut down". CONFIRMED on the live process -- uvicorn PID 34780 had closed its
    listening socket (shutdown had begun) yet stayed resident with 2,488 CPU-seconds. The
    lifespan teardown is a serial chain of `shutdown(wait=True)` and a 40 s stream join;
    `cancel_futures=True` drops only QUEUED work and cannot interrupt a RUNNING worker, so
    one blocked vendor call or long query stalls the whole chain. Python compounds it:
    concurrent.futures registers an atexit hook that joins every executor's non-daemon
    workers, so abandoning the lifespan does not free the interpreter either.

    REPRODUCED in isolation: a process with one wedged non-daemon thread never exits
    (>15 s, killed); with the watchdog armed it exits in 2.4 s.

    HOW THE RULE WAS VALIDATED: prototyped against the current file -- the lifespan does
    arm the watchdog, so this check is 0 today and only fires on regression.
    """
    out: list[Violation] = []
    server = REPO / "server.py"
    if not server.exists():
        return out
    text = server.read_text(encoding="utf-8", errors="replace")
    marker = "async def _app_lifespan"
    if marker not in text:
        return out
    body = text[text.index(marker):]
    end = body.find("\n@app.")
    if end > 0:
        body = body[:end]
    if "wait=True" in body and "_arm_shutdown_watchdog" not in body:
        out.append(Violation(
            server, text[: text.index(marker)].count("\n") + 1,
            "the lifespan joins background workers (wait=True) without arming "
            "_arm_shutdown_watchdog — one blocked worker makes the console unkillable "
            "by Ctrl+C (OBSERVED 2026-07-20)"))
    # The watchdog itself must refuse under pytest. OBSERVED 2026-07-20: TestClient runs
    # the lifespan inside the TEST process; an unguarded watchdog os._exit(0)'d PYTEST
    # 12 s later, mid-suite, silently, exit code 0 — tests/adversarial "passed" with zero
    # output and the full suite read as a hang (Cursor audit). RC-10 class.
    wd = "def _arm_shutdown_watchdog"
    if wd in text:
        wd_body = text[text.index(wd):]
        wd_end = wd_body.find("\ndef ")
        if wd_end > 0:
            wd_body = wd_body[:wd_end]
        if "PYTEST_CURRENT_TEST" not in wd_body:
            out.append(Violation(
                server, text[: text.index(wd)].count("\n") + 1,
                "_arm_shutdown_watchdog does not refuse under pytest — armed inside the "
                "test process it os._exit(0)'s the RUNNER mid-suite with a success code "
                "(OBSERVED 2026-07-20: silent zero-output 'pass')"))
    return out


def check_venv_parity() -> list[Violation]:
    """Active interpreter must live under repo .venv (multi-agent parity).

    OBSERVED (2026-07-25): Claude/Cursor share the filesystem but not the
    interpreter — global Python313 vs a project venv silently diverges packages
    and hook installs. VALIDATED: tools/check_venv_parity.py path resolve;
    CI (GITHUB_ACTIONS/CI) exempt because runners have no repo .venv.
    """
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    from tools.check_venv_parity import venv_parity_violations

    return [Violation(REPO / ".venv", 0, msg) for msg in venv_parity_violations()]


def check_credential_leak() -> list[Violation]:
    """Staged diffs must not introduce secrets, JWTs, or operator home paths.

    OBSERVED (2026-07-25): private-path guard only covers scoreboard_forensic
    tracked evidence; a Bearer token or C:\\Users\\… in a staged .py/.md still
    lands. VALIDATED: tools/check_credential_leak.py regex suite + unit tests.
    """
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    from tools.check_credential_leak import find_credential_leaks

    return [
        Violation(REPO / ".git", 0, hit)
        for hit in find_credential_leaks()
    ]


def check_sqlite_wal_contract() -> list[Violation]:
    """Production sqlite connects must use timeout>=30 and WAL pragmas helper.

    OBSERVED (2026-07-25): concurrent agent/server writers lock a DELETE-mode
    DB; EdDB._connect already sets timeout=30 + configure_sqlite_connection
    (WAL/NORMAL), but ad-hoc connects can skip both. VALIDATED: AST/source
    contract on db.py — configure_sqlite_connection body + every
    sqlite3.connect(…, timeout=…) site.
    """
    out: list[Violation] = []
    path = REPO / "db.py"
    try:
        src = path.read_text(encoding="utf-8")
    except OSError as e:
        return [Violation(path, 0, f"cannot read db.py: {e}")]
    if "PRAGMA journal_mode=WAL" not in src:
        out.append(Violation(path, 0, "configure_sqlite_connection missing PRAGMA journal_mode=WAL"))
    if "PRAGMA synchronous=NORMAL" not in src:
        out.append(Violation(path, 0, "configure_sqlite_connection missing PRAGMA synchronous=NORMAL"))
    if "busy_timeout" not in src:
        out.append(Violation(path, 0, "configure_sqlite_connection missing busy_timeout pragma"))
    # Every sqlite3.connect in db.py must pass timeout= (no default 5s lock storms).
    for i, line in enumerate(src.splitlines(), 1):
        if "sqlite3.connect(" not in line:
            continue
        if "timeout=" not in line:
            out.append(Violation(
                path, i,
                "sqlite3.connect without timeout= — require timeout>=30.0 "
                "(multi-agent / async lock storm class)"))
    return out


def check_ui_data_integration() -> list[Violation]:
    """UI cells must be wired to real data — no dead '—' placeholders (Tier 1).

    OBSERVED (2026-07-25): the console shipped illustrative gamma bars / sparklines / a
    "sample" activity feed, and terrain cells could sit at "—" while the data existed —
    the agent verified code + endpoints but never the RENDERED DOM. Tier 1 (static binding,
    here) fails the build if any data cell that ships as the "—" placeholder in
    static/index.html or static/chart.html has no JavaScript writer. The live tiers
    (endpoint assertions + Playwright headless render, which actually see the DOM) run via
    `python tools/check_ui_data_integration.py` with ED_UI_GATE_LIVE=1 in CI / manual — they
    need a running server + browser, so they are deliberately NOT per-commit gates (that
    dependency would itself become a flaky false-failure source).
    """
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    from tools.check_ui_data_integration import static_binding_violations

    return [Violation(REPO / rel, line, msg)
            for rel, line, msg in static_binding_violations()]


def check_vendor_field_coercion() -> list[Violation]:
    """One faucet for every Schwab vendor field: single-source numeric coercion (RC-FAUCET).

    OBSERVED (2026-07-25): the SAME raw leaf (strikePrice, totalVolume, bid/ask, greeks,
    daysToExpiration, mark, netChange, multiplier) was parsed a dozen ways across the
    money-path. Raw ``float(ct.get("strikePrice"))`` inside ``try/except (TypeError,
    ValueError)`` SILENTLY ADMITS NaN/±inf (``float('nan')`` does not raise): NaN became a
    dict key, corrupted sorted strike sets (ATM/spacing), poisoned volume sums, entered the
    IV smile, produced NaN charm, and passed ``abs(nan-target) >= 0.01`` as a FALSE contract
    match. A self-adversarial 5-iteration sweep found bugs the field-name grep MISSED —
    hidden behind intermediate variables (``sp = ct.get("strikePrice"); float(sp)``). This
    lock forbids raw float()/int(float()) coercion of a vendor field in BOTH forms; a site is
    clean only through a canonical numeric_contract reader or an explicit, reasoned
    ``# vendor-coercion-ok: <why safe>`` marker. VALIDATED: driven to zero the same day.
    """
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    from tools.check_vendor_field_coercion import violations

    return [Violation(REPO / rel, line, msg) for rel, line, msg in violations()]


def _git_output_lines(args: list[str]) -> list[str] | None:
    """git stdout lines, or None when not in a usable git/commit context (never a false block)."""
    import subprocess
    try:
        r = subprocess.run(["git", *args], cwd=str(REPO), capture_output=True, text=True, timeout=25)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    return r.stdout.splitlines()


def _staged_has_real_change(rel: str) -> bool:
    """True when the staged diff for `rel` adds/removes any non-blank line (not pure whitespace)."""
    lines = _git_output_lines(["diff", "--cached", "-U0", "--", rel])
    if not lines:
        return False
    for ln in lines:
        if ln.startswith("+++") or ln.startswith("---"):
            continue
        if (ln.startswith("+") or ln.startswith("-")) and ln[1:].strip():
            return True
    return False


def check_recursive_five_why_front_loaded() -> list[Violation]:
    """UNIVERSAL front-end of the recursive-5-why law: a code change ships with its root cause.

    OBSERVED (2026-07-26, RC-41): the five_why_recursive_lock validated the CONTENT of rows
    that already existed but never the ACT of opening one, so an entire session of fixes (charm
    RC-35, coercion RC-38 and their children) shipped with zero root-cause rows and the gate
    stayed green. Per the log's Rule 5, "I didn't do the 5-why" is a symptom whose real defect
    is a MISSING mechanical check — the law depended on goodwill at discovery time, and goodwill
    fails. The law is UNIVERSAL ("with everything we do", operator 2026-07-19) — this check is
    deliberately NOT scoped to a subsystem.

    Rule: any commit that stages a real change to a tracked .py file MUST co-stage a real
    '| RC-' row in governance/root_cause_log.md. A cosmetic touch of the log does not satisfy it
    (an added '| RC-' line is required), and the row's quality is separately enforced by
    five_why_recursive_lock — so a fix cannot reach a commit without a ROOT-terminal recursive
    entry. Front-end law: open the row at DISCOVERY, before the fix.

    VALIDATED: prototyped against this repo before enforcing — fires when a .py change is staged
    with no RC row, passes when a real row is co-staged, and no-ops (returns []) outside a git
    commit context so unit-test imports never false-block. Escapes NONE by design.
    """
    staged = _git_output_lines(["diff", "--cached", "--name-only"])
    if staged is None:
        return []  # not a commit context — never a false block
    staged_set = {s.strip().replace("\\", "/") for s in staged if s.strip()}
    if not staged_set:
        return []
    log_rel = "governance/root_cause_log.md"
    changed_code = sorted(
        f for f in staged_set if f.endswith(".py") and _staged_has_real_change(f)
    )
    if not changed_code:
        return []
    if log_rel not in staged_set:
        return [Violation(
            REPO / changed_code[0], 0,
            "Code changed (" + ", ".join(changed_code[:5]) +
            (" …" if len(changed_code) > 5 else "") + ") with NO co-staged root-cause row. "
            "The recursive-5-why law is UNIVERSAL and FRONT-LOADED (operator 2026-07-19): the "
            "moment you find an issue you OPEN its RC-<n> row in governance/root_cause_log.md and "
            "drive each cause to its ROOT before fixing. Every code change ships with its "
            "recursive root cause — co-stage a real '| RC-' row (its quality is enforced by "
            "five_why_recursive_lock). This scope is not narrowable.")]
    log_diff = _git_output_lines(["diff", "--cached", "-U0", "--", log_rel]) or []
    if not any(l.startswith("+| RC-") for l in log_diff):
        return [Violation(
            REPO / log_rel, 0,
            "governance/root_cause_log.md is staged but no '| RC-<n>' row was added or changed "
            "alongside a code change — a real recursive-5-why entry is required, not a cosmetic "
            "touch. Open the RC at discovery, drive to ROOT, fix end-to-end.")]
    return []


# (name, check, enforced). ENFORCED checks must be zero — they block pre-commit.
# ADVISORY checks are visible debt being driven to zero, then flipped to enforced
# (the ratchet: new code is held to them; existing debt is shown, never hidden).
CHECKS = [
    # ENFORCED (must be zero — block pre-commit):
    ("no_synthetic_domain_fixtures_in_tests", check_no_synthetic_domain_fixtures_in_tests, True),
    ("no_swallowed_test_failures", check_no_swallowed_test_failures, True),  # printed failure must fail the run
    ("root_cause_log", check_root_cause_log, True),
    ("five_why_recursive_lock", check_five_why_recursive_lock, True),  # end-to-end fixes, no patches ever
    ("recursive_five_why_front_loaded", check_recursive_five_why_front_loaded, True),  # UNIVERSAL: any code change ships a root-cause row
    ("no_terminal_null", check_no_terminal_null, True),                # every dead end names the next depth
    ("no_governance_duplication", check_no_governance_duplication, True),  # one item, one home
    ("checks_are_justified", check_checks_are_justified, True),  # observed + validated, or no ship
    ("no_tautological_assertions", check_no_tautological_assertions, True),  # catch, not pass
    ("open_item_cap", check_open_item_cap, True),   # ledgers burn down, never accumulate  # 5 whys, restarted on every new cause
    ("debt_ratchet", check_debt_ratchet, True),      # correctness advisory debt may never rise
    ("single_spot_authority", check_single_spot_authority, True),  # one faucet (RC-14)
    ("no_silent_swallow", check_no_silent_swallow, True),           # driven to zero 2026-07-17
    ("no_todo_without_tracking_id", check_todo_without_tracking_id, True),
    ("rc_numeric_claims_cite_a_command", check_rc_numeric_claims_cite_a_command, True),  # provenance, not the word "MEASURED" (RC-6)
    ("snapshots_read_names_the_timeframe", check_snapshots_read_names_the_timeframe, True),  # query PLAN, not code shape
    ("shutdown_is_bounded", check_shutdown_is_bounded, True),  # Ctrl+C must always work
    ("unproven_register", check_unproven_register, True),  # claims: evidenced or registered
    ("venv_parity", check_venv_parity, True),  # one interpreter — .venv only (CI exempt)
    ("credential_leak", check_credential_leak, True),  # staged secrets / home paths
    ("sqlite_wal_contract", check_sqlite_wal_contract, True),  # WAL + timeout on connects
    ("ui_data_integration", check_ui_data_integration, True),  # no dead "—" placeholders (Tier 1)
    ("vendor_field_coercion", check_vendor_field_coercion, True),  # one faucet per Schwab leaf (RC-FAUCET)
    # REMOVED 2026-07-25 (operator: "i don't want you on separate instances"): the
    # agent_worktree_boundary check required ED_AGENT_ROLE to be set and blocked all
    # commits from a single-instance workflow (fail-closed on unset role). Single
    # working tree in EdWebConsole is the supported model again; the sibling -Claude
    # worktree was removed. Dormant helpers (check_worktree_handoff.py,
    # agent_worktree_policy.json, db_authority claude routing) remain inert — they only
    # activate if ED_AGENT_ROLE is explicitly set — and can be fully purged later.
    # ADVISORY (visible debt, driven to zero, then flipped to enforced — the ratchet):
    ("tests_missing_explicit_assert", check_tests_missing_explicit_assert, False),  # review each
    ("orphan_dict_keys", check_no_orphan_dict_keys, False),   # silent-None leads (RC-15/RC-20)
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
