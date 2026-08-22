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
    - unproven_register            : evidence-integrity only for
                                     governance/unproven_register.md (zero work /
                                     due-date / commit-block authority).

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
import os
import re
import subprocess
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]

def _read_or_empty(p) -> str:
    """RC-116: a file that VANISHES between glob and read (another agent's scratch file,
    a mid-commit delete) must not crash the whole gate — a crashed gate protects nothing.
    Fixed governance paths deliberately do NOT use this: their absence is a real failure."""
    try:
        return p.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""

TESTS = REPO / "tests"
#: Run as a bare script, sys.path[0] is tools/ — so `import tools.x` fails and every check that
#: imports a sibling reports UNMEASURABLE. That is the correct behaviour for a broken import
#: (RC-57), but here the import is fine and only the path was wrong: check_single_faucet_provenance
#: went unmeasurable for that reason alone while the audit itself ran clean by hand.
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


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

#: RC-299 — the RECURSION cutover, separate from the 2026-07-24 structural one because it
#: adds a NEW requirement and must not retroactively invalidate rows written before the
#: rule existed. Operator law 2026-08-08: the five whys must be RECURSIVE. Depth and the
#: literal token ROOT were already enforced; neither asks whether the root is IRREDUCIBLE,
#: so a chain could name a new defect at why-2 and keep going in prose. RC-298's own why-4
#: named a defect in the RC-49 gate and spawned nothing, and the lock stayed silent.
FIVE_WHY_RECURSION_CUTOVER = "2026-08-08"
_PATCH_BANNED_PHRASES = (
    "workaround", "band-aid", "bandaid", "stopgap", "quick fix",
    "temporary fix", "papered over", "route around the",
)


#: RC-106 close contract (operator, 2026-07-28): "the locks check words and proxies, not reach."
#: Rows opened on/after this date close under a DECLARED-reach schema a checker can walk:
#: FIXED: named victims; no pending vocabulary (PARTIAL status exists for honest incompleteness);
#: VISIBLE_SURFACE: for DOM-id defects, with the id existing in static/ AND bound by a test;
#: OUT-OF-SCOPE: only with a tracker. Free-prose blast radius is exactly what let three closes
#: wear the END-TO-END label while Kalman, the visible #cv2 chip, and the RTH regex stayed broken.
CLOSE_CONTRACT_CUTOVER = "2026-07-28"
#: A CLOSED stamp may not defer its own proof — that is what PARTIAL is for. No escape marker.
_CLOSE_PENDING_PHRASES = (
    "pending", "proof owed", "awaiting", "closed for the code path", "code path only",
)
#: RC-144: matched as WHOLE WORDS. As bare substrings, "pending" fired inside "depending",
#: "impending" and "suspending" — MEASURED 2026-07-30 when a row stating that a metric "stops
#: depending on how the caller was launched" was flagged for deferring its own proof. The only
#: ways out of a false positive are rewording true evidence until the regex is satisfied, or
#: weakening the rule; both are worse than the bug, and the first is the citation theater
#: RC-136 was opened for. Word boundaries keep the rule's strength and drop the accidents.
_CLOSE_PENDING_RES = tuple(
    (p, re.compile(r"\b" + re.escape(p) + r"\b")) for p in _CLOSE_PENDING_PHRASES
)
#: The DOM-id net matches hyphenated ids only (#cv2-kl-trust) — the hyphen requirement keeps
#: hex colors and markdown anchors out.


def _five_why_lock_violations(
    lines: list[str], log_path,
    static_corpus: str | None = None,
    tests_corpus: str | None = None,
) -> list[Violation]:
    """Pure row validator for the recursive 5-why lock (unit-testable).

    `static_corpus` / `tests_corpus` are the concatenated static/*.html and tests/**/*.py
    contents used by the RC-106 close contract; None skips those existence checks (pure
    unit tests can inject tiny corpora).
    """
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
        # RC-299: RECURSION. Depth and the token ROOT were already required; neither asks
        # whether the root is IRREDUCIBLE. A chain ending "ROOT: the repo does not enforce
        # X" reads terminal while X is plainly another defect with its own causes. The row
        # format had no way to say which, so both were written identically. Now the author
        # must declare at the terminus: bedrock WITH a reason, or the child it points at.
        if opened >= FIVE_WHY_RECURSION_CUTOVER:
            up_why = why.upper()
            has_terminal = "ROOT: TERMINAL" in up_why
            spawns = _re.findall(r"ROOT:\s*SPAWNS\s+(RC-\d+)", why, _re.I)
            if not has_terminal and not spawns:
                out.append(Violation(
                    log_path, n,
                    f"{rc_id}: the why-chain names a ROOT but does not say whether it is "
                    f"BEDROCK or a POINTER. Recursion is not optional (operator law "
                    f"2026-08-08): end the chain with 'ROOT: TERMINAL — <why it cannot be "
                    f"reduced further>' or 'ROOT: SPAWNS RC-nnn — <the child defect>'. A "
                    f"cause found at why-2 is not a root, it is a new defect that gets its "
                    f"own five whys (RC-299)."))
            for child in spawns:
                if child not in ids:
                    out.append(Violation(
                        log_path, n,
                        f"{rc_id}: ROOT SPAWNS {child}, which has no row. A spawned child "
                        f"must carry its own five whys — that is what makes the regime "
                        f"recursive rather than a chain of promises (RC-299)."))
            if has_terminal:
                seg = why[up_why.find("ROOT: TERMINAL") + len("ROOT: TERMINAL"):]
                if len(seg.strip(" —-:").strip()) < 40:
                    out.append(Violation(
                        log_path, n,
                        f"{rc_id}: ROOT declared TERMINAL with no justification. Bedrock is "
                        f"a claim and it is the one place the recursion stops, so it must "
                        f"say WHY no further why exists — otherwise TERMINAL is just the "
                        f"word ROOT again (RC-299)."))

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
        # ── RC-106 close contract: declared, checkable reach ─────────────────────────────
        if status == "CLOSED" and opened >= CLOSE_CONTRACT_CUTOVER:
            up_fix = fix.upper()
            if "FIXED:" not in up_fix:
                out.append(Violation(
                    log_path, n,
                    f"{rc_id}: CLOSED without 'FIXED: <named victims>'. The close contract "
                    f"(RC-106) requires the repaired consumers to be ENUMERATED so coverage "
                    f"is checkable — free prose is how three closes wore END-TO-END while "
                    f"named victims stayed broken."))
            # Use vs mention: a row that DESCRIBES the pending rule (in backticks) is not
            # deferring proof — the same backtick convention every guard already uses.
            low_fix_used = _re.sub(r"`[^`]*`", "", low_fix)
            for phrase, rx in _CLOSE_PENDING_RES:
                if rx.search(low_fix_used):
                    out.append(Violation(
                        log_path, n,
                        f"{rc_id}: CLOSED while the fix cell defers its own proof "
                        f"({phrase!r}). A CLOSED stamp may not owe evidence — use status "
                        f"PARTIAL until the proof lands (RC-106). No escape marker."))
            dom_ids = sorted(set(_re.findall(
                r"#[a-z][a-z0-9]*(?:-[a-z0-9]+)+",
                f"{cells[4]} {why} {fix}".lower())))
            if dom_ids:
                if "VISIBLE_SURFACE:" not in up_fix:
                    out.append(Violation(
                        log_path, n,
                        f"{rc_id}: names DOM id(s) {dom_ids} but declares no "
                        f"'VISIBLE_SURFACE: #<id>'. A UI close must name the surface the "
                        f"operator SEES so the checker (and the test) can bind it — the "
                        f"hidden-chip close is the defect this contract exists for."))
                for did in dom_ids:
                    if static_corpus is not None and did[1:] not in static_corpus:
                        out.append(Violation(
                            log_path, n,
                            f"{rc_id}: VISIBLE_SURFACE names {did} but no such id exists "
                            f"in static/ — a surface that does not exist cannot have been "
                            f"verified."))
                    if tests_corpus is not None and did[1:] not in tests_corpus:
                        out.append(Violation(
                            log_path, n,
                            f"{rc_id}: no test binds {did}. The close contract requires a "
                            f"test that asserts the VISIBLE consumer, not a substring "
                            f"anywhere in the file (RC-102's test passed while the visible "
                            f"chip stayed blind)."))
            if "OUT-OF-SCOPE:" in up_fix:
                seg = fix[up_fix.index("OUT-OF-SCOPE:"):]
                if "RC-" not in seg and "register" not in seg.lower():
                    out.append(Violation(
                        log_path, n,
                        f"{rc_id}: OUT-OF-SCOPE without a tracker. Deferral is legal only "
                        f"with an RC id or register entry — otherwise it is the banned "
                        f"third state (flagged, not fixed, forgotten)."))
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
    static_corpus = "".join(
        _read_or_empty(p)
        for p in sorted((REPO / "static").glob("*.html"))) if (REPO / "static").exists() else ""
    tests_corpus = "".join(
        _read_or_empty(p)
        for p in sorted((REPO / "tests").rglob("*.py"))) if (REPO / "tests").exists() else ""
    return _five_why_lock_violations(lines, log_path, static_corpus, tests_corpus)


def check_root_cause_log() -> list[Violation]:
    """Every defect gets five whys, and finding a cause RESTARTS the count.

    OBSERVED: RC-14 was closed on code shape with a shallow chain and the underlying bug
    survived into RC-15 and RC-16 -- three rows for one defect. VALIDATED by prototype
    against the log: the depth rule flagged RC-6 (4 levels) and RC-7 (2 levels), both
    genuinely half-traced, and no complete chain was falsely flagged.

    Operator law 2026-07-19: a cause found at why-2 is not the root -- it is a new defect
    that gets its own five whys. Evidence-integrity validation remains (five-why depth,
    CLOSED-row proof, parseable dates). RC OPEN / due date / classification has zero
    work-state authority and does not independently block completion.

    See governance/root_cause_log.md for the rules and the row format.
    """
    out: list[Violation] = []
    log_path = REPO / "governance" / "root_cause_log.md"
    if not log_path.exists():
        out.append(Violation(log_path, 0, "governance/root_cause_log.md is missing — "
                                          "frozen historical evidence file is required"))
        return out
    for n, line in enumerate(log_path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.startswith("| RC-"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 5:
            continue
        rc_id, status, _opened, due = cells[0], cells[1], cells[2], cells[3]

        out.extend(_rc_row_violations(log_path, n, rc_id, status, cells))
        try:
            datetime.date.fromisoformat(due)
        except ValueError:
            out.append(Violation(log_path, n, f"{rc_id} has an unparseable due date {due!r}"))
    return out


def _ratchet_may_write() -> bool:
    """A CHECK MUST NOT MUTATE THE REPO (RC-90).

    check_debt_ratchet used to rewrite the baseline whenever a metric improved, and
    check_open_item_cap the ceiling. pre-commit stashes unstaged work and runs hooks against the
    STAGED-ONLY tree, so those counts legitimately differ from the working tree: the file was
    rewritten on every single run, pre-commit treats a hook that modifies a tracked file as a
    failure, and staging the rewrite could not help because the next run rewrote it again. Four
    consecutive commits were blocked on 2026-07-27 while the gate itself printed PASS with all 32
    enforced checks clean -- including the commit carrying the locks the operator had just
    mandated.

    Under a hook the ratchet still COMPARES and still BLOCKS on a real rise; it just does not
    record the new floor. Recording is deliberate, exactly as the docstring always claimed:
        python tools/check_institutional_correctness.py --rebaseline
    """
    if os.environ.get("PRE_COMMIT"):          # set by pre-commit for every hook it runs
        return False
    return os.environ.get("ED_RATCHET_NO_WRITE", "").strip().lower() not in ("1", "true", "on")


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
        # RC-385: READ-ONLY. Seeding is an explicit act (--rebaseline), never a side
        # effect of asking the gate a question.
        out.append(Violation(path, 0,
                             "advisory_debt_baseline.json is missing. Seed it deliberately: "
                             "python tools/check_institutional_correctness.py --rebaseline"))
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
    # RC-385: the ratchet READS its reference and never writes it. Measured 2026-08-15 on a
    # pristine checkout of origin/main: one call moved file_length 37->49,
    # function_complexity 462->547, ruff_quality 1081->1301 and flipped the file to CRLF, so
    # the act of MEASURING left a clean clone dirty with RAISED debt ceilings — and anyone
    # committing with blind staging would have legitimised them without deciding to. A gate
    # may read its reference or change it, never both in one call. `improved` is still
    # computed above because --rebaseline reuses this comparison; recording happens only
    # there, which is what both docstrings have always claimed.
    del improved
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

    #: Vocabulary that appears in nearly EVERY governance row (verdict words, evidence words,
    #: market-domain nouns). Two rows sharing these are discussing the same SUBJECT AREA, not the
    #: same ITEM — and this check exists to stop one ITEM being tracked twice. Without the
    #: stoplist the heuristic false-positived register:41 against RC-43 on words like "proven",
    #: "capture", "schwab", "barchart" (one is a CLAIM that our method matches Barchart; the other
    #: is a DEFECT in a closure that cited a bad number — different items, same topic).
    _GOVERNANCE_STOPWORDS = frozenset({
        "proven", "unproven", "verified", "measured", "observed", "remediated", "disproved",
        "confirm", "confirmed", "evidence", "verdict", "closure", "closed", "record", "records",
        "register", "registry", "governance", "operator", "before", "already", "original",
        "sample", "samples", "window", "windows", "capture", "captures", "captured", "method",
        "methods", "pattern", "patterns", "difference", "smaller", "larger", "observation",
        "observations", "contaminated", "contamination", "ticker", "tickers", "regime", "regimes",
        "session", "sessions", "intraday", "overnight", "expiry", "industry", "placebo",
        "schwab", "barchart", "spotgamma", "against", "because", "instead", "without",
        "reproduce", "reproduces", "reproducible", "numbers", "number", "median", "percent",
        # 2026-08-04: register:61 vs RC-159 false-positived on exactly these market-universal
        # terms (13 shared, all subject-area vocabulary — an overlay-confluence CLAIM vs a
        # display-levels DEFECT, different items entirely). Same class the stoplist documents.
        "banked", "enrolled", "sentinel", "sentinels", "predictive", "strikes",
        "morning", "forward", "minimum", "series",
    })

    def _terms(text: str) -> set[str]:
        return {w.lower() for w in re.findall(r"[a-zA-Z_]{6,}", text)} - _GOVERNANCE_STOPWORDS

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
    """Historical UNPROVEN/DISPROVED wording. Not a work queue."""
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


def _is_overdue(due: str) -> bool:
    """True when `due` (YYYY-MM-DD) is in the past. An unparseable date is NOT counted here —
    check_root_cause_log already fails loudly on a malformed due date, so this never
    double-reports and never silently treats junk as compliant."""
    try:
        return datetime.date.fromisoformat(due.strip()) < datetime.date.today()
    except (TypeError, ValueError):
        return False


def _overdue_governance_items(rc_path, reg_path) -> list[str]:
    """Measurement only: historical RC/register rows whose due date has passed.

    Zero work / due-date / commit-block authority. Unresolved work lives only
    on the sole master. Root-cause due = cells[3]; register due = cells[2].
    """
    out: list[str] = []
    if rc_path.exists():
        for line in rc_path.read_text(encoding="utf-8").splitlines():
            if not line.startswith("| RC-"):
                continue
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) > 3 and cells[1] == "OPEN" and _is_overdue(cells[3]):
                out.append(cells[0])
    if reg_path.exists():
        for line in reg_path.read_text(encoding="utf-8").splitlines():
            if not line.startswith("|"):
                continue
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) > 3 and cells[0] in ("UNPROVEN", "DISPROVED") and _is_overdue(cells[2]):
                out.append(f"register:{cells[3][:40]}")
    return out


def check_open_item_cap() -> list[Violation]:
    """Legacy RC/register due dates have zero work authority.

    Unresolved work lives only on the sole master. This named check remains so
    the ratchet file cannot return; it never blocks on due dates.

    Historical note: Governance ledgers must burn DOWN. The open count may never rise.

    Operator 2026-07-19: the ledgers must resolve, not accumulate.

    A fixed cap would repeat the mistake of the 800-line ceiling (RC-19): an arbitrary
    number invites an arbitrary remedy, and a permanently-red gate teaches you to ignore
    it. This is a RATCHET instead -- the same mechanism as advisory debt. The current open
    count is the new ceiling the moment it drops, so the only permitted direction is down,
    and no number had to be invented.

    MEASURE CORRECTED 2026-07-26 (RC-65, operator: "i don't care about caps as long as we have
    great code — i thought this was a mechanical lock"). Counting EVERY open item conflated two
    opposite things: honest new tracking and deferral. On 2026-07-26 a session that found real
    defects (RC-43's closure was wrong; RC-58's contamination set) FAILED this gate *because* it
    recorded them — which teaches the agent to stay silent, the precise opposite of this repo's
    purpose. A control that punishes discovery is worse than no control.

    What actually means "deferred forever" is an item PAST ITS DUE DATE. So the ratchet now counts
    OVERDUE dated items (root-cause rows and register claims both carry a due date) plus every
    unchecked OPEN_ITEMS.md row, which has no due date and therefore stays a pure parking-lot
    count. Opening a defect today with a real due date is free; letting it rot is not — and the
    burn-down pressure the operator asked for in 2026-07-19 is preserved exactly where it belongs.
    """
    out: list[Violation] = []
    rc = REPO / "governance" / "root_cause_log.md"
    open_items = _overdue_governance_items(
        rc, REPO / "governance" / "unproven_register.md")
    # OPEN_ITEMS.md joined the ratchet 2026-07-20. WHAT WAS OBSERVED: the cap covered
    # only the two governance ledgers, so OPEN_ITEMS.md was an UNGATED parking lot --
    # a "flagged, not fixed" disposition could sit there forever, which is exactly the
    # banned third state (operator: Fixed / Allowlisted-with-reason / Registered-with-
    # due-date, nothing else). Counting its unchecked rows puts the same only-down
    # pressure on it. VALIDATED BY PROTOTYPE: 39 unchecked rows at adoption (33 pre-existing + 6
    # registered from the 2026-07-20 audit remainder); the ceiling was re-baselined
    # 10 -> 49 IN THE SAME CHANGE (scope expansion, not backsliding) and
    # may only fall from there.
    # RC-280: RATCHET REMOVED 2026-08-07 on operator instruction ("WE DO NOT NEED RATCHETS.
    # WE NEED GREAT CODE. WE NEED TO REMOVE ALL RATCHETS"), and this mission's done_criteria:
    # no ceiling the operator did not name a number for. This check used to store a
    # high-water mark in governance/open_item_ceiling.json and block whenever the count rose
    # above it. MEASURED cost of that design: the ceiling stood at 37 against 39 items and
    # blocked the commit carrying the adversarial-audit request the operator had already sent
    # to Cursor, while 34 tests were red -- the control was spending the session on itself.
    # An invented number also invites an invented remedy: the cheapest way past a count is to
    # close a row rather than fix a defect, which is the opposite of the intent.
    #
    # What survives is the LAW without the number: a dated item may not rot. Zero overdue is
    # a standard, not a tolerance, and it needs no baseline to compare against.
    #
    # DELIBERATELY DROPPED: the unchecked OPEN_ITEMS.md rows this also counted. They carry no
    # due date, so they were pure parking-lot volume -- the quantity a ratchet measures and a
    # law cannot. Requiring a due date on every parked row is the honest successor and is a
    # separate change, not something to smuggle in here.
    # RC / register due dates have zero work authority (operator 2026-08-22).
    # Unresolved work and completion blocking live only on the sole master.
    # The helper `_overdue_governance_items` remains as a measurement, not a gate.
    del open_items
    return out


#: Receivers whose .get() is not a dict read we can reason about (routes, env, vendor libs).
_ORPHAN_KEY_SKIP_RECEIVERS = frozenset({
    "app", "router", "api", "client", "session", "requests", "httpx", "self",
    "environ", "os", "sys", "kwargs", "headers", "params", "cookies", "query",
    # `payload` is by definition an EXTERNAL contract we receive, not one we write — e.g. the
    # Claude Code PreToolUse hook JSON on stdin (tool_name / tool_input / file_path, RC-66).
    # Its keys can never appear as writes in this repo, so flagging them is a guaranteed
    # false positive of exactly the "confirm it comes from a vendor payload" class.
    "payload",
})


#: Committed data files whose keys ARE writes by this repository (RC-384). Explicit by
#: design — each entry names the reader file, so the list stays reviewable and cannot
#: quietly grow into "scan everything", which would invent a writer for any string.
#: The second field is a repo-relative .py path: a data-file key only excuses a .get()
#: in THAT file (Cursor audit of fd3403b2: walking every nested key into the GLOBAL
#: write set harvested 26 names including dir/enabled/note — the glob failure at file
#: scope). Credit is file_keys ∩ reader_.get() keys, applied only at that reader path.
_DATA_FILE_KEY_SOURCES: tuple[tuple[str, str], ...] = (
    # read by active_bundle_contract._load_migration_policy -> _legacy_allowance_open
    # and artifact_integrity_strict_absence
    ("governance/ML_ITEM4_MIGRATION_POLICY.json", "active_bundle_contract.py"),
    # read by v2_decision.a2_session_calendar.load_a2_session_calendar / _is_valid_calendar
    ("data/trading_calendar/us_equities.json", "v2_decision/a2_session_calendar.py"),
)


def _json_object_keys(path: Path) -> set[str]:
    """Every string key in a JSON document, at any depth. Missing/malformed -> empty."""
    found: set[str] = set()

    def walk(node: object) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                if isinstance(k, str):
                    found.add(k)
                walk(v)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    try:
        walk(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return set()
    return found


def _loader_get_keys(loader_rel: str) -> set[str]:
    """Literal .get("k") keys in the named reader. Unreadable -> empty (never widen writes)."""
    path = REPO / loader_rel
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return set()
    out: set[str] = set()
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call):
            continue
        if not isinstance(n.func, ast.Attribute) or n.func.attr != "get" or not n.args:
            continue
        a0 = n.args[0]
        if isinstance(a0, ast.Constant) and isinstance(a0.value, str):
            out.add(a0.value)
    return out


def _data_file_keys_for(loader_rel: str) -> set[str]:
    """Keys the named reader actually .get()s that exist in its named committed file."""
    found: set[str] = set()
    loader_rel = loader_rel.replace("\\", "/")
    for data_rel, named in _DATA_FILE_KEY_SOURCES:
        if named.replace("\\", "/") != loader_rel:
            continue
        found |= _json_object_keys(REPO / data_rel) & _loader_get_keys(named)
    return found


def _committed_data_file_keys() -> set[str]:
    """Union of loader-scoped harvests — diagnostics / tests, NOT a global write set."""
    found: set[str] = set()
    for _data_rel, loader_rel in _DATA_FILE_KEY_SOURCES:
        found |= _data_file_keys_for(loader_rel)
    return found


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
    # RC-384: committed data-file keys are credited ONLY at the named reader path
    # (file ∩ reader .get()), never dumped into this global write set. A global union
    # harvested 26 keys from the policy file including dir/enabled/note — the same
    # blindness a JSON glob would buy, at file scope (Cursor audit of fd3403b2).
    data_by_loader = {
        loader_rel.replace("\\", "/"): _data_file_keys_for(loader_rel)
        for _data_rel, loader_rel in _DATA_FILE_KEY_SOURCES
    }

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

    # RC-84 — a key that genuinely arrives from OUTSIDE this repo (a Schwab OAuth token, a chain
    # node, a SQL column alias, an operator's POST body) is never written here and never will be,
    # so without a way to say so the list can only grow and can never be worked to zero. The repo
    # already uses this idiom for the coercion gate ('# vendor-coercion-ok:') and for synthetic
    # test fixtures; the declaration carries a REASON so it is reviewed rather than waved through.
    out: list[Violation] = []
    for key, (path, line) in sorted(reads.items()):
        if key in writes:
            continue
        try:
            rel = str(Path(path).resolve().relative_to(REPO.resolve())).replace("\\", "/")
        except ValueError:
            rel = str(path).replace("\\", "/")
        if key in data_by_loader.get(rel, ()):
            continue
        try:
            src_line = path.read_text(encoding="utf-8", errors="replace").splitlines()[line - 1]
        except (OSError, IndexError):
            src_line = ""
        if "external-key-ok:" in src_line:
            continue
        out.append(Violation(
            path, line,
            f"key {key!r} is read from a dict but never written anywhere in the repo "
            f"- a stale or misspelled key is a silent None, not an error (RC-15/RC-20). "
            f"Fix the name, or if it genuinely arrives from outside this repo declare it inline "
            f"with '# external-key-ok: <where it comes from>'."))
    return out


# institutional-complexity-ok: this function IS an enumeration - one branch per way this
# language creates a dict key (literal, subscript assign, setdefault/pop, dict(k=v) keyword
# form, dataclass/TypedDict field). Its complexity is the COUNT of those ways, so splitting
# it scatters one cohesive list across helpers and makes the next omission harder to spot -
# and an omission here is precisely the RC-84 defect, where two missing branches made the
# check report live, correct money-path code as a suspected silent-None.
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
    # RC-84 - two more ways this repo legitimately CREATES a dict key. Without them the check
    # reported live, correct money-path code as a suspected silent-None: `mc_available`,
    # `ml_layer_probs`, `timeframe_reads` and `startup_git_sha` were all flagged as never written
    # while /api/state returned every one of them POPULATED on the running console. An instrument
    # that cries wolf on working code trains its reader to dismiss it, which costs more than the
    # defects it was built to catch.
    elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "dict":
        # dict(spot=..., regime=...) builds exactly the same keys as a dict literal.
        writes.update(kw.arg for kw in node.keywords if kw.arg)
    elif isinstance(node, ast.ClassDef):
        # Dataclass / TypedDict / NamedTuple FIELDS become dict keys the moment the instance goes
        # through asdict() or dict() - which is precisely how server.py reads `startup_git_sha`
        # off ProcessIdentityV1. A declared field IS a declaration that the key exists.
        for stmt in node.body:
            if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                writes.add(stmt.target.id)
            elif isinstance(stmt, ast.Assign):
                writes.update(t.id for t in stmt.targets if isinstance(t, ast.Name))


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
        src = _read_or_empty(p)
        if not src:
            continue   # RC-116: vanished mid-scan — nothing to police
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
    file a sole-master id and reference it."""
    out: list[Violation] = []
    for p in _production_py_files():
        try:
            lines = p.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        for i, ln in enumerate(lines, 1):
            if _TODO_RE.search(ln) and not _TRACK_ID_RE.search(ln):
                out.append(Violation(p, i, "TODO/FIXME/HACK without a tracking id — file it on the sole master and reference the id"))
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


def check_eol_style_invariant() -> list[Violation]:
    """RC-382 — a file's line-ending style must survive an edit.

    WHAT WAS OBSERVED (RC-382, measured 2026-08-15): three whole-file reflows landed in a
    single session, each turning a small intent into an unreviewable diff — the RC-372
    charter flip; .claude/settings.json committed as 78 insertions / 71 deletions for an
    8-line addition; and an RC-381 declaration pass committed as 2428 / 2427 for 15 lines.
    A fourth writer (csv.DictWriter, which emits CRLF regardless of how the handle was
    opened) was caught only by a test. No mechanism owned a file's terminator.

    HOW THE RULE WAS VALIDATED — prototyped before enforcing, not asserted:
      * Run against the live tree BEFORE registration: 0 violations, so the check was not
        born failing and could be enforced rather than shipped advisory.
      * Plant-verified in both directions on real git repos with core.autocrlf=false (the
        setting under which occurrence 3 still happened): a pure reflow and a style-flip
        hiding a real edit are both refused; an ordinary edit that preserves the terminator
        passes, a newly added file cannot violate a style it never had, and binary and
        `-text` paths are exempt by git attribute rather than by suffix guess.
      * RC-383 corrected a false-positive class found during that prototyping: paths pinned
        `text eol=lf` are normalised by git on the way into the blob, so they are judged on
        the form git will STORE. A gate that cries wolf on the repo's own configuration
        gets switched off, taking the real protection with it.
      * Since registering it has caught two occurrences nobody went looking for: my own
        .gitattributes edit, refused BEFORE it reached a commit, and
        advisory_debt_baseline.json on the merged main tree — the latter exposing RC-385,
        a gate that rewrites the baseline it measures.

    Delegates to tools/check_eol_style_invariant.py, which compares each changed file's
    bytes against its HEAD blob. Kept as a separate module because it is also the
    standalone --measure instrument, and because the rule is about BYTES rather than
    about source text: binding it to a library idiom would miss the next writer, and this
    class already arrived through four different ones.
    """
    try:
        from tools.check_eol_style_invariant import violations as _eol_violations
    except ImportError:  # pragma: no cover - import shape differs when run as a script
        from check_eol_style_invariant import violations as _eol_violations  # type: ignore

    import subprocess as _sp

    out: list[Violation] = []
    # Staged when there is an index to judge (pre-commit), worktree otherwise, so a
    # developer running the gate by hand sees the same verdict the commit will give.
    _staged_probe = _sp.run(
        ["git", "diff", "--cached", "--name-only"], cwd=str(REPO),
        capture_output=True, text=True, check=False,
    )
    staged = bool(_staged_probe.stdout.strip())
    for message in _eol_violations(staged=staged):
        path_part = message.split(":", 1)[0]
        out.append(Violation(Path(path_part), 0, message))
    return out


def check_absence_has_a_type() -> list[Violation]:
    """RC-301 — a function that can fail must be able to SAY so in its return type.

    THE CLASS: `absence-coerced-to-a-value` has been found SEVEN times in three days
    (RC-274, RC-277, RC-282, RC-284, RC-285, RC-289, RC-301). Each predecessor was found by
    an auditor pointing at one line, and each repair fixed the value while leaving the SHAPE
    producible — which is why the count kept climbing.

    WHY THE EXISTING GATES CANNOT SEE IT: `no_fake_defaults` and the silent-zero family
    match EXPRESSIONS (`x or 0.0`, `.get(k, 0)`). This defect lives in the RETURN TYPE. A
    function annotated `-> float` has already declared absence inexpressible, so `return
    0.0` in the except handler reads as the only way to satisfy the signature.

    HOW THE RULE WAS VALIDATED: PROTOTYPED before enforcing. A first pass over all
    non-Optional scalar returns found 78 and was almost entirely legitimate — `main() ->
    int` returning exit code 2, and predicates like `is_canonical_bar_start_ts_utc() ->
    bool` returning False, which is a real answer. Restricting to `-> float` MEASUREMENTS
    left TWO, both real: `math_levels.parity_f_minus_spot_from_contracts` (repaired to
    `float | None`; 0.0 there asserts the forward equals spot with no basis) and
    `lstm_data._safe_float` (marked, with its unverified contract stated). Zero on merit.
    """
    out: list[Violation] = []
    try:
        sys.path.insert(0, str(REPO / "tools"))
        from check_absence_has_a_type import violations as _v
        for msg in _v():
            out.append(Violation(REPO / msg.split(":")[0], 0, msg))
    except Exception as exc:                                        # noqa: BLE001
        out.append(Violation(REPO / "tools" / "check_absence_has_a_type.py", 0,
                             f"checker unavailable ({type(exc).__name__}: {exc}) — a gate "
                             f"that cannot run is not a gate"))
    return out


def check_one_producer() -> list[Violation]:
    """SP-01..SP-07 (RC-325) — ONE authorized production producer per canonical concept.

    OPERATOR MANDATE 2026-08-09, roughly the tenth instruction: "we need one and only one
    producer." Many consumers are expected; a consumer CARRIES the canonical value and may
    not reconstruct it from upstream primitives.

    WHY THE EARLIER LOCKS DID NOT SATISFY IT. `single_faucet_provenance` inspects `kl_*`
    and sees THREE keys in server.py; `phase2a_level_lock` governs NINETEEN price-level
    ids; server.py emits FIVE HUNDRED AND NINETY-TWO distinct payload keys. Worse,
    single_faucet_provenance checks which function WRITES a field name, not which computes
    the value, so it passes while a quantity is derived in several places.

    THIS CHECK is registry-driven: `governance/computation_registry.json` names the one
    permitted producer per concept, and a registered concept computed at 2+ sites FAILS.
    Unregistered fields are NOT_PROVEN — counted and reported by `--measure`, never
    silently passed, so "green" means "the mandate holds over this much" rather than "the
    mandate holds". Clone detection is a candidate generator (`deep_duplicate_probe_v1`);
    producer authority is the enforcement decision.
    """
    out: list[Violation] = []
    try:
        sys.path.insert(0, str(REPO / "tools"))
        from check_one_producer import violations as _v
        for msg in _v():
            out.append(Violation(REPO / "governance" / "computation_registry.json", 0, msg))
    except Exception as exc:                                        # noqa: BLE001
        out.append(Violation(REPO / "tools" / "check_one_producer.py", 0,
                             f"checker unavailable ({type(exc).__name__}: {exc}) — a gate "
                             f"that cannot run is not a gate"))
    return out


def check_five_why_reaches_bedrock() -> list[Violation]:
    """RC-321 — a five-why terminates on a DEFECT, never on an EXPLANATION.

    OPERATOR LAW (2026-08-09, non-negotiable): "we do 5 whys to bedrock."

    WHAT WAS OBSERVED. RC-315's chain was five levels deep, ended `ROOT: TERMINAL` with a
    real justification, and PASSED `five_why_recursive_lock` — while its level (4) read
    "because the operator's instruction ... removed the one check that had been catching
    me". An outside audit rejected it in one line: being asked to decide never suspended the
    evidence-before-assertion law.

    WHY THE EXISTING LOCK CANNOT SEE IT. `five_why_recursive_lock` enforces a chain's SHAPE
    — five levels, a terminal root with a justification or a spawned child that exists — and
    all of it held. Shape was enforced; OWNERSHIP of the cause was not.

    THE RULE. A why-step may not hand causation to another actor's instruction, request or
    message. Those are circumstances, not defects this repository can repair. Quoting a
    blame-shift in order to REJECT it is required of a corrected row, so a rejection marker
    in the same cell clears it.

    VALIDATED BEFORE WIRING: 290 rows scanned; a first pattern matched bare "time pressure"
    and produced one FALSE POSITIVE (RC-290 uses pressure to describe an incentive gradient
    and its root correctly names my own defect), so the RULE was narrowed rather than the
    ROW exempted. Zero on merit. Fires on RC-315 as first written, recovered with
    `git show e1bc6793:governance/root_cause_log.md`, and stays silent on it as corrected.
    """
    out: list[Violation] = []
    try:
        sys.path.insert(0, str(REPO / "tools"))
        from check_five_why_reaches_bedrock import violations as _v
        for msg in _v():
            out.append(Violation(REPO / "governance" / "root_cause_log.md", 0, msg))
    except Exception as exc:                                        # noqa: BLE001
        out.append(Violation(REPO / "tools" / "check_five_why_reaches_bedrock.py", 0,
                             f"checker unavailable ({type(exc).__name__}: {exc}) — a gate "
                             f"that cannot run is not a gate"))
    return out


def check_rc_mechanism_claims_cite_a_source() -> list[Violation]:
    """RC-319 — a claim about how the MARKET behaves must be checkable by a reader.

    WHAT WAS OBSERVED (2026-08-09). "Hedging MAGNITUDE pins price regardless of net sign"
    went into governance/mega2_traceable_inventory.py and a decision was built on it. It is
    false — magnitude sets the SIZE of the re-hedging flow, the SIGN of the dealer position
    sets whether it stabilises or repels — and an independent Cursor audit overturned it the
    next day. The claim was not unknowable. It was UNCITED, so the only way to catch it was
    to already know the mechanism.

    WHY THE EXISTING LOCKS DID NOT FIRE. `rc_numeric_claims_cite_a_command` demands
    provenance for NUMBERS and this claim has none. `five_why_recursive_lock` enforces a
    chain's SHAPE, and RC-315's chain was five deep with a clean terminal root while resting
    on a false premise. Depth was enforced; checkability was not — which is the gap the
    operator named: "if we are not enforcing correctness then what the hell are we doing?"

    THE RULE. Not "is the claim true" — no static check can know that, and asserting
    otherwise would repeat the overreach. A row or a derivation justification that asserts a
    market mechanism in the VERB sense must carry a DOI, a URL, a named paper, or a
    backticked reproducible command. It makes the claim refutable in place.

    VALIDATED BEFORE WIRING: 288 rows scanned, 36 mechanism mentions, one uncited; narrowed
    to the verb sense because the noun "pin" is how the field is NAMED and matching it would
    teach rewording instead of citing. Zero on merit in both scopes after the one real hit —
    the corrected RC-315 line — was repaired by adding its sources, not exempted. The
    negative control recovers the REAL false sentence with `git show 6f95a237:...` rather
    than reconstructing it, which is the failure RC-317 records.
    """
    out: list[Violation] = []
    try:
        sys.path.insert(0, str(REPO / "tools"))
        from check_rc_mechanism_claims_cite_a_source import violations as _v
        for msg in _v():
            out.append(Violation(REPO / msg.split(":")[0], 0, msg))
    except Exception as exc:                                        # noqa: BLE001
        out.append(Violation(REPO / "tools" / "check_rc_mechanism_claims_cite_a_source.py",
                             0, f"checker unavailable ({type(exc).__name__}: {exc}) — a "
                                f"gate that cannot run is not a gate"))
    return out


def check_test_claims_are_executed() -> list[Violation]:
    """RC-298 — a test that string-matches prose cannot detect a false claim.

    WHAT WAS MEASURED (2026-08-07). tests/test_charm_docstring_states_the_physics_v1.py, as
    shipped under RC-294, contained EIGHT assertions and every one read
    `assert "<a sentence I wrote>" in DOC`. It confirmed only that I had written what I had
    written. The claim it locked — "calls sell, puts buy" — was false, and the suite was
    green, because a string match cannot disagree with the string. One line of execution
    refuted the file: `math_levels.bs_charm` takes no call/put argument, and its sign tracks
    moneyness (+0.7654 at K=90 versus −1.5684 at K=105 for spot 100).

    RC-281 (three `# silent-zero-ok:` reasons) and RC-290 (both `# caps-ok:` reasons) are
    the same shape. In each case the verification method for a CLAIM was reading, and
    reading is what produced the claim.

    WHAT THIS DOES NOT DO. It cannot judge whether a claim is true. It refuses a file that
    could never find out — prose assertions with no call to the subject anywhere. Text
    assertions stay legal and this repo needs them (a marker carries a reason, a retired
    pattern has not returned, a gate is wired into a live path); what is refused is a file
    made entirely of them while standing in as a behavioural lock under RC-49.

    HOW THE RULE WAS VALIDATED: PROTOTYPED against this repository before enforcing, twice.
    The first shape counted a subject call only INSIDE the assert expression and produced
    six hits, five of them FALSE POSITIVES — tests/test_pred_1c_horizon_persistence_v1.py
    calls `_build_snapshot_dict(...)` and then asserts on the returned dict, the ordinary
    shape of a good test. Recounting calls at MODULE scope left ONE real offender,
    tests/test_stack_wire_5_v1.py (13 prose assertions, 0 calls), which was REPAIRED by
    adding an executed boundary check on `is_rth_open` rather than exempted. The rule
    therefore binds at zero on merit with no exemption used, which is why it is ENFORCED
    from the start rather than ratcheted.
    """
    out: list[Violation] = []
    try:
        sys.path.insert(0, str(REPO / "tools"))
        from check_test_claims_are_executed import violations as _v
        for msg in _v():
            out.append(Violation(REPO / msg.split(":")[0], 0, msg))
    except Exception as exc:                                        # noqa: BLE001
        out.append(Violation(REPO / "tools" / "check_test_claims_are_executed.py", 0,
                             f"checker unavailable ({type(exc).__name__}: {exc}) — a gate "
                             f"that cannot run is not a gate"))
    return out


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


def mypy_interpreter() -> str:
    """The interpreter that WILL run mypy — the single authority the panel also stamps.

    RC-143: check_mypy_types ran mypy through sys.executable, so the count depended on how the
    caller was launched. MEASURED 2026-07-29/30 at one HEAD: PATH python reported 753 while the
    repo .venv reported 751, and the panel stamped "repo .venv" either way, certifying a
    comparability it had not established. The repo already mandates ONE interpreter for its
    tooling (check_venv_parity), so the metric is pinned to it here and the choice is returned
    rather than assumed — a caller launched with system python now gets the same number, and
    the fallback is visible instead of silent.
    """
    cand = REPO / ".venv" / "Scripts" / "python.exe"
    if cand.exists():
        try:
            probe = subprocess.run([str(cand), "-c", "import mypy"],
                                   capture_output=True, timeout=60)
            if probe.returncode == 0:
                return str(cand)
        except (OSError, subprocess.SubprocessError):
            pass
    return sys.executable


def _tracked_py_files() -> set[str] | None:
    """Repo-relative .py paths git actually tracks, or None when git cannot answer.

    RC-145: `mypy .` walks the DISK, and the disk holds files the commit does not.
    MEASURED 2026-07-30 on a tree git called completely clean: 1,115 .py files in scope, 501
    of them untracked — a nested registered worktree (git omits it from `status` entirely) plus
    gitignored scratch probes, two of which contributed findings to the debt total. So the
    "clean tree" stamp was true and the number still described a different population on every
    machine, which is why two agents at one HEAD could not reconcile 759 against 751.
    """
    try:
        r = subprocess.run(["git", "ls-files", "*.py"], cwd=str(REPO),
                           capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    return {ln.strip().replace("\\", "/") for ln in r.stdout.splitlines() if ln.strip()}


def check_mypy_types() -> list[Violation]:
    """Delegate type checking to mypy. DORMANT until mypy is installed (returns nothing),
    then activates automatically — no environment change forced.

    RC-143: runs under mypy_interpreter(), not the caller's interpreter, so the count is a
    property of the TREE plus that one pinned instrument rather than of the launcher.
    RC-145: findings in files git does not track are DROPPED, so the number describes the
    committed codebase instead of whatever scratch files happen to sit on this disk. Debt in
    an untracked probe is not repo debt, and counting it made the metric unreproducible."""
    try:
        r = subprocess.run(
            [mypy_interpreter(), "-m", "mypy", ".", "--ignore-missing-imports",
             "--no-error-summary",
             "--explicit-package-bases", "--namespace-packages",
             "--exclude", r"(tests|archive|\.venv|node_modules)"],
            cwd=str(REPO), capture_output=True, text=True, timeout=900,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return []  # mypy not installed / timed out — dormant, not "clean"
    if "No module named mypy" in (r.stderr or ""):
        return []
    tracked = _tracked_py_files()
    out: list[Violation] = []
    for line in r.stdout.splitlines():
        m = re.match(r"^(.+?):(\d+):\s*error:\s*(.*)$", line.strip())
        if not m:
            continue
        rel = m.group(1).strip().replace("\\", "/")
        # RC-145: scope the count to the COMMIT. When git cannot answer (tracked is None) the
        # raw result stands rather than silently shrinking to "clean".
        if tracked is not None and rel not in tracked:
            continue
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
UNPROVEN_STALE_DAYS = 14  # retained as historical constant; not a work gate


_OPEN_STATUSES = {"UNPROVEN", "DISPROVED"}
_TERMINAL_STATUSES = {"PROVEN", "REMEDIATED"}


def parse_live_unproven_rows(text: str) -> list[dict[str, str]]:
    """UNPROVEN/DISPROVED register rows (evidence wording). Not a work queue."""
    out: list[dict[str, str]] = []
    for ln in (text or "").splitlines():
        if not ln.startswith("|"):
            continue
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if len(cells) >= 4 and cells[0] in _OPEN_STATUSES:
            out.append({
                "status": cells[0],
                "due": cells[2] if len(cells) > 2 else "",
                "claim": cells[3],
            })
    return out


def unmapped_live_unproven_rows(reg_text: str, master_text: str) -> list[str]:
    """Claims whose first 40 claim characters are absent from the sole master."""
    out: list[str] = []
    for row in parse_live_unproven_rows(reg_text):
        snippet = row["claim"][:40]
        if snippet and snippet in (master_text or ""):
            continue
        out.append(snippet or row["claim"][:40])
    return out


def unmapped_open_rc_ids(rc_text: str, master_text: str) -> list[str]:
    """OPEN/PARTIAL RC ids that do not appear on the sole master."""
    out: list[str] = []
    for ln in (rc_text or "").splitlines():
        if not ln.startswith("| RC-"):
            continue
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if len(cells) > 1 and cells[1] in ("OPEN", "PARTIAL") and cells[0] not in (master_text or ""):
            out.append(cells[0])
    return out


def check_unproven_register() -> list[Violation]:
    """Evidence-integrity only. Zero work-state / due-date / commit-block authority.

    The register may preserve historical PROVEN/REMEDIATED/UNPROVEN/DISPROVED wording.
    Missing file or an unparseable date on a register row is a broken evidence record.
    UNPROVEN / DISPROVED / a due date must not select work or block completion — that
    authority lives only on the sole master.
    """
    if not _UNPROVEN_REGISTER.exists():
        return [Violation(_UNPROVEN_REGISTER, 1,
                          "unproven register missing — historical evidence file is required")]
    out: list[Violation] = []
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
        try:
            datetime.date.fromisoformat(cells[2])
        except ValueError:
            out.append(Violation(_UNPROVEN_REGISTER, i,
                                 f"{status} row has an unparseable due date (want YYYY-MM-DD)"))
    return out


#: RC rows that predate the citation rule. Frozen, exactly like the CHECKS grandfather set:
#: PROTOTYPED against the log before shipping — 20 of 29 rows carry 3+ numeric claims and
#: ZERO reproducible citations, so enforcing retroactively would block every commit and
#: force fabricated citations onto numbers whose commands are long gone. The rule binds
#: rows opened from here forward.
_RC_CITATION_GRANDFATHERED = frozenset(f"RC-{i}" for i in range(1, 30))

#: A citation is a backticked fragment that could be RE-RUN to reproduce the number.
#: RC-136: `curl` and the HTTP-probe forms were MISSING, so the operator's RC-125 live-probe
#: law — which is curl-shaped by definition — could not satisfy this rule. Measured
#: 2026-07-29: RC-134's row cited `curl -s "http://127.0.0.1:8000/api/terrain?ticker=SPY"`
#: and the gate still failed, pressuring the author to reword TRUE evidence until the regex
#: was happy, which is the citation theater this rule exists to prevent. proof_only_guard's
#: COMMAND regex had to close the same gap for curl and 127.0.0.1 earlier that day.
#: The rule's STRENGTH is unchanged: numbers with no backticked command still fail, and a
#: backticked span that is prose rather than a command still fails.
_RC_CITATION_RE = re.compile(
    r"`[^`]*(SELECT |COUNT\(|SUM\(|PRAGMA |pytest|python |node |tools/|\.py"
    r"|curl |urllib|http://127\.0\.0\.1|https?://localhost)[^`]*`", re.I
)
#: A numeric CLAIM — a bare digit run, optionally with a unit. Dates and RC ids are excluded
#: by the callers stripping them, so "2026-07-20" does not read as three claims.
_RC_NUMBER_RE = re.compile(r"\b\d[\d,.]*\s*(?:GB|MB|KB|s|ms|%|x|rows|files|strikes|tests)?\b")
_RC_CITATION_MIN_NUMBERS = 3


#: Rows written BEFORE check_verdicts_declare_their_power existed. Frozen: the rule binds
#: NEW verdicts, exactly as the citation and justification rules do.
_VERDICT_POWER_GRANDFATHERED = frozenset({
    "RC-1",
    "RC-10",
    "RC-11",
    "RC-12",
    "RC-13",
    "RC-14",
    "RC-15",
    "RC-16",
    "RC-17",
    "RC-18",
    "RC-19",
    "RC-2",
    "RC-20",
    "RC-21",
    "RC-22",
    "RC-23",
    "RC-24",
    "RC-25",
    "RC-26",
    "RC-27",
    "RC-28",
    "RC-29",
    "RC-3",
    "RC-30",
    "RC-31",
    "RC-32",
    "RC-33",
    "RC-34",
    "RC-35",
    "RC-36",
    "RC-37",
    "RC-38",
    "RC-39",
    "RC-4",
    "RC-40",
    "RC-41",
    "RC-42",
    "RC-43",
    "RC-44",
    "RC-45",
    "RC-46",
    "RC-47",
    "RC-48",
    "RC-49",
    "RC-5",
    "RC-50",
    "RC-51",
    "RC-52",
    "RC-53",
    "RC-54",
    "RC-55",
    "RC-56",
    "RC-57",
    "RC-58",
    "RC-59",
    "RC-6",
    "RC-63",
    "RC-65",
    "RC-67",
    "RC-68",
    "RC-69",
    "RC-7",
    "RC-70",
    "RC-72",
    "RC-73",
    "RC-74",
    "RC-75",
    "RC-76",
    "RC-77",
    "RC-78",
    "RC-79",
    "RC-8",
    "RC-80",
    "RC-81",
    "RC-82",
    "RC-83",
    "RC-84",
    "RC-85",
    "RC-87",
    "RC-9",
})


def check_verdicts_declare_their_power() -> list[Violation]:
    """A recorded KILL / RETIRED / PROVEN must state the n and an interval it was decided on.

    WHAT WAS OBSERVED (2026-07-27). 'GEX-R1 RETIRED BY MEASUREMENT' was cited as settled fact for
    days. Re-derived on demand, the retirement study measured n=66, Spearman -0.051, 95% CI
    [-0.289, +0.194] -- an interval that CONTAINS the founding -0.22 the verdict was used to
    reject -- and 43% power against that effect, where 80% needs 160 sessions. The study could not
    have distinguished 'no effect' from 'the claimed effect'. It was a coin flip recorded as a
    kill.

    WHY THE EXISTING LOCK DID NOT FIRE. `rc_numeric_claims_cite_a_command` already demands the
    COMMAND behind a number, and that is necessary -- a sampled figure and an exact one read
    identically. It is not sufficient: a perfectly reproducible command can still be run on a
    sample far too small to support the verdict drawn from it. Reproducibility and power are
    different properties, and only the first was gated.

    Rule: a governance row asserting a hard verdict must carry `n=` AND one of a confidence
    interval / power figure. Absence of evidence is not evidence of absence, and a row that
    cannot show which of the two it holds must not record a kill.

    HOW THE RULE WAS VALIDATED: prototyped against the log before enforcing; the grandfather set
    freezes rows written before the rule so it binds new verdicts only -- the same design already
    used by `rc_numeric_claims_cite_a_command` and `checks_are_justified`.
    """
    out: list[Violation] = []
    log_path = REPO / "governance" / "root_cause_log.md"
    if not log_path.exists():
        return out
    verdict = re.compile(r"\b(KILL|KILLED|RETIRED|PROVEN|DISPROVEN)\b")
    has_n = re.compile(r"\bn\s*=\s*\d+", re.I)
    has_interval = re.compile(r"(95%\s*CI|confidence interval|\bpower\b)", re.I)
    for num, line in enumerate(log_path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.startswith("| RC-"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 7:
            continue
        rc_id = cells[0]
        if rc_id in _VERDICT_POWER_GRANDFATHERED:
            continue
        body = " ".join(cells[4:])
        if not verdict.search(body):
            continue
        if has_n.search(body) and has_interval.search(body):
            continue
        out.append(Violation(
            log_path, num,
            f"{rc_id} records a hard verdict without declaring the evidence that could support "
            f"it. State n= and a 95% CI or power figure, or soften the verdict to UNPROVEN. "
            f"A null at n=66 and a null at n=1000 read identically in prose; only the interval "
            f"tells them apart, and GEX-R1 was killed on a CI that contained the effect."))
    return out


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


def check_schwab_market_field_semantics() -> list[Violation]:
    """Truthful semantics for NUM_* and exchange_quote_ts (RC-440; M4/M5).

    M4: NUM_BIDS/NUM_ASKS are documented "Market Maker Count" (Schwab Streamer Guide, RC-443);
    empirically the count of nested per-participant rows (market-maker MPIDs + exchange MICs).
    They are NEVER an order count; asserting the count meaning must cite the vendor source —
    BLOCKED unless a marker cites authoritative evidence.
    M5: exchange_quote_ts must carry the Schwab exchange quote clock (QUOTE_TIME_MILLIS/sec,
    TRADE_TIME_MILLIS proxy), never a server wall clock (the wall clock is server_received_ts).
    The rename from the legacy 'fast_server_ts' made the name truthful; pinning the VALUE
    keeps it truthful — the field can never silently become a server timestamp. See the
    semantic normalization ledger.

    HOW THE RULE WAS VALIDATED: prototyped against the tree (returns [] clean) and locked by
    a negative-control test (tests/test_schwab_market_field_semantics_lock_v1.py) that injects
    each defect — NUM_* labeled an order/MM count, exchange_quote_ts assigned a wall clock —
    and asserts the block fires, plus that the reasoned markers suppress.
    """
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    from tools.check_schwab_market_field_semantics import violations

    return [Violation(REPO / rel, line, msg) for rel, line, msg in violations()]


def _git_output_lines(args: list[str]) -> list[str] | None:
    """git stdout lines, or None when not in a usable git/commit context (never a false block)."""
    import subprocess
    try:
        r = subprocess.run(["git", *args], cwd=str(REPO), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=25)
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
        if ln.startswith(("+++", "---")):
            continue
        if ln.startswith(("+", "-")) and ln[1:].strip():
            return True
    return False


#: Source files a FIXED cell can name. Deliberately NOT .json/.jsonl/.md/.txt: report and
#: ledger artifacts churn from daily runs, and treating them as "the fix" would make this
#: check fire on unrelated evidence writes (RC-137's own false-positive analysis).
#: RC-140: the first cut listed only py/html/js, so a closure naming a .ts or .css fix was
#: unrecognized and therefore unchecked (v31 measured it) — every source extension the repo
#: could plausibly ship a fix in is listed here now.
_FIXED_SOURCE_FILE_RE = re.compile(
    r"\b([\w][\w./\-]*\.(?:py|pyi|html|js|jsx|mjs|cjs|ts|tsx|css|scss|sql|ps1|bat|sh|yaml|yml))\b"
)
#: RC-141: RC-140 keyed this on the literal word FIXED, so dropping that token ("See VERIFIED
#: below.") walked straight through — v32 measured it, the same omit-the-watched-token class
#: as the prose escape it replaced. The obligation now attaches to CLOSING a row, not to any
#: word in it: every new closure either names checkable source or declares it changed none.
#: Kept only to describe the claim in messages, never as the trigger.
_FIXED_CLAIM_RE = re.compile(r"\bFIXED\b\s*[:\-]", re.I)
#: The declared escape for closures that genuinely change no source (a disposition, a
#: measurement, a deferral). Explicit, so "no code" is a STATEMENT rather than an omission.
_NO_CODE_CLAIM_RE = re.compile(
    r"no code change|no source change|documentation only|ledger only|disposition only", re.I)
#: Sentinel path reported when a FIXED claim names nothing machine-readable.
_UNNAMED_FIX = "<FIXED: names no machine-readable source path>"


#: A commit SHA cited inside a row — how a closure points at code that landed earlier.
_ROW_SHA_RE = re.compile(r"\b([0-9a-f]{7,40})\b")


def _row_cells(row: str) -> list[str]:
    return [c.strip() for c in row.strip("|").split("|")]


def _closed_row_code_not_shipped(
    added_rows: list[str],
    dirty: frozenset[str] | set[str],
    *,
    removed_rows: tuple[str, ...] | list[str] = (),
    staged: frozenset[str] | set[str] = frozenset(),
    sha_touches=None,
) -> list[tuple[str, list[str]]]:
    """PURE core of RC-137/RC-139: rows whose CLOSED claim is not backed by shipped code.

    Two distinct escapes, both closed here:
      DIRTY   (RC-134's shape) — the row names FIXED files that are sitting uncommitted, so
              the ledger says fixed while HEAD does not have it.
      ABSENT  (v30's shape) — the row is NEWLY closed and names FIXED files that are in
              neither this commit nor any commit the row cites by SHA. A clean worktree is
              not evidence: it reads identically whether the fix landed or was never written.

    A row is checked only when THIS commit adds/rewrites it. ABSENT applies only to rows
    BECOMING closed (a text edit to a long-closed row cannot re-litigate old history), and a
    cited SHA that actually touched the file satisfies it — closures may point at where the
    code landed instead of carrying it.
    """
    was_closed = {
        _row_cells(r)[0] for r in removed_rows
        if len(_row_cells(r)) >= 7 and _row_cells(r)[1].upper() == "CLOSED"
    }
    out: list[tuple[str, list[str]]] = []
    for row in added_rows:
        cells = _row_cells(row)
        if len(cells) < 7 or cells[1].upper() != "CLOSED":
            continue
        rc_id = cells[0]
        body = " ".join(cells[6:])
        shas = [s for s in _ROW_SHA_RE.findall(body) if not s.isdigit()]
        bad: list[str] = []
        # RC-140/RC-141: a closure naming nothing checkable is the emptiest of all — it
        # asserts a repair while giving the machine nothing to verify. The trigger is CLOSING
        # (not the word FIXED, which v32 showed could simply be omitted); an explicit no-code
        # declaration satisfies it, so a disposition-only closure stays legal by SAYING so.
        if (rc_id not in was_closed
                and not _FIXED_SOURCE_FILE_RE.search(body)
                and not _NO_CODE_CLAIM_RE.search(body)):
            bad.append(_UNNAMED_FIX)
        for m in _FIXED_SOURCE_FILE_RE.finditer(body):
            rel = m.group(1).replace("\\", "/").lstrip("./")
            if rel in bad or rel in staged:
                continue
            if rel in dirty:
                bad.append(rel)
                continue
            if rc_id in was_closed:
                continue      # already closed before this commit — not a new claim
            if sha_touches and any(sha_touches(s, rel) for s in shas):
                continue      # the row points at the commit that carried it
            bad.append(rel)
        if bad:
            out.append((rc_id, sorted(bad)))
    return out


def check_closed_rows_ship_their_code() -> list[Violation]:
    """A CLOSED row must be backed by a real code change where it says one exists.

    Three shapes are blocked, each measured on this repo before enforcing:
      DIRTY   (RC-134/RC-137) — the row names FIXED files sitting uncommitted, so the ledger
              says fixed while HEAD does not have it.
      ABSENT  (v30/RC-139)    — a NEW closure names FIXED files carried by neither this commit
              nor any commit it cites. A clean worktree is not evidence: it reads identically
              whether the fix landed or was never written.
      UNNAMED (v31/RC-140, widened by v32/RC-141) — a NEW closure names nothing
              machine-readable, so nothing about it can be verified. The trigger is CLOSING
              the row, NOT the word "FIXED": keying on that token meant omitting it walked
              through. A closure that genuinely changes no source stays legal by SAYING so
              ("no code change" / "documentation only" / "disposition only").

    Both satisfying paths demand a REAL change: a staged file whose diff is only whitespace,
    or a cited commit that merely touched the file without changing a non-blank line, does not
    count (v31: "touched != fixed").

    HONEST LIMIT, stated rather than hidden: no checker can decide whether a real change is
    the RIGHT change — a genuine but unrelated edit to a named file still satisfies this. The
    rule proves a closure points at real, non-whitespace work in the files it names; judging
    that work remains the audit's job. The same deliberate-proxy reasoning is written into
    enforced_checks_have_negative_controls.

    WHAT WAS OBSERVED (2026-07-29, RC-137). RC-134 was written CLOSED with a FIXED cell naming
    terrain_engine.py, server.py, live_decision_bundle.py and liquidity_value_engine.py, and the
    ledger row was committed while every one of those files stayed UNCOMMITTED. HEAD therefore
    still shipped the defect (`hvl=pick_hvl_strike`) for hours while the ledger asserted the fix
    had landed. It looked correct from the outside because the running console had loaded the
    working-tree files, so the live wire agreed with the ledger and disagreed with git — one
    `git checkout .` or a stash cycle would have silently reverted the running system.

    HOW VALIDATED: prototyped against this repo before enforcing. It is scoped to rows the
    commit actually touches — a commit that does not touch the ledger cannot be blocked by
    someone else's in-flight edits, and a later text edit to an old CLOSED row stays quiet once
    its files are committed. Returns [] outside a git/commit context, so it never false-blocks.
    """
    log_rel = "governance/root_cause_log.md"
    ledger_diff = _git_output_lines(["diff", "--cached", "-U0", "--", log_rel])
    if not ledger_diff:
        return []
    added = [ln[1:] for ln in ledger_diff if ln.startswith("+| RC-")]
    removed = [ln[1:] for ln in ledger_diff if ln.startswith("-| RC-")]
    if not added:
        return []

    status = _git_output_lines(["status", "--porcelain"])
    if status is None:
        return []
    dirty: set[str] = set()
    for ln in status:
        if len(ln) < 4:
            continue
        worktree_col, path = ln[1], ln[3:].strip().strip('"')
        if " -> " in path:
            path = path.split(" -> ")[-1].strip().strip('"')
        if ln[:2] == "??" or worktree_col in ("M", "D"):
            dirty.add(path.replace("\\", "/"))

    # RC-140 ("touched != fixed"): a staged path only counts when its diff changes a
    # non-blank line, so a whitespace-only edit cannot buy a closure.
    staged_files = {
        p.replace("\\", "/")
        for p in (_git_output_lines(["diff", "--cached", "--name-only"]) or [])
        if p.strip() and _staged_has_real_change(p.strip())
    }

    def _sha_touched(sha: str, rel: str) -> bool:
        """True when `sha` really CHANGED `rel` — how a closure may point at code that landed
        in an earlier commit. RC-140: name-only membership was too weak (a whitespace or
        mode-only touch passed), so the commit's own diff for that path must carry a
        non-blank +/- line."""
        diff = _git_output_lines(["show", "-U0", "--pretty=format:", sha, "--", rel])
        if not diff:
            return False
        return any(ln.startswith(("+", "-")) and not ln.startswith(("+++", "---"))
                   and ln[1:].strip() for ln in diff)

    out: list[Violation] = []
    gaps = _closed_row_code_not_shipped(
        added, dirty, removed_rows=removed, staged=staged_files, sha_touches=_sha_touched)
    for rc_id, files in gaps:
        if _UNNAMED_FIX in files:
            out.append(Violation(
                REPO / log_rel, 0,
                f"{rc_id} is being CLOSED with a FIXED claim that names no source file a "
                f"machine can check, so nothing about the repair is verifiable (RC-140, the "
                f"prose escape v31 measured). Name the files, or state the closure changes no "
                f"code (\"no code change\" / \"documentation only\" / \"disposition only\")."))
        files = [f for f in files if f != _UNNAMED_FIX]
        still_dirty = sorted(f for f in files if f in dirty)
        absent = sorted(f for f in files if f not in dirty)
        if still_dirty:
            out.append(Violation(
                REPO / log_rel, 0,
                f"{rc_id} is being committed as CLOSED but the code it names as FIXED is still "
                f"dirty in the working tree: {', '.join(still_dirty)}. Stage the fix with its "
                f"row, or the ledger asserts a repair that HEAD does not contain (RC-137: "
                f"RC-134 shipped CLOSED while HEAD still had the defect and only the running "
                f"process looked correct)."))
        if absent:
            out.append(Violation(
                REPO / log_rel, 0,
                f"{rc_id} is being CLOSED naming FIXED files this commit does not carry and no "
                f"cited commit touched: {', '.join(absent)}. A clean worktree is not evidence — "
                f"it looks identical whether the fix landed or was never written (RC-139, the "
                f"escape v30 measured in RC-137's first cut). Stage the fix, or cite the SHA "
                f"that carried it."))
    return out


def check_recursive_five_why_front_loaded() -> list[Violation]:
    """UNIVERSAL front-loaded admission: a production change ships with a master obligation.

    OBSERVED (2026-07-26, RC-41): the five-why lock validated existing rows but never the
    ACT of admitting a defect, so sessions of fixes shipped with no analysis. Method pivot
    (operator 2026-08-22): requiring a new `| RC-` row recreated a second current debt
    ledger. Admission is now an unresolved sole-master requirement. Root-cause / five-why
    reasoning remains mandatory on that same master item. A new RC row does not admit work.

    Rule: every staged PRODUCTION file must independently resolve to an unresolved
    master item whose SURFACES= field lists that exact repo-relative path.
    One covered file does not admit an uncovered sibling. A new/modified unrelated
    master item is not admission. Tests/governance/docs/reports edits are how you
    comply and do not themselves require a SURFACES= bind. Escapes NONE by design
    for production files.
    """
    try:
        from tools.pretooluse_guard import (
            ALWAYS_ALLOWED_EXACT,
            ALWAYS_ALLOWED_PREFIXES,
            PRODUCTION_SUFFIXES,
            SOLE_MASTER,
            master_admits_production_edit,
        )
    except ImportError:
        from pretooluse_guard import (  # type: ignore
            ALWAYS_ALLOWED_EXACT,
            ALWAYS_ALLOWED_PREFIXES,
            PRODUCTION_SUFFIXES,
            SOLE_MASTER,
            master_admits_production_edit,
        )
    staged = _git_output_lines(["diff", "--cached", "--name-only"])
    if staged is None:
        return []  # not a commit context — never a false block
    staged_set = {s.strip().replace("\\", "/") for s in staged if s.strip()}
    if not staged_set:
        return []
    prod_code = sorted(
        f for f in staged_set
        if f.endswith(PRODUCTION_SUFFIXES)
        and not f.startswith(ALWAYS_ALLOWED_PREFIXES)
        and f not in ALWAYS_ALLOWED_EXACT
        and _staged_has_real_change(f)
    )
    if not prod_code:
        return []
    try:
        cur = (REPO / SOLE_MASTER).read_text(encoding="utf-8", errors="replace")
    except OSError:
        cur = ""
    head_lines = _git_output_lines(["show", f"HEAD:{SOLE_MASTER}"])
    head_txt = "\n".join(head_lines) if head_lines is not None else ""
    uncovered = [
        f for f in prod_code
        if not master_admits_production_edit(f, current_text=cur, head_text=head_txt)
    ]
    if not uncovered:
        return []
    return [Violation(
        REPO / uncovered[0], 0,
        "Production changed with uncovered path(s): " + ", ".join(uncovered) +
        ". Every staged production file must independently bind to an unresolved "
        "master item via SURFACES=<repo-relative-path>. One covered file does not "
        "admit an uncovered sibling. Search the sole master; if absent, add one "
        "atomic `- [ ]` item and bind the exact paths on that same item. Do not "
        "open a current RC debt row. Root-cause / five-why evidence belongs on "
        "that same master item.")]


def check_adversarial_audit_test_lock() -> list[Violation]:
    """Second half of the operator's mandate: the self-adversarial-audit loop is machine-forced.

    OBSERVED (2026-07-26, RC-49): the operator specified a TWO-part lock — recursive-5-why AND a
    self-adversarial-audit loop (analyze -> fix -> adversarially audit -> fix -> re-audit until
    clean) — but only the recursive-5-why half was ever mechanized (recursive_five_why_front_loaded).
    The audit half ran on agent goodwill and the operator observed it had lapsed. Per RC-41's proven
    lesson, goodwill fails and must be machine-forced. The failure this stops: a code fix reaching a
    commit with nothing that locks it — no test — so a regression silently re-opens the exact defect
    (the RC-14 -> RC-15 -> RC-16 class, three rows for one bug).

    Rule: any commit staging a real change to a PRODUCTION (non-tests/) tracked .py file MUST
    co-stage a real change to a tests/ .py file — the adversarial audit's output, a test that fails
    if the fix regresses. A genuinely untestable change (measurement-only closure, docs, pure config)
    escapes ONLY via a co-staged sole-master line carrying an explicit 'NO-TEST-LOCK: <reason>' — the
    exemption is auditable, never silent. A root-cause-log row is not the exemption surface.

    VALIDATED BY PROTOTYPE before enforcing: run against staging scenarios — fires on a prod .py
    change with no co-staged test and no NO-TEST-LOCK, passes when a real tests/ change is co-staged,
    passes on a NO-TEST-LOCK exemption, ignores test-only and non-.py commits, and no-ops (returns [])
    outside a git commit context so unit-test imports never false-block. HONEST LIMIT: a pre-commit
    check forces the test-lock ARTIFACT, not the cognitive depth of the audit — the drift-audit skill
    remains the thinking; this makes skipping the lock fail the build.
    """
    staged = _git_output_lines(["diff", "--cached", "--name-only"])
    if staged is None:
        return []  # not a commit context — never a false block
    staged_set = {s.strip().replace("\\", "/") for s in staged if s.strip()}
    if not staged_set:
        return []

    def _is_test(p: str) -> bool:
        return p.startswith("tests/") and p.endswith(".py")

    prod_code = sorted(
        f for f in staged_set
        if f.endswith(".py") and not _is_test(f) and _staged_has_real_change(f)
    )
    if not prod_code:
        return []  # no production code changed — nothing to lock
    if any(_is_test(f) and _staged_has_real_change(f) for f in staged_set):
        return []  # the fix ships its locking test
    # No co-staged test — allow ONLY an explicit, auditable NO-TEST-LOCK exemption on the master.
    master_rel = "ED_CONSOLE_INSTITUTIONAL_TRUTH_AND_REMEDIATION_V1_MASTER_CHECKLIST.md"
    if master_rel in staged_set:
        master_diff = _git_output_lines(["diff", "--cached", "-U0", "--", master_rel]) or []
        if any(l.startswith("+") and "NO-TEST-LOCK:" in l for l in master_diff):
            return []
    return [Violation(
        REPO / prod_code[0], 0,
        "Production code changed (" + ", ".join(prod_code[:5]) +
        (" …" if len(prod_code) > 5 else "") + ") with NO co-staged test. The self-adversarial-audit "
        "loop is machine-forced (RC-49): every fix ships a test that locks it (fails on regression). "
        "Co-stage a real tests/ change, or — only for a genuinely untestable measurement-only/doc/"
        "config closure — add 'NO-TEST-LOCK: <reason>' to the co-staged sole-master item. Goodwill "
        "fails; the lock does not.")]


#: RC-61 — the recurring failure CLASSES distilled from the root-cause log. Each is a pattern that
#: has already cost real defects; a NEW row that repeats one must say how this time is different.
#: (pattern-name, regex over the why/root text, the RC ids where it already bit)
_RECURRENCE_CLASSES = (
    ("goodwill-not-machine-forced",
     re.compile(r"goodwill|no mechanical|not machine[- ]forced|depended on (agent|me) remember", re.I),
     "RC-41, RC-49, RC-53, RC-56"),
    ("unverified-claim-asserted",
     re.compile(r"without measur|asserted .*without|not reproducib|uncommitted one-off|from memory", re.I),
     "RC-39, RC-40, RC-43, RC-53"),
    ("session-scope-omitted",
     re.compile(r"market[- ]closed|weekend|holiday|non[- ]trading|session scop", re.I),
     "RC-54, RC-57, RC-58"),
    ("duplicate-authority",
     re.compile(r"two (different )?(authorit|classifier|implementation|engine|width)|each .* own|open[- ]coded per", re.I),
     "RC-14, RC-36, RC-42, RC-48, RC-59"),
    ("stale-record-trusted",
     re.compile(r"stale|out of date|outdated|superseded but|no longer true", re.I),
     "RC-44, RC-55"),
)


def check_root_cause_recurrence_declared() -> list[Violation]:
    """A new root cause that REPEATS a known class must say why this time is different.

    WHAT WAS OBSERVED (2026-07-26, RC-61): the operator asked what we actually DO with the
    root-cause log — and the answer was nothing. It is written at fix time and never read at
    author time, so the same classes recur: "goodwill instead of a lock" bit at RC-41, RC-49,
    RC-53 and RC-56; "claim asserted without measurement" at RC-39, RC-40, RC-43 and RC-53;
    "session scope omitted" at RC-54, RC-57 and RC-58; "two authorities for one quantity" at
    RC-14, RC-36, RC-42, RC-48 and RC-59. A log that records history without constraining the
    next entry is an archive, not a control.

    Rule: when a commit stages a NEW '| RC-' row whose why/root text matches a known recurring
    class, that row must also carry `RECURRENCE: <class> — <why this fix breaks the cycle>`.
    The point is not paperwork: it forces the author to notice they are repeating themselves and
    to state what is structurally different, at the moment the fix is designed.

    HOW THE RULE WAS VALIDATED: the five classes were derived FROM this repo's own log (each
    lists the RC ids where it already bit, so no class is speculative), and the check is scoped to
    NEWLY ADDED rows in the staged diff — existing history is never retro-flagged, and it returns
    [] outside a git commit context so unit-test imports never false-block.
    """
    log_rel = "governance/root_cause_log.md"
    staged = _git_output_lines(["diff", "--cached", "--name-only"])
    if staged is None:
        return []
    if log_rel not in {s.strip().replace("\\", "/") for s in staged if s.strip()}:
        return []
    # Only GENUINELY NEW rows bind. Editing an existing row (e.g. adding a reproduce command)
    # shows up as an added diff line too, and demanding a recurrence declaration for that would
    # cry wolf on ordinary maintenance — so compare against the ids already committed at HEAD.
    head = _git_output_lines(["show", f"HEAD:{log_rel}"]) or []
    existing_ids = {
        ln.strip().strip("|").split("|")[0].strip()
        for ln in head if ln.startswith("| RC-")
    }
    diff = _git_output_lines(["diff", "--cached", "-U0", "--", log_rel]) or []
    out: list[Violation] = []
    for ln in diff:
        if not ln.startswith("+| RC-"):
            continue
        row = ln[1:]
        cells = [c.strip() for c in row.strip().strip("|").split("|")]
        if len(cells) < 7:
            continue
        rc_id, why = cells[0], cells[5]
        if rc_id in existing_ids:
            continue
        if "RECURRENCE:" in row.upper():
            continue
        for name, pattern, priors in _RECURRENCE_CLASSES:
            if pattern.search(why):
                out.append(Violation(
                    REPO / log_rel, 0,
                    f"{rc_id} repeats the known failure class '{name}' (already recorded at "
                    f"{priors}) but does not declare it. The root-cause log is a CONTROL, not an "
                    f"archive: add 'RECURRENCE: {name} — <what is structurally different this "
                    f"time>' so a repeat is a deliberate, explained decision rather than an "
                    f"unnoticed loop."))
                break
    return out


#: RC-95 — ENFORCED checks that predate the negative-control law and have no test naming them.
#: A BURN-DOWN LIST, visible and shrinking, never silently accepted: remove an entry ONLY by
#: adding a test that injects a violation and asserts the check returns >= 1. Adding to this set
#: is prohibited — that is the entire point of the law.
_NEGATIVE_CONTROL_GRANDFATHERED = frozenset({
    "no_synthetic_domain_fixtures_in_tests", "no_swallowed_test_failures",
    "five_why_recursive_lock", "recursive_five_why_front_loaded", "single_faucet_provenance",
    "root_cause_recurrence_declared", "fix_crosswalks_to_violated_lock",
    "domain_constants_are_derived", "no_terminal_null", "no_governance_duplication",
    "checks_are_justified", "no_tautological_assertions", "open_item_cap",
    "no_silent_swallow", "no_todo_without_tracking_id",
    # RC-136 GRADUATED rc_numeric_claims_cite_a_command off this list: it now has real fire AND
    # quiet controls (test_citation_check_fires_when_numbers_carry_no_command /
    # test_citation_check_accepts_the_repos_live_probe_forms), which is stronger than the
    # name-presence proxy this set exempts. Burn-down, never addition.
    "snapshots_read_names_the_timeframe", "shutdown_is_bounded", "unproven_register",
    "venv_parity", "credential_leak", "sqlite_wal_contract",
})


def check_enforced_checks_have_negative_controls() -> list[Violation]:
    """A NEW ENFORCED check must ship with a test proving it CAN fail (RC-95).

    WHAT WAS OBSERVED (2026-07-27). Four instruments shipped INERT in one session: an alias-blind
    client detector (RC-76), a write-detector missing two shapes (RC-84), a verdict regex carrying
    literal 0x08 backspace characters that could never match (RC-87), and a gate that mutated the
    repo while printing PASS (RC-90). Each reported 0 violations while incapable of firing, and
    each was found only by ad-hoc injection. Green-and-inert is byte-identical to
    green-and-working; a control that makes the check SCREAM on an injected violation is the only
    thing that tells them apart. MEASURED at rule creation: 22 of 33 ENFORCED checks were named in
    no test file at all.

    Rule: every ENFORCED check id must appear in some tests/*.py file. The 22 pre-existing
    uncovered checks are grandfathered as a VISIBLE burn-down list above — removal only by adding
    the control, addition prohibited.

    HOW VALIDATED: name-presence is a deliberately cheap proxy (a test could name a check without
    injecting a violation), stated rather than hidden — it catches the observed failure mode,
    which was checks nobody's test referenced AT ALL. Tightening the proxy to require an actual
    injection assertion is the named NEXT-DEPTH once the burn-down list is empty.
    """
    tests_dir = REPO / "tests"
    if not tests_dir.exists():
        return [Violation(tests_dir, 0, "tests/ directory missing — nothing can prove any check fires")]
    corpus = " ".join(_read_or_empty(p) for p in tests_dir.glob("test_*.py"))
    out: list[Violation] = []
    for name, _fn, enforced in CHECKS:
        if not enforced or name in _NEGATIVE_CONTROL_GRANDFATHERED:
            continue
        if name in corpus:
            continue
        out.append(Violation(
            REPO / "tools" / "check_institutional_correctness.py", 0,
            f"ENFORCED check '{name}' has NO negative control — no test names it, so nothing can "
            f"prove it fires on an injected violation. Green-and-inert is indistinguishable from "
            f"green-and-working (RC-76/84/87/90: four inert instruments in one session). Ship a "
            f"test that injects the defect and asserts >= 1 violation, or register ADVISORY."))
    return out


#: RC-96 — AGENTS.md law headings that predate this rule and are honestly UNENFORCEABLE by a
#: machine (they bind judgement, not a detectable artifact). Grandfathered so the rule binds NEW
#: laws; each must still carry the literal word SOFT in its own text to stay here.
_AGENTS_LAW_GRANDFATHERED = frozenset({
    "never call an operator law", "fair-method clause", "agent truth lock", "immune rule",
})


#: RC-103 — files reading price_bars_1m with NO calendar authority when the rule was created.
#: BURN-DOWN, visible and shrinking: remove an entry only by gating the file (or deleting it).
#: Addition prohibited — that is the lock. Top of the burn-down by blast radius:
#: research/pilot_step3/data_loader.py (feeds the F2 pipeline) and challenger_eval_v1/runner.py.
_PRICE_BARS_GRANDFATHERED = frozenset({
    "tools/bar_history_recovery_audit_v1.py", "tools/canonical_1m_grid_validator_v1.py",
    "tools/data_faucet_audit.py", "tools/historical_backfill_enrolled_1m_v1.py",
    "tools/ingest_1m_to_staging.py", "tools/inspect_price_bars_1m_rth_gaps.py",
    "tools/issue19_rehydration_range_v1.py", "tools/pin_neutral_anchor_feasibility_sample_v1.py",
    "tools/study_pin_charm_v1.py", "tools/study_pin_direction_v1.py",
    "tools/study_pin_regime_cut_v1.py", "tools/study_pin_residence_v1.py",
    "tools/_multi_timeframe_audit_v1.py", "tools/_phase4a_fast_count.py",
    "tools/_phase4a_proof_not_exists.py", "tools/_phase4a_quantify_anchor_miss.py",
    "tools/_phase4b_audits.py", "tools/_phase4_bar_check.py", "tools/_phase4_snapshot_detail.py",
    "tools/research/d2_build_dual_label_scratch_db.py",
    "tools/legacy/horizon_7/audit_fused_policy_history_sufficiency_v1.py",
    "tools/legacy/horizon_7/backfill_fusion_policy_columns_v1.py",
    "tools/legacy/horizon_7/backfill_pred_1c_snapshots_v1.py",
    "tools/legacy/horizon_7/batch_backfill_movement_predictions_v1.py",
    "tools/legacy/horizon_7/build_checkpoint_provenance_bundle_v1.py",
    "tools/legacy/horizon_7/enforce_universal_ticker_readiness_v1.py",
    "tools/legacy/horizon_7/phase4c_rt_vs_backfill_equivalence_v1.py",
    "tools/legacy/horizon_7/report_pred_1c_governed_remediation_v1.py",
    "tools/legacy/horizon_7/run_phase11_monitoring_drift_live_readiness_v1.py",
    "tools/legacy/horizon_7/run_phase9_decision_policy_v1.py",
    "tools/legacy/horizon_7/run_phase9_policy_remediation_v1.py",
    "tools/legacy/horizon_7/validate_movement_prediction_coverage_v1.py",
    "tools/legacy/horizon_7/_phase4e_dataset_adequacy_v1.py",
    "tools/legacy/horizon_7/_phase5_discrimination_audit_v1.py",
    "tools/legacy/horizon_7/_quick_gov_pred1c.py",
    "tools/legacy/horizon_7/_verify_outcomes_vs_bars.py",
    "research/challenger_eval_v1/runner.py", "research/pilot_step3/data_loader.py",
})

_PRICE_BARS_CAL_RE = re.compile(
    r"is_trading_day_et|is_tradable_session|_is_measurable_day|is_capturable_session|"
    r"session_safe_log_returns|_load_closes|session-universe-ok")


def check_price_bars_readers_name_their_session() -> list[Violation]:
    """A NEW file reading price_bars_1m must reference a calendar authority (RC-103).

    WHAT WAS OBSERVED. price_bars_1m carries extended hours BY DESIGN (~1,000 bars/session,
    RC-26), and the session-blindness class recurred FIVE times through this one table: RC-54
    (three market-closed measurements in one session), RC-57 (calendar-blind shared filters),
    RC-58 (seven study loaders), RC-31 twice (thirteen bar-path runners, then HAR's own diff
    after the 'fix'). Each fix gated a CONSUMER while the TABLE stayed open.
    rth_only_market_measurement guards MEASUREMENT AUTHORITIES, and a raw SELECT is not an
    authority, so the whole class sat outside its scope. MEASURED at rule creation: 38 ungated
    direct readers in tools/ + research/.

    Rule: a tools/ or research/ file containing `FROM price_bars_1m` must reference a calendar
    authority (is_trading_day_et / is_tradable_session_ts_utc / _is_measurable_day /
    is_capturable_session / session_safe_log_returns / _load_closes) or carry an explicit
    `# session-universe-ok: <reason>`. The 38 offenders are grandfathered as a visible burn-down
    — removal only by gating or deleting the file, addition prohibited.

    HOW VALIDATED: measured against the live tree (38 found, all listed above); a gated file
    passes by construction because the gate call IS the reference the pattern matches.
    """
    out: list[Violation] = []
    for base in ("tools", "research"):
        root = REPO / base
        if not root.exists():
            continue
        for p in root.rglob("*.py"):
            sp = str(p.relative_to(REPO)).replace("\\", "/")
            if "__pycache__" in sp or "worktrees" in sp:
                continue
            if sp in _PRICE_BARS_GRANDFATHERED:
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if not re.search(r"FROM\s+price_bars_1m", text, re.I):
                continue
            # RC-106 mention-loophole: an authority named in a COMMENT satisfied the check
            # while the code stayed session-blind. Authorities must appear in CODE; the
            # session-universe-ok marker is the one legitimate comment form and is checked
            # against the raw text.
            code_only = "\n".join(ln.split("#", 1)[0] for ln in text.splitlines())
            if _PRICE_BARS_CAL_RE.search(code_only) or "session-universe-ok" in text:
                continue
            out.append(Violation(
                p, 0,
                f"{sp} reads price_bars_1m with NO calendar authority. The table carries "
                f"extended hours BY DESIGN; assuming bars == RTH is the class behind "
                f"RC-31/54/57/58 (five recurrences). Gate the day/timestamp with the time_et "
                f"authority, use _load_closes(session=)/session_safe_log_returns, or declare "
                f"'# session-universe-ok: <reason>'."))
    return out


def check_rc_citations_resolve() -> list[Violation]:
    """Every RC-N cited in code must resolve to a real row (RC-99).

    WHAT WAS OBSERVED (2026-07-27). The operator's adversarial audit found RC-96 cited in a
    docstring and a commit message with no such row. One row was written, the class was not
    locked, and the SAME defect recurred within the next turn as RC-98. A sweep then measured
    SEVEN phantom ids live in the tree: RC-60, 61, 62, 64, 66, 93, 98 — so this had been silently
    accumulating for weeks. A citation that resolves to nothing turns the governance log from an
    index into decoration: the reader follows the pointer, finds nothing, and learns to stop
    following pointers.

    WHY THE EXISTING GUARD DID NOT FIRE. proof_only_guard has a promise-check, but it scans the
    TURN'S PROSE for phrasing like "opening RC-N". A citation living in a DOCSTRING or a COMMIT
    MESSAGE is invisible to it — the two surfaces already logged as unguarded in E-13.

    Rule: any RC-N appearing in tracked .py/.html source must exist as a '| RC-N ' row.

    HOW VALIDATED: measured against the live tree at authoring time — 7 phantoms found, all real,
    each confirmed absent from the log by direct grep of the row prefix. Scoped to source files
    only: reports and audits legitimately discuss ids that may pre-date the log.
    """
    log = REPO / "governance" / "root_cause_log.md"
    if not log.exists():
        return []
    have = set(re.findall(r"^\| (RC-\d+) ", log.read_text(encoding="utf-8", errors="ignore"), re.M))
    seen: dict[str, Path] = {}
    roots = [REPO / "tools", REPO / "static", REPO]
    for root in roots:
        globs = root.glob("*.py") if root is REPO else root.rglob("*")
        for p in globs:
            if not p.is_file() or p.suffix not in (".py", ".html"):
                continue
            sp = str(p)
            if any(x in sp for x in (".venv", "worktrees", "__pycache__", ".git")):
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for m in re.finditer(r"\bRC-(\d+)\b", text):
                rc = "RC-" + m.group(1)
                if rc not in have and rc not in seen:
                    seen[rc] = p
    return [
        Violation(path, 0,
                  f"{rc} is cited here but NO '| {rc} ' row exists in "
                  f"governance/root_cause_log.md. A pointer that resolves to nothing teaches the "
                  f"next reader to stop following pointers (RC-96 recurred as RC-98 within one "
                  f"turn; a sweep then found 7 live phantoms). Write the row, or drop the id.")
        for rc, path in sorted(seen.items(), key=lambda kv: int(kv[0][3:]))
    ]


def check_adversarial_audits_are_answered() -> list[Violation]:
    """The newest adversarial audit must be CITED in the ledger (RC-118).

    WHAT WAS OBSERVED (2026-07-28). Audit v14 landed between agent turns and was never
    processed — v15's lead finding was literally "zero commits since v14 REJECT". The audit
    loop's own output had no delivery guarantee: a report that arrives in a gap silently
    vanishes, which is the absence-of-signal class operating on the audit loop itself.

    Rule: the highest reports/claude_finish_adversarial_audit_vN.md must have its 'vN' name
    appear in governance/root_cause_log.md — processing an audit leaves ledger evidence, so
    an unanswered one fails the gate instead of aging quietly.

    HOW VALIDATED: negative control injects a v99 audit file into a fake repo and demands the
    check fire until the ledger cites v99.
    """
    rdir = REPO / "reports"
    log = REPO / "governance" / "root_cause_log.md"
    if not rdir.exists() or not log.exists():
        return []
    best = 0
    for p in rdir.glob("claude_finish_adversarial_audit_v*.md"):
        # v18 gun accepted: `_v(\d+)\.md$` made `_v17_deep.md` INVISIBLE — a suffixed audit
        # slipped past the inbox entirely. The version is the digits after _v wherever the
        # filename puts them; suffixes like _deep are part of the same audit.
        m = re.search(r"_v(\d+)", p.name)
        if m:
            best = max(best, int(m.group(1)))
    if best == 0:
        return []
    tag = f"v{best}"
    # v17 graded the bare-word match WEAK, correctly: an incidental 'v16' anywhere satisfied
    # it. A processing receipt is a LINE that names the audit as an audit — the word 'audit'
    # (or 'processed') must sit on the same ledger line as the version tag.
    for line in _read_or_empty(log).splitlines():
        if re.search(rf"\b{tag}\b", line) and re.search(r"\baudit\b|\bprocessed\b", line, re.I):
            return []
    return [Violation(
        log, 0,
        f"adversarial audit {tag} has NO ledger citation — it arrived and nothing processed "
        f"it (v14 vanished exactly this way). Cite {tag} in the row that answers it, or the "
        f"audit loop has no delivery guarantee.")]


#: The ONLY status tokens an RC row may carry. Measured from the live ledger on
#: 2026-08-06: OPEN 4, CLOSED 227, REMEDIATED 1. Adding a token here is a
#: deliberate act that must also decide whether it belongs in CLOSED_CLASS.
DECLARED_RC_STATUSES: frozenset[str] = frozenset({"OPEN", "CLOSED", "REMEDIATED"})

#: Statuses that assert the defect is dealt with, and therefore must satisfy
#: the full close contract. Six independent clauses key on this classification.
CLOSED_CLASS_RC_STATUSES: frozenset[str] = frozenset({"CLOSED"})


def check_rc_status_vocabulary() -> list[Violation]:
    """An unrecognised RC status must FAIL, never fall through (RC-257).

    WHAT WAS MEASURED (2026-08-05, reproduced and widened 2026-08-06). Six
    independent clauses -- the measured-evidence rule, the END-TO-END
    declaration, the named-victims rule, the defers-its-own-proof rule, the
    fix-crosswalk rule and the code-not-shipped rule -- each gate themselves on
    `status == "CLOSED"`. One deliberately deficient row, carrying no
    END-TO-END declaration and no observed evidence, run through
    `_five_why_lock_violations` and `_rc_row_violations`:

        CLOSED                -> 1 + 1 violations   BLOCKED
        CLOSED_WITH_EVIDENCE  -> 0 + 0 violations   passes freely
        DONE                  -> 0 + 0 violations   passes freely
        FINISHED              -> 0 + 0 violations   passes freely
        totally_closed        -> 0 + 0 violations   passes freely

    So inventing a status token was not merely easier than satisfying the close
    contract -- it was indistinguishable from having satisfied it, and the
    token that defeats every clause reads STRONGER to a human than the one that
    triggers them. A plain typo does the same thing silently.

    The root cause is that the vocabulary was emergent: each checker
    re-derived it by literal equality and no check asked whether an
    unrecognised status should fail. Constraining the vocabulary at the source
    makes the six downstream equality comparisons safe by construction rather
    than by coincidence.

    HOW VALIDATED: negative controls in tests/test_rc_status_vocabulary_v1.py
    assert that CLOSED_WITH_EVIDENCE is REFUSED here, that every emergent
    token in the live ledger is declared, and that the declared set and the
    closed-class set stay consistent.
    """
    out: list[Violation] = []
    log = REPO / "governance" / "root_cause_log.md"
    if not log.exists():
        return out
    for n, line in enumerate(log.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.startswith("| RC-"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 2:
            continue                  # 7-cell schema is check_rc_log_rows_keep_schema
        rc_id, status = cells[0], cells[1]
        if status in DECLARED_RC_STATUSES:
            continue
        out.append(Violation(
            log, n,
            f"{rc_id} carries status {status!r}, which is not in the declared "
            f"vocabulary {sorted(DECLARED_RC_STATUSES)}. An unrecognised status "
            "SKIPS every close-contract clause instead of failing them "
            "(RC-257: CLOSED_WITH_EVIDENCE took a deficient row from 2 "
            "violations to 0). Use a declared token, or add this one to "
            "DECLARED_RC_STATUSES and decide explicitly whether it belongs in "
            "CLOSED_CLASS_RC_STATUSES."))
    return out


def check_rc_log_rows_keep_schema() -> list[Violation]:
    """Every RC row in the governance log keeps the 7-cell schema (RC-105).

    WHAT WAS OBSERVED (2026-07-28). While re-closing RC-31 its row had drifted to ELEVEN cells:
    evidence text containing math absolute-value bars (abs(diff) written as pipe-diff-pipe) and
    code snippets with pipes was being rendered by markdown as extra COLUMNS — the row truncates
    at the stray pipe and everything after it is invisible in any rendered view. A sweep found 26
    more rows off schema (RC-43's pipe-moneyness-pipe, RC-86's pipe-net-GEX-pipe, draft 'IN
    PROGRESS' segments). A truncated row still LOOKS closed: absence of visible evidence reads as
    clean, which is the exact absence-of-signal failure this log exists to prevent.

    Rule: a line starting '| RC-' must contain exactly 7 cells (8 pipe separators with the
    outer pair). Write abs(x), never pipe-x-pipe, inside cells. Clause 2 (Cursor audit v2,
    2026-08-02, OBSERVED on RC-189): the STATUS cell and the fix-cell PROSE must agree — a row
    whose status reads OPEN/PARTIAL while its fix cell narrates "CLOSED same turn" let a
    CLOSED claim be made in chat against an OPEN ledger; the inverse (status CLOSED, prose
    "IN PROGRESS") is the same lie mirrored.

    HOW VALIDATED: negative control in tests/test_enforced_check_negative_controls_v1.py injects
    an 8-cell row and asserts this check returns >= 1; the 26-row repair landed the same turn, so
    the check binds from a clean baseline with NO grandfather list. Clause 2 prototyped on the
    live log (fires on the observed RC-189 state, quiet after the flip) and negative-controlled
    in tests/test_ui_mockup_lock_v1.py.
    """
    log = REPO / "governance" / "root_cause_log.md"
    if not log.exists():
        return []
    return rc_row_schema_violations(
        log.read_text(encoding="utf-8", errors="ignore"), log)


def rc_row_schema_violations(text: str, log: Path) -> list[Violation]:
    """Schema + status/prose-consistency scan, callable on arbitrary log text so the negative
    control can drive the REAL logic without touching the live ledger."""
    out: list[Violation] = []
    for n, line in enumerate(text.splitlines(), 1):
        if not line.startswith("| RC-"):
            continue
        cells = line.count("|") - 1
        if cells != 7:
            out.append(Violation(
                log, n,
                f"row has {cells} cells, schema is 7 — an interior pipe truncates the rendered "
                f"row and hides the evidence after it (RC-105: 27 rows had silently drifted). "
                f"Replace interior pipes: write abs(x), not pipe-x-pipe."))
            continue
        parts = [c.strip() for c in line.strip().strip("|").split("|")]
        status, fix_cell = parts[1].upper(), parts[6]
        # Clause 2 binds rows opened on/after its ship date (2026-08-02) — the same
        # new-rows-only design as the verdict and citation rules; RC-73's historic cell
        # predates the clause and is not retro-flagged.
        if parts[2] < "2026-08-02":
            continue
        if status in ("OPEN", "PARTIAL") and re.match(r"\s*CLOSED\b", fix_cell):
            out.append(Violation(
                log, n,
                f"{parts[0]}: status cell says {status} while the fix cell narrates CLOSED — "
                f"a CLOSED claim against an OPEN ledger is how RC-189 was misreported "
                f"(Cursor audit v2). Flip the status, or write the prose honestly."))
        elif status == "CLOSED" and re.match(r"\s*IN PROGRESS\b", fix_cell):
            out.append(Violation(
                log, n,
                f"{parts[0]}: status CLOSED with an IN PROGRESS fix cell — the mirrored "
                f"dishonesty of the RC-189 case."))
    return out


def check_scheduled_producers_are_not_inert() -> list[Violation]:
    """A scheduled PRODUCER that fails every run must not stay silent (RC-97).

    WHAT WAS OBSERVED (2026-07-27). The daily terrain scorecard was registered as a scheduled task
    and had been dying at Python PRE-INIT on every run: its task command used the inline form
    `set PYTHONUTF8=1 && python …`, and cmd.exe assigns everything between '=' and '&&' to the
    variable, so PYTHONUTF8 became '1 ' with a trailing space. reports/scorecard_run.log ended in
    `Fatal Python error: preconfig_init_utf8_mode`, the artifact was 119.4 HOURS old, and nothing
    in the repo objected. The consumer was correctly fail-closed (RC-78 withholds stale figures),
    and a silent producer plus a polite consumer reads exactly like a quiet system — fail-closed
    on the READ side hid the WRITE side.

    Rule: a runner log that ends in a fatal/traceback marker is a FINDING, whatever the artifact
    downstream does about it. Absence of output is not evidence the job had nothing to do.

    HOW VALIDATED: run against the live tree at authoring time, where it flagged
    reports/scorecard_run.log on the exact fatal line above; it returns [] when the log is absent
    (a job that has never run is RC-70's cadence problem, tracked separately) so it cannot cry
    wolf on a clean checkout.
    """
    fatal = re.compile(r"Fatal Python error|Traceback \(most recent call last\)|"
                       r"ModuleNotFoundError|SyntaxError:", re.I)
    out: list[Violation] = []
    reports = REPO / "reports"
    if not reports.exists():
        return out
    for log in sorted(reports.glob("*_run.log")):
        try:
            text = log.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if not text.strip():
            continue
        m = fatal.search(text)
        if not m:
            continue
        out.append(Violation(
            log, 0,
            f"scheduled producer log ends in a fatal error ({m.group(0)!r}) — the job is "
            f"SCHEDULED BUT INERT and has been failing silently. A fail-closed consumer hides "
            f"this: it withholds the stale artifact and the system merely looks quiet (RC-97). "
            f"Fix the runner, prove the artifact mtime advances, then clear the log."))
    return out


def check_agents_laws_name_their_enforcer() -> list[Violation]:
    """A law written into AGENTS.md must name the check that enforces it, or say JUDGMENT-ONLY (RC-96).

    WHAT WAS OBSERVED. The operator's own lock audit ranked this fifth of five tightenings, and
    the repo's history is the evidence: RC-41 (recursive-5-why enforced on existing rows but not
    on the ACT of opening), RC-49 (adversarial-audit loop mandated as a mechanical lock, never
    mechanized), RC-56 (the RC-53 remedy shipped as AGENTS.md prose with no mechanical component).
    Thirteen of thirty-five catalogued lock failures are class
    `goodwill_instead_of_mechanical_lock` — a law in prose reads exactly like a law with a hook,
    and only the machine can tell them apart.

    Rule: each bold law/rule/clause heading in AGENTS.md must, within its own paragraph, either
    name an enforcing artifact (`check_*`, `*_guard.py`) or contain JUDGMENT-ONLY (excluded from
    lock-surface scorecard). Labelling a law JUDGMENT-ONLY is NOT a defeat — it is an honest
    declaration that the operator is the detector, which is the thing the mandate-to-mechanism law
    exists to make visible.

    HOW VALIDATED: run against AGENTS.md at authoring time — 4 of 8 headings named an enforcer,
    4 did not; those 4 are grandfathered above and must carry JUDGMENT-ONLY. The rule binds new
    laws only, the same design as the citation and recurrence rules.
    """
    p = REPO / "AGENTS.md"
    if not p.exists():
        return []
    text = p.read_text(encoding="utf-8", errors="ignore")
    out: list[Violation] = []
    pat = re.compile(r"\*\*([^*]{6,90}?(?:law|LAW|lock|rule|directive|clause)[^*]{0,40}?)\*\*")
    for m in pat.finditer(text):
        heading = m.group(1).strip()
        key = heading.lower().rstrip(":").rstrip(".")[:28]
        grandfathered = any(key.startswith(g[:28]) for g in _AGENTS_LAW_GRANDFATHERED)
        para = text[m.start():m.start() + 900]
        if grandfathered:
            # RC-96 LOOPHOLE, found by the operator's adversarial audit: grandfathered
            # entries used to `continue` unconditionally, so the docstring's requirement
            # that they carry SOFT was never checked and all four sat green with soft=False.
            # A grandfather clause that verifies nothing is an exemption, not a burn-down.
            if re.search(r"\b(SOFT|JUDGMENT-ONLY)\b", para):
                continue
            out.append(Violation(
                p, text[:m.start()].count("\n") + 1,
                f"grandfathered AGENTS.md law {heading[:60]!r} does not declare JUDGMENT-ONLY. "
                f"Grandfathering permits 'no machine enforces this YET'; it never permits "
                f"silence about it. Add JUDGMENT-ONLY, or name the check that enforces it."))
            continue
        if re.search(r"\b(check_[a-z_]+|[a-z_]+_guard\.py|SOFT|JUDGMENT-ONLY)\b", para):
            continue
        out.append(Violation(
            p, text[:m.start()].count("\n") + 1,
            f"AGENTS.md law {heading[:60]!r} names no enforcer. State the check id "
            f"(check_*/…_guard.py) that detects a breach, or write SOFT to declare openly that "
            f"the operator is the detector. A law in prose reads exactly like a law with a hook "
            f"— 13 of 35 catalogued lock failures are 'goodwill instead of a mechanical lock' "
            f"(RC-41/49/56)."))
    return out


def check_fix_crosswalks_to_violated_lock() -> list[Violation]:
    """A CLOSED root cause must name the LOCK that failed to prevent it, and the tightening.

    OPERATOR DIRECTIVE (2026-07-27): "i just don't want the fix. you then have to cross walk the
    fix to the 5 why's of why you still had to fix the issue. this will then tell us the
    violation. you can then tighten up the locks to prevent another similar violation."

    WHAT WAS OBSERVED. Every defect fixed on 2026-07-27 occurred INSIDE a repo carrying 32
    enforced checks, 7 pre-commit stages and 3 agent hooks — so each one is, by construction,
    evidence that some lock was missing, inert, or measuring the wrong property. RC-91 is the
    canonical case: single_faucet_provenance was green the entire time the panel served
    90-minute-old data, because provenance is static and freshness was nobody's property. A fix
    that closes without naming that gap fixes the instance and re-arms the class.

    Rule: a NEWLY closed '| RC-' row must carry `VIOLATION: <lock or law that should have caught
    this, or NO-LOCK-EXISTED>` and `TIGHTENED: <what now catches it>`. RECURRENCE: names the
    failure class; VIOLATION names the CONTROL that let it through — different questions.

    HOW VALIDATED: scoped to newly-CLOSED rows in the staged diff (same plumbing as
    check_root_cause_recurrence_declared, validated there); returns [] outside a commit context;
    existing history is never retro-flagged.
    """
    log_rel = "governance/root_cause_log.md"
    staged = _git_output_lines(["diff", "--cached", "--name-only"])
    if staged is None:
        return []
    if log_rel not in {s.strip().replace("\\", "/") for s in staged if s.strip()}:
        return []
    head = _git_output_lines(["show", f"HEAD:{log_rel}"]) or []
    closed_at_head = {
        ln.strip().strip("|").split("|")[0].strip()
        for ln in head
        if ln.startswith("| RC-") and len(ln.split("|")) > 2
        and ln.strip().strip("|").split("|")[1].strip() == "CLOSED"
    }
    diff = _git_output_lines(["diff", "--cached", "-U0", "--", log_rel]) or []
    out: list[Violation] = []
    for ln in diff:
        if not ln.startswith("+| RC-"):
            continue
        row = ln[1:]
        cells = [c.strip() for c in row.strip().strip("|").split("|")]
        if len(cells) < 7 or cells[1] != "CLOSED":
            continue
        rc_id = cells[0]
        if rc_id in closed_at_head:
            continue                    # already closed before this commit — not a new closure
        up = row.upper()
        if "VIOLATION:" in up and "TIGHTENED:" in up:
            continue
        out.append(Violation(
            REPO / log_rel, 0,
            f"{rc_id} closes a fix without the crosswalk. This repo carries dozens of locks, so "
            f"every defect that needed fixing is proof a control was missing, inert, or measuring "
            f"the wrong property. Add 'VIOLATION: <the lock/law that should have caught this, or "
            f"NO-LOCK-EXISTED>' and 'TIGHTENED: <what now catches this class>' — the fix without "
            f"the crosswalk re-arms the class (operator directive 2026-07-27)."))
    return out


#: RC-62 — domain constants that decide money-path behaviour must carry their derivation.
#: Names that set a THRESHOLD/BOUND on market logic (not plumbing sizes like timeouts or buffers).
_DOMAIN_CONST_RE = re.compile(
    r"^[A-Z][A-Z0-9_]*(_MIN_[A-Z0-9_]*PCT|_MAX_[A-Z0-9_]*PCT|_PCT|_THRESHOLD|_SPAN|_MARGIN|"
    r"_MIN_SPAN|_CUTOFF|_FLOOR|_CEILING)$")
#: A derivation is: a measurement, a citation, a named source, or an explicit operator decision.
_DERIVATION_RE = re.compile(
    r"MEASURED|OBSERVED|PROVEN|VERIFIED|DERIVED|per [A-Z]|operator|vendor|"
    r"industry standard|https?://|RC-\d+|\bsee \w+\.py|convergence", re.I)
_DOMAIN_CONST_FILES = ("math_levels.py", "math_exposure_core.py", "math_probabilities.py")
#: FROZEN grandfather set (prototyped 2026-07-26: exactly these). These are TRADING-POLICY numbers
#: — stop-loss bands, a direction threshold, a greek-bias cut — whose correct values are an
#: operator decision, not something an agent may invent a derivation for. They are visible debt to
#: be justified or re-set deliberately; the rule binds every NEW market threshold immediately.
_DOMAIN_CONST_GRANDFATHERED = frozenset({
    ("math_exposure_core.py", "GREEK_BIAS_THRESHOLD"),
    ("math_probabilities.py", "DIRECTION_THRESHOLD_PCT"),
    ("math_probabilities.py", "STOP_BASE_PCT"),
    ("math_probabilities.py", "STOP_TIME_DECAY_PCT"),
    ("math_probabilities.py", "STOP_VIX_MED_PCT"),
    ("math_probabilities.py", "STOP_VIX_HIGH_PCT"),
    ("math_probabilities.py", "STOP_FLOOR_PCT"),
    ("math_probabilities.py", "STOP_CEILING_PCT"),
})


def check_domain_constants_are_derived() -> list[Violation]:
    """A market-logic threshold must state where its VALUE came from, not just what it does.

    WHAT WAS OBSERVED (2026-07-26, RC-62): the operator asked who set GAMMA_FLIP_MIN_SPAN_PCT =
    0.05 and what is scientific about it. Nothing was: its entire justification was a comment
    restating the value ("chain must reach +/-5% around spot before the flip is trusted"). That
    one number decides how many strikes EVERY live chain fetch requests and whether the operator
    is told a flip is TRUSTED or LOW_CONFIDENCE — including declaring $SPX untrustworthy. The
    repo already forces new GATE CHECKS to justify themselves (checks_are_justified) but nothing
    forced the same of DOMAIN CONSTANTS, which carry more decision weight.

    Rule: in the math modules, a constant whose name marks it as a market threshold (…_PCT,
    …_THRESHOLD, …_SPAN, …_MARGIN, …_FLOOR, …_CEILING) must have a nearby comment or docstring
    containing a derivation marker — MEASURED/OBSERVED/PROVEN/DERIVED, a named source, a vendor
    or operator decision, an RC id, or a convergence study. Restating the value is not a
    derivation.

    HOW THE RULE WAS VALIDATED: prototyped against the math modules before enforcing; scoped to
    the three math files (where market thresholds live) rather than repo-wide, so plumbing
    constants — timeouts, buffer sizes, retry counts — are never flagged. Constants that ARE
    already derived (e.g. STRIKE_COUNT_MARGIN, which explains Schwab's off-centre strike
    placement) pass unchanged.
    """
    out: list[Violation] = []
    for fname in _DOMAIN_CONST_FILES:
        path = REPO / fname
        if not path.exists():
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        for n, line in enumerate(lines, start=1):
            if "=" not in line or line.startswith((" ", "\t")):
                continue
            name = line.split("=", 1)[0].strip()
            if not _DOMAIN_CONST_RE.match(name):
                continue
            if (fname, name) in _DOMAIN_CONST_GRANDFATHERED:
                continue
            # The derivation must belong to THIS constant: its own line plus the CONTIGUOUS
            # comment block directly above it. A wider window let a neighbour's comment vouch
            # for it — the first draft of this check passed GAMMA_FLIP_MIN_SPAN_PCT itself
            # because the following constant's comment used the word "derived".
            block = [line]
            k = n - 2                       # 0-based index of the line above
            while k >= 0 and lines[k].lstrip().startswith("#"):
                block.append(lines[k])
                k -= 1
            if _DERIVATION_RE.search("\n".join(block)):
                continue
            out.append(Violation(
                path, n,
                f"{name} is a market-logic threshold with no stated derivation. This value "
                f"decides product behaviour, so a comment restating it is not justification "
                f"(RC-62: GAMMA_FLIP_MIN_SPAN_PCT=0.05 governed every chain fetch width and every "
                f"TRUSTED verdict on nothing but assertion). State the measurement, the source, "
                f"or the operator decision that produced this number."))
    return out


def check_single_faucet_provenance() -> list[Violation]:
    """Every rendered field is fed by DECLARED sources only — measured, never assumed (RC-73).

    WHAT WAS OBSERVED (2026-07-27): single-source-of-truth was a governing law enforced per
    PRODUCER (single_spot_authority, chain_width_single_faucet) while nothing could answer the
    operator's real question — is this field on my screen live, and how many faucets feed it?
    Every answer was agent prose. That is how a 2.1-hour-frozen volume panel (session volume
    understated 281 percent), a three-faucet spot bind, a 110-hour-old scorecard file and a
    19.1-minute bar lag all survived. Worse, a "fix" that ADDED a live source while keeping the
    old one as a FALLBACK made it strictly worse (per_strike 2 -> 3 faucets) — a fallback IS a
    second faucet, and only the instrument caught it.

    Rule: `tools/data_faucet_audit.py` statically traces every UI endpoint to the sources it
    reads and fails when a concept is fed by a source outside its DECLARED_FAUCETS contract. A
    deliberate second field (e.g. the prior-day ghost served from the morning archive) is declared
    there and reviewed; anything undeclared appearing later is a violation, not a judgement call.

    HOW THE RULE WAS VALIDATED: prototyped before enforcing — it MEASURED violations 3 -> 0 across
    the RC-68/RC-69 fixes, and immediately caught the fallback regression above. It also corrected
    itself: counting resolve_spot as a per-concept data faucet scored the single-spot-authority
    LAW as a violation, so universal authorities are excluded. Import failure is reported, never
    silently passed (RC-57: a metric that cannot be measured is not a pass).
    """
    try:
        from tools.data_faucet_audit import run as _faucet_run
    except Exception as e:                                   # unmeasurable is NOT a pass
        return [Violation(REPO / "tools" / "data_faucet_audit.py", 0,
                          f"faucet provenance is unmeasurable ({type(e).__name__}: {e}); a metric "
                          f"that cannot be measured must never report as compliant")]
    try:
        rep = _faucet_run(str(REPO / "data" / "ed_console.db"))
    except Exception as e:
        return [Violation(REPO / "tools" / "data_faucet_audit.py", 0,
                          f"faucet audit failed to run: {type(e).__name__}: {e}")]
    out: list[Violation] = []
    for v in rep.get("faucet_violations", []):
        out.append(Violation(
            REPO / "server.py", 0,
            f"concept {v['concept']!r} is fed by UNDECLARED source(s) {v['undeclared']} "
            f"(declared: {v['declared']}). One rendered field, one faucet — a fallback is a "
            f"second faucet. Either remove the extra source or declare it in "
            f"tools/data_faucet_audit.py::DECLARED_FAUCETS with the field it legitimately serves."))
    return out


def check_chain_width_single_faucet() -> list[Violation]:
    """Every level-computing chain fetch must size itself from ONE authority.

    WHAT WAS OBSERVED (2026-07-26, RC-59): the console/analytics path fetched option chains at a
    hardcoded CHAIN_STRIKE_COUNT=20 ("keep fast") while the terrain path sized from measured
    geometry, so the SAME ticker was analysed at two different widths and the levels persisted to
    `snapshots` were narrower than the ones shown on screen. Two widths is two answers. The width
    is a function of the +/-5% span bar and the instrument's own strike spacing, and MEASURED
    across 52 chains the fixed count was wrong in BOTH directions (~48 equities need under 20 and
    got 40; $SPX needs ~150 and got 40) — so a hardcoded literal cannot be right for any universe.

    Rule: in server.py, a `strike_count=` argument on a chain fetch must be
    `resolve_chain_strike_count(...)` (or a variable derived from it), never a bare constant —
    unless the line declares `chain-width-faucet-ok: <reason>` for a fetch that provably computes
    no levels (e.g. the expiry-list dropdown).

    HOW THE RULE WAS VALIDATED: prototyped against server.py before enforcing — it flags exactly
    the bare-constant fetches and passes the faucet-routed ones and the single declared exemption;
    scoped to server.py because that is where the live fetches live, so it cannot cry wolf across
    offline tools that legitimately choose their own width.
    """
    out: list[Violation] = []
    path = REPO / "server.py"
    try:
        src = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return out
    for n, line in enumerate(src.splitlines(), start=1):
        if "strike_count=" not in line or "def " in line:
            continue
        if "chain-width-faucet-ok" in line:
            continue
        arg = line.split("strike_count=", 1)[1].strip().rstrip(",)").strip()
        if not arg or arg.startswith(("resolve_chain_strike_count", "_width", "_terrain_strike_count")):
            continue
        if arg.isidentifier() and arg.isupper():          # a bare CONSTANT is the defect
            out.append(Violation(
                path, n,
                f"chain fetch sizes itself from the bare constant {arg!r} instead of the ONE "
                f"width authority resolve_chain_strike_count(ticker) (RC-59). A fixed count is "
                f"wrong in both directions across a real universe. Use the faucet, or declare "
                f"'chain-width-faucet-ok: <reason>' if this fetch computes no levels."))
    return out


#: RC-56 — a measured claim committed to the governance record must carry its evidence.
#: Claim vocabulary: words that assert a FINDING (not mere description).
_CLAIM_WORDS = re.compile(
    r"\b(MEASURED|PROVEN|VERIFIED|OBSERVED|CONFIRMED|median|mean|percentile|"
    r"correlation|accuracy|hit rate|p-value|significan)", re.I)
#: An explicit hypothesis tag exempts a line — an untested claim may be RECORDED, never asserted.
_UNVERIFIED_TAG = re.compile(r"\[UNVERIFIED\]|\[HYPOTHESIS\]|UNPROVEN", re.I)


def check_measured_claims_cite_evidence() -> list[Violation]:
    """A quantitative FINDING added to the governance record must cite how to reproduce it.

    WHAT WAS OBSERVED (2026-07-26, RC-53/RC-56): I asserted "far-OTM strikes carry large open
    interest" as a load-bearing premise with no measurement, then "confirmed" it with unequal
    comparison buckets that manufactured the result; per-strike OI is in fact HIGHEST near ATM
    (1,452) and DECLINES to the wings (765). Separately RC-43 was CLOSED on figures (0.068 percent)
    from an uncommitted one-off that could not be re-run and proved wrong by 5-9x when finally
    reproduced. The operator's ruling was explicit: every claim must be fact-based and proven, and
    a written law is NOT a lock — "there are times you say you will mechanically lock something and
    then i find out that you didn't and you call it goodwill". This check is the mechanical half of
    the AGENTS.md evidence-before-assertion law: chat prose cannot be hook-gated, but anything
    COMMITTED to the record can be, and is.

    Rule: when a commit stages a .md under governance/ or reports/, every ADDED line that states a
    quantitative finding (a claim word plus >=2 numbers) must either appear in a file that carries a
    backticked reproducible command (`SELECT ...`, `python ...`, `pytest ...`, a tools/ path), or be
    tagged [UNVERIFIED]/[HYPOTHESIS]/UNPROVEN. Dates and RC/issue ids are stripped before counting so
    "2026-07-26" and "RC-43" never read as claims.

    HOW THE RULE WAS VALIDATED: prototyped against this repo's staged governance edits before
    enforcing, and deliberately scoped to STAGED-DIFF ADDED LINES rather than whole files — a
    whole-file scan would flag years of historical prose and cry wolf, while the diff scope binds
    exactly the new claims a commit introduces. Returns [] outside a git commit context so unit-test
    imports never false-block.
    """
    staged = _git_output_lines(["diff", "--cached", "--name-only"])
    if staged is None:
        return []
    targets = [
        s.strip().replace("\\", "/") for s in staged
        if s.strip().endswith(".md")
        and (s.strip().replace("\\", "/").startswith(("governance/", "reports/")))
    ]
    out: list[Violation] = []
    for rel in targets:
        path = REPO / rel
        try:
            whole = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        diff = _git_output_lines(["diff", "--cached", "-U0", "--", rel]) or []
        for ln in diff:
            if not ln.startswith("+") or ln.startswith("+++"):
                continue
            body = ln[1:]
            if _UNVERIFIED_TAG.search(body) or not _CLAIM_WORDS.search(body):
                continue
            stripped = re.sub(r"\d{4}-\d{2}-\d{2}|RC-\d+|#\d+", "", body)
            if len(_RC_NUMBER_RE.findall(stripped)) < 2:
                continue
            if _RC_CITATION_RE.search(body) or _RC_CITATION_RE.search(whole):
                continue
            out.append(Violation(
                path, 0,
                "adds a MEASURED claim with numbers but the file cites no reproducible command. "
                "A number that cannot be re-run is not evidence (RC-43 closed on an uncommitted "
                "one-off that was wrong by 5-9x). Add a backticked command that reproduces it, or "
                "tag the line [UNVERIFIED]."))
            break   # one violation per file is enough to block; do not spam
    return out


#: RC-54 — market-data measurement must be scoped to trading sessions.
_RTH_MARKET_READ = re.compile(
    r"FROM\s+(snapshots|snapshots_1m_normalized|option_chain_morning_full|price_bars_1m)\b"
    r"|flip_drift_log\.jsonl",
    re.I)  # price_bars_1m added on the v7 reopen of RC-103: the RTH lock covered every market
           # table EXCEPT the one the session-blindness class recurred through five times.
_RTH_STATS = re.compile(r"\b(statistics\.|np\.(mean|median|percentile|std)|\.mean\(|\.median\()")
#: Data MAINTENANCE (backfill/normalize/migrate) legitimately processes every row — a backfill that
#: skipped weekends would corrupt the store. Only MEASUREMENT is scoped.
_RTH_WRITES = re.compile(
    r"\b(UPDATE\s+snapshots|INSERT\s+INTO\s+snapshots|ALTER\s+TABLE|executemany|CREATE\s+TABLE)", re.I)
#: CALENDAR-AWARE authorities only. `is_rth_ts_utc` is deliberately NOT here: it is clock-only and
#: returns True for Saturday 10:00 and Memorial Day 10:00 (measured), so accepting it would let a
#: holiday-blind file satisfy a calendar check — the first version of this lock did exactly that
#: (RC-57). `filter_df_to_rth_ts_utc` / `filter_ts_utc_list_to_rth` ARE accepted because RC-57
#: rebuilt them on is_tradable_session_ts_utc; they are calendar-aware as of that fix.
_RTH_AUTHORITIES = re.compile(
    r"is_trading_day_et|is_tradable_session_ts_utc|filter_df_to_rth_ts_utc|"
    r"filter_ts_utc_list_to_rth|rth-scope-ok")
#: FROZEN grandfather set — measurement files that predate the lock (prototyped 2026-07-26: exactly
#: these 17). Visible debt, not hidden: several (study_pin_*) back conclusions in
#: governance/unproven_register.md that must be re-run under RTH scoping before they are re-cited.
_RTH_GRANDFATHERED = frozenset({
    "calibration/analyze_phase3.py",
    "research/cost_aware_eval_v1/faint_lead_kill_v1.py",
    "tools/_multi_timeframe_audit_v1.py",
    "tools/_phase8_remediate_tmp.py",
    "tools/feature_curation_gate.py",
    "tools/legacy/horizon_7/_phase5_discrimination_audit_v1.py",
    "tools/legacy/horizon_7/run_phase11_monitoring_drift_live_readiness_v1.py",
    "tools/legacy/horizon_7/run_phase9_decision_policy_v1.py",
    "tools/legacy/horizon_7/run_phase9_policy_remediation_v1.py",
    "tools/legacy/horizon_7/validate_movement_prediction_coverage_v1.py",
    "tools/run_final_fused_vs_xgb_comparison_v1.py",
    "tools/run_phase8_calibration_global_v1.py",
    "tools/study_pin_charm_v1.py",
    "tools/study_pin_direction_v1.py",
    "tools/study_pin_regime_cut_v1.py",
    "tools/study_pin_residence_v1.py",
    "tools/study_terrain_readiness_v1.py",
    "scratchpad/_spy_hourly_gamma_vol_storm.py",
    "tools/liquidity_synthesis_experiments_v1.py",
    "tools/lp01_touch_study_v1.py",
})


def check_rth_only_market_measurement() -> list[Violation]:
    """Any measurement over market data must be scoped to TRADING sessions (operator mandate).

    WHAT WAS OBSERVED (2026-07-26, RC-54): the same defect three times in one session. (a) An
    intraday gamma-flip-drift reading was taken from `reports/flip_drift_log.jsonl` whose only
    records were a SUNDAY 11:20-12:54 ET window — market shut, spot frozen — which reported a
    median flip movement of 0.023 percent and would have been published as "the flip is stable
    intraday". (b) `tools/flip_iv_sensitivity_v1.py` loaded `option_chain_morning_full` with NO
    session filter, so 72 of 215 source rows (33.5 percent: 35 Sat + 35 Sun + 2 Sun) were
    market-closed captures polluting the RC-43 numbers. (c) gamma/charm fixture tests needed
    clock-pinning for the same reason. A market-closed row has frozen spot and stale IV, so it
    drags every statistic toward "nothing moved" — it does not merely add noise, it BIASES toward
    the null. Operator ruling: RTH-only is non-negotiable and must be mechanical.

    Rule: a file that READS market data (snapshots / snapshots_1m_normalized /
    option_chain_morning_full / flip_drift_log.jsonl) AND aggregates it (statistics/mean/median)
    must reference a calendar-aware session authority (`is_trading_day_et`,
    `is_tradable_session_ts_utc`, `filter_df_to_rth_ts_utc`, `filter_ts_utc_list_to_rth`) or carry
    `# rth-scope-ok: <reason>`. Data MAINTENANCE (backfill/normalize/migrate — detected by row
    writes) is exempt by design: it must process every row.

    HOW THE RULE WAS VALIDATED: prototyped against the repo BEFORE enforcing. 105 files read the
    market tables; the naive form flagged 34, of which the write-exemption correctly removed the
    backfills/normalizer, leaving exactly 17 genuine unscoped MEASUREMENT files — frozen into
    _RTH_GRANDFATHERED so the rule binds new and changed code without a 17-file emergency. The
    grandfathered set is visible debt to drive down, and notably includes the study_pin_* tools
    whose results are cited as PROVEN in governance/unproven_register.md and therefore need
    re-running under RTH scoping before they may be re-cited.
    """
    out: list[Violation] = []
    for path in _production_py_files():
        rel = path.relative_to(REPO).as_posix()
        if rel in _RTH_GRANDFATHERED:
            continue
        try:
            src = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if not (_RTH_MARKET_READ.search(src) and _RTH_STATS.search(src)):
            continue
        if _RTH_WRITES.search(src) or _RTH_AUTHORITIES.search(src):
            continue
        out.append(Violation(
            path, 1,
            "measures market data with NO trading-session scoping. A market-closed row has frozen "
            "spot and stale IV, so it biases every statistic toward 'nothing moved' (RC-54: a "
            "Sunday-only sample nearly shipped as 'the flip is stable intraday'). Filter with "
            "time_et.is_trading_day_et / is_tradable_session_ts_utc (or ml_data_common's df/list "
            "filters), or declare '# rth-scope-ok: <reason>'."))
    return out


def check_universal_ticker_scope() -> list[Violation]:
    """SPY-only / sentinel-complete work without OUT-OF-SCOPE is a breach (RC-160).

    WHAT WAS OBSERVED (operator 2026-07-30): prompts, experiments, Chart features, Collect
    paths, and reports were repeatedly framed as complete while scoped to SPY (or sentinels)
    alone — the same class as operable-surface SENTINEL_vs_OPERABLE (rule 02) and RC-1's
    non-SPY starvation, but at the WORK-DEFINITION layer. Without a lock, "at least SPY" and
    `default="SPY"` experiment tools launder a partial universe into a system answer. The
    operator mandate: UNIVERSAL for everything we do, enforced with Cursor and Claude.

    Rule (practical — does NOT retro-flag historical report prose):
      1. tools/liquidity_*.py, *_experiment*.py, lp01_*.py must not default --tickers / TICKERS
         to SPY alone (AST). Escape: `# universal-scope-ok:` / OUT-OF-SCOPE / operator waiver.
      2. static/chart.html must keep parameterized ticker fetches and must not gate
         storm/highlight/combo/accrual on `=== 'SPY'` (or hardcode `ticker=SPY` APIs).
      3. STAGED prompt / agent-instruction .md files (reports/*prompt*, .cursor/rules/,
         .claude/*.md, AGENTS.md, …) must not add SPY-only / sentinel-complete framing without
         UNIVERSAL / enrolled-universe / OUT-OF-SCOPE language.

    HOW THE RULE WAS VALIDATED: prototyped against the live tree before enforcing — existing
    liquidity_* tools default to SPY,QQQ,IWM (pass); chart.html already uses ticker=${tk}
    (pass); historical reports/ are out of whole-file scope so they do not false-block. Negative
    controls in tests/test_universal_ticker_scope_v1.py inject SPY-only defaults, Chart gates,
    and prompt prose and demand a scream; universal wording stays quiet.
    """
    from tools.universal_scope_lock import (
        chart_spy_only_feature_violations,
        chart_ticker_path_violations,
        experiment_tool_paths,
        is_prompt_or_agent_instruction_path,
        spy_only_content_violation,
        spy_only_ticker_default_violations,
        ticker_specific_implementation_scope_violation,
    )

    out: list[Violation] = []

    for path in experiment_tool_paths(REPO):
        src = _read_or_empty(path)
        if not src:
            continue
        for lineno, msg in spy_only_ticker_default_violations(path, src):
            out.append(Violation(path, lineno, msg))

    chart = REPO / "static" / "chart.html"
    if chart.exists():
        csrc = _read_or_empty(chart)
        for lineno, msg in chart_ticker_path_violations(csrc):
            out.append(Violation(chart, lineno, msg))
        for lineno, msg in chart_spy_only_feature_violations(csrc):
            out.append(Violation(chart, lineno, msg))

    staged = _git_output_lines(["diff", "--cached", "--name-only"])
    if staged is not None:
        for raw in staged:
            rel = raw.strip().replace("\\", "/")
            if not rel or not is_prompt_or_agent_instruction_path(rel):
                continue
            path = REPO / rel
            whole = _read_or_empty(path)
            diff = _git_output_lines(["diff", "--cached", "-U0", "--", rel]) or []
            added = "\n".join(
                ln[1:] for ln in diff
                if ln.startswith("+") and not ln.startswith("+++")
            )
            # Prefer ADDED text (binds new prompt framing); fall back to whole file for new files.
            text = added if added.strip() else whole
            reason = spy_only_content_violation(text)
            if reason is not None:
                out.append(Violation(path, 0, reason))
            fix_scope = ticker_specific_implementation_scope_violation(text, rel=rel)
            if fix_scope is not None:
                out.append(Violation(path, 0, fix_scope))

    return out




def check_chart_intent_and_next_rth() -> list[Violation]:
    """Chart-intent soft-out + next-RTH weekday lies in residual prose (RC-163).

    WHAT WAS OBSERVED (operator 2026-07-30): Cursor repeatedly closed Collect /
    accrual slices as ACCEPT/Done while Chart render (yellow OV / GEX bars) stayed
    OUT-OF-SCOPE or soft OBSERVED with no open P0/CHART_CONSUMER residual — banking
    was treated as product delivery. Separately, forward residuals used a hardcoded
    weekday-named live-proof label when the next RTH (America/New_York +
    is_trading_day_et) was Friday 2026-07-31. Both are the goodwill-instead-of-lock
    class RC-66/RC-160 already named; Chart intent and residual calendars had no
    detector.

    Rule (practical — binds STAGED ADDED text on residual/handoff/RC/prompt paths,
    not historical whole-file prose):
      1. Collect/accrual/bank finish language + Chart OUT-OF-SCOPE / soft OBSERVED
         without proven consumer / STATUS PARTIAL + Chart residual /
         `# chart-intent-ok:` → BLOCK.
      2. Chart mandate framed Done via bank/accrual alone without proven consumer
         → BLOCK (same escape set).
      3. Weekday-named live-proof phrases (Monday proof / Monday live proof /
         MONDAY_PROOF / next Monday) when next RTH weekday ≠ Monday → BLOCK unless
         `# next-rth-ok:` + computed date.

    HOW THE RULE WAS VALIDATED: negative controls in
    tests/test_chart_intent_lock_v1.py inject Done+Chart-OOS and Monday-proof-on-
    Friday blobs and demand a scream; PARTIAL+CHART_CONSUMER, chart-intent-ok,
    next-rth-ok, and NEXT_RTH_PROOF+Friday stay quiet. Live tree staged scan is
    empty outside a commit context (no false block).
    """
    from tools.chart_intent_lock import (
        is_residual_language_path,
        residual_language_violations,
    )

    out: list[Violation] = []
    staged = _git_output_lines(["diff", "--cached", "--name-only"])
    if staged is None:
        return out
    for raw in staged:
        rel = raw.strip().replace("\\", "/")
        if not rel or not is_residual_language_path(rel):
            continue
        path = REPO / rel
        whole = _read_or_empty(path)
        diff = _git_output_lines(["diff", "--cached", "-U0", "--", rel]) or []
        added = "\n".join(
            ln[1:] for ln in diff
            if ln.startswith("+") and not ln.startswith("+++")
        )
        text = added if added.strip() else whole
        for reason in residual_language_violations(text):
            out.append(Violation(path, 0, reason))
    return out


# (name, check, enforced). ENFORCED checks must be zero — they block pre-commit.
# ADVISORY checks are visible debt being driven to zero, then flipped to enforced
# (the ratchet: new code is held to them; existing debt is shown, never hidden).
def check_collect_window_single_law() -> list[Violation]:
    """Operator Collect-window law (RC-183, non-negotiable 2026-08-01): `price_bars_1m`
    persistence is 08:15–15:15 CT — ET bar-end minutes (555, min(975, close+15)] on trading
    days — enforced at the ONE write seam, `EdDB.upsert_1m_bars`.

    WHAT WAS OBSERVED (2026-08-01). Three windows governed one table: the Schwab backfill
    fetched full extended hours and upserted ungated (MEASURED: 820,531 of its rows sit outside
    the law), the live accumulator buffered a wider 540–990 window (315,660 outside rows), and
    the completeness checker measured a THIRD grid (classic cash RTH 570–960). Total measured
    outside-law rows: 1,224,370 of 2,537,437 (48.25%). Nobody disagreed about the law; nothing
    encoded it.

    Rule (static, three clauses):
    1. `time_et.py` defines the authority (`COLLECT_WINDOW_START_MINS`, `COLLECT_WINDOW_END_MINS`,
       `is_collect_window_bar_end_ts_utc`).
    2. `db.py`'s `upsert_1m_bars` calls the authority before appending rows.
    3. No tracked .py outside `db.py` INSERTs into `price_bars_1m` directly — every writer goes
       through the seam, or declares `# collect-window-ok: <reason>` on the INSERT line.

    HOW VALIDATED: prototyped before registering — clause 3 walked the tree and found the only
    direct INSERT sites are `db.py` itself and test fixtures under `tests/` (fixtures build
    read-side scenarios and are exempt by path); clauses 1–2 fail when either symbol is renamed
    or the call removed (checked by string mutation during development). Negative control:
    `tests/test_collect_window_law_v1.py` names this check and injects a violating write.
    Escapes: `# collect-window-ok: <reason>`.
    """
    out: list[Violation] = []
    te = REPO / "time_et.py"
    dbp = REPO / "db.py"
    te_src = te.read_text(encoding="utf-8", errors="replace") if te.exists() else ""
    db_src = dbp.read_text(encoding="utf-8", errors="replace") if dbp.exists() else ""
    for sym in ("COLLECT_WINDOW_START_MINS", "COLLECT_WINDOW_END_MINS",
                "def is_collect_window_bar_end_ts_utc"):
        if sym not in te_src:
            out.append(Violation(te, 0, f"collect-window authority missing: {sym} not in time_et.py"))
    if "is_collect_window_bar_end_ts_utc" not in db_src:
        out.append(Violation(dbp, 0,
                             "upsert_1m_bars no longer gates on the collect-window authority — "
                             "the ONE write seam for price_bars_1m has lost the operator law"))
    for rel in sorted(_tracked_py_files() or []):
        rel = rel.replace("\\", "/")
        if rel in ("db.py", "tools/check_institutional_correctness.py") \
                or rel.startswith("tests/") or rel.startswith("governance/"):
            continue
        py = REPO / rel
        try:
            src = py.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for n, line in enumerate(src.splitlines(), start=1):
            # \b excludes price_bars_1m_staging (underscore continues the word); requiring
            # INTO excludes prose like "Insert missing ... price_bars_1m rows" in docstrings.
            if re.search(r"INSERT\s+(?:OR\s+\w+\s+)?INTO\s+price_bars_1m\b", line, re.I) \
                    and "collect-window-ok:" not in line:
                out.append(Violation(py, n,
                                     "direct INSERT into price_bars_1m bypasses the "
                                     "upsert_1m_bars seam and therefore the collect-window law "
                                     "(08:15-15:15 CT). Route through EdDB.upsert_1m_bars, or "
                                     "declare '# collect-window-ok: <reason>'."))
    return out


def check_ui_mockup_approval() -> list[Violation]:
    """Mockup-before-code law on gated UI surfaces (RC-186, operator non-negotiable 2026-08-02).

    WHAT WAS OBSERVED (RC-186): the operator ordered the Chart-tab redesign to render mockups
    for approval BEFORE any code lands ("before we do anything and this is a non negotiable we
    render mock ups"). Design-approval was a chat event that never became machine-readable
    state, so no lock could consult it — the RC-66/RC-93 goodwill-instead-of-lock class. The
    precedent is measured: the 2026-07-25 UI rebuild wiped two working screens without consent.

    Rule (four clauses):
    1. governance/ui_mockup_approvals.json must exist and parse as a JSON object — the lock
       reads absence as gate-nothing (a missing registry means no surface was placed under the
       law), so a deleted or corrupted registry would silently evaporate the law (self-audit
       finding, 2026-08-02).
    2. tools/pretooluse_guard.py must reference tools/ui_mockup_lock.py — the continuum's
       front end stays wired; a commit-time check alone does NOT satisfy the operator's
       mandate-to-mechanism law.
    3. For every surface listed in governance/ui_mockup_approvals.json with a status other
       than approved-with-operator-provenance, STAGED changes to that surface are violations
       unless the staged added text declares '# ui-mockup-ok: <reason>' as a comment-form
       declaration (RC-189 GUN 3: bare/mid-word token occurrences no longer count).
    4. RC-189 GUN 1: STAGED added text on the registry that introduces "status": "approved"
       must carry operator_quote in the same added text — a bare self-approve flip cannot
       reach a commit even if it somehow got written.
    5. RC-194 (operator non-negotiable 2026-08-02: "you are to always confirm first with
       actual code before you ship"): STAGED changes to a registry surface that carries an
       approved_variant require a co-staged reports/ship_confirmation_*.md whose text names
       the surface AND the literals RENDERED-FRAME and FEATURE-BY-FEATURE — the artifact of
       having walked the approved spec against the actual code and an actual rendered frame.
       OBSERVED: the v6 build shipped verified by structure/tests only; the operator saw the
       first rendered pixel and found collisions and missing agreed features. VALIDATED:
       negative control in tests/test_ui_mockup_lock_v1.py drives the clause callee both ways.

    HOW VALIDATED: prototyped on the live tree before registering (no gated surface staged ->
    silent; the one gated surface, static/chart.html, correctly reports a violation when its
    path is fed directly to the callee). Negative controls in tests/test_ui_mockup_lock_v1.py
    drive the REAL mockup_approval_violation on pending / approved / escape / unlisted registry
    states and demand a scream exactly on the pending case.
    """
    from tools.ui_mockup_lock import REGISTRY_REL, mockup_approval_violation

    out: list[Violation] = []
    reg = REPO / REGISTRY_REL
    try:
        reg_ok = isinstance(json.loads(_read_or_empty(reg) or "null"), dict)
    except (ValueError, json.JSONDecodeError):
        reg_ok = False
    if not reg_ok:
        out.append(Violation(
            reg, 0,
            "mockup-approval registry missing or unparseable — in this state the RC-186 law "
            "gates NOTHING (absence reads as no-surface-registered). Restore the registry."))
    guard = REPO / "tools/pretooluse_guard.py"
    if "ui_mockup_lock" not in _read_or_empty(guard):
        out.append(Violation(guard, 0,
                             "mockup-before-code front end unwired: pretooluse_guard.py no "
                             "longer references ui_mockup_lock (RC-186 continuum broken)"))
    staged = _git_output_lines(["diff", "--cached", "--name-only"])
    if staged is None:
        return out
    for raw in staged:
        rel = raw.strip().replace("\\", "/")
        if not rel:
            continue
        diff = _git_output_lines(["diff", "--cached", "-U0", "--", rel]) or []
        added = "\n".join(
            ln[1:] for ln in diff
            if ln.startswith("+") and not ln.startswith("+++")
        )
        if rel == REGISTRY_REL \
                and re.search(r'"status"\s*:\s*"approved"', added) \
                and '"operator_quote"' not in added:
            out.append(Violation(REPO / rel, 0,
                                 "registry flip to approved WITHOUT operator_quote in the "
                                 "staged text — approval is the operator's action, and a bare "
                                 "self-approve flip may not reach a commit (RC-189 GUN 1)."))
        reason = mockup_approval_violation(rel, added)
        if reason:
            out.append(Violation(REPO / rel, 0, reason))
        out.extend(ship_confirmation_violations(rel, staged))
    return out


def ship_confirmation_violations(rel: str, staged_names: list) -> list[Violation]:
    """Clause 5 of check ui_mockup_approval (RC-194): confirm with actual code before ship.

    OBSERVED (RC-194): the v6 Chart build shipped verified by structure and tests only; the
    operator saw the first rendered pixel and found collisions and missing agreed features.
    Rule: a staged change to an approved registry surface requires a co-staged
    reports/ship_confirmation_*.md naming the surface plus the RENDERED-FRAME and
    FEATURE-BY-FEATURE literals. VALIDATED: negative-control test drives this callee with and
    without the co-staged confirmation.
    """
    from tools.ui_mockup_lock import mockup_gated_entry

    rel = rel.replace("\\", "/")
    entry = mockup_gated_entry(rel)
    if entry is None or not entry.get("approved_variant"):
        return []
    names = {str(s).strip().replace("\\", "/") for s in (staged_names or [])}
    for cand in names:
        if cand.startswith("reports/ship_confirmation_") and cand.endswith(".md"):
            body = _read_or_empty(REPO / cand)
            if rel in body and "RENDERED-FRAME" in body and "FEATURE-BY-FEATURE" in body:
                return []
    return [Violation(
        REPO / rel, 0,
        f"{rel} is an APPROVED design surface and its change ships with NO co-staged "
        f"reports/ship_confirmation_*.md carrying the surface name + RENDERED-FRAME + "
        f"FEATURE-BY-FEATURE evidence. Operator law (RC-194): confirm the approved spec "
        f"against actual code and an actual rendered frame BEFORE the ship claim.")]


#: RC-205 production-surface geometry no longer MIRRORS tools/pretooluse_guard.py — FC-13
#: replaced the mirror with the thing itself. `classify_path` is the single authority for
#: "is this path ours, and is it a product surface"; a mirrored copy is a second producer
#: that drifts, which is what this consolidation exists to remove.


def research_before_act_violations(staged: list, log_path: Path) -> list[str]:
    """Callee for check research_before_act — separated so the negative controls can drive it
    against a temp log without staging anything (the check_ui_mockup_approval pattern).

    RC-205: research must pass full turn_self_audit.research_violation (resolvable path/URL),
    not merely a non-empty string."""
    try:
        from tools.pretooluse_guard import classify_path
    except ImportError:
        from pretooluse_guard import classify_path  # type: ignore
    prod = [s for s in staged if classify_path(s).production]
    if not prod:
        return []
    # RC-396 — EVIDENCE-ABSENT is not EVIDENCE-FAILING. This log is deliberately UNTRACKED:
    # it is per-turn local scratch, so a clean checkout has never held one. On the required
    # CI runner the delta owner stages the candidate (so staged-scope checks can see it) and
    # the log cannot exist there by construction, which made every production PR score a
    # fabricated `research_before_act: 0 -> 1` — the check reporting on the absence of
    # something the environment is incapable of holding, rather than on the author's
    # conduct. MEASURED on PR #127.
    #
    # Same shape `check_writer_no_drift` already resolves for identity: with no genuine
    # context it abstains and the local PreToolUse/Stop layer carries enforcement. A log
    # that EXISTS is the operator context this law owns, and there it still bites in full —
    # stale day, empty research and unresolvable references all scream (negative controls
    # in tests/test_ui_mockup_lock_v1.py drive exactly those against a temp log).
    if not log_path.exists():
        return []
    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").strip().splitlines()
        rec = json.loads(lines[-1]) if lines else {}
    except (OSError, ValueError):
        rec = {}
    import time as _time
    rec_day = _time.strftime("%Y-%m-%d", _time.localtime(float(rec.get("ts_utc", 0) or 0)))
    today = _time.strftime("%Y-%m-%d", _time.localtime())
    research = str(rec.get("research", "")).strip()
    if rec_day != today:
        return [f"staged production changes ({', '.join(prod[:4])}{'…' if len(prod) > 4 else ''}) "
                f"with no SAME-DAY research-bearing self-audit record "
                f"(last record day={rec_day or 'none'}). "
                f"Operator ULTIMATE LAW (RC-203/RC-205): research THEN act — run "
                f"tools/turn_self_audit.py --research '<reference consulted>' before committing."]
    try:
        from tools.turn_self_audit import research_violation
    except ImportError:
        from turn_self_audit import research_violation  # type: ignore
    bad = research_violation(research, prod)
    if bad is None:
        return []
    return [f"staged production changes ({', '.join(prod[:4])}{'…' if len(prod) > 4 else ''}) "
            f"fail research_violation: {bad}"]


def check_research_before_act() -> list[Violation]:
    """Research-then-act, enforced at COMMIT (RC-203/RC-205, operator ULTIMATE LAW 2026-08-02).

    WHAT WAS OBSERVED (RC-205): the operator ordered the law locked "to the highest degree"
    ("I DON'T WANT BINDING. I WANT A MECHANICAL LOCK"), and Cursor's lock research measured
    the gap: RC-203 lived only in turn_self_audit (--research) and an operator_law_guard Stop
    clause, so a commit could land with production changes and NO research artifact anywhere.
    The same-day defects that founded the law: an invented drag clamp while the reference
    implementation (chart.html clampView) sat in-repo, and a bubble layer contradicting the
    spec recorded in the direction doc §3.3.

    Rule: when staged changes touch production surfaces (the pretooluse_guard continuum:
    .py/.html/.js/.css/.ts/.sql outside the compliance lanes), the LAST record in
    reports/turn_self_audit_log.jsonl must be from TODAY and pass full research_violation
    (resolvable repo path or http URL — not a non-empty vibe string).

    HOW VALIDATED: negative controls in tests/test_ui_mockup_lock_v1.py and
    tests/test_plus_player_law_v1.py drive research_before_act_violations on (a) staged
    production + empty/absent research -> scream, (b) same-day resolvable record -> silent,
    (c) governance-only staging -> silent, (d) non-resolving path -> scream.
    """
    staged = _git_output_lines(["diff", "--cached", "--name-only"])
    if staged is None:
        return []
    names = [s.strip().replace("\\", "/") for s in staged if s.strip()]
    reasons = research_before_act_violations(
        names, REPO / "reports" / "turn_self_audit_log.jsonl")
    return [Violation(REPO / "reports" / "turn_self_audit_log.jsonl", 0, r) for r in reasons]


def _plus_player_known_enforcers() -> set[str]:
    names = {name for name, _fn, _en in CHECKS}
    names.update({
        "guard:proof_only_guard", "guard:operator_law_guard", "guard:stop_guard",
        "guard:turn_self_audit", "runtime:decision_gate",
        "soft:operator_review", "soft:operator_review+catalog",
    })
    return names


def plus_player_law_violations(catalog: dict | None = None) -> list[str]:
    """Callee for check_plus_player_law — injectable for negative controls."""
    try:
        from tools.plus_player_locks import (
            catalog_completeness_violations, load_catalog,
        )
    except ImportError:
        from plus_player_locks import (  # type: ignore
            catalog_completeness_violations, load_catalog,
        )
    out = list(catalog_completeness_violations(catalog))
    try:
        data = catalog if catalog is not None else load_catalog()
    except Exception as e:
        return out or [f"catalog load failed: {e}"]
    known = _plus_player_known_enforcers()
    # plus_player_* checks are registered below; allow forward refs
    known.update({
        "plus_player_law", "plus_player_cursor_hooks", "research_before_act",
        "honesty_guard_wired", "find_prove_significance_substance",
        "admission_evidence_resolves", "purged_cv_research",
        "prereg_before_confirmatory", "decision_path_wired",
        "claude_cursor_guard_parity", "collect_datasheet_staged",
    })
    for a in data.get("attributes") or []:
        enf = str(a.get("enforcer") or "")
        if not enf:
            continue
        if enf.startswith("soft:"):
            out.append(f"{a.get('id')}: soft: enforcer banned (RC-208)")
            continue
        if enf.startswith("guard:") or enf.startswith("runtime:"):
            continue
        if enf not in known:
            out.append(f"{a.get('id')}: unknown enforcer {enf!r} (not a CHECK id)")
    return out


def check_plus_player_law() -> list[Violation]:
    """Ultimate plus-player catalog: ENFORCED-only, soft_partial banned (RC-205/RC-209).

    WHAT WAS OBSERVED: Soft-registered \"until CHECK ships\" rows were treated as locks;
    operator ruled Soft theater unacceptable for non-negotiables. An .md scorecard is not
    a lock. Catalog may list only attributes with real CHECK/guard/runtime enforcers.

    Rule: governance/plus_player_attributes.json — every row enforcement==enforced with a
    known enforcer; soft_partial/soft: forbidden; CORE_ENFORCED_IDS must be present.

    HOW VALIDATED: tests/test_plus_player_law_v1.py + test_honesty_guard_v1.py inject
    incomplete/soft catalogs -> BLOCK; live catalog must return [].
    """
    rel = "governance/plus_player_attributes.json"
    reasons = plus_player_law_violations()
    return [Violation(REPO / rel, 0, r) for r in reasons]


def plus_player_cursor_hooks_violations(hooks_text: str | None = None) -> list[str]:
    """Callee for check_plus_player_cursor_hooks."""
    p = REPO / ".cursor" / "hooks.json"
    if hooks_text is None:
        if not p.is_file():
            return [".cursor/hooks.json missing — Cursor continuum cannot invoke .py guards (RC-205)"]
        hooks_text = p.read_text(encoding="utf-8", errors="replace")
    need = (
        "operator_law_guard.py",
        "pretooluse_guard.py",
        "stop_guard.py",
        "proof_only_guard.py",
        "honesty_guard.py",
    )
    missing = [n for n in need if n not in hooks_text]
    if missing:
        return [f".cursor/hooks.json must invoke {', '.join(missing)} (same .py as Claude)"]
    return []


def check_plus_player_cursor_hooks() -> list[Violation]:
    """Cursor must invoke the same .py guards as Claude (RC-205/RC-208 continuum).

    WHAT WAS OBSERVED: Claude hooks lived in .claude/settings.json while Cursor had only
    soft .mdc rules; meta-check only required two of five Stop/PreToolUse scripts, so
    honesty/proof/stop could silently unwired.

    Rule: .cursor/hooks.json names pretooluse_guard, operator_law_guard, stop_guard,
    proof_only_guard, honesty_guard.

    HOW VALIDATED: tests/test_plus_player_law_v1.py / test_honesty_guard_v1.py drive
    plus_player_cursor_hooks_violations with empty/partial text -> BLOCK; live file must pass.
    """
    reasons = plus_player_cursor_hooks_violations()
    return [Violation(REPO / ".cursor" / "hooks.json", 0, r) for r in reasons]


def check_find_prove_significance_substance() -> list[Violation]:
    """Staged Find&Prove reports: significance/Sharpe/alpha needs n_trials + method or [UNVERIFIED].

    WHAT WAS OBSERVED (RC-210): Find&Prove substance scored ~5/10 — experiment reports could claim
    significance/Sharpe/alpha with no trial ledger or multiple-testing correction, the Harvey–Liu–Zhu
    (2016) and Bailey–López de Prado DSR (2014) failure class.

    Rule: staged reports/** or governance/** experiment .md/.json with significance/Sharpe/alpha
    language must carry n_trials + multiple_testing_method (bonferroni|bh|dsr|hlz) or [UNVERIFIED].

    HOW VALIDATED: tests/test_find_prove_locks_v1.py injects bad/good report text -> BLOCK/clear.
    """
    staged = _git_output_lines(["diff", "--cached", "--name-only"])
    if staged is None:
        return []
    try:
        from tools.find_prove_locks import significance_substance_violations
    except ImportError:
        from find_prove_locks import significance_substance_violations  # type: ignore
    out: list[Violation] = []
    for rel in staged:
        rel = rel.strip().replace("\\", "/")
        if not rel.endswith((".md", ".json")):
            continue
        if not rel.startswith(("reports/", "governance/")):
            continue
        path = REPO / rel
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for msg in significance_substance_violations(text, rel=rel):
            out.append(Violation(path, 0, msg))
    return out


def check_admission_evidence_resolves() -> list[Violation]:
    """ADMITTED decision-path rows: evidence paths must resolve (SR 11-7 / RSK-02).

    WHAT WAS OBSERVED: empty registry already forces WAIT at runtime, but a future ADMITTED row
    with vibe-string evidence refs would pass schema while citing nothing real — SR 11-7 validation
    substance gap.

    Rule: when governance/decision_path_admissions.json lists ADMITTED entries, every evidence
    field that is a repo path must resolve to an existing file (http URLs exempt). Empty list -> [].

    HOW VALIDATED: tests/test_find_prove_locks_v1.py drives admission_evidence_resolves_violations.
    """
    try:
        from tools.find_prove_locks import admission_evidence_resolves_violations
    except ImportError:
        from find_prove_locks import admission_evidence_resolves_violations  # type: ignore
    p = REPO / "governance" / "decision_path_admissions.json"
    reasons = admission_evidence_resolves_violations()
    return [Violation(p, 0, r) for r in reasons]


def check_purged_cv_research() -> list[Violation]:
    """Research runners: sklearn KFold/train_test_split without purge/embargo -> BLOCK (AFML).

    WHAT WAS OBSERVED: López de Prado AFML Ch.7 — plain k-fold on overlapping financial labels
    leaks; research continuum had no static ban on the failure mode.

    Rule: research/**/*.py using KFold|train_test_split|ShuffleSplit|GroupKFold must also carry
    purge/embargo/walk_forward marker or ``# leakage-ok:`` waiver in the same file.

    HOW VALIDATED: tests/test_find_prove_locks_v1.py injects leaky sklearn import -> BLOCK.
    """
    try:
        from tools.find_prove_locks import purged_cv_violations
    except ImportError:
        from find_prove_locks import purged_cv_violations  # type: ignore
    out: list[Violation] = []
    research = REPO / "research"
    if not research.is_dir():
        return out
    for path in sorted(research.rglob("*.py")):
        if path.name.startswith("test_"):
            continue
        try:
            src = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        rel = path.relative_to(REPO).as_posix()
        for msg in purged_cv_violations(src, rel=rel):
            out.append(Violation(path, 0, msg))
    return out


def check_prereg_before_confirmatory() -> list[Violation]:
    """research/** CONFIRMATORY claims require resolvable prereg_path (Arnott/COS).

    WHAT WAS OBSERVED: exploratory results reported as confirmatory without prereg — Ioannidis /
    Nosek TOP failure class; no mechanical gate on research/** artifacts.

    Rule: any research/**/*.py or prereg JSON claiming CONFIRMATORY must name a resolvable
    prereg_path or ship prereg_v1.json alongside.

    HOW VALIDATED: tests/test_find_prove_locks_v1.py injects CONFIRMATORY without prereg -> BLOCK.
    """
    try:
        from tools.find_prove_locks import prereg_confirmatory_violations
    except ImportError:
        from find_prove_locks import prereg_confirmatory_violations  # type: ignore
    out: list[Violation] = []
    research = REPO / "research"
    if not research.is_dir():
        return out
    for path in sorted(research.rglob("*")):
        if path.suffix not in (".py", ".json", ".md"):
            continue
        if path.name.startswith("test_"):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        rel = path.relative_to(REPO).as_posix()
        for msg in prereg_confirmatory_violations(text, rel=rel, file_dir=path.parent):
            out.append(Violation(path, 0, msg))
    return out


def check_decision_path_wired() -> list[Violation]:
    """call_engine.compute_call must invoke evaluate_decision_path_admission (SR 11-7).

    WHAT WAS OBSERVED: runtime gate exists but no commit-time AST proof that TRADE authority
    cannot bypass admission — regression could re-wire around the gate silently.

    Rule: call_engine.compute_call() source must call evaluate_decision_path_admission and surface
    WAIT_BLOCKER_REASON_ADMISSION.

    HOW VALIDATED: tests/test_find_prove_locks_v1.py strips the call -> BLOCK.
    """
    try:
        from tools.find_prove_locks import decision_path_wired_violations
    except ImportError:
        from find_prove_locks import decision_path_wired_violations  # type: ignore
    p = REPO / "call_engine.py"
    reasons = decision_path_wired_violations()
    return [Violation(p, 0, r) for r in reasons]


def check_claude_cursor_guard_parity() -> list[Violation]:
    """Claude and Cursor must invoke the same five .py guards (RC-205/209 continuum).

    WHAT WAS OBSERVED: plus_player_cursor_hooks checked Cursor only; Claude settings could drift
    unwired while meta-check reported green on half the continuum.

    Rule: .cursor/hooks.json AND .claude/settings.json must name pretooluse_guard, operator_law_guard,
    stop_guard, proof_only_guard, honesty_guard.

    HOW VALIDATED: tests/test_find_prove_locks_v1.py + test_honesty_guard_v1.py parity controls.
    """
    try:
        from tools.find_prove_locks import claude_cursor_parity_violations
    except ImportError:
        from find_prove_locks import claude_cursor_parity_violations  # type: ignore
    reasons = claude_cursor_parity_violations()
    return [Violation(REPO / ".cursor" / "hooks.json", 0, r) for r in reasons]


def check_collect_datasheet_staged() -> list[Violation]:
    """Staged new Collect tables require governance/datasheets/<table>.yaml (Gebru et al. 2021).

    WHAT WAS OBSERVED: new tables could land without motivation/composition documentation —
    BCBS 239 / FAIR data-provenance gap on schema migrations.

    Rule: staged diff adding CREATE TABLE in db.py or calibration/*.py must ship a datasheet YAML
    with motivation, composition, collection, recommended_uses. Existing tables grandfathered
    (diff-scoped only).

    HOW VALIDATED: tests/test_find_prove_locks_v1.py injects table without datasheet -> BLOCK.
    """
    staged = _git_output_lines(["diff", "--cached", "--name-only"])
    if staged is None:
        return []
    try:
        from tools.find_prove_locks import collect_datasheet_violations, new_table_names_in_diff
    except ImportError:
        from find_prove_locks import collect_datasheet_violations, new_table_names_in_diff  # type: ignore
    targets = [
        s.strip().replace("\\", "/") for s in staged
        if s.strip().replace("\\", "/") in ("db.py",) or s.strip().replace("\\", "/").startswith("calibration/")
    ]
    if not targets:
        return []
    tables: set[str] = set()
    for rel in targets:
        diff = _git_output_lines(["diff", "--cached", "-U0", "--", rel]) or []
        tables |= new_table_names_in_diff(diff)
    if not tables:
        return []
    out: list[Violation] = []
    for table in sorted(tables):
        ds = REPO / "governance" / "datasheets" / f"{table}.yaml"
        text = None
        if ds.is_file():
            try:
                text = ds.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                pass
        for msg in collect_datasheet_violations(table, text):
            out.append(Violation(ds, 0, msg))
    return out


def check_honesty_guard_wired() -> list[Violation]:
    """Honesty guard must be on Claude AND Cursor Stop continuum (RC-209).

    WHAT WAS OBSERVED: operator asked whether a lock bans lying/omission/dodging — answer was
    no; agents kept writing .md briefs as if they were locks. Without a Stop .py on BOTH
    continua, the law is goodwill. Institutional analogues: PCAOB AS 1215 (no omission of
    inconsistent info); Simmons et al. 2011 (disclose flexibility); Peng 2011 (reproducible
    claims).

    Rule: .claude/settings.json AND .cursor/hooks.json Stop hooks must invoke
    tools/honesty_guard.py.

    HOW VALIDATED: tests/test_honesty_guard_v1.py asserts both continua + honesty_violations BLOCK.
    """
    out: list[Violation] = []
    for rel in (".claude/settings.json", ".cursor/hooks.json"):
        p = REPO / rel
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            out.append(Violation(p, 0, f"{rel} missing — honesty Stop continuum unwired (RC-209)"))
            continue
        if "honesty_guard.py" not in text:
            out.append(Violation(
                p, 0, f"{rel} Stop continuum missing honesty_guard.py (RC-209)"))
    return out


#: RC-212 (operator law 2026-08-02: "tighten up the one faucet mechanical lock so this
#: issue cannot happen again, or for that matter any other way two faucets can manifest.
#: this is strictly prohibited."): the vanna defect WAS a second faucet — a hand-rolled
#: formula beside the bs_* truth faucet — and the four level producers are the same class
#: at domain scale. Two clauses, both on STAGED ADDED TEXT so grandfathered code lives
#: until its registered migration.
_GREEK_FAUCET_ESCAPE = "# greek-faucet-ok:"
_LEVEL_DOMAIN_VOCAB = ("level", "strike", "wall", "terrain", "exposure", "force", "flow")


def domain_faucet_violations(rel: str, added: str, registry_text: str,
                             registry_staged_added: str = "") -> list[str]:
    """Callee for check domain_faucet_registry — testable without staging.

    Clause A: an added @app.get route in the level domain that the registry does not
    authorize blocks, unless the registry itself is co-staged WITH an operator_quote.
    Clause B: an added d1-style greek formula outside math_levels.py blocks (compute
    greeks only at the bs_* faucet), escape `# greek-faucet-ok: <reason>` per edit."""
    out: list[str] = []
    try:
        reg = json.loads(registry_text or "null")
        producers = set((reg or {}).get("level_domain_producers", {}).keys())
    except (ValueError, TypeError):
        return [f"{rel}: level-faucet registry unparseable — the domain lock gates NOTHING "
                f"in this state; restore governance/level_faucets.json"]
    if rel.endswith(".py"):
        for m in re.finditer(r'@app\.(?:get|post)\(\s*"(/api/[^"]+)"', added):
            path = m.group(1)
            if any(v in path.lower() for v in _LEVEL_DOMAIN_VOCAB) and path not in producers:
                if '"operator_quote"' not in registry_staged_added:
                    out.append(
                        f"{rel}: NEW level-domain producer {path} is not in "
                        f"governance/level_faucets.json (RC-212: one faucet per domain — "
                        f"adding a producer requires the registry co-staged with an "
                        f"operator_quote; the target is ONE /api/levels service)")
        if rel != "math_levels.py" and _GREEK_FAUCET_ESCAPE not in added:
            for m in re.finditer(r"math\.log\(\s*(?:spot|spt|S)\s*/", added):
                seg = added[m.start():m.start() + 240]
                if "sqrt" in seg:
                    out.append(
                        f"{rel}: added a d1-style greek formula outside math_levels.py "
                        f"(RC-212: greeks are computed ONLY at the bs_* faucet — the "
                        f"vanna defect was exactly a second formula faucet; call "
                        f"bs_vanna/bs_gamma/bs_charm or declare {_GREEK_FAUCET_ESCAPE} "
                        f"<reason>)")
                    break
    return out


def check_domain_faucet_registry() -> list[Violation]:
    """One faucet per DOMAIN, enforced at commit (RC-212, operator law 2026-08-02).

    WHAT WAS OBSERVED (RC-211/RC-212): per-strike vanna shipped as `vega/(S*sigma)` —
    a second formula faucet beside math_levels' bs_* truth faucet — always positive,
    wrong sign below spot, REFUTED by finite difference; and the levels domain grew four
    producers under green per-value faucet locks because every existing lock guards one
    VALUE against two sources, none guards the DOMAIN against many producers.

    Rule: (A) a staged new /api route in the level domain must be authorized in
    governance/level_faucets.json, and adding an authorization requires an operator_quote
    in the registry's own staged text; (B) staged d1-style greek formulas outside
    math_levels.py block, escape `# greek-faucet-ok: <reason>`.

    HOW VALIDATED: negative controls in tests/test_ui_mockup_lock_v1.py drive
    domain_faucet_violations on (a) unregistered producer -> scream, (b) registered ->
    silent, (c) co-staged registry with quote -> silent, (d) inline greek -> scream,
    (e) escape declared -> silent, (f) corrupt registry -> scream.
    """
    reg_path = REPO / "governance" / "level_faucets.json"
    registry_text = _read_or_empty(reg_path)
    out: list[Violation] = []
    staged = _git_output_lines(["diff", "--cached", "--name-only"])
    if staged is None:
        return out
    names = [s.strip().replace("\\", "/") for s in staged if s.strip()]
    reg_added = ""
    if "governance/level_faucets.json" in names:
        diff = _git_output_lines(
            ["diff", "--cached", "-U0", "--", "governance/level_faucets.json"]) or []
        reg_added = "\n".join(ln[1:] for ln in diff
                              if ln.startswith("+") and not ln.startswith("+++"))
    for rel in names:
        if not rel.endswith(".py"):
            continue
        diff = _git_output_lines(["diff", "--cached", "-U0", "--", rel]) or []
        added = "\n".join(ln[1:] for ln in diff
                          if ln.startswith("+") and not ln.startswith("+++"))
        for reason in domain_faucet_violations(rel, added, registry_text, reg_added):
            out.append(Violation(REPO / rel, 0, reason))
    if not registry_text.strip():
        out.append(Violation(reg_path, 0,
                             "level-faucet registry missing — the RC-212 domain lock "
                             "gates NOTHING (restore governance/level_faucets.json)"))
    return out


def check_phase2a_single_level_computation() -> list[Violation]:
    """ONE computation and ONE materialization per (ticker, level_id, scope, generation).

    WHAT WAS OBSERVED (operator, 2026-08-08, measured live on one ticker at one instant):
    /api/levels served overnight 773.3975/773.3975 while /api/liquidity-snapshot served
    773.40/772.55, and the prior-day value area disagreed intermittently between them.
    Both endpoints ran the SAME engine helpers — over different bar inputs. The existing
    single-writer lock (tests/test_levels_single_producer_v1.py) was green throughout,
    because no forbidden payload KEY was written; the duplication was one layer down, in
    the call graph, where no check was looking.

    Rule: the Phase 2A helpers are invoked only from
    liquidity_value_engine.build_price_level_snapshot and the declared checkpoint/replay
    sites; every other surface CARRIES the materialized value. Alias-resolved, so the
    same helper under another import name, another variable, or a forwarding wrapper
    still fires. Level rows — including entries inside `levels: [{"id", "price"}]` —
    must take their number from the snapshot. Browsers must not reconstruct the family.

    HOW VALIDATED: negative controls in tests/test_phase2a_price_level_snapshot_v1.py
    inject (a) a second endpoint computation, (b) the same helper aliased and called from
    a wrapper, (c) a levels[] row carrying a computed/hardcoded price, and (d) an in-page
    VWAP accumulation, and assert each one screams; the legal carriage forms stay silent.
    """
    try:
        from tools.phase2a_level_lock import scan_repo
    except ImportError:  # pragma: no cover - import shape differs under the hook runner
        from phase2a_level_lock import scan_repo  # type: ignore
    out: list[Violation] = []
    for reason in scan_repo(REPO):
        head = str(reason).split(":", 1)[0]
        out.append(Violation(REPO / head, 0, str(reason)))
    return out


def check_log_law() -> list[Violation]:
    """LOG LAW (operator/PM 2026-08-04, RC-237): closable work has exactly ONE home
    (the sole master). The two historical ledgers are evidence, not work queues.

    OBSERVED (RC-237, measured 2026-08-04): five markdown files outside the two ledgers
    carried status-bearing work rows — `reports/rc_open_drain_latest.md` 21 rows,
    `reports/zero_debt_work_law_v1.md` 10, and three audit reports 3–7 each — beside the
    real ledger's own open class. Closable work therefore had more than one home, and
    whichever list a reader opened looked authoritative while the other rotted; a drain
    measured against the wrong list reports progress the defect ledger does not have.

    VALIDATED BY PROTOTYPE before enforcing: run against the whole tree first, it found
    exactly those five files and nothing else — no false positive on prose that merely
    mentions RC ids, on the two sanctioned ledgers, or on telemetry .jsonl/.log (events are
    explicitly not debt). The threshold is three work rows because two reads as discussion
    rather than a queue; frozen dated snapshots keep an operator escape (`# log-law-ok:`).
    Register due dates have zero work authority and do not participate. 10 negative controls in
    tests/test_log_law_v1.py, plus a wiring assertion (RC-238) that this registration is
    ENFORCED rather than merely present. Delegates to tools/log_law.py so the gate, the
    tests and the CLI all judge by ONE implementation.
    """
    try:
        from tools.log_law import log_law_violations
    except ImportError:  # pragma: no cover - import shape differs under the hook runner
        from log_law import log_law_violations  # type: ignore
    return [Violation(REPO / "governance" / "root_cause_log.md", 0, m)
            for m in log_law_violations(REPO)]


def check_active_writer_law() -> list[Violation]:
    """Operator-selected ACTIVE_WRITER; no permanent identity privilege (RC-452).

    WHAT WAS OBSERVED: governance/sole_writer.json and pm_mission.json hardcoded
    Claude=permanent writer and Cursor=permanent auditor, so an operator assignment of
    Cursor as ACTIVE_WRITER was still a SoD violation. The operator superseded that
    identity split on 2026-08-22: both agents may implement; the operator selects the
    active writer per mission; one canonical worktree total.

    Rule: sole_writer / pm_mission must set pm=operator, must not set permanent_writer
    or permanent_auditor, must not assert the superseded identity phrases, and
    active_writer must agree with writer when both are present. A second normal
    project worktree BLOCKS.

    HOW VALIDATED: tests/test_active_writer_law_v1.py injects permanent_writer=claude,
    Cursor-auditor-only standing_law, disagreed active_writer/writer, and a second
    normal worktree → BLOCK; live assignment with Cursor or Claude ACTIVE_WRITER PASS.
    """
    try:
        from tools.writer_drift_lock import (
            canonical_worktree_violations,
            permanent_identity_violations,
        )
    except ImportError:
        from writer_drift_lock import (  # type: ignore
            canonical_worktree_violations,
            permanent_identity_violations,
        )
    msgs = list(permanent_identity_violations())
    msgs.extend(canonical_worktree_violations())
    return [
        Violation(REPO / "governance" / "sole_writer.json", 0, m)
        for m in msgs
    ]


def check_requirement_proof() -> list[Violation]:
    """Parent/child proof authority (RC-459). Child PASS never closes a parent."""
    try:
        from tools.requirement_proof import TREE_PATH, requirement_proof_violations
    except ImportError:
        from requirement_proof import TREE_PATH, requirement_proof_violations  # type: ignore
    return [
        Violation(TREE_PATH, 0, m)
        for m in requirement_proof_violations()
    ]


def check_find_it_fix_it() -> list[Violation]:
    """FIND IT → FIX IT: sole master is the obligation authority (RC-480).

    RC log is historical evidence only. It does not create, classify, promote,
    defer, or close work, and it does not determine Stop eligibility.

    HOW VALIDATED: tests/test_find_it_fix_it_lock_v1.py — RC rows have zero
    execution authority; second-list and master-parent obligations still BLOCK.
    """
    try:
        from tools.find_it_fix_it_lock import SOLE_MASTER_PATH, active_obligation_offenders
    except ImportError:
        from find_it_fix_it_lock import SOLE_MASTER_PATH, active_obligation_offenders  # type: ignore
    return [
        Violation(SOLE_MASTER_PATH, 0, f"{rid}: {why}")
        for rid, why in active_obligation_offenders("")
    ]


def check_writer_no_drift() -> list[Violation]:
    """LOCK-1 commit backstop (RC-232): staged changes must come from the mission's
    resolved writer — the maker-checker split enforced at commit, delegating to
    tools/writer_drift_lock.py.

    IDENTITY GATE (measured limitation): pre-commit hook processes do not reliably carry
    ED_AGENT_ROLE, and the role helper fails closed to 'cursor' — which made the WRITER'S
    own landing read as drift (4 false blocks measured on the RC-232 landing commit).
    When the env carries no identity, this backstop stays silent and the PreToolUse layer
    (which always has identity via each agent's hook env) carries the enforcement.

    HOW VALIDATED: prototyped against the RC-232 landing — with identity absent the old
    form false-blocked the sole writer's own commit; with identity present (Cursor env)
    the negative controls in tests/test_writer_drift_lock_v1.py prove BLOCK on
    chart.html/server.py and ALLOW on the PM allowlist.
    """
    out: list[Violation] = []
    import os as _os
    if _os.environ.get("ED_AGENT_ROLE", "").strip().lower() not in ("cursor", "claude"):
        return out  # identity gate: PreToolUse carries enforcement for identity-less contexts
    try:
        from tools.writer_drift_lock import live_writer_drift_violations
    except ImportError:
        try:
            from writer_drift_lock import live_writer_drift_violations  # type: ignore
        except ImportError:
            return out
    for reason in live_writer_drift_violations(REPO, staged_only=True):
        out.append(Violation(REPO / "governance" / "pm_mission.json", 0, str(reason)))
    return out


def check_rc_document_without_resolve() -> list[Violation]:
    """RC-228/RC-230 (LOCK-6): newly ADDED OPEN/PARTIAL RC rows must carry a resolve path
    (FIXED:/NEXT-DEPTH:/OUT-OF-SCOPE: with tracker) — a row documented without one is the
    backlog-growth defect RC-228 measured (23 open-class rows by 2026-08-04). Delegates to
    tools/rc_resolve_lock.py, the module RC-228 shipped; registered ENFORCED under RC-230.

    HOW VALIDATED: prototyped against the live ledger — the RC-232 landing's own row was
    caught missing the literal FIXED: token (real block, fixed in place); negative controls
    in tests/test_rc_document_without_resolve_v1.py inject an added OPEN row without a
    resolve path and assert >= 1 violation through this registered wrapper.
    """
    out: list[Violation] = []
    try:
        from tools.rc_resolve_lock import added_open_rows_without_resolve
    except ImportError:
        from rc_resolve_lock import added_open_rows_without_resolve  # type: ignore
    rc_path = REPO / "governance" / "root_cause_log.md"
    added = _git_output_lines(["diff", "--cached", "-U0", "--", "governance/root_cause_log.md"]) or []
    added_lines = [ln[1:] for ln in added if ln.startswith("+") and not ln.startswith("+++")]
    for reason in added_open_rows_without_resolve(added_lines):
        out.append(Violation(rc_path, 0, str(reason)))
    return out


CHECKS = [
    # ENFORCED (must be zero — block pre-commit):
    ("no_synthetic_domain_fixtures_in_tests", check_no_synthetic_domain_fixtures_in_tests, True),
    ("no_swallowed_test_failures", check_no_swallowed_test_failures, True),  # printed failure must fail the run
    ("root_cause_log", check_root_cause_log, True),
    ("five_why_recursive_lock", check_five_why_recursive_lock, True),  # end-to-end fixes, no patches ever
    ("recursive_five_why_front_loaded", check_recursive_five_why_front_loaded, True),  # UNIVERSAL: production change requires an admitted master obligation
    ("adversarial_audit_test_lock", check_adversarial_audit_test_lock, True),  # RC-49: every fix ships a locking test (audit's output)
    ("rth_only_market_measurement", check_rth_only_market_measurement, True),  # RC-54: market-closed rows bias every statistic
    ("measured_claims_cite_evidence", check_measured_claims_cite_evidence, True),  # RC-56: a committed finding carries its reproduce command
    ("universal_ticker_scope", check_universal_ticker_scope, True),  # RC-160: no SPY-only work framed as complete
    ("chart_intent_and_next_rth", check_chart_intent_and_next_rth, True),  # RC-163: Chart Done ≠ bank; no weekday-proof lies
    ("ui_mockup_approval", check_ui_mockup_approval, True),  # RC-186: no UI redesign code before an approved mockup
    ("research_before_act", check_research_before_act, True),  # RC-203/RC-205 ULTIMATE LAW: named reference before commit
    ("domain_faucet_registry", check_domain_faucet_registry, True),  # RC-212: one faucet per DOMAIN; greeks only at bs_*
    ("phase2a_single_level_computation", check_phase2a_single_level_computation, True),  # Phase 2A: one computation + one materialization per (ticker, level_id, scope, generation)
    ("rc_document_without_resolve", check_rc_document_without_resolve, True),  # RC-228/RC-230 LOCK-6: added OPEN rows must carry a resolve path
    ("writer_no_drift", check_writer_no_drift, True),  # RC-232 LOCK-1: staged paths must come from the mission's resolved writer
    ("active_writer_law", check_active_writer_law, True),  # RC-452: operator-selected ACTIVE_WRITER; no permanent identity
    ("find_it_fix_it", check_find_it_fix_it, True),  # RC-453: one RC-log authority; omission and backlog-escape BLOCK
    ("requirement_proof", check_requirement_proof, True),  # RC-459: child PASS never closes a parent
    # LOG LAW (RC-237) — ARMED under the PM GO of 2026-08-04T18:58Z, scope staged_lock_surface
    # (governance/operator_go.json, granted_by cursor_pm). One defect ledger, one epistemic
    # ledger, telemetry stays telemetry: a THIRD markdown work queue or an OVERDUE epistemic
    # row now BLOCKS pre-commit. RC-238 records the window in which this line sat commented —
    # a proven-but-unwired lock reads as enforced to anyone who only runs the tests.
    ("log_law", check_log_law, True),
    ("plus_player_law", check_plus_player_law, True),  # RC-205: attribute catalog complete + bound
    ("plus_player_cursor_hooks", check_plus_player_cursor_hooks, True),  # RC-205/208: Cursor invokes same .py guards
    ("honesty_guard_wired", check_honesty_guard_wired, True),  # RC-209: Stop honesty_guard.py present
    ("find_prove_significance_substance", check_find_prove_significance_substance, True),  # RC-210: HLZ/DSR n_trials
    ("admission_evidence_resolves", check_admission_evidence_resolves, True),  # RC-210: SR 11-7 evidence paths
    ("purged_cv_research", check_purged_cv_research, True),  # RC-210: AFML no plain KFold
    ("prereg_before_confirmatory", check_prereg_before_confirmatory, True),  # RC-210: Arnott/COS prereg
    ("decision_path_wired", check_decision_path_wired, True),  # RC-210: SR 11-7 AST TRADE gate
    ("claude_cursor_guard_parity", check_claude_cursor_guard_parity, True),  # RC-205/209 full continuum
    ("collect_datasheet_staged", check_collect_datasheet_staged, True),  # RC-210: Gebru datasheets
    ("chain_width_single_faucet", check_chain_width_single_faucet, True),  # RC-59: one strike-count authority
    ("single_faucet_provenance", check_single_faucet_provenance, True),  # RC-73: measured, not asserted
    ("root_cause_recurrence_declared", check_root_cause_recurrence_declared, True),
    ("fix_crosswalks_to_violated_lock", check_fix_crosswalks_to_violated_lock, True),
    ("enforced_checks_have_negative_controls", check_enforced_checks_have_negative_controls, True),
    ("agents_laws_name_their_enforcer", check_agents_laws_name_their_enforcer, True),
    ("scheduled_producers_are_not_inert", check_scheduled_producers_are_not_inert, True),
    ("rc_citations_resolve", check_rc_citations_resolve, True),
    ("rc_status_vocabulary", check_rc_status_vocabulary, True),  # RC-257: unknown status must fail, not skip
    ("rc_log_rows_keep_schema", check_rc_log_rows_keep_schema, True),
    ("adversarial_audits_are_answered", check_adversarial_audits_are_answered, True),
    ("collect_window_single_law", check_collect_window_single_law, True),  # RC-183: 08:15-15:15 CT at the ONE write seam
    ("price_bars_readers_name_their_session", check_price_bars_readers_name_their_session, True),  # RC-61: the log is a control, not an archive
    ("domain_constants_are_derived", check_domain_constants_are_derived, True),  # RC-62: a market threshold states where its value came from
    ("no_terminal_null", check_no_terminal_null, True),                # every dead end names the next depth
    ("no_governance_duplication", check_no_governance_duplication, True),  # one item, one home
    ("checks_are_justified", check_checks_are_justified, True),  # observed + validated, or no ship
    ("no_tautological_assertions", check_no_tautological_assertions, True),  # catch, not pass
    ("open_item_cap", check_open_item_cap, True),   # ledgers burn down, never accumulate  # 5 whys, restarted on every new cause
    # RC-67 (operator 2026-07-26): ADVISORY, not enforced. It still computes and REPORTS every
    # metric delta, so a real regression stays visible — but a COUNT may no longer block a commit.
    # A counter cannot distinguish a regression from a false positive or from a deliberate,
    # higher-quality addition: it failed the build when the operator-mandated PreToolUse guard
    # read its own external hook payload (+3 orphan keys, all false positives). Correctness is
    # judged by the checks that read the CODE (no_fake_defaults, no_silent_swallow,
    # vendor_field_coercion, rth_only_market_measurement, domain_constants_are_derived,
    # chain_width_single_faucet, adversarial_audit_test_lock) and by the Code Health Panel's
    # BLOCKING tier — same class as the RC-19 shape-metric ceilings, already ruled track-only.
    ("debt_ratchet", check_debt_ratchet, False),
    ("single_spot_authority", check_single_spot_authority, True),  # one faucet (RC-14)
    ("no_silent_swallow", check_no_silent_swallow, True),           # driven to zero 2026-07-17
    ("no_todo_without_tracking_id", check_todo_without_tracking_id, True),
    ("rc_numeric_claims_cite_a_command", check_rc_numeric_claims_cite_a_command, True),
    # RC-319: numbers had to cite a command; a MECHANISM claim could say anything.
    ("rc_mechanism_claims_cite_a_source", check_rc_mechanism_claims_cite_a_source, True),
    # RC-321: the depth rule measured how FAR a chain went, never whose action was at the
    # bottom of it. Five levels ending on the operator's instruction is not bedrock.
    ("five_why_reaches_bedrock", check_five_why_reaches_bedrock, True),
    # RC-325 SP-01: one authorized production producer per canonical concept. ENFORCED
    # because an unregistered gate enforces nothing — it sat at zero registrations while
    # being reported as a lock.
    ("one_producer", check_one_producer, True),
    # RC-137: a CLOSED row must ship the code it names (the ledger cannot outrun HEAD).
    ("closed_rows_ship_their_code", check_closed_rows_ship_their_code, True),
    ("verdicts_declare_their_power", check_verdicts_declare_their_power, True),  # provenance, not the word "MEASURED" (RC-6)
    ("snapshots_read_names_the_timeframe", check_snapshots_read_names_the_timeframe, True),  # query PLAN, not code shape
    ("shutdown_is_bounded", check_shutdown_is_bounded, True),  # Ctrl+C must always work
    ("unproven_register", check_unproven_register, True),  # evidence integrity only; zero work authority
    ("venv_parity", check_venv_parity, True),  # one interpreter — .venv only (CI exempt)
    ("credential_leak", check_credential_leak, True),  # staged secrets / home paths
    ("sqlite_wal_contract", check_sqlite_wal_contract, True),  # WAL + timeout on connects
    ("ui_data_integration", check_ui_data_integration, True),  # no dead "—" placeholders (Tier 1)
    ("vendor_field_coercion", check_vendor_field_coercion, True),  # one faucet per Schwab leaf (RC-FAUCET)
    ("schwab_market_field_semantics", check_schwab_market_field_semantics, True),  # RC-440 M4/M5: NUM_* not order-count; exchange_quote_ts not a wall clock
    # REMOVED 2026-07-25 (operator: "i don't want you on separate instances"): the
    # agent_worktree_boundary check required ED_AGENT_ROLE to be set and blocked all
    # commits from a single-instance workflow (fail-closed on unset role). Single
    # working tree in EdWebConsole is the supported model again; the sibling -Claude
    # worktree was removed. Dormant helpers (check_worktree_handoff.py,
    # agent_worktree_policy.json, db_authority claude routing) remain inert — they only
    # activate if ED_AGENT_ROLE is explicitly set — and can be fully purged later.
    # ADVISORY (visible debt, driven to zero, then flipped to enforced — the ratchet):
    # RC-67: PROMOTED to directly ENFORCED for the same reason as no_fake_defaults — a test that
    # cannot fail on regression is not a test, and this was only blocking via the retired counter.
    # Driven to 0 by RC-46, so it binds on the code rather than on a delta.
    ("tests_missing_explicit_assert", check_tests_missing_explicit_assert, True),
    ("orphan_dict_keys", check_no_orphan_dict_keys, False),   # silent-None leads (RC-15/RC-20)
    ("function_complexity", check_function_complexity, False),      # too-branchy functions
    ("function_length", check_function_length, False),             # over-long functions
    ("file_length", check_file_length, False),                     # over-long files (split them)
    ("ruff_quality", check_ruff_quality, False),                   # dead code / bugs / simplify (ruff)
    # RC-67: PROMOTED to directly ENFORCED. This was only ever blocking as a side effect of the
    # count-ratchet, so retiring the ratchet would have left fabricated neutrals unguarded — and a
    # fabricated 0.5 probability entering the decision path is the exact opposite of the quality
    # bar the operator set. Driven to 0 by RC-47, so it binds cleanly and judges the CODE, not a
    # counter. Legitimate config parameters declare `# fake-default-ok: <reason>`.
    ("no_fake_defaults", check_no_fake_defaults, True),
    # RC-298: a test that only string-matches prose cannot detect a false claim. Measured:
    # tests/test_charm_docstring_states_the_physics_v1.py shipped eight assertions, all of
    # the form `assert "<sentence>" in DOC`, locking "calls sell, puts buy" — which one call
    # to bs_charm refutes. Same shape produced RC-281 and RC-290. This does NOT judge whether
    # a claim is true; it refuses a file that could never find out. ENFORCED from the start
    # because it was driven to zero before wiring (one real offender repaired, zero
    # exemptions used), so it binds on merit rather than on a baseline.
    ("test_claims_are_executed", check_test_claims_are_executed, True),
    # RC-301: the seventh occurrence of absence-coerced-to-a-value, attacked as a CLASS.
    # The existing gates match expressions; this one matches the RETURN TYPE, which is
    # where the honest option gets foreclosed before the literal is ever written.
    # Prototyped 78 -> 2 (exit codes and predicates excluded), both repaired or marked, so
    # it binds at zero on merit rather than on a baseline.
    ("absence_has_a_type", check_absence_has_a_type, True),
    # RC-382: line-ending style is an invariant across an edit. Three whole-file reflows
    # landed in one session (RC-372 charter, settings.json, RC-381 slice 1) because no
    # mechanism owned the terminator. Tests the OUTCOME — bytes on disk vs bytes in HEAD —
    # so it holds for any writer, not just the libraries that caused the known cases.
    ("eol_style_invariant", check_eol_style_invariant, True),
    ("mypy_types", check_mypy_types, False),                       # dormant until mypy installed
]

_MAX_PRINT = 15  # cap advisory output; full count is always reported


#: Operator PM GATE DECISION (2026-08-04 ~00:4x CT, mission one-faucet-closeout-v1, relayed
#: verbatim): "Forward-only grandfather — patch institutional RC checks so retroactive
#: close-contract / document-without-resolve / stuffed-evidence rules apply ONLY to RC rows
#: opened on/after 2026-07-28 (or RC-227+). Do NOT remediate RC-6..history tonight. Do NOT
#: --no-verify. Do NOT roll back the whole checker." Scratchpad probe debris (audit scripts,
#: mostly untracked) is likewise exempt from the file-hygiene classes — production and tools/
#: surfaces stay fully enforced. Forward enforcement is untouched: any row >= RC-227 faces
#: every check at full strength.
RC_GRANDFATHER_CUTOFF = 227
_GRANDFATHERED_ROW_CHECKS = frozenset({
    "five_why_recursive_lock", "closed_rows_ship_their_code",
    "verdicts_declare_their_power", "rc_numeric_claims_cite_a_command",
    "rc_citations_resolve", "root_cause_recurrence_declared",
    "fix_crosswalks_to_violated_lock",
})
_SCRATCHPAD_EXEMPT_CHECKS = frozenset({
    "no_silent_swallow", "vendor_field_coercion",
    "snapshots_read_names_the_timeframe", "price_bars_readers_name_their_session",
})


def _apply_forward_only_grandfather(name: str, violations: list) -> list:
    """Forward-only enforcement per the operator gate decision above (T1-locked)."""
    out = []
    for v in violations:
        rel = str(v.path).replace("\\", "/")
        if name in _SCRATCHPAD_EXEMPT_CHECKS and "scratchpad/" in rel:
            continue
        if name in _GRANDFATHERED_ROW_CHECKS:
            m = re.search(r"RC-(\d+)", str(v.msg))
            if m and int(m.group(1)) < RC_GRANDFATHER_CUTOFF:
                continue
        out.append(v)
    return out


#: RC-246: where the ADVISORY run leaves its dated result so the debt stays visible daily
#: even though it no longer blocks a commit. The PM's approval of P1 was conditional on
#: exactly this — advisory debt must surface, debt_ratchet must not be silently dropped.
ADVISORY_REPORT_REL = "reports/advisory_debt_latest.json"


def run_checks(*, mode: str = "all") -> tuple[int, list[tuple[str, bool, int]]]:
    """Run the catalogue and return (enforced_violation_count, per-check results).

    RC-246: `mode` splits WHO PAYS for a check from WHETHER it can veto.
      * "enforced" — the pre-commit path. Advisory checks are structurally incapable of
        failing the gate (they print and return 0), so charging every commit 153s of the
        244s wall for them bought nothing and made the gate expensive enough to route
        around — this repo has the scar tissue to prove that (RC-215, RC-234).
      * "advisory" — the scheduled/rehab path. Runs the seven and writes them down.
      * "all" — unchanged default, so a human invoking the gate by hand still sees
        everything in one place.
    """
    enforced_violations = 0
    results: list[tuple[str, bool, int]] = []
    hotspots: dict[str, dict[str, int]] = {}
    for name, fn, enforced in CHECKS:
        if mode == "enforced" and not enforced:
            continue
        if mode == "advisory" and enforced:
            continue
        tag = "ENFORCED" if enforced else "ADVISORY"
        violations = _apply_forward_only_grandfather(name, fn())
        results.append((name, enforced, len(violations)))
        if not enforced and violations:
            # RC-251: WHERE, not just how much. Per-file counts are what turn a total into a
            # bounded work list; without them the only options are ignore or mass-rewrite.
            per_file: dict[str, int] = {}
            for v in violations:
                try:
                    rel = str(Path(v.path).resolve().relative_to(REPO.resolve())).replace("\\", "/")
                except (ValueError, OSError, AttributeError):
                    rel = str(getattr(v, "path", "?")).replace("\\", "/")
                per_file[rel] = per_file.get(rel, 0) + 1
            hotspots[name] = dict(
                sorted(per_file.items(), key=lambda kv: -kv[1])[:20]
            )
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
    return enforced_violations, results, hotspots


def write_advisory_report(
    results: list[tuple[str, bool, int]],
    hotspots: dict[str, dict[str, int]] | None = None,
) -> Path:
    """Persist the advisory tally — the visibility half of P1's approval.

    RC-251: a total is not a work list. The report now carries per-file HOTSPOTS alongside the
    counts, because a number without a location supports no smallest-safe-change: the only
    actions a bare total affords are 'ignore it' or 'mass-rewrite thousands of findings', and
    the second is banned. `hotspots` maps check name -> {repo-relative path: count}.
    """
    import json as _json
    import time as _time

    payload = {
        "measured_at_utc": _time.time(),
        "checks": {name: count for name, enforced, count in results if not enforced},
        "total_advisory_violations": sum(c for _n, e, c in results if not e),
        "hotspots": hotspots or {},
    }
    out = REPO / ADVISORY_REPORT_REL
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(_json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return out


def rebaseline() -> int:
    """RC-385: the ONLY writer of the advisory debt baseline. Deliberate, never a side effect.

    Both `_ratchet_may_write` and `check_debt_ratchet` have pointed at `--rebaseline` as the
    explicit recording path since RC-90 — and it was never implemented, so the only recording
    that existed was the invisible auto-write this replaces. Raising a debt ceiling is now an
    act someone performs and can be asked to justify.

    Correctness metrics on `_RATCHET_BLOCKS_ON_RISE` are still refused a RISE here: this is a
    recorder, not an amnesty. It lowers floors that genuinely improved, seeds a missing file,
    and tracks shape/style counters that are allowed to float.
    """
    path = _debt_baseline_path()
    current = {name: len(fn()) for name, fn, enforced in CHECKS
               if not enforced and name != "debt_ratchet"}
    try:
        baseline = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except ValueError:
        print(f"REFUSED: {path} is unparseable — repair it before rebaselining.")
        return 1

    raised, changes = [], []
    for name, count in sorted(current.items()):
        base = baseline.get(name)
        if base is None:
            baseline[name] = count
            changes.append(f"  seed  {name}: {count}")
            continue
        if count == base:
            continue
        if count > base and name in _RATCHET_BLOCKS_ON_RISE:
            raised.append(f"  {name}: {base} -> {count} (+{count - base})")
            continue
        if count == 0 and base > 10:
            # RC-90 honesty guard: a collapse to zero is a checker failure until proven
            # otherwise, and recording it would silently destroy the ratchet.
            print(f"REFUSED: {name} reported 0 against a baseline of {base} — checker failure, "
                  f"not perfection. Nothing written.")
            return 1
        baseline[name] = count
        changes.append(f"  {'lower' if count < base else 'track'} {name}: {base} -> {count}")

    if raised:
        print("REFUSED: correctness debt may not be rebaselined UPWARD. Clean it, or lower "
              "another correctness count to pay for it:")
        print("\n".join(raised))
        return 1
    if not changes:
        print("advisory_debt_baseline.json already matches the tree — nothing to record.")
        return 0
    # newline pinned: this file is committed LF and an EOL flip would bury the real delta
    # under a whole-file diff (RC-382/RC-383).
    path.write_text(json.dumps(baseline, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8", newline="\n")
    print(f"recorded {len(changes)} change(s) in {path}:")
    print("\n".join(changes))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "--rebaseline" in args:
        return rebaseline()
    if "--enforced-only" in args:
        enforced_violations, _, _ = run_checks(mode="enforced")
        if enforced_violations:
            print(f"\nINSTITUTIONAL CORRECTNESS GATE: FAIL "
                  f"({enforced_violations} enforced violation(s))")
            return 1
        print("\nINSTITUTIONAL CORRECTNESS GATE: PASS (enforced checks clean; advisory debt "
              f"runs on its own schedule and is recorded in {ADVISORY_REPORT_REL})")
        return 0
    if "--advisory" in args:
        _, results, hotspots = run_checks(mode="advisory")
        path = write_advisory_report(results, hotspots)
        total = sum(c for _n, e, c in results if not e)
        print(f"\nADVISORY DEBT: {total} violation(s) across "
              f"{len([1 for _n, e, _c in results if not e])} checks — recorded in {path}")
        return 0                      # advisory NEVER blocks; it reports
    enforced_violations = 0
    for name, fn, enforced in CHECKS:
        tag = "ENFORCED" if enforced else "ADVISORY"
        violations = _apply_forward_only_grandfather(name, fn())
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
