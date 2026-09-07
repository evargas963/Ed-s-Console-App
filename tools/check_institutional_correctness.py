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
import hashlib
import json
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
    # BEDROCK 2026-09-06: the arrow count is gone. It measured form, not cause: four `->`
    # could be written in a minute and were, hundreds of times, and RC-315's chain was five
    # deep on a false premise. Causal sufficiency (the chain ends at the wrong model,
    # assumption, semantics, placement or computation, each link a measured fact) is judged
    # in review. What a machine CAN check is that the cell is not empty.
    if not why.strip():
        out.append(Violation(log_path, n, f"{rc_id} has an empty why-chain cell."))
    if status in ("CLOSED", "REMEDIATED"):
        # REMEDIATED joined the evidence gate 2026-08-25 (audit round 2 red-team):
        # OPEN->REMEDIATED used to terminate an overdue row with no evidence and no
        # re-date reason — the same silencing CLOSED is gated against.
        # BEDROCK 2026-09-06: "a digit plus one of four words" is replaced by the one
        # checkable evidence property: a backticked command a reader can re-run.
        evidence = cells[6] if len(cells) >= 7 else ""
        opened = cells[2] if len(cells) >= 3 else ""
        # Forward-binding from the bedrock cutover, like every other row rule: rows closed
        # under the old digit-plus-word rule are history and are not re-judged.
        if opened >= CLOSE_COMMAND_CUTOVER and not _RUNNABLE_COMMAND_RE.search(evidence):
            out.append(Violation(
                log_path, n,
                f"{rc_id} is {status} without a re-runnable command in its evidence cell. "
                f"Closure cites the exact command whose output proved the fix, in backticks; "
                f"describing the code change is not proof that it works."))
    return out


#: Bedrock doctrine cutover (2026-09-06): closure evidence is a re-runnable command.
CLOSE_COMMAND_CUTOVER = "2026-09-06"

#: A backticked span that is a command someone can run — the same standard the numeric
#: claim rule holds, held once here for closure evidence.
_RUNNABLE_COMMAND_RE = re.compile(
    r"`[^`]*(?:python|pytest|node |curl |SELECT |sqlite3|tools/|\.py|\.ps1|git )[^`]*`")


# RC-470: _five_why_lock_violations (the recursive five-why grammar validator) is
# retired with its check - governance/retired_checks.md. The surviving ledger
# substance lives in _rc_row_violations (why-chain depth + CLOSED evidence) below.


def check_root_cause_log() -> list[Violation]:
    """Every defect gets five whys, and finding a cause RESTARTS the count.

    OBSERVED: RC-14 was closed on code shape with a shallow chain and the underlying bug
    survived into RC-15 and RC-16 -- three rows for one defect. VALIDATED by prototype
    against the log: the depth rule flagged RC-6 (4 levels) and RC-7 (2 levels), both
    genuinely half-traced, and no complete chain was falsely flagged.

    Operator law 2026-07-19: a cause found at why-2 is not the root -- it is a new defect
    that gets its own five whys. An entry stays OPEN until the chain terminates with no new
    defect AND the fix is verified. An OPEN entry past its due date is an enforced
    violation. Since RC-406 it binds at merge via the CI delta gate, which blocks only
    violations NEW relative to origin/main -- rows that age into overdue on both sides
    pass, and a re-date clears the violation; the REDATE_LOCK in
    tools/operating_process_lock.py is what forces every re-date to carry its reason
    and lineage in the row.

    See governance/root_cause_log.md for the rules and the row format.

    SIMPLICITY REHAB T2-2 (2026-08-24, governance/retired_checks.md): this is now the ONE
    enforced validator for the root-cause ledger. The nine other ledger checks run inside it
    via _root_cause_ledger_folded_violations — same file, one validator, no predicate
    weakened; their public check_* wrappers stay importable for the negative controls.
    """
    out: list[Violation] = []
    log_path = REPO / "governance" / "root_cause_log.md"
    if not log_path.exists():
        out.append(Violation(log_path, 0, "governance/root_cause_log.md is missing - every "
                                          "defect must be traced to a root cause there"))
        out.extend(_root_cause_ledger_folded_violations())
        return out
    today = datetime.date.today()
    for n, line in enumerate(log_path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.startswith("| RC-"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 5:
            continue
        rc_id, status, _opened, due = cells[0], cells[1], cells[2], cells[3]
        if status == "ARCHIVED":
            continue                      # settled history; substance lives at the git pointer

        out.extend(_rc_row_violations(log_path, n, rc_id, status, cells))
        # RC-503: BLOCKED is unfinished work, so it carries a due date and goes overdue exactly
        # like OPEN. Excluding it would have made "blocked" a way to stop the clock, which is
        # the deferral this ledger's whole due-date discipline exists to prevent.
        if status not in ("OPEN", "BLOCKED"):
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
    out.extend(_root_cause_ledger_folded_violations())
    return out


def _root_cause_ledger_folded_violations() -> list[Violation]:
    """SIMPLICITY REHAB T2-2 (2026-08-24, governance/retired_checks.md): the nine other
    root-cause-ledger validators run INSIDE check_root_cause_log — one enforced check for
    the whole ledger, every predicate intact. Each retired registration's substance lives
    in the private helper named here; the public check_<name> wrappers stay importable so
    the negative controls keep driving the real logic. The forward-only grandfather is
    applied under each ORIGINAL name (RC-227 cutoff, _GRANDFATHERED_ROW_CHECKS unchanged),
    so consolidation moves no violation on or off the surface."""
    out: list[Violation] = []
    for folded_name, helper in (
        ("rc_citations_resolve", _rc_citations_resolve_violations),
        ("rc_status_vocabulary", _rc_status_vocabulary_violations),
        ("rc_log_rows_keep_schema", _rc_log_rows_keep_schema_violations),
        ("rc_numeric_claims_cite_a_command", _rc_numeric_claims_cite_a_command_violations),
        # BEDROCK 2026-09-06: rc_mechanism_claims_cite_a_source is no longer folded. It
        # matched English verbs ("pins price", "repels") in ledger prose — a control that
        # decides a real question by matching free text is not enforcement (AGENTS.md).
        # The law (cite a market mechanism or mark it unproven) stands; review judges it.
        ("closed_rows_ship_their_code", _closed_rows_ship_their_code_violations),
        ("adversarial_audits_are_answered", _adversarial_audits_are_answered_violations),
    ):
        out.extend(_apply_forward_only_grandfather(folded_name, helper()))
    return out


def check_rc_citations_resolve() -> list[Violation]:
    """Wrapper kept importable for the negative controls; the substance runs inside
    check_root_cause_log (retired registration, governance/retired_checks.md)."""
    return _rc_citations_resolve_violations()


def check_rc_status_vocabulary() -> list[Violation]:
    """Wrapper kept importable for the negative controls; the substance runs inside
    check_root_cause_log (retired registration, governance/retired_checks.md)."""
    return _rc_status_vocabulary_violations()


def check_rc_log_rows_keep_schema() -> list[Violation]:
    """Wrapper kept importable for the negative controls; the substance runs inside
    check_root_cause_log (retired registration, governance/retired_checks.md)."""
    return _rc_log_rows_keep_schema_violations()


def check_rc_numeric_claims_cite_a_command() -> list[Violation]:
    """Wrapper kept importable for the negative controls; the substance runs inside
    check_root_cause_log (retired registration, governance/retired_checks.md)."""
    return _rc_numeric_claims_cite_a_command_violations()


def check_closed_rows_ship_their_code() -> list[Violation]:
    """Wrapper kept importable for the negative controls; the substance runs inside
    check_root_cause_log (retired registration, governance/retired_checks.md)."""
    return _closed_rows_ship_their_code_violations()


def check_adversarial_audits_are_answered() -> list[Violation]:
    """Wrapper kept importable for the negative controls; the substance runs inside
    check_root_cause_log (retired registration, governance/retired_checks.md)."""
    return _adversarial_audits_are_answered_violations()


# check_no_governance_duplication RETIRED (SIMPLICITY REHAB 2026-08-24,
# governance/retired_checks.md): a >12-shared-6-letter-words heuristic between two
# markdown ledgers whose 60-term stoplist documented two false positives and zero true
# catches. Ledger shape stays enforced by rc_log_rows_keep_schema; the epistemic
# ledger by unproven_register.


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
    ("config/ML_ITEM4_MIGRATION_POLICY.json", "active_bundle_contract.py"),
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


# check_checks_are_justified RETIRED (SIMPLICITY REHAB 2026-08-24,
# governance/retired_checks.md): docstring-shape policing of this gate file against
# itself with a frozen grandfather set — prose regulation, no product defect class.
# A misbehaving NEW check is blocked by the delta gate regardless of its docstring;
# PR review reads docstrings.


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


# ── TEST_SYSTEM_REHAB_V2 recurrence locks (2026-08-31) ───────────────────────────
# Two objective recurrence classes PROVEN this rehab (an exact-duplicate test family,
# and dozens of independent whole-repo scans duplicating the shared repo_index
# observation) must not silently return. Both cores are pure functions over a `root`
# directory so tests/test_rehab_recurrence_locks_v1.py can prove BLOCK/PASS against a
# synthetic tmp_path tree, never the real repository — the real-tree wrappers below
# just point that same logic at TESTS.

_DUPLICATE_TEST_JUSTIFY_MARKER = "institutional-duplicate-ok"
_SCAN_JUSTIFY_MARKER = "institutional-scan-ok"


def _module_level_import_bindings(tree: ast.Module) -> dict[str, str]:
    """{local_name: resolved_module_path} for every TOP-LEVEL `import X [as Y]` /
    `from X import Y [as Z]` in a file — used to tell apart two test functions whose
    BODY text is identical but that reference differently-imported names (e.g. both
    call `runner.run_study(...)`, where `runner` is bound to a different module in
    each file). Only module-level bindings are resolved; a name imported inside the
    function itself is already visible to the plain AST-dump hash."""
    out: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                out[alias.asname or alias.name.split(".")[0]] = alias.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                out[alias.asname or alias.name] = f"{node.module}.{alias.name}"
    return out


def _normalized_test_body_hash(node: ast.FunctionDef, import_bindings: dict[str, str]) -> str:
    """AST dump of a test function's body with its own name stripped, so two
    byte-identical bodies under different names still hash equal — but two bodies
    that read/construct anything differently (a different Name, Attribute, or
    Constant node anywhere) hash DIFFERENT, so a same-shaped test against a
    genuinely different production module is never flagged.

    TEST_SYSTEM_REHAB_V2: also resolves every module-level-imported name the
    function body actually references (e.g. `runner` bound to a different module
    per file) and folds the sorted resolved-module list into the hash — two
    identically-shaped test bodies calling into genuinely different production
    modules now hash DIFFERENT on that basis alone, with no exemption marker
    needed. A marker remains for cases resolution cannot structurally distinguish
    (e.g. a truly interchangeable literal/config difference)."""
    dumped = ast.dump(node, annotate_fields=True, include_attributes=False)
    normalized = dumped.replace(f"name='{node.name}'", "name='X'", 1)
    referenced_modules = sorted({
        import_bindings[n.id]
        for n in ast.walk(node)
        if isinstance(n, ast.Name) and n.id in import_bindings
    })
    return hashlib.sha256(
        (normalized + "|" + ",".join(referenced_modules)).encode()
    ).hexdigest()


def _find_duplicate_test_groups(root: Path) -> list[list[tuple[Path, int, str]]]:
    """Groups of 2+ top-level test functions (anywhere under `root`, excluding
    archive/) whose bodies are byte-identical once each function's own name is
    normalized away. A function whose span contains the exemption marker is
    excluded from grouping entirely (never silently paired with anything)."""
    groups: dict[str, list[tuple[Path, int, str]]] = {}
    for p in sorted(root.rglob("test_*.py")):
        if "archive" in p.relative_to(root).parts:
            continue
        src = _read_or_empty(p)
        if not src:
            continue
        try:
            tree = ast.parse(src, filename=str(p))
        except SyntaxError:
            continue
        import_bindings = _module_level_import_bindings(tree)
        lines = src.splitlines()
        for node in ast.walk(tree):
            if not (isinstance(node, ast.FunctionDef) and node.name.startswith("test_")):
                continue
            lo, hi = node.lineno, getattr(node, "end_lineno", node.lineno)
            seg = "\n".join(lines[lo - 1: hi])
            if _DUPLICATE_TEST_JUSTIFY_MARKER in seg:
                continue
            h = _normalized_test_body_hash(node, import_bindings)
            groups.setdefault(h, []).append((p, node.lineno, node.name))
    return [members for members in groups.values() if len(members) > 1]


def check_no_duplicate_tests() -> list[Violation]:
    """Fail if two test functions have a byte-identical body (own name aside) —
    TEST_SYSTEM_REHAB_V2's exact-duplicate-test recurrence lock."""
    out: list[Violation] = []
    for members in _find_duplicate_test_groups(TESTS):
        names = ", ".join(f"{p.relative_to(REPO)}:{ln}::{n}" for p, ln, n in members)
        p0, ln0, _n0 = members[0]
        out.append(Violation(
            p0, ln0,
            f"duplicate test body (byte-identical once the function's own name is "
            f"normalized away) across: {names}. If these exercise genuinely "
            f"different production modules, add '# institutional-duplicate-ok: "
            f"<reason>' inside the function; otherwise delete the redundant copy "
            f"and keep the canonical one.",
        ))
    return out


def _string_const(node: ast.AST) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _is_py_source_scan_call(node: ast.Call) -> bool:
    """True for a `.rglob(...)`/`.glob(...)` call whose PATTERN targets .py source
    files -- the only shape that is actually redundant with `repo_index` (which only
    indexes .py files). A `tmp_path.rglob("*.json")` cleanup-verification scan, or any
    glob for a non-.py artifact type, can never be satisfied by the shared corpus
    regardless of its receiver, so it is not flagged at all -- not exempted, genuinely
    a different observation. `os.walk(...)` takes no pattern and is always flagged
    (rare in this codebase; the marker covers a real non-.py need)."""
    if not isinstance(node.func, ast.Attribute):
        return False
    if node.func.attr not in ("rglob", "glob"):
        return False
    if not node.args:
        return False
    pattern = _string_const(node.args[0])
    return pattern is not None and ".py" in pattern


def _is_os_walk_call(node: ast.Call) -> bool:
    fn = node.func
    if isinstance(fn, ast.Attribute) and fn.attr == "walk":
        return isinstance(fn.value, ast.Name) and fn.value.id == "os"
    return isinstance(fn, ast.Name) and fn.id == "walk"  # `from os import walk`


def _is_git_ls_files_call(node: ast.Call) -> bool:
    """`subprocess.run/check_output/check_call(["git", "ls-files", ...], ...)` --
    TEST_SYSTEM_REHAB_V2 final remediation: the independent audit found ~9-10 test
    files bypassing the redundant-scan lock this way, structurally invisible to
    `_is_py_source_scan_call`/`_is_os_walk_call` (a `subprocess.run` call, not a
    `.rglob`/`.glob`/`os.walk` call). Matched on the command list alone; whether it's
    actually redundant with `repo_index` depends on what happens to the result
    afterward -- see `_reads_py_source_in_function`."""
    fn = node.func
    if not (isinstance(fn, ast.Attribute) and fn.attr in ("run", "check_output", "check_call")
            and isinstance(fn.value, ast.Name) and fn.value.id == "subprocess"):
        return False
    first = node.args[0] if node.args else next(
        (kw.value for kw in node.keywords if kw.arg == "args"), None)
    if not isinstance(first, (ast.List, ast.Tuple)):
        return False
    strs = [e.value for e in first.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
    return "git" in strs and "ls-files" in strs


def _reads_py_source(fn_node: ast.AST) -> bool:
    """True if `fn_node`'s body reads file CONTENT (`.read_text(`, `.read_bytes(`,
    bare `open(`, `inspect.getsource(`) anywhere. A bare `git ls-files` that only
    inspects FILENAMES (e.g. classifying paths, checking a module is inventoried)
    never re-reads the corpus `repo_index` already holds and is a genuinely cheaper,
    different observation -- not flagged. `git ls-files` + a subsequent per-file
    read is the exact shape `.rglob`+`.read_text()` already is."""
    for n in ast.walk(fn_node):
        if not isinstance(n, ast.Call):
            continue
        f = n.func
        if isinstance(f, ast.Attribute) and f.attr in ("read_text", "read_bytes", "getsource"):
            return True
        if isinstance(f, ast.Name) and f.id == "open":
            return True
    return False


def _reads_py_source_in_function(fn_node: ast.FunctionDef | ast.AsyncFunctionDef,
                                  module: ast.Module) -> bool:
    """`_reads_py_source(fn_node)`, widened one hop: the common shape in this repo is a
    small helper (`_tracked_py_under`, `_iter_repo_py_files`, ...) whose ONLY job is
    the `git ls-files` call, with the actual per-file read happening in whichever
    function CALLS that helper by name -- still one observation, just split across
    two functions for readability. A single-hop caller check catches that split
    without a general cross-function dataflow analysis."""
    if _reads_py_source(fn_node):
        return True
    name = getattr(fn_node, "name", None)
    if not name:
        return False
    for candidate in ast.walk(module):
        if not isinstance(candidate, (ast.FunctionDef, ast.AsyncFunctionDef)) or candidate is fn_node:
            continue
        calls_helper = any(
            isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == name
            for n in ast.walk(candidate))
        if calls_helper and _reads_py_source(candidate):
            return True
    return False


def _find_py_source_scan_sites(root: Path, *, name_glob: str,
                                exclude_dir_parts: frozenset[str] = frozenset()) -> list[tuple[Path, int]]:
    """THE ONE AST walk for .py-source repo scans (`.rglob`/`.glob` targeting *.py,
    `os.walk`, or `git ls-files` followed by a per-file content read) under `root`,
    restricted to files matching `name_glob`. TEST_SYSTEM_REHAB_V2 (2026-08-31) first
    unified this with tests/test_gate_scope_is_the_git_index_v1.py's older, independent
    census walk (which only matched `.rglob(`), then (final remediation pass) extended
    it again to catch the `subprocess.run(["git","ls-files",...])` + read/parse shape
    an independent audit found bypassing the lock entirely -- a materially equivalent
    full-tree observation the original detector's call-shape matching couldn't see.
    Detection and the exemption marker are BOTH scoped to the ENCLOSING FUNCTION, not
    the whole file: a file (or even one function) may legitimately consume
    `repo_index` for one purpose and still be caught building a second, independent
    .py-source scan alongside it -- a file-wide "repo_index appears somewhere" bypass
    would hide exactly that."""
    out: list[tuple[Path, int]] = []
    for p in sorted(root.rglob(name_glob)):
        if exclude_dir_parts & set(p.relative_to(root).parts):
            continue
        src = _read_or_empty(p)
        if not src:
            continue
        try:
            tree = ast.parse(src, filename=str(p))
        except SyntaxError:
            continue
        lines = src.splitlines()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            # TEST_SYSTEM_REHAB_V2 final remediation (perf root-fix): `_enclosing_func_span`
            # is a FULL ast.walk(tree) by itself -- calling it for every Call node in the
            # file (there can be hundreds) turned this per-file pass into O(nodes^2) and
            # made the real-tree lock test pathologically slow (180s+ for one test, over
            # ~150 tests/*.py files). It must only run once a node is ALREADY a candidate
            # (a confirmed rglob/glob/os.walk scan, or a git-ls-files call that needs its
            # enclosing function inspected) -- exactly the original, fast shape.
            is_scan = _is_py_source_scan_call(node) or _is_os_walk_call(node)
            is_git_ls_candidate = (not is_scan) and _is_git_ls_files_call(node)
            if not (is_scan or is_git_ls_candidate):
                continue
            line = getattr(node, "lineno", 0)
            span = _enclosing_func_span(tree, line)
            if is_git_ls_candidate and span is not None:
                for fn_node in ast.walk(tree):
                    if (isinstance(fn_node, (ast.FunctionDef, ast.AsyncFunctionDef))
                            and (fn_node.lineno, getattr(fn_node, "end_lineno", fn_node.lineno)) == span):
                        is_scan = _reads_py_source_in_function(fn_node, tree)
                        break
            if not is_scan:
                continue
            seg = "\n".join(lines[span[0] - 1: span[1]]) if span else lines[max(0, line - 1)]
            if _SCAN_JUSTIFY_MARKER in seg:
                continue
            out.append((p, line))
    return out


def _find_new_repo_scans(root: Path) -> list[tuple[Path, int]]:
    """Test files under `root` (excluding archive/) that build their own .py-source
    repo-wide observation instead of consuming the shared `repo_index` fixture --
    the ENFORCEMENT-scoped view of `_find_py_source_scan_sites` (test_*.py only)."""
    return _find_py_source_scan_sites(root, name_glob="test_*.py", exclude_dir_parts=frozenset({"archive"}))


def check_no_new_independent_repo_scan_in_tests() -> list[Violation]:
    """Fail if a NEW test performs its own repo-wide .py-source scan
    (`.rglob`/`.glob` targeting *.py, or `os.walk`) instead of consuming the shared
    `repo_index` fixture (tests/conftest.py) — TEST_SYSTEM_REHAB_V2's duplicate-repo-
    observation recurrence lock. A genuinely specialized scan (a scope the shared
    corpus cannot supply) is exempted with '# institutional-scan-ok: <reason>' inside
    the SAME function — the marker does not cover the rest of the file. A scan for a
    non-.py artifact type (temp-dir cleanup checks, model-artifact directories, etc.)
    is a different observation entirely and is never flagged, not merely exempted."""
    return [
        Violation(
            p, line,
            "new independent repo-wide .py-source scan (.rglob/.glob/os.walk) in a "
            "test that does not consume the shared `repo_index` fixture "
            "(tests/conftest.py) for THIS observation — share the existing "
            "current-tree observation, or justify a genuinely specialized scan with "
            "'# institutional-scan-ok: <reason>' inside the same function.",
        )
        for p, line in _find_new_repo_scans(TESTS)
    ]


def _is_constant_true_or_assertion(node: ast.Assert) -> bool:
    """TEST_SYSTEM_REHAB_V2 final remediation: narrow, mechanical detection ONLY --
    `assert X or True` / `assert True or X` (a boolean `or` with a literal `True`
    disjunct anywhere in it) is vacuously true regardless of X, definitionally, no
    theorem-proving required. Four real instances of exactly this literal shape were
    found and fixed by the Cursor audit (test_chain_accrual_and_storm1_v1.py,
    test_phase2a_and_producer_probes_v1.py, test_silent_zero_reasons_are_true_v1.py,
    test_charm_vote_gate.py) -- this locks that class so it cannot silently
    reappear. Deliberately does NOT attempt to catch the broader, context-dependent
    `assert X or Y` weakness (Y a real but contextually-always-true expression given
    prior lines) -- that requires human judgment per instance, not a general
    Boolean-expression prover, and was fixed individually instead."""
    test = node.test
    return (isinstance(test, ast.BoolOp) and isinstance(test.op, ast.Or)
            and any(isinstance(v, ast.Constant) and v.value is True for v in test.values))


def _find_constant_true_or_assertions(root: Path) -> list[tuple[Path, int]]:
    """AST walk for `assert <expr> or True` / `assert True or <expr>` under `root`,
    restricted to test_*.py (the same scope `_find_new_repo_scans` uses)."""
    out: list[tuple[Path, int]] = []
    for p in sorted(root.rglob("test_*.py")):
        if "archive" in p.relative_to(root).parts:
            continue
        src = _read_or_empty(p)
        if not src:
            continue
        try:
            tree = ast.parse(src, filename=str(p))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Assert) and _is_constant_true_or_assertion(node):
                out.append((p, node.lineno))
    return out


def check_no_constant_true_or_assertions() -> list[Violation]:
    """Fail if a NEW `assert X or True` / `assert True or X` appears -- a boolean OR
    with a literal True disjunct can never fail, so the assertion provides zero
    coverage regardless of what X evaluates to. TEST_SYSTEM_REHAB_V2's third
    recurrence lock, narrowly scoped to this one mechanically-obvious shape (see
    `_is_constant_true_or_assertion`)."""
    return [
        Violation(
            p, line,
            "assert <expr> or True (or True or <expr>) is vacuously true regardless "
            "of <expr> -- this assertion can never fail and provides zero coverage. "
            "Assert the real condition, or delete the line if nothing is actually "
            "being checked.",
        )
        for p, line in _find_constant_true_or_assertions(TESTS)
    ]


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


MAX_FILE_LINES = 800       # a file above this is doing too much — split into focused modules
MAX_FUNC_LINES = 80        # a function above this is hard to read/fix — split it
_LENGTH_MARKER = "institutional-length-ok"


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


def check_single_stream_authority() -> list[Violation]:
    """SINGLE-STREAM-AUTHORITY (2026-08-30) — exactly one production Schwab StreamClient
    constructor, repo-wide. order_flow_streaming.py used to open a second, independent
    session at server startup, racing the canonical capture daemon on the same account.
    Root-fixed: that module now reads the daemon's capture DB read-only and opens no
    Schwab session. This gate is the mutation-tested proof it stays that way — a future
    change that reintroduces a second constructor (or renames/duplicates the daemon
    itself) fails here, not merely in a design review.
    """
    out: list[Violation] = []
    try:
        sys.path.insert(0, str(REPO / "tools"))
        from check_single_stream_authority import violations as _v
        for msg in _v():
            out.append(Violation(REPO / "tools" / "run_stream_capture.py", 0, msg))
    except Exception as exc:                                        # noqa: BLE001
        out.append(Violation(REPO / "tools" / "check_single_stream_authority.py", 0,
                             f"checker unavailable ({type(exc).__name__}: {exc}) — a gate "
                             f"that cannot run is not a gate"))
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


_UNPROVEN_REGISTER = REPO / "governance" / "unproven_register.md"


_OPEN_STATUSES = {"UNPROVEN", "DISPROVED"}
_TERMINAL_STATUSES = {"PROVEN", "REMEDIATED"}


def _unproven_register_violations() -> list[Violation]:
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


def _rc_numeric_claims_cite_a_command_violations() -> list[Violation]:
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
        if rc_id in _RC_CITATION_GRANDFATHERED or cells[1] == "ARCHIVED":
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


def _closed_rows_ship_their_code_violations() -> list[Violation]:
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
    that work remains the audit's job.

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


# RC-470: check_recursive_five_why_front_loaded retired (governance/retired_checks.md).
# It required a co-staged RC row for EVERY staged .py change, which turned ordinary
# feature work into ledger essays (measured: 430 rows / 1.4MB / 124 OPEN at census).
# Defect rows and their quality stay enforced by root_cause_log; closures stay bound
# to real code by closed_rows_ship_their_code.


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


def _rc_citations_resolve_violations() -> list[Violation]:
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


def _adversarial_audits_are_answered_violations() -> list[Violation]:
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
#: BLOCKED joined the vocabulary for RC-503. "This mission is objectively blocked" was
#: previously asserted by a `BLOCKED_ON_*` substring inside the free-text fix cell, and
#: tools/mission_latch.py read that substring to decide both turn-end legality AND production
#: authority — prose deciding enforcement, which is the one thing this repository's controls
#: are not allowed to do. Making it a STATUS puts the claim in a machine-parsed column that
#: this very check polices, so an unrecognised or misspelled token fails loudly instead of
#: silently granting or denying authority. It is NOT in CLOSED_CLASS: a blocked defect is
#: unfinished work, so the close contract must not treat it as dealt with.
#: RC-520: ARCHIVED is a CLOSED row compacted to one line — id, dates, headline and a git
#: pointer to the blob that carries its full five-why chain and evidence. It asserts nothing
#: new (the close contract was satisfied when the row closed and is verifiable at the
#: pointer), so the row-substance validators skip it; the id still resolves for citations
#: and the row still keeps the seven-cell schema. `tools/mission_latch.py --archive-closed-before`
#: is the ONE writer of that form.
DECLARED_RC_STATUSES: frozenset[str] = frozenset({"OPEN", "CLOSED", "REMEDIATED", "BLOCKED", "ARCHIVED"})

#: Statuses that assert the defect is dealt with, and therefore must satisfy
#: the full close contract. Six independent clauses key on this classification.
CLOSED_CLASS_RC_STATUSES: frozenset[str] = frozenset({"CLOSED"})


def _rc_status_vocabulary_violations() -> list[Violation]:
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


def _rc_log_rows_keep_schema_violations() -> list[Violation]:
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


def _measured_claims_cite_evidence_own_violations() -> list[Violation]:
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


def check_measured_claims_cite_evidence() -> list[Violation]:
    """The evidence gate, consolidated (SIMPLICITY REHAB T2-3, 2026-08-24).

    One enforced check now runs every surviving evidence predicate:
      * the staged-governance-claims rule above (_measured_claims_cite_evidence_own_violations,
        RC-56 — a committed numeric finding carries its reproduce command or [UNVERIFIED]);
      * the unproven-register rule (_unproven_register_violations — claims are evidenced or
        registered, overdue rows block, missing register fails closed).

    The folded registration is declared retired in governance/retired_checks.md; its public
    check_* wrapper stays importable so the negative controls keep driving the real logic, and
    NO predicate was weakened. The forward-only grandfather is applied under the ORIGINAL name
    so consolidation moves no violation on or off the surface. (The verdict-power rule that was
    folded here too — a prose matcher — was unfolded and DELETED, bedrock 2026-09-06.)
    """
    out = _measured_claims_cite_evidence_own_violations()
    # BEDROCK 2026-09-06: verdicts_declare_their_power is no longer folded. It matched
    # verdict words (KILL / RETIRED / PROVEN) in ledger prose and demanded n= and CI
    # tokens beside them — free-text matching, which AGENTS.md rules out as enforcement.
    # The substance (a numeric finding cites its reproduce command) is the own-violations
    # rule above; statistical power is judged in review, as the Framework doc requires.
    for folded_name, helper in (
        ("unproven_register", _unproven_register_violations),
    ):
        out.extend(_apply_forward_only_grandfather(folded_name, helper()))
    return out


def check_unproven_register() -> list[Violation]:
    """Wrapper kept importable for the negative controls; the substance runs inside
    check_measured_claims_cite_evidence (retired registration, governance/retired_checks.md)."""
    return _unproven_register_violations()


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
        spy_only_ticker_default_violations,
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

    # BEDROCK 2026-09-06: rule 3 (SPY-only PHRASES in staged prompt prose) is retired. It was
    # a free-text matcher, and AGENTS.md rules that out as enforcement. Rules 1 and 2 are the
    # structural half — SPY-only ticker DEFAULTS in experiment tools and SPY-gated Chart
    # features — and they stay, because they read code, not wording. The law itself
    # (UNIVERSAL ticker scope) is unchanged in AGENTS.md.
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


#: RC-205 production-surface geometry no longer MIRRORS tools/pretooluse_guard.py — FC-13
#: replaced the mirror with the thing itself. `classify_path` is the single authority for
#: "is this path ours, and is it a product surface"; a mirrored copy is a second producer
#: that drifts, which is what this consolidation exists to remove.


# RC-470: the plus_player catalog checks (plus_player_law, plus_player_cursor_hooks)
# and their callees are retired - governance/retired_checks.md. Roster demotions are
# caught by the delta-gate roster comparison + declared-retirement manifest; hook-wiring
# changes are reviewed by the operator at merge (RC-475 — the CODEOWNERS equivalence the
# retirement rows cited was superseded when the authority model was torn down).


def check_admission_evidence_resolves() -> list[Violation]:
    """ADMITTED decision-path rows: evidence paths must resolve (SR 11-7 / RSK-02).

    WHAT WAS OBSERVED: empty registry already forces WAIT at runtime, but a future ADMITTED row
    with vibe-string evidence refs would pass schema while citing nothing real — SR 11-7 validation
    substance gap.

    Rule: when config/decision_path_admissions.json lists ADMITTED entries, every evidence
    field that is a repo path must resolve to an existing file (http URLs exempt). Empty list -> [].

    HOW VALIDATED: tests/test_find_prove_locks_v1.py drives admission_evidence_resolves_violations.
    """
    try:
        from tools.find_prove_locks import admission_evidence_resolves_violations
    except ImportError:
        from find_prove_locks import admission_evidence_resolves_violations  # type: ignore
    p = REPO / "config" / "decision_path_admissions.json"
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


# claude_cursor_guard_parity RETIRED (declared governance/retired_checks.md 2026-08-24;
# executed in the SIMPLICITY REHAB): hook parity is an operator merge-review property
# (RC-475 superseded the CODEOWNERS equivalence the row cited). The
# declared-but-still-enforced state this replaces was itself the manifest lying — the
# defect class RC-468's seam exists to catch.


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


# RC-470: check_honesty_guard_wired retired (governance/retired_checks.md) - an
# unwiring of the hook files is reviewed by the operator at merge (RC-475 superseded
# the CODEOWNERS equivalence the row cited). The honesty guard itself stays on Stop.


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
        # Clause A binds PRODUCERS. A test module cannot serve a route; the literal it
        # carries is the negative-control fixture that proves this clause fires (measured
        # 2026-09-06: moving that control between test files read as a "new producer").
        route_sites = re.finditer(r'@app\.(?:get|post)\(\s*"(/api/[^"]+)"', added) \
            if not rel.replace("\\", "/").startswith("tests/") else iter(())
        for m in route_sites:
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


# RC-470: check_log_law retired (governance/retired_checks.md); tools/log_law.py is
# deleted with it. Ledger topology stays covered by no_governance_duplication,
# rc_log_rows_keep_schema and unproven_register.


# RC-470: check_writer_no_drift retired (governance/retired_checks.md). Measured before
# retiring: the commit hook never ran this check (RC-406); CI deliberately set no role
# (RC-396); it fired only in local verification shells. 2026-08-24 teardown: the whole
# writer/role machinery (writer_drift_lock, CODEOWNERS, ED_AGENT_ROLE) was then removed
# with Architecture A — authority changes are approved by the operator's word in chat
# (RC-475), with required CI as the machine gate at merge.


# RC-470: check_rc_document_without_resolve retired (governance/retired_checks.md) -
# backlog growth stays enforced by open_item_cap and stop_guard's RC-72 turn block.


#: RC-520 — surfaces that were retired because their responsibility has ONE owner now.
#: MEASURED 2026-09-05 on 466378c6: each of these either restated another file's
#: authority (MEMORY.md called itself an Active Rule Source; four .cursor rules restated
#: AGENTS.md law), carried a queue/ledger nobody executed (the operator-trust ledger and its
#: JSON gate had zero executable readers), or regenerated classification headers from a
#: 2026-05 model (the consolidation builders). Resurrecting one re-creates the split the
#: mission removed, so presence alone is the violation — what the file says is irrelevant.
_RC520_RETIRED_SURFACES: tuple[tuple[str, str], ...] = (
    ("MEMORY.md", "host facts live in docs/host/README.md; law in AGENTS.md"),
    ("docs/OPEN_ITEMS_OPERATOR_TRUST.md", "acceptance lives in OPEN_ITEMS.md; defects in governance/root_cause_log.md"),
    ("governance/OPERATOR_TRUST_STABILIZATION_GATE.json", "no executable reader; the required CI checks are the gate"),
    ("docs/governance/AGENT_SELF_GOVERNANCE.md", "agent procedure lives in governance/AGENT_OPERATING_PROCESS_V1.md"),
    ("docs/plans/GOVERNANCE_CONSOLIDATION_EXECUTION_PLAN.md", "a finished 2026-05 plan; history is git"),
    ("governance/consolidation", "generated classification artifacts; nothing consumes them"),
    ("tools/build_phase0_rule_classification.py", "classification headers are not regenerated from a retired model"),
    ("tools/build_phase2_md_classification.py", "classification headers are not regenerated from a retired model"),
    ("tools/build_phase0_do_not_rename.py", "consolidation builder with no consumer"),
    ("tools/build_phase3_repo_cleanup.py", "consolidation builder with no consumer"),
    ("tools/import_memory_archive_phase1c.py", "one-shot memory import; the archive is already in git"),
    ("reports/tqm_rehab_agent_brief.md", "procedure lives in governance/REHAB_PROGRAM.md; reports/ holds measurements"),
)

#: The ONE Cursor adapter. Every other `.cursor/rules/*.mdc` was a restatement of AGENTS.md.
_RC520_CURSOR_ADAPTER = "00-always.mdc"

#: Headings that turned OPEN_ITEMS.md into a law + queue + history mixture (RC-520 census).
_RC520_OPEN_ITEMS_FOREIGN_HEADINGS = ("GOVERNING LAW", "RECONCILIATION HISTORY", "LEDGER DENOMINATOR")
_RC520_OPEN_SECTION = "## Open acceptance items"

#: Headings that made ACTIVE_PROGRAM.md a second standing-truth surface.
_RC520_ACTIVE_PROGRAM_FOREIGN_HEADINGS = ("KNOWN RISKS", "STANDING RUNTIME LAW", "FEATURE PLACEMENT MATRIX")


def check_authority_surfaces_have_one_owner(root: Path | None = None) -> list[Violation]:
    """RC-520 — one semantic responsibility has one canonical file, and stays that way.

    WHAT WAS OBSERVED (2026-09-05, 466378c6). ACTIVE_PROGRAM.md called OPEN_ITEMS.md the
    ledger while OPEN_ITEMS.md named governance/root_cause_log.md the single work ledger;
    OPEN_ITEMS.md (101 KB) mixed acceptance verdicts with a restated GOVERNING LAW, a Now
    list, queues, defects duplicated from the closure schema, an open-RC denominator and a
    reconciliation history; MEMORY.md called itself an Active Rule Source; four .cursor rule
    files restated AGENTS.md; the consolidation builders could regenerate 2026-05
    classification headers over the whole tree. Every one of those was created by ADDING a
    surface beside the last, and nothing refused the addition.

    THE RULE, judged on presence and structure rather than on prose: the retired surfaces
    stay deleted; `.cursor/rules/` holds exactly the one adapter; OPEN_ITEMS.md carries no
    root-cause row, no closed checkbox in its open-items section and none of the foreign
    headings; ACTIVE_PROGRAM.md carries no DONE row and no standing-law section. Each of
    those is a shape a resurrected duplicate must take, so each is a mutation this refuses.
    The acceptance board's own checked criteria are legitimate specification state and are
    not touched.
    """
    root = root or REPO
    out: list[Violation] = []
    for rel, owner in _RC520_RETIRED_SURFACES:
        p = root / rel
        if p.exists():
            out.append(Violation(p, 0, f"`{rel}` was retired by RC-520 ({owner}). Presence is the "
                                       f"defect: a second surface for an owned responsibility "
                                       f"re-creates the split authority the mission removed. Put "
                                       f"the content with its owner and delete this."))
    rules = root / ".cursor" / "rules"
    if rules.is_dir():
        for f in sorted(rules.iterdir()):
            if f.name != _RC520_CURSOR_ADAPTER:
                out.append(Violation(f, 0, f"`.cursor/rules/{f.name}` is a second Cursor rule surface; "
                                           f"the one adapter is `{_RC520_CURSOR_ADAPTER}` and it points "
                                           f"at AGENTS.md. Law lives in AGENTS.md, not in a vendor file."))
    oi = root / "OPEN_ITEMS.md"
    if oi.is_file():
        in_open = False
        for n, line in enumerate(oi.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if line.startswith("## ") or line.startswith("# "):
                in_open = line.startswith(_RC520_OPEN_SECTION)
                if any(h in line.upper() for h in _RC520_OPEN_ITEMS_FOREIGN_HEADINGS):
                    out.append(Violation(oi, n, f"OPEN_ITEMS.md is the acceptance specification only; "
                                                f"the section {line.strip()!r} is law, a ledger "
                                                f"snapshot or history, each of which has another owner."))
            if line.startswith("| RC-"):
                out.append(Violation(oi, n, "a root-cause row in OPEN_ITEMS.md: defects have ONE home, "
                                            "governance/root_cause_log.md. Cite the row; do not copy it."))
            if in_open and line.startswith("- [x] "):
                out.append(Violation(oi, n, "a closed row in the open-acceptance-items section: closed "
                                            "rows are history (git), not specification. Delete it."))
    ap = root / "ACTIVE_PROGRAM.md"
    if ap.is_file():
        for n, line in enumerate(ap.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if line.startswith("| ") and "| DONE |" in line:
                out.append(Violation(ap, n, "a DONE row in ACTIVE_PROGRAM.md: it records CURRENT work; "
                                            "finished work leaves the file and git keeps it."))
            if line.startswith("#") and any(h in line.upper() for h in _RC520_ACTIVE_PROGRAM_FOREIGN_HEADINGS):
                out.append(Violation(ap, n, f"the section {line.strip()!r} is standing truth, not "
                                            f"current work; runtime rules live with their runbook "
                                            f"(TRAINING_AND_MAINTENANCE.md) and risks with their owner."))
    return out


def check_test_hygiene() -> list[Violation]:
    """ONE registered test-hygiene lint (bedrock PR B, 2026-09-06; declared step 1 in
    governance/retired_checks.md).

    Eight structure lints over tests/ — no synthetic domain fixtures, no swallowed failures,
    no duplicate bodies, no independent repo scans, no constant-true assertions, no
    tautological assertions, no test without an assert, claims are executed — shared one
    responsibility (a test that cannot fail, or fails for the wrong reason) under eight
    roster names. Every predicate runs here unchanged and keeps its own docstring and
    negative controls; the roster carries one name for one responsibility.
    """
    out: list[Violation] = []
    for predicate in (
        check_no_synthetic_domain_fixtures_in_tests,
        check_no_swallowed_test_failures,
        check_no_duplicate_tests,
        check_no_new_independent_repo_scan_in_tests,
        check_no_constant_true_or_assertions,
        check_no_tautological_assertions,
        check_tests_missing_explicit_assert,
        check_test_claims_are_executed,
    ):
        out.extend(predicate())
    return out


def check_level_producers_have_consumers() -> list[Violation]:
    """REPORTED: every registered level-domain producer route has a client consumer.

    RC-163's structural half. The retired chart_intent_and_next_rth check matched "Done" and
    "OUT-OF-SCOPE" in residual prose to catch a computed value shipped with no consumer; the
    invariant underneath is measurable without prose: a route registered as a producer in
    governance/level_faucets.json that no static asset fetches is a value nobody sees.
    MEASURED 2026-09-06 on this tree: four registered routes have no static reference, so this
    reports rather than enforces; it binds when the operator wires or retires them.
    """
    reg = REPO / "governance" / "level_faucets.json"
    try:
        producers = json.loads(reg.read_text(encoding="utf-8")).get("level_domain_producers") or {}
    except (OSError, ValueError):
        return [Violation(reg, 0, "governance/level_faucets.json unreadable — the producer register "
                                  "cannot be measured")]
    static_dir = REPO / "static"
    corpus = "".join(
        p.read_text(encoding="utf-8", errors="replace")
        for p in sorted(static_dir.glob("*.html")) + sorted(static_dir.glob("*.js"))
        if p.is_file())
    out: list[Violation] = []
    for route in sorted(producers):
        if not isinstance(route, str) or not route.startswith("/api/"):
            continue
        if route not in corpus:
            out.append(Violation(
                reg, 0,
                f"{route} is a registered level-domain producer with NO client consumer in "
                f"static/ — a computed value nobody sees (RC-163 class). Wire a consumer or "
                f"retire the route; a registered producer is not a delivered one."))
    return out


CHECKS = [
    # RC-520 (2026-09-05): one owner per responsibility, kept by refusing the shapes a
    # resurrected duplicate must take (retired surface present, second .cursor rule, ledger
    # row or closed row or foreign heading in OPEN_ITEMS.md, DONE row or standing-law
    # heading in ACTIVE_PROGRAM.md). ENFORCED at 0 on the tree that removed them.
    ("authority_surfaces_have_one_owner", check_authority_surfaces_have_one_owner, True),
    # ENFORCED (must be zero — block pre-commit):
    # BEDROCK PR B (2026-09-06, step 2 of the two-step contract; declared 2026-09-06 in
    # governance/retired_checks.md): the eight test-hygiene lints — synthetic domain
    # fixtures, swallowed failures, duplicate bodies, independent repo scans, constant-true
    # assertions, tautological assertions, missing asserts, claims-not-executed — are ONE
    # registered check. Every predicate runs unchanged inside check_test_hygiene; each keeps
    # its own history in its docstring. One roster name for one responsibility.
    ("test_hygiene", check_test_hygiene, True),
    # SIMPLICITY REHAB T2-2 (2026-08-24, governance/retired_checks.md): root_cause_log is
    # the ONE enforced ledger validator. The nine other ledger registrations
    # (rc_citations_resolve, rc_status_vocabulary, rc_log_rows_keep_schema,
    # rc_numeric_claims_cite_a_command, rc_mechanism_claims_cite_a_source,
    # root_cause_recurrence_declared, fix_crosswalks_to_violated_lock,
    # closed_rows_ship_their_code, adversarial_audits_are_answered) are RETIRED as
    # registrations only — their full validation now runs INSIDE check_root_cause_log via
    # _root_cause_ledger_folded_violations, and their check_* wrappers stay importable.
    ("root_cause_log", check_root_cause_log, True),
    # RC-470 (operator-approved retirement, 2026-08-24): five_why_recursive_lock and
    # recursive_five_why_front_loaded RETIRED - see governance/retired_checks.md for
    # each retired check's equivalence. root_cause_log (why-chain + measured evidence
    # on every defect row) and closed_rows_ship_their_code (closures point at real
    # code) keep the substance; the retired checks policed ledger-prose grammar.
    ("rth_only_market_measurement", check_rth_only_market_measurement, True),  # RC-54: market-closed rows bias every statistic
    # SIMPLICITY REHAB T2-3 (2026-08-24, governance/retired_checks.md): the ONE enforced
    # evidence validator. verdicts_declare_their_power and unproven_register are RETIRED as
    # registrations only — their full validation runs INSIDE
    # check_measured_claims_cite_evidence, and their check_* wrappers stay importable.
    ("measured_claims_cite_evidence", check_measured_claims_cite_evidence, True),  # RC-56: a committed finding carries its reproduce command
    ("universal_ticker_scope", check_universal_ticker_scope, True),  # RC-160: no SPY-only work framed as complete
    # chart_intent_and_next_rth and ui_mockup_approval REMOVED 2026-09-06 (bedrock PR B, step 2;
    # declared in governance/retired_checks.md): prose matchers over residual text and a second
    # approval authority. RC-163's structural half is level_producers_have_consumers below.
    ("domain_faucet_registry", check_domain_faucet_registry, True),  # RC-212: one faucet per DOMAIN; greeks only at bs_*
    ("phase2a_single_level_computation", check_phase2a_single_level_computation, True),  # Phase 2A: one computation + one materialization per (ticker, level_id, scope, generation)
    # RC-470: rc_document_without_resolve RETIRED (governance/retired_checks.md) -
    # backlog growth stays enforced by open_item_cap; same-day unfinished rows still
    # block turn end (stop_guard RC-72).
    # RC-470: writer_no_drift RETIRED (governance/retired_checks.md). Measured before
    # retiring: the commit hook never ran it (RC-406); CI deliberately set no role
    # (RC-396); it fired only in local verification shells. The role machinery it
    # policed was removed entirely in the 2026-08-24 Architecture A teardown.
    # RC-470: log_law RETIRED (governance/retired_checks.md) - a third queue describing
    # the same item stays blocked by no_governance_duplication, ledger schema by
    # rc_log_rows_keep_schema, epistemic closure by unproven_register.
    # RC-470: plus_player_law, plus_player_cursor_hooks and honesty_guard_wired RETIRED
    # (governance/retired_checks.md) - roster demotions are caught by the delta-gate
    # roster comparison + declared-retirement manifest; hook-wiring changes are
    # operator-reviewed at merge (RC-475); honesty_guard.py itself stays on Stop.
    # find_prove_significance_substance REMOVED 2026-09-06 (bedrock PR B; declared): matched
    # significance vocabulary in staged prose. The structural Find&Prove checks stay below.
    ("admission_evidence_resolves", check_admission_evidence_resolves, True),  # RC-210: SR 11-7 evidence paths
    ("purged_cv_research", check_purged_cv_research, True),  # RC-210: AFML no plain KFold
    ("prereg_before_confirmatory", check_prereg_before_confirmatory, True),  # RC-210: Arnott/COS prereg
    ("decision_path_wired", check_decision_path_wired, True),  # RC-210: SR 11-7 AST TRADE gate
    ("collect_datasheet_staged", check_collect_datasheet_staged, True),  # RC-210: Gebru datasheets
    ("chain_width_single_faucet", check_chain_width_single_faucet, True),  # RC-59: one strike-count authority
    ("single_faucet_provenance", check_single_faucet_provenance, True),  # RC-73: measured, not asserted
    ("scheduled_producers_are_not_inert", check_scheduled_producers_are_not_inert, True),
    ("collect_window_single_law", check_collect_window_single_law, True),  # RC-183: 08:15-15:15 CT at the ONE write seam
    ("price_bars_readers_name_their_session", check_price_bars_readers_name_their_session, True),  # RC-61: the log is a control, not an archive
    ("domain_constants_are_derived", check_domain_constants_are_derived, True),  # RC-62: a market threshold states where its value came from
    # no_terminal_null REMOVED 2026-09-06 (bedrock PR B; declared): surrender vocabulary in
    # ledger prose and next_depth tokens in null reports — a prose matcher; the law stays.
    # no_governance_duplication + checks_are_justified RETIRED 2026-08-24 (SIMPLICITY
    # REHAB, governance/retired_checks.md)
    # no_tautological_assertions: inside test_hygiene (bedrock PR B).
    # open_item_cap REMOVED 2026-09-06 (step 2 of the two-step contract; declared retired on
    # main 2026-09-02 in governance/retired_checks.md as a PROVEN DUPLICATE of root_cause_log's
    # overdue clause and the register validator — one overdue item fails one check, not two).
    # debt_ratchet REMOVED 2026-09-06 (bedrock step 4b) with the advisory-debt loop: a counter
    # cannot distinguish a regression from a false positive (RC-67), and the loop it fed —
    # baseline file, daily scan, TQM queue, code-health panel — produced a 3,360-finding
    # backlog the doctrine itself called "not a work order" (RC-280: no ratchets). Correctness
    # is judged by the checks that read the CODE and by ruff in CI.
    ("single_spot_authority", check_single_spot_authority, True),  # one faucet (RC-14)
    ("no_silent_swallow", check_no_silent_swallow, True),           # driven to zero 2026-07-17
    ("no_todo_without_tracking_id", check_todo_without_tracking_id, True),
    # RC-470: five_why_reaches_bedrock RETIRED with the five-why grammar family
    # (governance/retired_checks.md) - it regex-judged chain-ending terminology; chain
    # presence and depth stay enforced by root_cause_log.
    # RC-325 SP-01: one authorized production producer per canonical concept. ENFORCED
    # because an unregistered gate enforces nothing — it sat at zero registrations while
    # being reported as a lock.
    ("one_producer", check_one_producer, True),
    # OPTIONS_ORDER_FLOW_V1 Phase 1-3 (2026-08-30): exactly one production Schwab
    # StreamClient constructor, repo-wide. ENFORCED — mutation-tested
    # (tests/test_single_stream_authority_v1.py), not a design-review-only script.
    ("single_stream_authority", check_single_stream_authority, True),
    ("snapshots_read_names_the_timeframe", check_snapshots_read_names_the_timeframe, True),  # query PLAN, not code shape
    ("shutdown_is_bounded", check_shutdown_is_bounded, True),  # Ctrl+C must always work
    ("venv_parity", check_venv_parity, True),  # one interpreter — .venv only (CI exempt)
    ("credential_leak", check_credential_leak, True),  # staged secrets / home paths
    ("sqlite_wal_contract", check_sqlite_wal_contract, True),  # WAL + timeout on connects
    ("ui_data_integration", check_ui_data_integration, True),  # no dead "—" placeholders (Tier 1)
    ("vendor_field_coercion", check_vendor_field_coercion, True),  # one faucet per Schwab leaf (RC-FAUCET)
    ("schwab_market_field_semantics", check_schwab_market_field_semantics, True),  # RC-440 M4/M5: NUM_* not order-count; exchange_quote_ts not a wall clock
    # REMOVED 2026-07-25 (operator: "i don't want you on separate instances"): the
    # agent_worktree_boundary check required ED_AGENT_ROLE to be set and blocked all
    # commits from a single-instance workflow (fail-closed on unset role). 2026-08-24
    # teardown: its dormant helpers (check_worktree_handoff.py,
    # agent_worktree_policy.json, ED_AGENT_ROLE itself) were fully purged; db_authority
    # keeps the ONE-DB property with no role fork.
    # ADVISORY (visible debt, driven to zero, then flipped to enforced — the ratchet):
    # RC-67: PROMOTED to directly ENFORCED for the same reason as no_fake_defaults — a test that
    # cannot fail on regression is not a test, and this was only blocking via the retired counter.
    # Driven to 0 by RC-46, so it binds on the code rather than on a delta.
    # tests_missing_explicit_assert: inside test_hygiene (bedrock PR B).
    # orphan_dict_keys stays REPORTED (not enforced): a silent-None lead is a real product
    # class (RC-15/RC-20) with inherited volume; it is a report the operator reads, never a
    # ratchet. function_complexity / function_length / file_length / ruff_quality / mypy_types
    # and debt_ratchet REMOVED 2026-09-06 (bedrock step 4b): the advisory-debt loop (ratchet,
    # baseline file, daily scan, TQM queue, code-health panel) produced a 3,360-finding backlog
    # the doctrine itself called "not a work order"; shape/style counting was a ratchet
    # (RC-280), and ruff runs in CI.
    ("orphan_dict_keys", check_no_orphan_dict_keys, False),   # silent-None leads (RC-15/RC-20)
    # REPORTED (bedrock PR B, 2026-09-06): RC-163's structural invariant — every registered
    # level-domain producer has a client consumer — measured over governance/level_faucets.json
    # and static/. Reported, not enforced, because the tree carries orphans today; it binds
    # when the operator wires or retires them (the repo's promote-at-zero pattern).
    ("level_producers_have_consumers", check_level_producers_have_consumers, False),
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
    # test_claims_are_executed: inside test_hygiene (bedrock PR B).
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
]

_MAX_PRINT = 15  # cap per-check output; full count is always reported


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
    "closed_rows_ship_their_code",
    "rc_numeric_claims_cite_a_command",
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
    # BEDROCK 2026-09-06: the "advisory" mode, the hotspot tally and the debt report left with
    # the advisory-debt loop; a non-enforced check is simply REPORTED here, never ratcheted.
    enforced_violations = 0
    results: list[tuple[str, bool, int]] = []
    for name, fn, enforced in CHECKS:
        if mode == "enforced" and not enforced:
            continue
        tag = "ENFORCED" if enforced else "REPORTED"
        violations = _apply_forward_only_grandfather(name, fn())
        results.append((name, enforced, len(violations)))
        if violations:
            if enforced:
                enforced_violations += len(violations)
            note = "" if enforced else " — reported, not vetoing"
            print(f"FAIL [{name}] ({tag}) — {len(violations)} violation(s){note}:")
            for v in violations[:_MAX_PRINT]:
                print(v)
            if len(violations) > _MAX_PRINT:
                print(f"  … and {len(violations) - _MAX_PRINT} more")
        else:
            print(f"PASS [{name}] ({tag})")
    return enforced_violations, results


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    # BEDROCK 2026-09-06: --rebaseline and --advisory left with the advisory-debt loop.
    mode = "enforced" if "--enforced-only" in args else "all"
    enforced_violations, _results = run_checks(mode=mode)
    if enforced_violations:
        print(f"\nINSTITUTIONAL CORRECTNESS GATE: FAIL ({enforced_violations} enforced violation(s))")
        return 1
    print("\nINSTITUTIONAL CORRECTNESS GATE: PASS (enforced checks clean"
          + ("; reported checks shown above)" if mode == "all" else ")"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
