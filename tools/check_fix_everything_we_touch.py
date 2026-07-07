"""Pre-commit guard: AGENTS.md § Fix everything we touch + self-governance loop.

Blocks:
  1. Commit messages that claim read-only / investigation-only completion when
     landing audit work (the operator top rule: fix everything we touch).
  2. Staged V4 review memos that record actionable ``code edit`` or open
     ``audit catch`` rows without staging the matching ``*.py`` target in the
     same commit.

Authoritative rule source: AGENTS.md (§ Do not lie to the operator, § Fix everything we touch,
§ Self-governance quality loop). Paired test: tests/test_check_fix_everything_we_touch.py.

Usage:
  python tools/check_fix_everything_we_touch.py              # pre-commit scoped (fast path)
  python tools/check_fix_everything_we_touch.py --full-static  # manual / CI objective-audit (not local pre-push)
  python tools/check_fix_everything_we_touch.py --profile      # per-subcheck timings artifact
  python tools/check_fix_everything_we_touch.py path [path]  # explicit paths
  python tools/check_fix_everything_we_touch.py --commit-msg .git/COMMIT_EDITMSG
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parent.parent
MEMO_DIR = REPO_ROOT / "governance" / "SCHWAB_V4_REVIEW_MEMOS"

# Phase 3K — pytest session reuse for expensive repo-wide static audit (pre-push bundle).
_SESSION_STATIC_AUDIT_CACHE: dict[tuple[str, ...], list[str]] | None = None


def _pytest_reuse_static_audit() -> bool:
    return os.environ.get("ED_PYTEST_REUSE_STATIC_AUDIT") == "1"


def reset_session_static_audit_cache_for_tests() -> None:
    """Clear in-process static audit cache (tests only)."""
    global _SESSION_STATIC_AUDIT_CACHE
    _SESSION_STATIC_AUDIT_CACHE = None


def session_static_audit_cache_for_tests() -> dict[tuple[str, ...], list[str]] | None:
    """Expose cache for pytest cache-correctness assertions."""
    return _SESSION_STATIC_AUDIT_CACHE

CODE_EDIT_LINE = re.compile(
    r"^\s*-\s*\*\*code edit:\*\*\s*(.+)$",
    re.MULTILINE | re.IGNORECASE,
)

# Commit messages that signal "I looked but did not fix" — rejection-grade per operator 2026-05-24.
META_COMMIT_LINE = re.compile(
    r"\b(?:"
    r"blocks?|banned modes|commit-message guard|investigation-only language|"
    r"rejection-grade|mechanical lock|check_fix_everything_we_touch"
    r")\b",
    re.IGNORECASE,
)
DO_NOT_LIE_META_LINE = re.compile(
    r"\b(?:"
    r"do not lie|partial coverage|unverified claim|verified.? without evidence|"
    r"operator-as-catch|mechanical enforcement|commit-msg guard|"
    # Hyphenated technical descriptors — only used when describing the checker itself,
    # not in real violations (which read like prose, not keyword-case identifiers).
    r"unverified-admission|scope-extension|verify-in-turn-or-omit|verify-in-turn"
    r")\b",
    re.IGNORECASE,
)
EVIDENCE_CITE = re.compile(
    r"(?:"
    r":\d+"
    r"|@\s*[0-9a-f]{7,40}\b"
    r"|\btests/[\w./-]+"
    r"|\btest_[\w]+"
    r"|\bpytest\b"
    r")",
    re.IGNORECASE,
)
UNVERIFIED_CLAIM_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("verified without evidence cite", re.compile(r"\bverified\b", re.IGNORECASE)),
    ("confirmed without evidence cite", re.compile(r"\bconfirmed\b", re.IGNORECASE)),
    (
        "guarantee without cited mechanism",
        re.compile(r"\bguarantee(?:s|d)?\b", re.IGNORECASE),
    ),
    ("all clear without evidence cite", re.compile(r"\ball\s+clear\b", re.IGNORECASE)),
    (
        "inference verdict (looks/appears/seems/should-be clean/orphaned/safe/correct/ready/complete)",
        re.compile(
            r"\b(?:looks|appears|seems|should\s+be)\s+(?:clean|orphaned|safe|correct|ready|complete|good|fine)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "echoed upstream summary as fact (per cursor/subagent/peer summary without source read)",
        re.compile(
            r"\bper\s+(?:cursor|subagent|claude|peer)['’]?s?\s+(?:summary|report|claim|read)\b",
            re.IGNORECASE,
        ),
    ),
)
# Explicit unverified admissions — fire regardless of any nearby evidence cite
# (an admission like "haven't verified" cannot be redeemed by a cite somewhere else on the line).
UNVERIFIED_ADMISSION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "explicit unverified admission (haven't verified / haven't checked / haven't enumerated / haven't read)",
        re.compile(
            r"\bhaven['’]?t\s+(?:verified|checked|enumerated|read|done|confirmed)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "explicit unverified admission (not verified this turn / not checked here / unverified by me)",
        re.compile(
            r"\b(?:not\s+(?:verified|checked|enumerated|confirmed)\s+(?:this\s+turn|in\s+turn|here|by\s+me)"
            r"|unverified\s+by\s+me)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "deferred verification (separate / further / deeper verification needed / pending)",
        re.compile(
            r"\b(?:separate|further|deeper|additional)\s+verification\s+(?:needed|required|pending|to\s+do|is\s+needed)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "deferred verification (would need to verify / would need to check / would have to confirm)",
        re.compile(
            r"\bwould\s+(?:need|have)\s+to\s+(?:verify|check|read|enumerate|confirm)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "scope-extension claim without same-turn check (same gap/pattern/issue applies / parallel observation)",
        re.compile(
            r"\b(?:same\s+(?:gap|pattern|issue|bug|problem)\s+(?:applies|likely|would|presumably|extends)"
            r"|parallel\s+(?:concern|observation|gap|pattern)\s+(?:applies|likely)"
            r"|presumably\s+(?:affects|extends|applies)"
            r"|likely\s+(?:applies|affects|the\s+case))\b",
            re.IGNORECASE,
        ),
    ),
    (
        "out-of-turn scope dodge (out of scope of this turn / out of scope of this verification)",
        re.compile(
            r"\bout\s+of\s+scope\s+of\s+(?:this\s+(?:turn|verification|check|reply|response))\b",
            re.IGNORECASE,
        ),
    ),
)
RULE_DRIFT_META_LINE = re.compile(
    r"\b(?:"
    r"zero\s+drift|rule\s+compliance|check_fix_everything_we_touch|"
    r"forbidden\s+phrase|excuse\s+pattern|banned\s+phrase|"
    r"rejection-grade|mechanical\s+enforcement|partial\s+enforcement|pre-commit\s+guard"
    r")\b",
    re.IGNORECASE,
)

# Excuse / partial-completion phrases (AGENTS § Banned phrases — Excuse / partial-completion).
# Normative list lives in AGENTS.md; by-design family uses context-aware detection in
# governance.forbidden_phrases (canonical control titles vs excuse prose).
EXCUSE_PARTIAL_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("patch-only completion excuse", re.compile(r"\b(?:patch\s+only|minimal\s+patch|small\s+patch)\b", re.IGNORECASE)),
    ("mostly/substantially complete", re.compile(r"\b(?:mostly|substantially)\s+complete\b", re.IGNORECASE)),
    ("good enough for now", re.compile(r"\bgood\s+enough\s+for\s+now\b", re.IGNORECASE)),
    ("not in scope", re.compile(r"\bnot\s+in\s+scope\b", re.IGNORECASE)),
    ("intentional asymmetry", re.compile(r"\bintentional\s+asymmetry\b", re.IGNORECASE)),
    ("rules are guidance", re.compile(r"\brules?\s+are\s+(?:just\s+)?guidance\b", re.IGNORECASE)),
    ("operator will catch", re.compile(r"\boperator\s+will\s+catch\b", re.IGNORECASE)),
    ("acceptable drift", re.compile(r"\bacceptable\s+drift\b", re.IGNORECASE)),
    ("partial fix as stop reason", re.compile(r"\bpartial\s+fix\b", re.IGNORECASE)),
)

STAGED_DRIFT_SCAN_SUFFIXES = (".py", ".html", ".js", ".jsx", ".ts", ".tsx", ".css", ".md")
STAGED_DRIFT_ALLOWLIST_PREFIXES = (
    "governance/",
    "docs/governance/",
)
STAGED_DRIFT_ALLOWLIST_EXACT = {
    "AGENTS.md",
    "CLAUDE.md",
    "ACTIVE_PROGRAM.md",
    "OPEN_ITEMS.md",
    "MEMORY.md",
    "tools/check_fix_everything_we_touch.py",
    "tests/test_check_fix_everything_we_touch.py",
    "tests/test_forbidden_phrases.py",
    "tests/test_precommit_performance_audit.py",
    # Self-referential enforcement surfaces: these files DEFINE or LOCK the banned-phrase
    # patterns, so scanning their literal regex/assert text is noise, not drift.
    "tools/check_no_deferral_language.py",
    "tests/test_check_no_deferral_language.py",
    "tools/enforce_all_rules.py",
    "tests/test_governance_consolidation.py",
}


def _import_forbidden_helpers():
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from governance.forbidden_phrases import find_forbidden_phrases

    return find_forbidden_phrases


def _staged_path_allowlisted_for_drift_scan(rel: str) -> bool:
    if rel in STAGED_DRIFT_ALLOWLIST_EXACT:
        return True
    return any(rel.startswith(p) for p in STAGED_DRIFT_ALLOWLIST_PREFIXES)


def _line_rule_drift_hits(path: Path, line_no: int, line: str) -> list[str]:
    if RULE_DRIFT_META_LINE.search(line) or META_COMMIT_LINE.search(line) or DO_NOT_LIE_META_LINE.search(line):
        return []
    hits: list[str] = []
    find_forbidden = _import_forbidden_helpers()
    for phrase in find_forbidden(line):
        hits.append(
            f"{path}:{line_no}: banned phrase ({phrase!r}): {line.strip()[:200]!r} "
            f"(AGENTS § Rule compliance — zero drift)"
        )
    for label, pat in EXCUSE_PARTIAL_PATTERNS:
        if pat.search(line):
            hits.append(
                f"{path}:{line_no}: excuse/partial-completion hit ({label}): {line.strip()[:200]!r} "
                f"(AGENTS § Banned phrases — land the fix or [REAL-GATE: …], do not excuse)"
            )
    return hits


def check_staged_rule_drift(staged: set[str]) -> list[str]:
    """Scan staged source/docs for banned + excuse phrases (AGENTS § Rule compliance — zero drift)."""
    errors: list[str] = []
    for rel in sorted(staged):
        if _staged_path_allowlisted_for_drift_scan(rel):
            continue
        if not rel.endswith(STAGED_DRIFT_SCAN_SUFFIXES):
            continue
        path = REPO_ROOT / rel
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            errors.append(f"{rel}: cannot read for rule-drift scan ({exc})")
            continue
        for line_no, line in enumerate(text.splitlines(), start=1):
            errors.extend(_line_rule_drift_hits(path, line_no, line))
    return errors


INVESTIGATION_ONLY_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "read-only investigation",
        re.compile(r"\bread-?only\s+investigation\b", re.IGNORECASE),
    ),
    (
        "investigation only / investigation was read-only",
        re.compile(
            r"\binvestigation\s+(?:only|was\s+read-?only|complete[^.\n]{0,40}no\s+(?:fix|code))\b",
            re.IGNORECASE,
        ),
    ),
    (
        "no further code change needed",
        re.compile(r"\bno\s+further\s+code\s+change\b", re.IGNORECASE),
    ),
    (
        "memo-only admissible (audit with open code edit)",
        re.compile(
            r"\bmemo-?only\s+(?:is\s+)?(?:admissible|ok|correct)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "report FIND without fix",
        re.compile(
            r"\b(?:report(?:ed|ing)?|flagged|flag(?:ged)?|surfaced?)\s+(?:the\s+)?FIND\b.{0,80}\b(?:without|no)\s+(?:fix|landing)\b",
            re.IGNORECASE,
        ),
    ),
)


def _git_staged_paths() -> set[str]:
    try:
        proc = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return set()
    if proc.returncode != 0:
        return set()
    return {ln.strip().replace("\\", "/") for ln in proc.stdout.splitlines() if ln.strip()}


def _path_is_allowlisted_commit_msg(path: Path) -> bool:
    s = path.as_posix()
    return s.endswith("AGENTS.md") or "/governance/" in s or s.endswith("/tests/test_check_fix_everything_we_touch.py")


def is_actionable_code_edit(text: str) -> bool:
    t = text.strip().lower()
    if not t:
        return False
    if t.startswith("none"):
        return False
    if "landed" in t or "already fixed" in t:
        return False
    return True


def memo_target_py(memo_path: Path) -> Path | None:
    stem = memo_path.name
    if not stem.endswith(".py.md"):
        return None
    rel = stem[: -len(".md")]
    return Path(rel)


def memo_has_open_audit_catch(text: str) -> bool:
    if not re.search(r"\baudit catch\b", text, re.IGNORECASE):
        return False
    if re.search(r"\*\*Closed:\*\*", text, re.IGNORECASE):
        return False
    if re.search(r"code edit:\*\* landed", text, re.IGNORECASE):
        return False
    return True


def check_v4_memo(memo_path: Path, staged: set[str]) -> list[str]:
    if not memo_path.is_file():
        return []
    try:
        rel_memo = memo_path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        rel_memo = memo_path.as_posix()
    target = memo_target_py(memo_path)
    if target is None:
        return []

    try:
        text = memo_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return [f"{rel_memo}: cannot read memo ({exc})"]

    target_posix = target.as_posix()
    py_staged = target_posix in staged

    errors: list[str] = []
    actionable = [m.group(1) for m in CODE_EDIT_LINE.finditer(text) if is_actionable_code_edit(m.group(1))]
    if actionable and not py_staged:
        errors.append(
            f"{rel_memo}: actionable code edit recorded ({len(actionable)} row(s)) "
            f"but {target_posix} is not staged — fix+test must land same commit (AGENTS § Fix everything we touch)."
        )

    if memo_has_open_audit_catch(text) and not py_staged:
        errors.append(
            f"{rel_memo}: open audit catch without **Closed:** / landed code edit "
            f"and {target_posix} not staged — land the fix in this commit."
        )
    return errors


def check_commit_message(path: Path) -> list[str]:
    if _path_is_allowlisted_commit_msg(path):
        return []
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    hits: list[str] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        if META_COMMIT_LINE.search(line) or DO_NOT_LIE_META_LINE.search(line):
            continue
        for label, pat in INVESTIGATION_ONLY_PATTERNS:
            if pat.search(line):
                hits.append(f"{path}:{line_no}: investigation-only hit ({label}): {line.strip()[:200]!r}")
        for label, pat in UNVERIFIED_ADMISSION_PATTERNS:
            if pat.search(line):
                hits.append(
                    f"{path}:{line_no}: unverified-admission hit ({label}): {line.strip()[:200]!r} "
                    f"(AGENTS § Do not lie / verify-in-turn-or-omit — verify the claim or remove it; "
                    f"caveats narrate the gap, they don't close it)"
                )
        if EVIDENCE_CITE.search(line):
            continue
        for label, pat in UNVERIFIED_CLAIM_PATTERNS:
            if pat.search(line):
                hits.append(
                    f"{path}:{line_no}: unverified-claim hit ({label}): {line.strip()[:200]!r} "
                    f"(AGENTS § Do not lie — cite tests/, @ SHA, or :line on same line)"
                )
        hits.extend(_line_rule_drift_hits(path, line_no, line))
    hits.extend(check_meet_or_exceed_signoff(path))
    if path.name == "COMMIT_EDITMSG":
        try:
            from tools.check_repo_hygiene_policy import check_hygiene_touch_disposition

            hits.extend(
                check_hygiene_touch_disposition(staged=_git_staged_paths(), commit_text=text)
            )
        except Exception as exc:  # pragma: no cover
            hits.append(f"{path}: repo hygiene touch disposition check failed ({exc})")
    return hits


# Artifact-content rule (AGENTS § Action-not-documentation, 2026-05-25):
# governance artifacts that describe issues without paired code edits are doc-only
# and rejection-grade. Action-language tokens that indicate "this artifact identifies
# work to do" — must be paired with a code change in the same commit.
ACTION_LANGUAGE_TOKENS = (
    "FIND-",
    "fix direction",
    "Risk:",
    "Remaining:",
    "Open:",
    "TODO:",
    "TODO ",
    "tracked as ",
    "needs follow-on",
    "remediation",
)

# Artifact paths whose content is governed by the Action-not-documentation rule.
# Rule files / sign-off pins / OPEN_ITEMS are excluded — see the rule's honest-limit.
ACTION_RULE_ARTIFACT_PREFIXES = (
    "governance/audits/",
    "governance/SCHWAB_V4_REVIEW_MEMOS/",
)
ACTION_RULE_ARTIFACT_PATTERNS = (
    "governance/PHASE_PLAN_",
)

# Code-change extensions that satisfy the "paired code edit" requirement.
CODE_EXTENSIONS = (".py", ".html", ".js", ".jsx", ".ts", ".tsx", ".css", ".sql")


def _path_is_action_rule_artifact(rel: str) -> bool:
    if not rel.endswith(".md"):
        return False
    if any(rel.startswith(pref) for pref in ACTION_RULE_ARTIFACT_PREFIXES):
        return True
    return any(pat in rel for pat in ACTION_RULE_ARTIFACT_PATTERNS)


def _staged_has_code_change(staged: set[str]) -> bool:
    return any(p.endswith(CODE_EXTENSIONS) for p in staged)


# Storage-needs-consumer rule (AGENTS § Storage-needs-consumer, 2026-05-25):
# Persistence-layer modules that add new INSERT statements without a paired
# production caller leave dormant writers in the repo. The 4-dormant-tables
# pattern (level_crosses / confluence_log / model_accuracy / session_log)
# proves the failure mode: full schemas + writers shipped, zero callers,
# zero operator value. Block at pre-commit.
PERSISTENCE_LAYER_FILES = (
    "db.py",
    "calibration/writer.py",
)

# Pass 2b: paths whose edits require regenerating
# governance/artifacts/persistence_consumer_map.json in the same commit.
PERSISTENCE_MAP_TRIGGER_FILES = (
    "db.py",
    "calibration/writer.py",
    "tools/audit_persistence_consumers.py",
)
PERSISTENCE_MAP_PATH = "governance/artifacts/persistence_consumer_map.json"
PERSISTENCE_AUDIT_TOOL = "tools/audit_persistence_consumers.py"


def _count_insert_stmts(text: str) -> int:
    """Count distinct INSERT INTO statements in text (rough heuristic; case-insensitive)."""
    if not text:
        return 0
    return text.upper().count("INSERT INTO ")


def _staged_has_non_persistence_caller(staged: set[str]) -> bool:
    """True if commit stages any production .py / .html / .js outside db.py / persistence /
    tests / tools — i.e., a plausible production caller for a new writer."""
    for p in staged:
        if not p.endswith(CODE_EXTENSIONS):
            continue
        if p in PERSISTENCE_LAYER_FILES:
            continue
        if p.startswith("tests/") or p.startswith("tools/") or p.startswith("calibration/writer"):
            continue
        return True
    return False


def check_storage_writer_has_consumer(staged: set[str]) -> list[str]:
    """Block commits that add new INSERT statements in a persistence-layer file
    without a paired production caller in the same commit.

    Per AGENTS § Storage-needs-consumer (2026-05-25 operator escalation): new
    writers without callers are the dormant-table pattern (level_crosses etc.)
    — schema + writer ship but produce zero operator value because nothing
    invokes them. This check fires when the staged version of a persistence
    file has MORE `INSERT INTO` statements than the HEAD version, AND no
    production .py file is also staged.
    """
    errors: list[str] = []
    for rel in sorted(staged):
        if rel not in PERSISTENCE_LAYER_FILES:
            continue
        staged_path = REPO_ROOT / rel
        if not staged_path.is_file():
            continue
        try:
            staged_text = staged_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        head_text = _git_show_head_utf8(rel)
        new_inserts = _count_insert_stmts(staged_text) - _count_insert_stmts(head_text)
        if new_inserts <= 0:
            continue
        if not _staged_has_non_persistence_caller(staged):
            errors.append(
                f"{rel}: adds {new_inserts} new INSERT INTO statement(s) but commit has no "
                f"paired production caller (no .py / .html / .js outside db.py / persistence / "
                f"tests / tools). AGENTS § Storage-needs-consumer — new writers must land with "
                f"a live caller AND a consumer in the same commit (see the 4-dormant-tables "
                f"precedent: level_crosses / confluence_log / model_accuracy / session_log). "
                f"Either stage the production caller this commit, or split the writer to a "
                f"later commit that includes the caller."
            )
    return errors


def _git_show_head_utf8(rel: str) -> str:
    """Read HEAD:<rel> as UTF-8 text (errors=replace).

    Default subprocess text mode uses the platform encoding (cp1252 on
    Windows) which raises UnicodeDecodeError on non-ASCII bytes in source
    files (em-dashes, smart quotes, anything from a copy-paste). Force
    UTF-8 + replace so the diff comparison stays correct even when HEAD
    has non-ASCII content the platform encoding can't represent.
    """
    try:
        proc = subprocess.run(
            ["git", "show", f"HEAD:{rel}"],
            cwd=REPO_ROOT,
            capture_output=True,
            check=False,
        )
    except OSError:
        return ""
    if proc.returncode != 0:
        return ""
    try:
        return proc.stdout.decode("utf-8", errors="replace")
    except (UnicodeDecodeError, AttributeError):
        return ""


_INSERT_TABLE_RE = re.compile(
    r"INSERT\s+(?:OR\s+(?:REPLACE|IGNORE|ABORT|FAIL|ROLLBACK)\s+)?INTO\s+([A-Za-z_][A-Za-z0-9_]*)",
    re.IGNORECASE,
)


def _extract_inserted_tables(text: str) -> set[str]:
    return {m.group(1).lower() for m in _INSERT_TABLE_RE.finditer(text or "")}


def _load_persistence_map() -> dict[str, list[str]] | None:
    """Return {table_lower -> [reader_files]} from persistence_consumer_map.json,
    or None if the map is missing / corrupt (Pass 2b catches those separately)."""
    map_path = REPO_ROOT / PERSISTENCE_MAP_PATH
    if not map_path.is_file():
        return None
    try:
        obj = json.loads(map_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    table_readers: dict[str, list[str]] = {}
    for writer in obj.get("writers", []):
        for tbl, readers in (writer.get("read_consumers") or {}).items():
            slot = table_readers.setdefault(tbl.lower(), [])
            for r in readers or []:
                if r not in slot:
                    slot.append(r)
    return table_readers


def _real_gate_tracked_tables() -> set[str]:
    """Tables mentioned on any OPEN_ITEMS line that also carries [REAL-GATE: <tag>].

    This is the deferral escape hatch for Pass 1b: a known-dormant table can
    receive new INSERTs (e.g., a refactor that adds a write inside an existing
    helper) without failing the gate, provided the dormancy is tracked.
    """
    open_items = REPO_ROOT / "OPEN_ITEMS.md"
    if not open_items.is_file():
        return set()
    try:
        text = open_items.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return set()
    table_readers = _load_persistence_map() or {}
    known_tables = set(table_readers.keys())
    real_gate_tables: set[str] = set()
    for line in text.splitlines():
        if "[REAL-GATE:" not in line:
            continue
        lower_line = line.lower()
        for tbl in known_tables:
            if tbl in lower_line:
                real_gate_tables.add(tbl)
    return real_gate_tables


def check_persistence_writer_has_reader(staged: set[str]) -> list[str]:
    """Pass 1b — every staged new INSERT must hit a table with a read consumer
    (per persistence_consumer_map.json) OR a tracked [REAL-GATE: <tag>] row.

    Complement to Pass 1's check_storage_writer_has_consumer (which checks for
    a paired caller). Pass 1b checks for a paired READER — the consumer side.
    Together they enforce AGENTS § Storage-needs-consumer at pre-commit time.

    Honest limit: "reader" here means a file containing a SELECT/JOIN/UPDATE
    against the target table per the audit tool's static scan. Whether the
    reader's output reaches an operator-visible surface is product judgment
    the lock cannot verify.
    """
    triggers = [f for f in staged if f in PERSISTENCE_LAYER_FILES]
    if not triggers:
        return []

    table_readers = _load_persistence_map()
    if table_readers is None:
        return []  # Pass 2b already fires on missing / corrupt map

    real_gate_tables = _real_gate_tracked_tables()

    errors: list[str] = []
    for rel in sorted(triggers):
        staged_path = REPO_ROOT / rel
        if not staged_path.is_file():
            continue
        try:
            staged_text = staged_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        head_text = _git_show_head_utf8(rel)
        staged_tables = _extract_inserted_tables(staged_text)
        head_tables = _extract_inserted_tables(head_text)
        new_tables = staged_tables - head_tables
        for tbl in sorted(new_tables):
            readers = table_readers.get(tbl, [])
            if readers:
                continue
            if tbl in real_gate_tables:
                continue
            errors.append(
                f"{rel}: new INSERT INTO {tbl} — table has 0 read consumers per "
                f"{PERSISTENCE_MAP_PATH} and no OPEN_ITEMS row mentions {tbl} "
                f"under a [REAL-GATE: <tag>] tag. AGENTS § Storage-needs-consumer / "
                f"Pass 1b — land a reader in the same commit (API endpoint, log line, "
                f"scheduled audit, or test asserting on row content), OR add an OPEN_ITEMS "
                f"row tagged [REAL-GATE: <tag>] that names {tbl}."
            )
    return errors


def _persistence_map_matches_sources() -> tuple[bool | None, str]:
    """Run the audit tool's --check against the working tree.

    Returns (matches, detail):
      * (True,  "")        — on-disk map matches what the tool emits from sources.
      * (False, stderr)    — map is stale vs sources (real persistence drift).
      * (None,  reason)    — tool absent / unrunnable; caller treats as "cannot verify".

    Split out as a module-level helper so tests can monkeypatch the source-match
    verdict without shelling out to the real audit tool.
    """
    audit_tool_path = REPO_ROOT / PERSISTENCE_AUDIT_TOOL
    if not audit_tool_path.is_file():
        return None, "audit tool absent"
    try:
        proc = subprocess.run(
            [sys.executable, str(audit_tool_path), "--check"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        return None, f"cannot run audit tool ({exc})"
    if proc.returncode == 0:
        return True, ""
    return False, (proc.stderr.strip() or "(no detail)")


def _persistence_map_changed_vs_head() -> bool:
    """True if persistence_consumer_map.json differs from HEAD (staged or unstaged).

    A behavior-neutral edit to a trigger file (e.g. removing an unused import)
    leaves the generated map byte-identical to HEAD, so there is nothing to
    stage and Pass 2b must NOT demand a phantom map row in the commit.
    """
    try:
        proc = subprocess.run(
            ["git", "diff", "HEAD", "--name-only", "--", PERSISTENCE_MAP_PATH],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return False
    if proc.returncode != 0:
        return False
    return bool(proc.stdout.strip())


def check_persistence_map_fresh(staged: set[str]) -> list[str]:
    """Pass 2b — persistence_consumer_map.json must stay in sync with persistence sources.

    Triggers when commit stages any of db.py / calibration/writer.py /
    tools/audit_persistence_consumers.py.

    Behavior-aware (2026-06-03): the map is REQUIRED in the commit only when the
    edit actually changes persistence behavior — i.e. the on-disk map is stale
    vs sources, OR the regenerated map differs from HEAD. A behavior-neutral
    edit to a trigger file (removing an unused import, a comment, a type hint)
    leaves the map identical to HEAD; demanding a phantom map row there makes the
    gate unsatisfiable and forces bypasses, which is the opposite of enforcement.

    Failure modes still blocked:
      1. Source edit makes the map stale vs sources, map not re-staged -> regen+stage.
      2. Source edit changes the map vs HEAD, map staged but content stale -> regen+re-stage.
      3. Source edit changes the map vs HEAD, map not staged at all -> stage it.
    """
    triggers = [f for f in staged if f in PERSISTENCE_MAP_TRIGGER_FILES]
    if not triggers:
        return []

    map_staged = PERSISTENCE_MAP_PATH in staged
    matches, detail = _persistence_map_matches_sources()

    if matches is False:
        # Real persistence drift: the on-disk map no longer matches sources.
        if not map_staged:
            return [
                f"{PERSISTENCE_MAP_PATH}: stale vs persistence sources but not staged while "
                f"{', '.join(triggers)} staged ({detail}). Pass 2b — regenerate with "
                f"`python tools/audit_persistence_consumers.py --stable-time` and stage it in the same commit."
            ]
        return [
            f"{PERSISTENCE_MAP_PATH}: staged but stale content vs persistence sources ({detail}). "
            f"Pass 2b — regenerate with `python tools/audit_persistence_consumers.py --stable-time` and re-stage."
        ]

    # matches is True (map current with sources) or None (tool absent — can't verify).
    # Require the map in the commit only if a real persistence change is present,
    # detected as a map diff vs HEAD. Behavior-neutral trigger-file edits leave the
    # map identical to HEAD and pass without a phantom map row.
    if _persistence_map_changed_vs_head() and not map_staged:
        return [
            f"{PERSISTENCE_MAP_PATH}: changed vs HEAD but not staged while "
            f"{', '.join(triggers)} staged. Pass 2b — stage the regenerated map in the same commit."
        ]
    return []


def check_action_not_documentation(staged: set[str]) -> list[str]:
    """Block governance-artifact-only commits that contain action language without paired code.

    Per AGENTS § Action-not-documentation (2026-05-25 operator escalation):
    plans/phases/memos/audits must carry CODE-FIX scope in the same commit, not
    just describe state. The existing §Fix everything we touch covers V4 memos
    via check_v4_memo; this function extends the same rule to audits and phase
    plans (which previously could land doc-only).
    """
    if _staged_has_code_change(staged):
        return []  # paired code present — rule satisfied
    errors: list[str] = []
    for rel in sorted(staged):
        if not _path_is_action_rule_artifact(rel):
            continue
        artifact_path = REPO_ROOT / rel
        if not artifact_path.is_file():
            continue
        try:
            text = artifact_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        present_tokens = [tok for tok in ACTION_LANGUAGE_TOKENS if tok in text]
        if present_tokens:
            errors.append(
                f"{rel}: contains action language ({', '.join(present_tokens[:4])}) "
                f"but commit has no paired code change (.py / .html / .js / .css / .sql). "
                f"AGENTS § Action-not-documentation — plans/phases/memos/audits must carry "
                f"code-fix scope in the same commit, not just describe state. "
                f"Either land the code fix this commit, or strip the action-language sections "
                f"and re-stage as a sign-off-pin-only update."
            )
    return errors


TO_DICT_RECORDS_RE = re.compile(r"""\.to_dict\s*\(\s*['"]records['"]\s*\)""")
_MVP_FEED_MARKERS = (
    "build_inference_snapshot_v1_from_db_row",
    "build_db_mvp_feature_row",
)
_MVP_INGRESS_OWNER = "features/training_canonical_input.py"


def check_mvp_dataframe_ingress() -> list[str]:
    """Ban raw ``df.to_dict('records')`` on code paths that feed MVP coercion.

    Canonical ingress: ``features.training_canonical_input.records_for_mvp_from_dataframe``.
    DATA-PIPELINE-INTEGRITY (2026-05-26): Pass 1 patched one boundary; META bypass
    reproduced the absorption_score NaN failure on SPY after XGB/LSTM/Transformer trained.
    """
    errors: list[str] = []
    for path in REPO_ROOT.rglob("*.py"):
        rel = path.relative_to(REPO_ROOT).as_posix().replace("\\", "/")
        if rel.startswith(("tests/", "governance/", "tools/")):
            continue
        if rel == _MVP_INGRESS_OWNER:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if not TO_DICT_RECORDS_RE.search(text):
            continue
        if not any(marker in text for marker in _MVP_FEED_MARKERS):
            continue
        if "records_for_mvp_from_dataframe" in text:
            continue
        errors.append(
            f"{rel}: raw df.to_dict('records') on MVP feed path — use "
            "features.training_canonical_input.records_for_mvp_from_dataframe"
        )
    return errors


INSTITUTIONAL_CONTRACT_MARKERS: tuple[tuple[str, str], ...] = (
    ("server.py", "def _resolve_ticker_param"),
    ("server.py", "analytics_refresh_due"),
    ("static/index.html", "INSTITUTIONAL_BUNDLE_TRUST_SEC"),
    ("static/index.html", "function laneStaleOperatorLabel"),
    ("static/index.html", "SYNCING ANALYTICS"),
    ("static/index.html", "UI_LATENCY_CONTRACT"),
    ("static/index.html", "_lastSseAnalyticsPayloadMs"),
    ("static/index.html", "function _analyticsUiPending"),
    ("static/index.html", "TIER-C-NONBLOCK-SWITCH"),
    ("static/index.html", "ANALYTICS_PENDING_POLL_MS"),
    ("static/index.html", "_tierCRestAbortController"),
    ("static/index.html", "_edTierCCacheByTicker"),
    ("static/index.html", "function manualFullRefresh"),
    ("static/index.html", "UI_MAXIMIZE_CONTRACT"),
    ("static/index.html", "ED_UI_MAXIMIZE_SLA_MS"),
    ("static/index.html", "function _scheduleServerAnalyticsWarm"),
    ("static/index.html", "function renderTierCPartialAnalytics"),
    ("static/index.html", "analytics_partial_tier_c"),
    ("server.py", "UI_MAXIMIZE_SLA_MS"),
    ("server.py", 'POST /api/analytics/warm'),
    ("server.py", "def post_analytics_warm"),
    ("server.py", "_schedule_analytics_warm"),
    ("ml_predict.py", "def prewarm_inference_models_for_ticker"),
    ("server.py", "_get_quote_hot_executor"),
    ("features/shared_sequence_context.py", "build_guest_wire_sequence_context"),
    ("AGENTS.md", "Mandatory enforcement registry"),
    ("AGENTS.md", "Meet-or-Exceed Closure Cycle"),
    ("server.py", '@app.get("/api/build")'),
)
INSTITUTIONAL_BANNED_SERVER_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "analytics_stale must not be sse_live alone (institutional operator coherence)",
        re.compile(
            r"md\[\"analytics_stale\"\]\s*=\s*bool\s*\(\s*sse_live\s+or\s+\(",
            re.MULTILINE,
        ),
    ),
)


def check_ablation_schwab_universe_contract() -> list[str]:
    """AGENTS § Ablation universe — Schwab-catalog first."""
    errors: list[str] = []
    build_py = REPO_ROOT / "tools" / "build_feature_assignment_matrix_v2.py"
    gate_py = REPO_ROOT / "tools" / "feature_curation_gate.py"
    agents = REPO_ROOT / "AGENTS.md"
    for path, needle in (
        (build_py, "resolve_expanded_schwab_ablation_universe"),
        (build_py, "MIN_ABLATION_EXPANSION_FACTOR"),
        (build_py, "build_schwab_ablation_field_registry"),
        (gate_py, "whole_stack_cell_target"),
        (agents, "Schwab-catalog ablation universe"),
    ):
        if not path.is_file():
            errors.append(f"{path}: missing (Schwab ablation universe contract)")
            continue
        if needle not in path.read_text(encoding="utf-8", errors="replace"):
            errors.append(f"{path}: missing Schwab ablation marker {needle!r}")
    registry = REPO_ROOT / "governance" / "artifacts" / "schwab_ablation_field_registry.json"
    manifest = REPO_ROOT / "governance" / "artifacts" / "feature_ablation_manifest_leaf.json"
    if not registry.is_file():
        errors.append(f"missing {registry} — run build_schwab_ablation_field_registry")
    else:
        try:
            reg = json.loads(registry.read_text(encoding="utf-8"))
            n = int(reg.get("schwab_field_count") or 0)
            if n < 2300:
                errors.append(f"schwab_ablation_field_registry: expected ~2393 rows, got {n}")
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            errors.append(f"schwab_ablation_field_registry unreadable: {exc}")
    if manifest.is_file():
        try:
            man = json.loads(manifest.read_text(encoding="utf-8"))
            grain = str((man.get("ablation_method") or {}).get("feature_grain") or "")
            if grain != "schwab_expanded_atomic":
                errors.append(f"manifest feature_grain must be schwab_expanded_atomic (got {grain!r})")
            reg_n = int((man.get("totals") or {}).get("registered_ml_cone_columns") or 0)
            ablate_n = int((man.get("totals") or {}).get("ablation_group_count") or 0)
            ratio = float((man.get("totals") or {}).get("expansion_ratio_vs_cone") or 0)
            if reg_n > 0 and ablate_n < reg_n * 2:
                errors.append(
                    f"manifest ablation_group_count {ablate_n} < 2× registered cone {reg_n}"
                )
            if reg_n > 0 and ratio < 2.0:
                errors.append(f"manifest expansion_ratio_vs_cone {ratio} < 2.0")
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            errors.append(f"feature_ablation_manifest_leaf unreadable: {exc}")
    return errors


_ZERO_BIAS_AGENTS_MARKERS: tuple[str, ...] = (
    "ZERO-BIAS",
    "model × horizon",
    "build toward the **zero-bias target**",
    "members` as assignment",
    "Candidate-discovery pinned to XGB",
    "check_zero_bias_ablation_contract",
)

# Feature-consuming ablation models → manifest ingest families checked by the detector.
# Transformer: 5m structure stream only (prepare_transformer_data / _permute_eval_transformer_group
# use ENCODED_FEATURES_5M — no X_1m, no X_conf). LSTM: dual stream + confluence via drop_conf.
ZERO_BIAS_FEATURE_MODEL_INGEST_FAMILIES: dict[str, tuple[str, ...]] = {
    "xgb": ("xgb",),
    "lstm": ("lstm_5m", "lstm_1m"),
    "transformer": ("lstm_5m",),
}
ZERO_BIAS_WHOLE_STACK_LAYERS: tuple[str, ...] = ("meta", "monte_carlo", "regime", "fusion")


def check_zero_bias_ablation_contract() -> list[str]:
    """AGENTS § ZERO-BIAS — survivor output is the only placement router (O-56)."""
    errors: list[str] = []
    agents = REPO_ROOT / "AGENTS.md"
    if not agents.is_file():
        errors.append("AGENTS.md missing (ZERO-BIAS contract)")
        return errors
    agents_text = agents.read_text(encoding="utf-8", errors="replace")
    for marker in _ZERO_BIAS_AGENTS_MARKERS:
        if marker not in agents_text:
            errors.append(f"AGENTS.md: missing ZERO-BIAS marker {marker!r}")

    manifest_path = REPO_ROOT / "governance" / "artifacts" / "feature_ablation_manifest_leaf.json"
    if not manifest_path.is_file():
        errors.append(f"missing {manifest_path} — ZERO-BIAS requires live manifest")
        return errors
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"feature_ablation_manifest_leaf unreadable: {exc}")
        return errors

    method = payload.get("ablation_method") or {}
    primary = str(method.get("primary_pass") or "").lower()
    confirm = str(method.get("confirm_pass") or "").lower()
    if "grouped" in primary or "grouped" in confirm:
        errors.append(
            "manifest ablation_method still grouped — target is atomic per-feature per (model × horizon)"
        )

    model_families = ("xgb", "lstm_5m", "lstm_1m")

    # MODEL COVERAGE — all 7 FULL_STACK layers must be EXPLICITLY accounted (no silent 3-of-7).
    # Feature-consuming base models (ablation_method.models) each map to ingest-checked families;
    # upper-stack layers consume base OUTPUTS (no raw-feature members) → covered by whole-stack scoring.
    try:
        from governed_stack_contract import FULL_STACK_MODEL_LAYERS as _FULL_STACK
    except Exception:
        _FULL_STACK = ("xgb", "lstm", "transformer", "meta", "monte_carlo", "regime", "fusion")
    _feature_models = tuple(method.get("models") or ("xgb", "lstm", "transformer"))
    for _fm in _feature_models:
        _fams = ZERO_BIAS_FEATURE_MODEL_INGEST_FAMILIES.get(_fm)
        if _fams is None:
            errors.append(f"ZERO-BIAS coverage: feature-model {_fm!r} (in ablation_method.models) has NO ingest mapping in the detector — add it; the gate must check every feature-consuming model")
        elif not all(f in model_families for f in _fams):
            errors.append(f"ZERO-BIAS coverage: feature-model {_fm!r} maps to {_fams}, not all ingest-checked")
    _classified = set(_feature_models) | set(ZERO_BIAS_WHOLE_STACK_LAYERS)
    for _layer in _FULL_STACK:
        if _layer not in _classified:
            errors.append(f"ZERO-BIAS coverage: stack layer {_layer!r} unclassified (must be a checked feature-model OR a named whole-stack layer) — no silent omission of any of the 7")

    groups = [g for g in (payload.get("groups") or []) if g.get("disposition") == "ABLATE"]
    if not groups:
        errors.append("ablation manifest has no ABLATE groups")
        return errors

    errors.extend(check_feature_list_no_model_preassignment())

    from tools.build_feature_assignment_matrix_v2 import (
        _registered_ml_columns,
        atomic_column_for_manifest_group,
    )

    registered = _registered_ml_columns()
    live_union = set().union(*registered.values())
    manifest_atomic_cols: set[str] = set()
    reg_atomic_cols: set[str] = set()
    mislabeled_not_wired = 0
    mislabeled_in_cone = 0
    missing_atomic = 0
    db_wire: set[str] = set()
    try:
        from db import DB_PATH as _DBP
        from tools.feature_curation_gate import ablation_db_wire_ablatable_columns

        dbp = _DBP if isinstance(_DBP, Path) else Path(str(_DBP))
        if dbp.is_file():
            db_wire = ablation_db_wire_ablatable_columns(str(dbp))
    except Exception:
        db_wire = set()
    for g in groups:
        col = atomic_column_for_manifest_group(g)
        if not col:
            missing_atomic += 1
            continue
        manifest_atomic_cols.add(col)
        tier = str(g.get("catalog_tier") or "")
        if tier.startswith("REGISTERED"):
            reg_atomic_cols.add(col)
        registered_ml_cone = tier in ("REGISTERED_UNIVERSE", "REGISTERED_CONFLUENCE") and col in live_union
        must_be_in_cone = registered_ml_cone or (bool(db_wire) and col in db_wire)
        if db_wire:
            if (
                g.get("ingest_status") == "in_cone"
                and col not in db_wire
                and not registered_ml_cone
            ):
                mislabeled_in_cone += 1
            if g.get("ingest_status") == "not_wired" and must_be_in_cone:
                mislabeled_not_wired += 1
        elif g.get("ingest_status") == "not_wired" and registered_ml_cone:
            mislabeled_not_wired += 1
    if missing_atomic:
        errors.append(
            f"BIAS: {missing_atomic} ABLATE groups missing atomic_column — one atomic feature per row"
        )
    if mislabeled_in_cone:
        errors.append(
            f"BIAS: {mislabeled_in_cone} in_cone groups are not DB-wire ablatable — "
            f"reconcile manifest ingest_status to ablation_db_wire_ablatable_columns"
        )
    if mislabeled_not_wired:
        errors.append(
            f"BIAS: {mislabeled_not_wired} not_wired groups belong in the ML/DB wire cone — "
            f"ingest_status must be in_cone"
        )
    try:
        import lstm_data

        conf = set(getattr(lstm_data, "CONFLUENCE_FEATURES", []) or [])
        wire_scoring_cols: set[str] = set()
        try:
            from db import DB_PATH as _DBP
            from tools.feature_curation_gate import (
                ablation_db_wire_ablatable_columns,
                ablation_scoring_groups,
            )

            if (_DBP if isinstance(_DBP, Path) else Path(str(_DBP))).is_file():
                dbp_s = str(_DBP)
                wire_scoring_cols = {
                    str(atomic_column_for_manifest_group(g) or "")
                    for g in ablation_scoring_groups(payload, db_path=dbp_s)
                }
                wire = ablation_db_wire_ablatable_columns(dbp_s)
                conf_in_scoring = sorted(c for c in conf if c in wire_scoring_cols)
                if conf_in_scoring:
                    errors.append(
                        f"BIAS: LSTM confluence features in wire scoring groups without DB persistence: "
                        f"{conf_in_scoring}"
                    )
                conf_in_wire = sorted(c for c in conf if c in wire)
                if conf_in_wire:
                    errors.append(
                        f"BIAS: confluence columns on DB wire surface (unexpected): {conf_in_wire}"
                    )
        except Exception as exc:  # pragma: no cover - defensive
            errors.append(f"could not verify wire-only confluence exclusion: {exc}")
    except Exception as exc:  # pragma: no cover - defensive
        errors.append(f"could not verify live-feature coverage: {exc}")
    try:
        drift = live_union ^ reg_atomic_cols
        if drift:
            errors.append(
                f"STALE: manifest registered atomic columns differ from live cone by {len(drift)} "
                f"columns — regenerate manifest"
            )
    except Exception as exc:  # pragma: no cover - defensive
        errors.append(f"could not verify cone staleness: {exc}")

    try:
        db_wire_verify: set[str] = set(db_wire)
        if not db_wire_verify:
            try:
                from db import DB_PATH as _DBP
                from tools.feature_curation_gate import ablation_db_wire_ablatable_columns

                dbp = _DBP if isinstance(_DBP, Path) else Path(str(_DBP))
                if dbp.is_file():
                    db_wire_verify = ablation_db_wire_ablatable_columns(str(dbp))
            except Exception:
                db_wire_verify = set()
        not_ingestible: list[str] = []
        for g in groups:
            tier = str(g.get("catalog_tier") or "")
            if not tier.startswith("REGISTERED"):
                continue
            col = atomic_column_for_manifest_group(g)
            if not col:
                continue
            gid = str(g.get("group_id") or "?")
            if col in db_wire_verify:
                continue
            if col not in live_union:
                not_ingestible.append(f"{gid}:{col}")
        if not_ingestible:
            sample = ", ".join(not_ingestible[:4])
            errors.append(
                f"BIAS: {len(not_ingestible)} registered manifest features not in live ingest cone "
                f"— e.g. {sample}. Regenerate manifest from live code."
            )
    except Exception as exc:  # pragma: no cover - defensive
        errors.append(f"could not verify registered ingest coverage: {exc}")
    return errors


def check_ablation_agnostic_ingest_contract() -> list[str]:
    """Wire-only ablation ingest — DB identity enrich; scoring groups filtered to DB wire atoms."""
    errors: list[str] = []
    agents = REPO_ROOT / "AGENTS.md"
    if agents.is_file():
        agents_text = agents.read_text(encoding="utf-8", errors="replace")
        for marker in (
            "Ablation producer→consumer inventory",
            "audit_ablation_ingest_purity",
            "audit_ablation_score_path_bias",
            "check_ablation_agnostic_ingest_contract",
            "ready_for_unbiased_ablation",
        ):
            if marker not in agents_text:
                errors.append(f"AGENTS.md: missing agnostic-ingest marker {marker!r}")

    gate_py = REPO_ROOT / "tools" / "feature_curation_gate.py"
    if not gate_py.is_file():
        errors.append("agnostic ingest: missing feature_curation_gate.py")
        return errors
    gate_text = gate_py.read_text(encoding="utf-8", errors="replace")
    for required in (
        "ablation_db_wire_ablatable_columns",
        "audit_ablation_ingest_purity",
        "audit_ablation_score_path_bias",
        "ready_for_unbiased_ablation",
        "ready_for_production_path_ablation",
        "DB identity row surface",
        "ABLATION_INGEST_DERIVED_PREFIXES",
    ):
        if required not in gate_text:
            errors.append(f"agnostic ingest: feature_curation_gate.py missing {required!r}")

    enrich_banned = (
        "attach_confluence_feature_columns",
        "engineer_single_snapshot(",
        "build_xgb_pre_engineering_snapshot_for_tick(",
    )
    try:
        import ast

        tree = ast.parse(gate_text, filename=str(gate_py))
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            if node.name != "_enrich_rows_for_whole_stack_ablation":
                continue
            fn_src = ast.get_source_segment(gate_text, node) or ""
            for banned in enrich_banned:
                if banned in fn_src:
                    errors.append(
                        f"agnostic ingest: _enrich_rows_for_whole_stack_ablation must not call {banned!r}"
                    )
    except SyntaxError as exc:
        errors.append(f"agnostic ingest: cannot AST-parse feature_curation_gate.py ({exc})")

    abi_py = REPO_ROOT / "arch_competition" / "ablation_bundle_inference.py"
    if abi_py.is_file():
        abi_text = abi_py.read_text(encoding="utf-8", errors="replace")
        for tok in (
            "wire_neutral_xgb_predict_from_row",
            "wire_neutral_confluence_vector",
            "wire_row_surface_bars",
            "score_unified_ablation_fusion_from_wire_row",
        ):
            if tok not in abi_text:
                errors.append(f"agnostic ingest: ablation_bundle_inference.py missing {tok!r}")

    mp_py = REPO_ROOT / "ml_predict.py"
    if mp_py.is_file():
        mp_text = mp_py.read_text(encoding="utf-8", errors="replace")
        if "overlay_ablation_wire_row_on_sequence_bars" in mp_text:
            errors.append(
                "agnostic ingest: ml_predict.py must not reference overlay_ablation_wire_row_on_sequence_bars"
            )
        if "ablation_wire_row" in mp_text:
            errors.append("agnostic ingest: ml_predict.py must not thread ablation_wire_row")

    if "ablation_db_wire_ablatable_columns" not in gate_text.split("def ablation_scoring_groups", 1)[-1][:800]:
        errors.append(
            "agnostic ingest: ablation_scoring_groups must filter to ablation_db_wire_ablatable_columns"
        )

    return errors


def check_ablation_manifest_generator_no_model_preassignment() -> list[str]:
    """ZERO-BIAS — manifest group-builder source must not emit model-stamp fields."""
    errors: list[str] = []
    path = REPO_ROOT / "tools" / "build_feature_assignment_matrix_v2.py"
    if not path.is_file():
        errors.append("ZERO-BIAS generator: build_feature_assignment_matrix_v2.py missing")
        return errors
    text = path.read_text(encoding="utf-8", errors="replace")
    if "resolve_ablation_universe_legacy_stack_only" in text:
        errors.append(
            "ZERO-BIAS generator: resolve_ablation_universe_legacy_stack_only must be deleted — "
            "no compound model-stamp builder may remain"
        )
    banned_emit = ('"members":', '"member_counts":', '"members_note":', '"horizon_disposition":')
    for token in banned_emit:
        if token in text:
            errors.append(
                f"ZERO-BIAS generator: {path.name} still contains group-dict emission {token} — "
                f"feature list builders must use _atomic_ablation_group (pure features only)"
            )
    return errors


def check_feature_list_no_model_preassignment() -> list[str]:
    """AGENTS § ZERO-BIAS — the feature list is JUST features; NO model may be pre-ordained in it.
    Model x horizon placement is ablation's OUTPUT, derived live from each model's interface — never
    baked into the data. Any feature entry carrying members / member_counts / members_note (model
    pre-assignment) is pre-bias and FAILS the build. The runtime already derives columns from the
    live cone, so these fields are vestigial bias that must be removed from the list itself.
    (This gate exists because 'stripped' was asserted repeatedly while the tags stayed in the data —
    now it's mechanically true or the build is red.)"""
    errors: list[str] = []
    manifest = REPO_ROOT / "governance" / "artifacts" / "feature_ablation_manifest_leaf.json"
    if not manifest.is_file():
        return errors
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        errors.append(f"feature-list bias check: manifest unreadable: {exc}")
        return errors
    banned = ("members", "member_counts", "members_note", "horizon_disposition")
    hits = [
        (g.get("group_id"), [k for k in banned if k in g])
        for g in (data.get("groups") or [])
        if any(k in g for k in banned)
    ]
    if hits:
        errors.append(
            f"ZERO-BIAS feature list: {len(hits)}/{len(data.get('groups') or [])} feature entries "
            f"pre-ordain models (e.g. {hits[0][0]} carries {hits[0][1]}). The list must be JUST "
            f"features — strip model/horizon pre-assignment fields in the manifest generator; model x "
            f"horizon placement is ablation's output, derived live, never baked into the data."
        )
    return errors


def check_ablation_single_authority() -> list[str]:
    """One grid authority — leaf manifest/report only; no compound fallback or stamped legacy artifacts."""
    errors: list[str] = []
    legacy_manifest = REPO_ROOT / "governance" / "artifacts" / "feature_ablation_manifest.json"
    legacy_report = REPO_ROOT / "governance" / "artifacts" / "feature_ablation_report.json"
    if legacy_manifest.is_file():
        errors.append(
            f"ablation authority: stamped legacy manifest still on disk ({legacy_manifest}) — delete it"
        )
    if legacy_report.is_file():
        errors.append(
            f"ablation authority: legacy compound report still on disk ({legacy_report}) — delete it"
        )
    stack_py = REPO_ROOT / "arch_competition" / "stack_bundle_eval_v1.py"
    if stack_py.is_file():
        text = stack_py.read_text(encoding="utf-8", errors="replace")
        if "return LEGACY_COMPOUND_MANIFEST_PATH" in text:
            errors.append(
                "ablation authority: stack_bundle_eval_v1 still falls back to LEGACY_COMPOUND_MANIFEST_PATH"
            )
    gate_py = REPO_ROOT / "tools" / "feature_curation_gate.py"
    if gate_py.is_file():
        text = gate_py.read_text(encoding="utf-8", errors="replace")
        if "--ablation-include-o56" in text and "Parallel ablation paths retired" not in text:
            errors.append(
                "ablation authority: feature_curation_gate still exposes parallel O-56 path without hard reject"
            )
    return errors


def check_no_ablation_gate_bypass_in_money_path() -> list[str]:
    """AGENTS § No patches — solid fixes only. Covers the ENTIRE seven-model stack load/score path
    (xgb, lstm, transformer, meta, monte_carlo, regime, fusion + adapters + orchestration), not a
    hand-picked subset. Ablation must NOT relax production gates to force stale/legacy bundles
    through the live path. The ablation-scored-eval flag and any silent
    sequence prefix-slice (live-width -> legacy-checkpoint-width) belong in an OFFLINE scorer, never
    in the inference money-path: a prefix-slice feeds the model the FIRST N live features, which are
    NOT the N it trained on, so LSTM/Transformer knockout scores are semantically wrong while
    preflight reads green. Any such reference in an inference module is a patch -> rejection-grade."""
    errors: list[str] = []
    # The ENTIRE seven-model stack's production load/score path — a gate-relax patch is forbidden across
    # ALL of it, never a hand-picked subset. Every one of xgb, lstm, transformer, meta, monte_carlo,
    # regime, fusion (with its input adapter) + the orchestration/contracts. The offline scorer
    # (arch_competition/**) is the ONLY place legacy-bundle adaptation may live.
    money_path = (
        # xgb
        "xgboost_model.py", "ml_predict.py", "ml_train.py", "features/xgb_model_input.py",
        # lstm
        "lstm_data.py", "lstm_model.py", "features/lstm_sequence_input.py",
        # transformer
        "transformer_model.py", "transformer_train.py",
        # meta (weighted / stacked overlay)
        "prediction_engine.py",
        # monte_carlo
        "monte_carlo.py", "mc_fusion_adjustment.py", "features/monte_carlo_stack_input.py",
        # regime
        "regime_engine.py",
        # fusion
        "bayesian_fusion.py", "fusion_contract.py", "features/fusion_model_input.py",
        # orchestration + contracts
        "signals.py", "rules_engine.py", "model_contract.py", "active_bundle_contract.py",
    )
    # Deprecated gate-relax tokens only — NOT ED_ABLATION_SCORING_PASS / ablation_scoring_pass_active
    # (legitimate offline-scoring pass with thin delegate to arch_competition/**).
    bypass_re = re.compile(
        r"ED_ABLATION_SCORED_EVAL|_is_ablation_scored_eval|check_ablation_scorable_bundle",
        re.IGNORECASE,
    )
    ml_predict_delegate_markers = (
        "ablation_scoring_pass_active",
        "ablation_bundle_inference",
        "validate_ablation_scoring_bundle_meta",
    )
    slice_tokens = ("align_encoded_sequence_to_checkpoint", "[:, :, :pre_w]", "[:,:,:pre_w]")
    for rel in money_path:
        p = REPO_ROOT / rel
        if not p.is_file():
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        m = bypass_re.search(text)
        if m:
            errors.append(
                f"PATCH: {rel} references deprecated ablation gate-relax ({m.group(0)!r}) — "
                f"use ED_ABLATION_SCORING_PASS + offline scorer (arch_competition/**) only."
            )
        if rel == "ml_predict.py" and "ablation_scoring_pass_active" in text:
            missing_delegate = [t for t in ml_predict_delegate_markers if t not in text]
            if missing_delegate:
                errors.append(
                    f"PATCH: ml_predict.py uses ablation_scoring_pass_active without offline delegate "
                    f"markers {missing_delegate!r} — production path must stay fail-closed."
                )
        elif rel != "ml_predict.py" and "ablation_scoring_pass_active" in text:
            errors.append(
                f"PATCH: {rel} references ablation_scoring_pass_active outside ml_predict thin-delegate — "
                f"legacy encode belongs in arch_competition/ablation_bundle_inference.py only."
            )
        if any(tok in text for tok in slice_tokens):
            errors.append(
                f"PATCH: {rel} silent-prefix-slices the sequence tensor to a legacy checkpoint width — "
                f"the first N live features are NOT the trained N. Use frozen-lineage encode (trained "
                f"feature names from meta) or fail closed; never silent-slice."
            )
    return errors


def check_ablation_seven_model_four_horizon_grid() -> list[str]:
    """AGENTS § Ablation grid — all seven stack models × all four horizons (operator binding).

    Rejects partial grids (feature×horizon-only, base-3-only, missing horizons/models).
    Runs on every pre-commit — spec shape must match operator intent before any scored run.
    """
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from governed_stack_contract import FULL_STACK_MODEL_LAYERS, STAGE3_ABLATION_HORIZONS

    errors: list[str] = []
    agents = REPO_ROOT / "AGENTS.md"
    if agents.is_file():
        agents_text = agents.read_text(encoding="utf-8", errors="replace")
        for marker in (
            "Ablation grid — all seven models × all four horizons",
            "check_ablation_seven_model_four_horizon_grid",
        ):
            if marker not in agents_text:
                errors.append(f"AGENTS.md: missing ablation grid marker {marker!r}")

    gate_py = REPO_ROOT / "tools" / "feature_curation_gate.py"
    if gate_py.is_file():
        gate_text = gate_py.read_text(encoding="utf-8", errors="replace")
        banned_fragments = (
            "feature × horizon only",
            "feature×horizon only",
            "Stage 3 grid: feature × horizon only",
        )
        for frag in banned_fragments:
            if frag in gate_text:
                errors.append(
                    f"feature_curation_gate.py: banned partial-grid doc {frag!r} — "
                    f"grid must be feature × all 7 models × all 4 horizons"
                )

    try:
        from tools.ablation_static_lock_index import get_ablation_static_lock_index
        from tools.feature_curation_gate import (
            ablation_cell_accounting,
            ablation_grid_groups,
            ablation_scoring_groups,
            whole_stack_catalog_cell_target,
            whole_stack_fusion_cell_target,
        )
    except Exception as exc:  # pragma: no cover - defensive
        errors.append(f"ablation grid: cannot import feature_curation_gate ({exc})")
        return errors

    idx = get_ablation_static_lock_index()
    if idx.gate_import_error:
        errors.append(
            f"ablation grid: cannot import feature_curation_gate ({idx.gate_import_error})"
        )
        return errors

    manifest_path = idx.manifest_path
    if not manifest_path.is_file():
        errors.append(f"ablation grid: missing {manifest_path}")
        return errors

    if idx.manifest_load_error:
        errors.append(f"ablation grid: manifest unreadable: {idx.manifest_load_error}")
        return errors

    if idx.spec_build_error:
        errors.append(f"ablation grid: spec build failed: {idx.spec_build_error}")
        return errors

    manifest = idx.manifest
    enriched = idx.enriched
    specs = idx.specs
    required_models = list(FULL_STACK_MODEL_LAYERS)
    required_horizons = list(STAGE3_ABLATION_HORIZONS)
    captured = ablation_grid_groups(manifest)
    dbp_str = str(idx.db_path) if idx.db_path is not None else None
    scoring = ablation_scoring_groups(manifest, db_path=dbp_str)
    from tools.ablation_static_lock_index import enriched_rows_for_spec_build

    accounting = ablation_cell_accounting(
        manifest, specs, enriched_rows=enriched_rows_for_spec_build(enriched)
    )
    catalog_target = whole_stack_catalog_cell_target(manifest)
    runnable_target = int(accounting.get("runnable_target") or 0)
    catalog_formula = len(captured) * len(required_models) * len(required_horizons)
    scoring_formula = len(scoring) * len(required_models) * len(required_horizons)

    if catalog_target != catalog_formula:
        errors.append(
            f"ablation grid: whole_stack_catalog_cell_target={catalog_target} != "
            f"features({len(captured)})×models({len(required_models)})×"
            f"horizons({len(required_horizons)})={catalog_formula}"
        )
    if whole_stack_fusion_cell_target(manifest) != runnable_target:
        errors.append(
            "ablation grid: whole_stack_fusion_cell_target must equal runnable_target "
            "(enriched row sample required for fidelity-first runnable count)"
        )
    if len(specs) != scoring_formula:
        errors.append(
            f"ablation grid: scoring spec count {len(specs)} != in_cone({len(scoring)})×"
            f"models({len(required_models)})×horizons({len(required_horizons)})={scoring_formula} "
            f"(Stage 3 scores in_cone only; catalog retains not_wired Schwab slots)"
        )
    if accounting.get("runnable_target") != runnable_target:
        errors.append("ablation grid: ablation_cell_accounting runnable_target mismatch")
    if runnable_target > scoring_formula:
        errors.append(
            f"ablation grid: runnable_target={runnable_target} exceeds scoring grid {scoring_formula}"
        )

    if not specs:
        errors.append("ablation grid: zero placement cells — grid is empty")
        return errors

    missing_model_on_spec = [s for s in specs if not s.get("model_family")]
    if missing_model_on_spec:
        errors.append(
            f"ablation grid: {len(missing_model_on_spec)} cells missing model_family — "
            f"every cell must name one of the seven stack models"
        )

    bad_models = sorted(
        {str(s.get("model_family")) for s in specs if s.get("model_family")} - set(required_models)
    )
    if bad_models:
        errors.append(f"ablation grid: unknown model_family values {bad_models!r}")

    have_models = {str(s.get("model_family")) for s in specs if s.get("model_family")}
    missing_models = [m for m in required_models if m not in have_models]
    if missing_models:
        errors.append(
            f"ablation grid: missing stack models on grid axis {missing_models!r} — "
            f"all seven required: {required_models}"
        )

    have_hz = {str(s.get("horizon_slug")) for s in specs if s.get("horizon_slug")}
    missing_hz = [h for h in required_horizons if h not in have_hz]
    if missing_hz:
        errors.append(
            f"ablation grid: missing horizons on grid axis {missing_hz!r} — "
            f"all four required: {required_horizons}"
        )

    expected_triples: set[tuple[str, str, str]] = set()
    for g in scoring:
        gid = str(g["group_id"])
        for model in required_models:
            for hz in required_horizons:
                expected_triples.add((gid, model, hz))

    spec_triples = {
        (str(s.get("group_id")), str(s.get("model_family")), str(s.get("horizon_slug")))
        for s in specs
        if s.get("group_id") and s.get("model_family") and s.get("horizon_slug")
    }
    missing_triples = expected_triples - spec_triples
    if missing_triples:
        sample = ", ".join(f"{gid}@{model}/{hz}" for gid, model, hz in sorted(missing_triples)[:4])
        errors.append(
            f"ablation grid: missing {len(missing_triples)} (feature×model×horizon) cells "
            f"(e.g. {sample})"
        )

    silent_empty = [
        s for s in specs
        if not s.get("group_columns") and s.get("grid_skip_reason") is None
    ]
    if silent_empty:
        errors.append(
            f"ablation grid: {len(silent_empty)} cells have empty group_columns without "
            f"grid_skip_reason — every non-scorable cell must document why (not_wired, no_model_interface, …)"
        )

    return errors


def check_ablation_equal_layer_consumers() -> list[str]:
    """FIX-1: each stack model resolves its own knockout columns — no base-entry union for upper layers."""
    errors: list[str] = []
    gate_py = REPO_ROOT / "tools" / "feature_curation_gate.py"
    if not gate_py.is_file():
        errors.append("ablation equal-layer: missing tools/feature_curation_gate.py")
        return errors
    gate_text = gate_py.read_text(encoding="utf-8", errors="replace")
    banned_fragments = (
        "_whole_stack_group_columns_all_entry_points",
        "no_stack_entry_columns",
        "_ablation_in_cone_fallback_columns",
        "registry gaps use fallback",
    )
    for frag in banned_fragments:
        if frag in gate_text:
            errors.append(
                f"ablation equal-layer: feature_curation_gate.py still references banned "
                f"registry/fallback bias {frag!r} — use fidelity-first unified knockouts"
            )
    required_markers = (
        "_ablation_atomic_knockout_column_candidates",
        "_whole_stack_knockout_columns",
        "audit_ablation_row_fidelity",
        "ablation_scoring_groups",
        "knockout_resolution",
    )
    for marker in required_markers:
        if marker not in gate_text:
            errors.append(
                f"ablation fidelity: feature_curation_gate.py missing required marker {marker!r}"
            )

    contract_py = REPO_ROOT / "governed_stack_contract.py"
    if contract_py.is_file():
        ctext = contract_py.read_text(encoding="utf-8", errors="replace")
        for marker in (
            "stack_layer_ablation_snapshot_columns",
            "REGIME_LAYER_SNAPSHOT_COLUMNS",
            "FUSION_OVERLAY_SNAPSHOT_COLUMNS",
            "atomic_column_consumed_by_stack_layer",
        ):
            if marker not in ctext:
                errors.append(f"ablation equal-layer: governed_stack_contract.py missing {marker!r}")

    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    try:
        from governed_stack_contract import FULL_STACK_MODEL_LAYERS, STACK_AUTHORITY_LAYERS
        from tools.ablation_static_lock_index import get_ablation_static_lock_index
        from tools.feature_curation_gate import ablation_row_fidelity_sample_active
    except Exception as exc:  # pragma: no cover
        errors.append(f"ablation equal-layer: import failed ({exc})")
        return errors

    idx = get_ablation_static_lock_index()
    if idx.gate_import_error:
        errors.append(f"ablation equal-layer: import failed ({idx.gate_import_error})")
        return errors

    if not idx.manifest_path.is_file():
        return errors

    if idx.manifest_load_error or idx.spec_build_error:
        errors.append(
            f"ablation equal-layer: manifest/spec build failed: "
            f"{idx.manifest_load_error or idx.spec_build_error}"
        )
        return errors

    specs = idx.specs
    fidelity_active = ablation_row_fidelity_sample_active(idx.enriched)

    multi_base_upper = [
        s
        for s in specs
        if s.get("model_family") in STACK_AUTHORITY_LAYERS
        and len(s.get("stack_entry_layers") or []) > 1
    ]
    if multi_base_upper:
        sample = multi_base_upper[0]
        errors.append(
            f"ablation equal-layer: {len(multi_base_upper)} upper-layer cells list multiple "
            f"stack_entry_layers (e.g. {sample.get('group_id')}@{sample.get('model_family')} "
            f"layers={sample.get('stack_entry_layers')!r}) — one layer per cell only"
        )

    wrong_entry = [
        s
        for s in specs
        if s.get("group_columns")
        and s.get("stack_entry_layers")
        and s.get("model_family") not in (s.get("stack_entry_layers") or [])
    ]
    if wrong_entry:
        sample = wrong_entry[0]
        errors.append(
            f"ablation equal-layer: cell {sample.get('group_id')}@{sample.get('model_family')} "
            f"has columns but stack_entry_layers={sample.get('stack_entry_layers')!r} "
            f"≠ [model_family]"
        )

    in_cone = [
        s
        for s in specs
        if s.get("ingest_status") == "in_cone" and s.get("model_family") in FULL_STACK_MODEL_LAYERS
    ]
    regime_fusion_scorable = [
        s for s in in_cone if s.get("model_family") in ("regime", "fusion", "meta") and s.get("group_columns")
    ]
    if fidelity_active and not regime_fusion_scorable:
        errors.append(
            "ablation equal-layer: zero in_cone regime/fusion/meta cells with group_columns — "
            "upper-layer registries may be empty or miswired"
        )

    preplacement = [
        s
        for s in specs
        if s.get("ingest_status") == "in_cone"
        and str(s.get("grid_skip_reason") or "") == "no_model_interface"
    ]
    if preplacement:
        sample = preplacement[0]
        errors.append(
            f"ablation ZERO-BIAS: {len(preplacement)} in_cone cells use banned pre-placement "
            f"skip no_model_interface (e.g. {sample.get('group_id')}@{sample.get('model_family')})"
        )

    runnable_by_model: dict[str, int] = {}
    for s in specs:
        if s.get("runnable"):
            mf = str(s.get("model_family") or "")
            runnable_by_model[mf] = runnable_by_model.get(mf, 0) + 1
    counts = [runnable_by_model.get(m, 0) for m in FULL_STACK_MODEL_LAYERS]
    if fidelity_active and len(set(counts)) > 1:
        errors.append(
            f"ablation ZERO-BIAS: unequal runnable counts per model (pre-placement) — {runnable_by_model}"
        )

    ng_cells = [
        s for s in specs
        if s.get("group_id") == "reg__atomic__net_gamma"
        and s.get("horizon_slug") == "1c"
    ]
    if (
        fidelity_active
        and ng_cells
        and not all(s.get("runnable") for s in ng_cells if s.get("ingest_status") == "in_cone")
    ):
        errors.append(
            "ablation ZERO-BIAS: reg__atomic__net_gamma must be runnable on all seven models @1c"
        )

    return errors


def check_ablation_full_stack_non_negotiable() -> list[str]:
    """Non-negotiable ablation integrity — 7 models × 4 horizons; no partial-ready escape hatches.

    Binds operator rule (2026-06-06): partial grids, cell gating, and XGB-only ready are
    rejection-grade. Agents and CI must pass this on every run via pre-commit or
    ``python tools/feature_curation_gate.py --ablation-audit``.
    """
    errors: list[str] = []
    gate_py = REPO_ROOT / "tools" / "feature_curation_gate.py"
    if not gate_py.is_file():
        errors.append("ablation integrity: missing tools/feature_curation_gate.py")
        return errors
    gate_text = gate_py.read_text(encoding="utf-8", errors="replace")

    required_gate_markers = (
        'result["ready"] = bool(result["ready_for_unbiased_ablation"])',
        "ready_for_unbiased_ablation",
        "audit_ablation_ingest_purity",
        "ingest_purity",
        "audit_ablation_score_path_bias",
        "score_path_bias",
        "ABLATION_SCORING_PASS_ENV",
        "probe_whole_stack_seven_layers",
        "audit_ablation_placement_validity",
        "placement_validity",
        "audit_ablation_row_fidelity",
        "row_fidelity",
        "ablation_scoring_groups",
        "all seven stack models",
        "--ablation-audit",
        "--ablation-integrity",
        "build_ablation_experiment_integrity",
        "experiment_integrity",
        'if not pf["ready"]:',
    )
    for marker in required_gate_markers:
        if marker not in gate_text:
            errors.append(f"ablation integrity: feature_curation_gate.py missing {marker!r}")

    banned_gate_fragments = (
        "whole_stack_cell_gated",
        "per_model_cell_gated",
        'ready_for_xgb_per_model"] or result["ready_for_whole_stack"]',
        "XGB per-model ablation (--ablation-include-o56) can run now",
        "stack_probe_skipped",
        "check_ablation_scorable_bundle",
        "align_encoded_sequence_to_checkpoint",
        "ED_ABLATION_SCORED_EVAL",
    )
    for frag in banned_gate_fragments:
        if frag in gate_text:
            errors.append(
                f"ablation integrity: feature_curation_gate.py banned partial-path fragment {frag!r}"
            )

    offline_modules = (
        "arch_competition/ablation_bundle_inference.py",
        "arch_competition/encoder_lineage_v2.py",
    )
    for rel in offline_modules:
        p = REPO_ROOT / rel
        if not p.is_file():
            errors.append(f"ablation integrity: missing offline scorer {rel}")
            continue
        src = p.read_text(encoding="utf-8", errors="replace")
        if rel.endswith("ablation_bundle_inference.py"):
            for tok in (
                "try_load_lstm_offline",
                "try_load_transformer_offline",
                "predict_lstm_offline",
                "predict_transformer_offline",
                "validate_ablation_scoring_bundle_meta",
                "score_unified_ablation_fusion_from_wire_row",
                "wire_row_surface_bars",
            ):
                if tok not in src:
                    errors.append(f"ablation integrity: {rel} missing {tok!r}")
        if rel.endswith("encoder_lineage_v2.py"):
            for tok in ("resolve_encoder_lineage", "encode_snapshot_5m_v2", "ENCODED_FEATURES_5M_V2"):
                if tok not in src:
                    errors.append(f"ablation integrity: {rel} missing {tok!r}")

    mp_py = REPO_ROOT / "ml_predict.py"
    if mp_py.is_file():
        mp_text = mp_py.read_text(encoding="utf-8", errors="replace")
        if "ablation_scoring_pass_active" not in mp_text:
            errors.append("ablation integrity: ml_predict.py missing ablation_scoring_pass_active for bundle load")
        if "live_ablation_experiment_active" not in mp_text:
            errors.append("ablation integrity: ml_predict.py missing live_ablation_experiment_active for pre-train cards")
        if "resolve_experiment_bundle_dir" not in mp_text:
            errors.append("ablation integrity: ml_predict.py missing resolve_experiment_bundle_dir")
        if "validate_ablation_scoring_bundle_meta" not in mp_text:
            errors.append("ablation integrity: ml_predict.py missing validate_ablation_scoring_bundle_meta")
        if "try_load_lstm_offline" in mp_text or "predict_lstm_offline" in mp_text:
            errors.append(
                "ablation integrity: ml_predict.py must not delegate LSTM/TR scoring — "
                "use arch_competition/ablation_bundle_inference.py unified scorer only"
            )
        if "overlay_ablation_wire_row_on_sequence_bars" in mp_text or "ablation_wire_row" in mp_text:
            errors.append("ablation integrity: ml_predict.py must not thread ablation_wire_row or DB window overlay")
        if "ED_ABLATION_SCORED_EVAL" in mp_text:
            errors.append("ablation integrity: ml_predict.py must not reference ED_ABLATION_SCORED_EVAL")

    sbe_py = REPO_ROOT / "arch_competition" / "stack_bundle_eval_v1.py"
    if sbe_py.is_file():
        sbe_text = sbe_py.read_text(encoding="utf-8", errors="replace")
        for tok in ("def whole_stack_cell_gated", "def per_model_cell_gated"):
            if tok in sbe_text:
                errors.append(
                    f"ablation integrity: stack_bundle_eval_v1.py still defines cell gating ({tok}) — "
                    f"full 2632-cell grid must never skip scored cells"
                )
        if "ED_ABLATION_SCORING_PASS" not in sbe_text:
            errors.append("ablation integrity: stack_bundle_eval_v1.py missing ED_ABLATION_SCORING_PASS")
        if "LIVE_ABLATION_EXPERIMENT_ENV" not in sbe_text:
            errors.append("ablation integrity: stack_bundle_eval_v1.py missing LIVE_ABLATION_EXPERIMENT_ENV")

    agents = REPO_ROOT / "AGENTS.md"
    if agents.is_file():
        agents_text = agents.read_text(encoding="utf-8", errors="replace")
        for marker in (
            "check_ablation_full_stack_non_negotiable",
            "--ablation-audit",
            "audit_ablation_placement_validity",
            "audit_ablation_row_fidelity",
            "audit_ablation_ingest_purity",
            "check_graphrag_fidelity_ablation_contract",
            "check_ablation_agnostic_ingest_contract",
            "ready_for_unbiased_ablation",
        ):
            if marker not in agents_text:
                errors.append(f"AGENTS.md: missing ablation integrity marker {marker!r}")

    return errors


def audit_ablation_placement_validity(
    *,
    tickers: list[str] | None = None,
    horizons: list[str] | None = None,
    offline_probe: bool = True,
) -> dict:
    """Valid (feature × model × horizon) placement — not grid cardinality alone.

    Ablation scores **offline v2 bundles** under ED_ABLATION_SCORING_PASS — not live production
    serving. Fails when:
      * offline LSTM/TR won't load under ablation pass (bundle/scorer broken)
      * knockout columns resolve for lstm/transformer but do not map to checkpoint encoder indices
      * map_knockout_columns_to_encoder_indices (FIX 2) missing
    """
    import os

    errors: list[str] = []
    stats: dict = {}
    probe_tickers = tickers if tickers is not None else ["SPY"]
    probe_horizons = horizons if horizons is not None else ["1c"]
    stats["offline_probe_tickers"] = probe_tickers
    stats["offline_probe_horizons"] = probe_horizons

    abi = REPO_ROOT / "arch_competition" / "ablation_bundle_inference.py"
    if not abi.is_file() or "map_knockout_columns_to_encoder_indices" not in abi.read_text(
        encoding="utf-8", errors="replace"
    ):
        errors.append(
            "placement validity: ablation_bundle_inference.py missing "
            "map_knockout_columns_to_encoder_indices (FIX 2)"
        )

    if offline_probe:
        prev_ablation = os.environ.get("ED_ABLATION_SCORING_PASS")
        os.environ["ED_ABLATION_SCORING_PASS"] = "1"
        try:
            if str(REPO_ROOT) not in sys.path:
                sys.path.insert(0, str(REPO_ROOT))
            from active_bundle_contract import active_bundle_dir
            from arch_competition.ablation_bundle_inference import (
                map_knockout_columns_to_encoder_indices,
                try_load_lstm_offline,
                try_load_transformer_offline,
            )

            offline_failures: list[str] = []
            reference_checkpoint: dict | None = None
            for t in probe_tickers:
                for hz in probe_horizons:
                    bundle = active_bundle_dir(t, hz, models_dir=REPO_ROOT / "models")
                    if not bundle.is_dir():
                        offline_failures.append(f"missing bundle {t}/{hz}")
                        continue
                    lstm_loaded = try_load_lstm_offline(t, hz, bundle)
                    tr_loaded = try_load_transformer_offline(t, hz, bundle)
                    if lstm_loaded is None:
                        offline_failures.append(f"offline lstm {t}/{hz}")
                    elif reference_checkpoint is None:
                        reference_checkpoint = lstm_loaded[1]
                    if tr_loaded is None:
                        offline_failures.append(f"offline transformer {t}/{hz}")
            stats["offline_load_failures"] = offline_failures
            if offline_failures:
                sample = ", ".join(offline_failures[:6])
                errors.append(
                    f"placement validity: offline ablation loads failed (e.g. {sample}) — "
                    f"scorer must load v2 bundles under ED_ABLATION_SCORING_PASS"
                )

            manifest_path = (
                REPO_ROOT / "governance" / "artifacts" / "feature_ablation_manifest_leaf.json"
            )
            if reference_checkpoint is not None and manifest_path.is_file():
                from tools.feature_curation_gate import (
                    _atomic_column_for_group,
                    ablation_scoring_groups,
                    build_ablation_enriched_row_sample,
                    load_ablation_manifest,
                    _whole_stack_knockout_columns,
                )

                manifest = load_ablation_manifest(manifest_path)
                dbp = REPO_ROOT / "data" / "ed_console.db"
                enriched = (
                    build_ablation_enriched_row_sample(
                        db_path=str(dbp), manifest=manifest, tickers=probe_tickers
                    )
                    if dbp.is_file()
                    else []
                )
                groups = ablation_scoring_groups(manifest)
                lstm_noop: list[str] = []
                tr_noop: list[str] = []
                lstm_scorable = 0
                tr_scorable = 0
                lstm_variance_masked = 0
                tr_variance_masked = 0
                from arch_competition.ablation_bundle_inference import (
                    offline_v2_knockout_snapshot_columns,
                )

                for g in groups:
                    col = _atomic_column_for_group(g)
                    if not col:
                        continue
                    from tools.ablation_static_lock_index import enriched_rows_for_spec_build

                    if not _whole_stack_knockout_columns(
                        g, enriched_rows_for_spec_build(enriched)
                    ):
                        continue
                    lstm_cols = offline_v2_knockout_snapshot_columns(col, "lstm")
                    if lstm_cols:
                        from arch_competition.encoder_lineage_v2 import (
                            FEATURES_1M_V2,
                            FEATURES_5M_V2,
                        )

                        has_pre = has_post = False
                        cols_5m = [c for c in lstm_cols if c in FEATURES_5M_V2]
                        cols_1m = [c for c in lstm_cols if c in FEATURES_1M_V2]
                        if cols_5m:
                            m5 = map_knockout_columns_to_encoder_indices(
                                reference_checkpoint, cols_5m, stream="lstm_5m"
                            )
                            has_pre = has_pre or bool(m5.get("pre_mask_indices"))
                            has_post = has_post or bool(m5.get("post_mask_indices"))
                        if cols_1m:
                            m1 = map_knockout_columns_to_encoder_indices(
                                reference_checkpoint, cols_1m, stream="lstm_1m"
                            )
                            has_pre = has_pre or bool(m1.get("pre_mask_indices"))
                            has_post = has_post or bool(m1.get("post_mask_indices"))
                        if has_post:
                            lstm_scorable += 1
                        elif has_pre:
                            lstm_variance_masked += 1
                        else:
                            lstm_noop.append(col)
                    tr_cols = offline_v2_knockout_snapshot_columns(col, "transformer")
                    if tr_cols:
                        mapped = map_knockout_columns_to_encoder_indices(
                            reference_checkpoint, tr_cols, stream="transformer_5m"
                        )
                        if mapped.get("post_mask_indices"):
                            tr_scorable += 1
                        elif mapped.get("pre_mask_indices"):
                            tr_variance_masked += 1
                        else:
                            tr_noop.append(col)
                stats["captured_cone_atoms"] = len(groups)
                stats["lstm_scorable_atoms"] = lstm_scorable
                stats["transformer_scorable_atoms"] = tr_scorable
                stats["lstm_variance_masked_atoms"] = lstm_variance_masked
                stats["transformer_variance_masked_atoms"] = tr_variance_masked
                stats["lstm_noop_knockout_atoms"] = len(lstm_noop)
                stats["transformer_noop_knockout_atoms"] = len(tr_noop)
                if lstm_noop:
                    errors.append(
                        f"placement validity: {len(lstm_noop)}/{lstm_scorable} scorable lstm cells "
                        f"have knockouts that do not map to checkpoint encoder indices "
                        f"(e.g. {lstm_noop[:4]})"
                    )
                if tr_noop:
                    errors.append(
                        f"placement validity: {len(tr_noop)}/{tr_scorable} scorable transformer cells "
                        f"have knockouts that do not map to checkpoint encoder indices "
                        f"(e.g. {tr_noop[:4]})"
                    )
        except Exception as exc:
            errors.append(f"placement validity: offline probe failed: {type(exc).__name__}: {exc}")
        finally:
            if prev_ablation is None:
                os.environ.pop("ED_ABLATION_SCORING_PASS", None)
            else:
                os.environ["ED_ABLATION_SCORING_PASS"] = prev_ablation

    return {"ok": not errors, "errors": errors, "stats": stats}


def check_graphrag_fidelity_ablation_contract() -> list[str]:
    """GraphRAG fidelity-first ablation — unified knockouts, row-fidelity preflight, no registry fallback."""
    errors: list[str] = []
    agents = REPO_ROOT / "AGENTS.md"
    if not agents.is_file():
        errors.append("GraphRAG fidelity: AGENTS.md missing")
        return errors
    agents_text = agents.read_text(encoding="utf-8", errors="replace")
    for marker in (
        "GraphRAG fidelity-first",
        "DB identity row surface",
        "audit_ablation_row_fidelity",
        "audit_ablation_ingest_purity",
        "_whole_stack_knockout_columns",
        "check_graphrag_fidelity_ablation_contract",
        "Fidelity-first knockouts",
        "tags attribution only",
    ):
        if marker not in agents_text:
            errors.append(f"GraphRAG fidelity: AGENTS.md missing marker {marker!r}")

    gate_py = REPO_ROOT / "tools" / "feature_curation_gate.py"
    if not gate_py.is_file():
        errors.append("GraphRAG fidelity: missing feature_curation_gate.py")
        return errors
    gate_text = gate_py.read_text(encoding="utf-8", errors="replace")
    for banned in (
        "_ablation_in_cone_fallback_columns",
        "registry gaps use fallback",
    ):
        if banned in gate_text:
            errors.append(
                f"GraphRAG fidelity: feature_curation_gate.py still contains banned bias {banned!r}"
            )
    for required in (
        "audit_ablation_row_fidelity",
        "audit_ablation_ingest_purity",
        "build_ablation_enriched_row_sample",
        "ablation_scoring_groups",
        "_enrich_rows_for_whole_stack_ablation",
        "ablation_db_wire_ablatable_columns",
        'result["ingest_purity"]',
        'result["ready_for_unbiased_ablation"]',
        "knockout_resolution",
    ):
        if required not in gate_text:
            errors.append(
                f"GraphRAG fidelity: feature_curation_gate.py missing required {required!r}"
            )
    blank_slate_fn_names = frozenset(
        {
            "_enrich_rows_for_whole_stack_ablation",
            "_whole_stack_knockout_columns",
            "_ablation_atomic_knockout_column_candidates",
            "build_ablation_enriched_row_sample",
            "audit_ablation_row_fidelity",
        }
    )
    blank_slate_banned_calls = (
        "engineer_single_snapshot(",
        "build_xgb_pre_engineering_snapshot_for_tick(",
        "xgb_engineered_members_to_raw_snapshot(",
        "_merge_engineered_feature_surface(",
        "attach_confluence_feature_columns",
    )
    try:
        import ast

        tree = ast.parse(gate_text, filename=str(gate_py))
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef) or node.name not in blank_slate_fn_names:
                continue
            fn_src = ast.get_source_segment(gate_text, node) or ""
            for banned in blank_slate_banned_calls:
                if banned in fn_src:
                    errors.append(
                        f"GraphRAG fidelity: {node.name} must not call XGB-biased "
                        f"enrichment/knockout {banned.rstrip('(')!r}"
                    )
    except SyntaxError as exc:
        errors.append(f"GraphRAG fidelity: cannot AST-parse feature_curation_gate.py ({exc})")
    sbe_py = REPO_ROOT / "arch_competition" / "stack_bundle_eval_v1.py"
    if sbe_py.is_file():
        sbe_text = sbe_py.read_text(encoding="utf-8", errors="replace")
        for banned_branch in (
            'if af == "meta" and knockout_cols',
            "apply_ablation_knockout_columns(clean_row, permuted_row",
            "elif af in FEATURE_ABLATION_ML_STACK_LAYERS",
        ):
            if banned_branch in sbe_text:
                errors.append(
                    f"GraphRAG fidelity: stack_bundle_eval_v1.py still has per-layer knockout "
                    f"branch {banned_branch!r} — one permuted row through full stack only"
                )
        if "Single ablation score path: seven layers from one permuted DB wire row" not in sbe_text:
            if "Score one row through the unified ablation stack" not in sbe_text:
                errors.append(
                    "GraphRAG fidelity: stack_bundle_eval_v1.py missing unified wire-row ablation scorer doc"
                )
    return errors


def run_ablation_integrity_audit(
    *,
    db_path: str | None = None,
    tickers: list[str] | None = None,
    runtime: bool = True,
) -> dict:
    """Static contract + optional runtime preflight — agent/operator gate before scored ablation."""
    static_errors: list[str] = []
    static_errors.extend(check_ablation_seven_model_four_horizon_grid())
    static_errors.extend(check_ablation_equal_layer_consumers())
    static_errors.extend(check_ablation_full_stack_non_negotiable())
    static_errors.extend(check_no_ablation_gate_bypass_in_money_path())
    static_errors.extend(check_feature_list_no_model_preassignment())
    static_errors.extend(check_zero_bias_ablation_contract())
    static_errors.extend(check_graphrag_fidelity_ablation_contract())
    static_errors.extend(check_ablation_agnostic_ingest_contract())

    out: dict = {
        "audit": "ablation_full_stack_non_negotiable",
        "static_ok": not static_errors,
        "static_errors": static_errors,
    }

    if runtime:
        dbp = Path(db_path) if db_path else REPO_ROOT / "data" / "ed_console.db"
        out["db_path"] = str(dbp)
        if dbp.is_file():
            if str(REPO_ROOT) not in sys.path:
                sys.path.insert(0, str(REPO_ROOT))
            from tools.feature_curation_gate import (
                load_ablation_manifest,
                run_ablation_preflight,
                whole_stack_fusion_cell_target,
            )

            manifest_path = REPO_ROOT / "governance" / "artifacts" / "feature_ablation_manifest_leaf.json"
            manifest = load_ablation_manifest(manifest_path)
            pf = run_ablation_preflight(manifest, db_path=str(dbp), tickers=tickers or [])
            placement = audit_ablation_placement_validity()
            out["preflight"] = pf
            out["placement_validity"] = placement
            out["whole_stack_cell_target"] = whole_stack_fusion_cell_target(manifest)
            preflight_ok = bool(pf.get("ready_for_unbiased_ablation"))
            placement_ok = bool(placement.get("ok"))
            out["runtime_ok"] = preflight_ok and placement_ok
            if pf.get("ready") and not pf.get("ready_for_unbiased_ablation"):
                out["runtime_ok"] = False
                static_errors.append(
                    "runtime: preflight ready != ready_for_unbiased_ablation — "
                    "partial-ready / production-path-only escape hatch"
                )
            if pf.get("ready_for_production_path_ablation") and not pf.get("ready_for_unbiased_ablation"):
                out["production_path_only"] = True
            if preflight_ok and not placement_ok:
                static_errors.append(
                    "runtime: preflight ready but placement_validity failed — "
                    "grid cardinality / ablation-env probe is not valid placement"
                )
                static_errors.extend(placement.get("errors") or [])
        else:
            out["runtime_ok"] = False
            out["runtime_skip"] = f"database missing: {dbp}"

    out["static_ok"] = not static_errors
    out["static_errors"] = static_errors
    out["ok"] = out["static_ok"] and (not runtime or bool(out.get("runtime_ok")))
    return out


def check_production_fusion_score_path_contract() -> list[str]:
    """Ablation whole-stack scoring must mirror live signals fusion (all 7 layers, same entrypoints).

    Meta is in the production graph via stack_probs → MC drift, not as a bayesian_fusion.fuse arg.
    """
    from governed_stack_contract import (
        FULL_STACK_MODEL_LAYERS,
        PRODUCTION_FUSION_FINAL_PREDICTION,
        PRODUCTION_FUSION_LIVE_ENTRYPOINT,
        PRODUCTION_FUSION_SCORE_LAYERS,
    )

    errors: list[str] = []
    seven = list(FULL_STACK_MODEL_LAYERS)

    eval_py = REPO_ROOT / "arch_competition" / "stack_bundle_eval_v1.py"
    sig_py = REPO_ROOT / "signals.py"
    if not eval_py.is_file() or not sig_py.is_file():
        return ["production fusion path: missing stack_bundle_eval_v1.py or signals.py"]

    eval_src = eval_py.read_text(encoding="utf-8", errors="replace")
    sig_src = sig_py.read_text(encoding="utf-8", errors="replace")

    if list(PRODUCTION_FUSION_SCORE_LAYERS) != seven:
        errors.append(
            f"production fusion path: PRODUCTION_FUSION_SCORE_LAYERS must equal FULL_STACK_MODEL_LAYERS "
            f"{seven!r}"
        )

    ablation_markers = (
        "def _production_fusion_prob_for_row(",
        "score_unified_ablation_fusion_from_wire_row",
    )
    for tok in ablation_markers:
        if tok not in eval_src:
            errors.append(
                f"production fusion path: ablation scorer missing {tok!r} — "
                f"must use unified wire-row scorer (not production_fusion_payload_for_stack fork)"
            )

    fn_block = eval_src.split("def _production_fusion_prob_for_row", 1)[-1].split("\ndef ", 1)[0]
    if "ablation_wire_row=" in fn_block:
        errors.append(
            "production fusion path: _production_fusion_prob_for_row still threads ablation_wire_row"
        )

    live_markers = ("production_fusion_payload_for_stack(", "bayesian_fusion.fuse(")
    for tok in live_markers:
        if tok not in sig_src:
            errors.append(
                f"production fusion path: {PRODUCTION_FUSION_LIVE_ENTRYPOINT} missing {tok!r}"
            )

    if "mc_model_direction_inputs" not in sig_src:
        errors.append(
            "production fusion path: signals missing mc_model_direction_inputs — "
            "meta stack_probs must feed monte_carlo drift in production"
        )

    manifest_path = REPO_ROOT / "governance" / "artifacts" / "feature_ablation_manifest_leaf.json"
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            m_layers = list((manifest.get("ablation_method") or {}).get("full_stack_layers") or [])
            if m_layers != seven:
                errors.append(
                    f"production fusion path: leaf manifest full_stack_layers={m_layers!r} != "
                    f"contiguous 7-layer stack {seven!r}"
                )
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"production fusion path: leaf manifest unreadable: {exc}")

    if errors:
        return errors

    if PRODUCTION_FUSION_FINAL_PREDICTION not in (
        "bayesian_fusion.fuse + mc_fusion_adjustment.fuse_payload_apply_mc_adjustment",
    ):
        errors.append("production fusion path: PRODUCTION_FUSION_FINAL_PREDICTION drift")
    return errors


def check_full_stack_ablation_coverage() -> list[str]:
    """AGENTS § ZERO-BIAS / § Full stack — per-feature effect must be measured through the
    CONTIGUOUS 7-layer stack (xgb→lstm→transformer→meta→monte_carlo→regime→fusion) at EVERY
    governed horizon via _full_fusion_prob_for_row. Partial stack lists, mode-lift-only scoring,
    or per-base-model MCC permute without whole-stack fusion do NOT close this gate."""
    from governed_stack_contract import (
        FEATURE_ABLATION_ML_STACK_LAYERS,
        FULL_STACK_MODEL_LAYERS,
    )

    seven_layers = FULL_STACK_MODEL_LAYERS
    seven_contiguous = "→".join(seven_layers)
    permute_entry_layers = FEATURE_ABLATION_ML_STACK_LAYERS
    required_horizons = ("1c", "5c", "15c", "60c")
    errors: list[str] = []
    leaf_report = REPO_ROOT / "governance" / "artifacts" / "feature_ablation_report_leaf.json"
    legacy_report = REPO_ROOT / "governance" / "artifacts" / "feature_ablation_report.json"
    if not leaf_report.is_file():
        if legacy_report.is_file():
            errors.append(
                "full-stack coverage: leaf ablation report missing — "
                f"{leaf_report.name} not on disk; legacy compound report "
                f"{legacy_report.name} is not admissible (6-layer / wrong manifest era). "
                "Run: python tools/feature_curation_gate.py --ablation "
                f"(alias: --build-ablation-report) on "
                f"{leaf_report.parent / 'feature_ablation_manifest_leaf.json'}"
            )
        else:
            errors.append(
                "full-stack coverage: no leaf ablation report — the contiguous 7-layer stack "
                f"({seven_contiguous}) is UNEVALUATED at all horizons "
                f"{required_horizons}. Run: python tools/feature_curation_gate.py --ablation"
            )
        return errors
    report_path = leaf_report
    try:
        rep = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"full-stack coverage: report unreadable: {exc}")
        return errors

    # (a) PROVENANCE — atomic leaf manifest only (compound manifest = stale biased run).
    src = str(rep.get("source_manifest") or "").replace("\\", "/")
    if not src.endswith("feature_ablation_manifest_leaf.json"):
        errors.append(
            f"full-stack coverage: report is STALE — source_manifest={src!r} is not the atomic "
            f"leaf manifest; regenerate on the unbiased leaf manifest before any number is trusted."
        )

    # (b) CONTIGUOUS 7-LAYER STACK declared on report (no partial-stack pre-decision).
    report_layers = list(rep.get("full_stack_layers") or [])
    if report_layers != list(seven_layers):
        errors.append(
            f"full-stack coverage: report full_stack_layers={report_layers!r} is not the "
            f"contiguous 7-layer stack {list(seven_layers)!r} — partial stack = bias."
        )

    # (c) PER-FEATURE PLACEMENT — feature × all seven models × all four horizons.
    fusion_cells = rep.get("whole_stack_feature_cells") or rep.get("whole_stack_feature_group_cells") or []
    try:
        from tools.ablation_static_lock_index import get_ablation_static_lock_index
        from tools.feature_curation_gate import (
            _ablation_pool_tickers,
            ablation_grid_groups,
        )
        from governed_stack_contract import FULL_STACK_MODEL_LAYERS as _REQUIRED_MODELS

        idx = get_ablation_static_lock_index()
        if idx.manifest_load_error or idx.manifest is None:
            errors.append(
                f"full-stack coverage: could not load placement manifest cone: "
                f"{idx.manifest_load_error or 'manifest missing'}"
            )
            return errors
        manifest = idx.manifest
        expected_target = idx.runnable_target
        expected_groups = {g["group_id"] for g in ablation_grid_groups(manifest)}
        expected_pool_tickers = _ablation_pool_tickers(manifest)
        required_models = list(_REQUIRED_MODELS)
    except Exception as exc:  # pragma: no cover - defensive
        errors.append(f"full-stack coverage: could not load placement manifest cone: {exc}")
        return errors

    for c in fusion_cells:
        if not isinstance(c, dict):
            continue
        if c.get("anchor_ticker") is not None:
            errors.append(
                "full-stack coverage: whole_stack_feature_cells carry anchor_ticker — "
                "placement grid pools tickers; anchor is not a grid axis."
            )
            break
        if not c.get("model_family"):
            errors.append(
                "full-stack coverage: whole_stack_feature_cells missing model_family — "
                "every cell must be feature × model × horizon (all seven models)."
            )
            break
        pt = c.get("pool_tickers")
        if not pt:
            errors.append(
                "full-stack coverage: whole_stack_feature_cells missing pool_tickers — "
                "pooled ticker scoring must declare SPY+QQQ+IWM row pool."
            )
            break

    report_pool = list(rep.get("stage3_pool_tickers") or [])
    if fusion_cells and report_pool != expected_pool_tickers:
        errors.append(
            f"full-stack coverage: stage3_pool_tickers={report_pool!r} != "
            f"manifest pool {expected_pool_tickers!r}."
        )

    real = [
        c
        for c in fusion_cells
        if isinstance(c, dict)
        and c.get("status") == "ok"
        and c.get("log_loss_delta") is not None
        and c.get("baseline_multiclass_log_loss") is not None
        and c.get("permuted_multiclass_log_loss") is not None
    ]
    if not real:
        errors.append(
            "full-stack coverage: per-feature scoring through the CONTIGUOUS 7-layer stack "
            f"({seven_contiguous}) is 0 at ALL horizons {required_horizons}. "
            "Path: permute at every stack entry (xgb+lstm+transformer columns) → re-score through "
            "xgb→lstm→transformer→meta(MC drift)→monte_carlo→regime→fusion "
            "via score_unified_ablation_fusion_from_wire_row (Stage 3). "
            "Run: python tools/feature_curation_gate.py --ablation"
        )
        return errors

    if len(real) < expected_target:
        errors.append(
            f"full-stack coverage: {len(real)}/{expected_target} placement cells scored — "
            f"expected captured-cone feature×model×horizon grid ({len(expected_groups)} features × "
            f"{len(required_models)} models × {len(required_horizons)} horizons)."
        )

    scored_triples = {
        (c.get("group_id"), c.get("model_family"), c.get("horizon_slug")) for c in real
    }
    missing_triples: list[str] = []
    for gid in sorted(expected_groups):
        for model in required_models:
            for hz in required_horizons:
                if (gid, model, hz) not in scored_triples:
                    missing_triples.append(f"{gid}@{model}/{hz}")
    if missing_triples:
        sample = ", ".join(missing_triples[:4])
        errors.append(
            f"full-stack coverage: missing scored (feature×model×horizon) cells "
            f"({len(missing_triples)} — e.g. {sample})."
        )

    # (d) derived layer participation — never accept a hardcoded stamp equal to all 7 on every cell.
    for c in real:
        layers = list(c.get("stack_layers_scored") or [])
        if not layers:
            gid = c.get("group_id")
            hz = c.get("horizon_slug")
            errors.append(
                f"full-stack coverage: cell {hz}/{gid} missing derived stack_layers_scored "
                f"(must come from production_fusion_payload_for_stack audit, not a constant stamp)."
            )
            break
        if layers == list(seven_layers) and c.get("mc_stack_probability_source") is None and c.get("mc_base_probability_source") is None:
            errors.append(
                f"full-stack coverage: cell {c.get('horizon_slug')}/"
                f"{c.get('group_id')} has stack_layers_scored=all 7 but no "
                f"mc_stack_probability_source — suspected hardcoded stamp, not derived audit."
            )
            break
        missing_layers = [layer for layer in seven_layers if layer not in layers]
        if missing_layers:
            errors.append(
                f"full-stack coverage: cell {c.get('horizon_slug')}/{c.get('group_id')} "
                f"missing stack layers {missing_layers!r} in derived stack_layers_scored."
            )
            break
        dm = str(c.get("decision_mode") or "")
        if dm and dm not in ("full_fusion", "full_fusion_confirm_drop"):
            errors.append(
                f"full-stack coverage: cell decision_mode={dm!r} is not full_fusion — "
                f"mode-lift / per-model axes do not substitute for 7-layer contiguous scoring."
            )
            break
        mc_src = c.get("mc_stack_probability_source") or c.get("mc_base_probability_source")
        if mc_src == "stack_probs_meta_or_weighted" and "meta" not in layers:
            errors.append(
                f"full-stack coverage: cell {c.get('horizon_slug')}/"
                f"{c.get('group_id')} used stack_probs for MC but meta not in stack_layers_scored."
            )
            break
        pt = c.get("pool_tickers")
        if not pt or list(pt) != expected_pool_tickers:
            errors.append(
                f"full-stack coverage: cell {c.get('horizon_slug')}/{c.get('group_id')} "
                f"pool_tickers={pt!r} != manifest pool {expected_pool_tickers!r}."
            )
            break
        paired = c.get("paired_rows")
        if paired is None or int(paired) <= 0:
            errors.append(
                f"full-stack coverage: cell {c.get('horizon_slug')}/{c.get('group_id')} "
                f"missing paired_rows — pooled ticker scoring must report row count."
            )
            break

    # (e) Stack entry — permute columns resolved from live ingest cone for this model layer.
    for c in real:
        entry_layers = list(c.get("stack_entry_layers") or [])
        model = str(c.get("model_family") or "")
        if model in permute_entry_layers and not entry_layers:
            errors.append(
                f"full-stack coverage: cell {c.get('horizon_slug')}/{c.get('group_id')}/"
                f"{model} missing stack_entry_layers for a base-model placement cell."
            )
            break
        if entry_layers and not set(entry_layers).issubset(set(permute_entry_layers)):
            errors.append(
                f"full-stack coverage: cell {c.get('horizon_slug')}/{c.get('group_id')} "
                f"stack_entry_layers={entry_layers!r} not subset of base entry layers "
                f"{list(permute_entry_layers)!r}."
            )
            break

    # (f) EVERY horizon — no horizon pre-excluded from whole-stack measurement.
    have_hz = {c.get("horizon_slug") for c in real}
    missing_hz = [h for h in required_horizons if h not in have_hz]
    if missing_hz:
        errors.append(
            f"full-stack coverage: whole-stack fusion missing horizons {missing_hz} — "
            f"all of {required_horizons} must be measured through the 7-layer stack "
            f"({seven_contiguous})."
        )

    have_models = {c.get("model_family") for c in real}
    missing_models = [m for m in required_models if m not in have_models]
    if missing_models:
        errors.append(
            f"full-stack coverage: whole-stack fusion missing stack models {missing_models} — "
            f"all of {required_models} must appear on the placement grid."
        )

    return errors


_FULL_STACK_CONTRACT_FILES: tuple[tuple[str, str | None], ...] = (
    ("governed_stack_contract.py", "FULL_STACK_MODEL_LAYERS"),
    ("tools/feature_curation_gate.py", "FULL_STACK_MODEL_LAYERS"),
    ("tools/build_feature_assignment_matrix_v2.py", "FULL_STACK_MODEL_LAYERS"),
    ("AGENTS.md", "Full stack — all seven models"),
    ("ACTIVE_PROGRAM.md", "seven stack models"),
    ("tools/live_diag_compare.py", "_summarize_full_stack_layers"),
)
_FULL_STACK_BANNED_TRAIN_PATHS: tuple[str, ...] = (
    "ml_train.py",
    "ml_predict.py",
    "lstm_data.py",
    "transformer_train.py",
    "signals.py",
)


def check_full_stack_models_contract() -> list[str]:
    """AGENTS § Full stack — all seven models must be named everywhere ablation/stack is described."""
    errors: list[str] = []
    try:
        from governed_stack_contract import (
            FULL_STACK_MODEL_COUNT,
            FULL_STACK_MODEL_LAYERS,
        )
    except ImportError as exc:
        return [f"governed_stack_contract: cannot import stack roster ({exc})"]

    if FULL_STACK_MODEL_COUNT != 7:
        errors.append(
            f"governed_stack_contract: FULL_STACK_MODEL_COUNT must be 7 (got {FULL_STACK_MODEL_COUNT})"
        )

    for rel, needle in _FULL_STACK_CONTRACT_FILES:
        path = REPO_ROOT / rel
        if not path.is_file():
            errors.append(f"{rel}: missing (full stack models contract)")
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if needle and needle not in text:
            errors.append(f"{rel}: missing full-stack marker {needle!r}")
        for layer in FULL_STACK_MODEL_LAYERS:
            if layer not in text:
                errors.append(f"{rel}: missing stack model slug {layer!r}")

    for rel in _FULL_STACK_BANNED_TRAIN_PATHS:
        path = REPO_ROOT / rel
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if "attach_5m_additive_context" in text:
            errors.append(
                f"{rel}: must not call attach_5m_additive_context — m5_* lag dupes are dead (2026-06-04)"
            )

    manifest = REPO_ROOT / "governance/artifacts/feature_ablation_manifest_leaf.json"
    if manifest.is_file():
        try:
            man = json.loads(manifest.read_text(encoding="utf-8"))
            layers = list((man.get("ablation_method") or {}).get("full_stack_layers") or [])
            if set(layers) != set(FULL_STACK_MODEL_LAYERS):
                errors.append(
                    f"feature_ablation_manifest_leaf.json: full_stack_layers must be all seven "
                    f"{list(FULL_STACK_MODEL_LAYERS)} (got {layers})"
                )
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            errors.append(f"feature_ablation_manifest_leaf.json unreadable: {exc}")

    return errors


_FUSION_ONLY_CARD_MARKERS: tuple[tuple[str, str], ...] = (
    ("prediction_engine.py", 'ED_MH_EMPIRICAL_SUPPORT", "0.0"'),
    ("prediction_engine.py", "Per-horizon fusion is the sole product triplet"),
    ("bayesian_fusion.py", 'ED_SIGNAL_LAYER_FUSION_BLEND", "0.0"'),
    ("static/index.html", 'id="tf-signal-consolidated"'),
    ("static/index.html", "slug: 'consolidated'"),
    # Six pills since 2026-06-10: 1M/5M/15M/60M + ALL + PLAN (trade-plan card).
    # PLAN track widened 2026-06-11 (operator: values were ellipsizing).
    ("static/index.html", "repeat(5, minmax(0, 1fr)) minmax(0, 1.26fr)"),
    ("static/index.html", 'id="tf-signal-plan"'),
    ("static/index.html", "Primary horizon pill tagged PRIMARY"),
    ("static/index.html", "others AGREE/CONFLICT vs primary (not vs ALL)"),
    ("static/index.html", "function engineTradeableSetup"),
    ("static/index.html", "d.final_tradeable"),
    ("ACTIVE_PROGRAM.md", "Fusion-only horizon cards"),
    ("AGENTS.md", "Fusion-only horizon cards"),
)
_FUSION_ONLY_CARD_BANNED: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "prediction_engine.py: ED_MH_EMPIRICAL_SUPPORT default must not be 0.15",
        re.compile(r'ED_MH_EMPIRICAL_SUPPORT",\s*"0\.15"', re.MULTILINE),
    ),
    (
        "bayesian_fusion.py: ED_SIGNAL_LAYER_FUSION_BLEND default must not be 0.38",
        re.compile(r'ED_SIGNAL_LAYER_FUSION_BLEND",\s*"0\.38"', re.MULTILINE),
    ),
    (
        "static/index.html: implicit BLEND when fusion+empirical both present is banned",
        re.compile(
            r"if\s*\(\s*hzFusionOk\s*&&\s*empPresent\s*\)\s*return\s*['\"]BLEND['\"]",
            re.MULTILINE,
        ),
    ),
    (
        "static/index.html: PRIMARY badge on ALL/consolidated pill is banned",
        re.compile(
            r"slug\s*===\s*['\"]consolidated['\"]\s*\)\s*return\s*['\"]PRIMARY['\"]",
            re.MULTILINE,
        ),
    ),
    (
        "static/index.html: trade-active glow on individual primary slug is banned",
        re.compile(
            r"slug\s*===\s*prim\s*&&\s*dir\s*===\s*finalBias",
            re.MULTILINE,
        ),
    ),
)


def check_fusion_only_card_contract() -> list[str]:
    """AGENTS § Fusion-only horizon cards — zero default blend; withhold when fusion missing; 5th ALL card."""
    errors: list[str] = []
    for rel, needle in _FUSION_ONLY_CARD_MARKERS:
        path = REPO_ROOT / rel
        if not path.is_file():
            errors.append(f"{rel}: missing (fusion-only card contract)")
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            errors.append(f"{rel}: cannot read for fusion-only card contract: {exc}")
            continue
        if needle not in text:
            errors.append(f"{rel}: missing fusion-only marker {needle!r}")
    for label, pat in _FUSION_ONLY_CARD_BANNED:
        rel = label.split(":", 1)[0]
        path = REPO_ROOT / rel
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if pat.search(text):
            errors.append(label)
    tests = REPO_ROOT / "tests" / "test_prediction_engine_chunk1_fail_closed.py"
    if tests.is_file():
        ttext = tests.read_text(encoding="utf-8", errors="replace")
        if "test_overlay_withholds_product_triplets_when_fusion_missing" not in ttext:
            errors.append(
                "tests/test_prediction_engine_chunk1_fail_closed.py: missing "
                "test_overlay_withholds_product_triplets_when_fusion_missing"
            )
    ui_tests = REPO_ROOT / "tests" / "test_issue18_ui_contract.py"
    if ui_tests.is_file():
        utext = ui_tests.read_text(encoding="utf-8", errors="replace")
        for fn in (
            "test_render_timeframe_signal_row_includes_consolidated_slug",
            "test_derive_source_for_horizon_no_implicit_blend_when_fusion_ok",
            "test_individual_horizon_cards_primary_agree_conflict_vocabulary",
            "test_trade_active_glow_only_on_all_card",
        ):
            if f"def {fn}" not in utext:
                errors.append(f"tests/test_issue18_ui_contract.py: missing {fn}")
    return errors


_FOUR_HORIZON_PROMOTION_MARKERS: tuple[tuple[str, str], ...] = (
    ("ml_scheduler.py", "scheduler_nightly_all_horizons_enabled"),
    ("ml_scheduler.py", "for _hz in ALL_GOVERNED_HORIZONS"),
    ("ml_scheduler.py", "--all-horizons"),
    ("ml_scheduler.py", "execute_promotion_if_eligible"),
    ("arch_competition/scheduler_auto_promote_policy.py", "scheduler_nightly_all_horizons_enabled"),
    ("arch_competition/promotion_execution.py", "scheduler_active_root"),
    ("active_bundle_contract.py", "def scheduler_active_root"),
    ("verify_active_models.py", "PRIMARY_DECISION_HORIZONS"),
)


def check_four_horizon_promotion_contract() -> list[str]:
    """ACTIVE_PROGRAM Phase 2 — nightly + CLI train/promote all four primary horizons into canonical active roots."""
    errors: list[str] = []
    for rel, needle in _FOUR_HORIZON_PROMOTION_MARKERS:
        path = REPO_ROOT / rel
        if not path.is_file():
            errors.append(f"{rel}: missing (four-horizon promotion contract)")
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            errors.append(f"{rel}: cannot read for four-horizon promotion contract: {exc}")
            continue
        if needle not in text:
            errors.append(f"{rel}: missing four-horizon promotion marker {needle!r}")
    policy = REPO_ROOT / "arch_competition" / "scheduler_auto_promote_policy.py"
    if policy.is_file():
        ptext = policy.read_text(encoding="utf-8", errors="replace")
        if "ED_ML_SCHEDULER_ALL_HORIZONS" not in ptext:
            errors.append(
                "arch_competition/scheduler_auto_promote_policy.py: missing ED_ML_SCHEDULER_ALL_HORIZONS env gate"
            )
    sched = REPO_ROOT / "ml_scheduler.py"
    if sched.is_file():
        stext = sched.read_text(encoding="utf-8", errors="replace")
        if "manual via arch_competition.manual_control" in stext:
            errors.append(
                "ml_scheduler.py: --all-horizons help must not claim manual-only promotion (use execute_promotion_if_eligible)"
            )
    promote_tests = REPO_ROOT / "tests" / "test_arch_competition_auto_promote.py"
    if promote_tests.is_file():
        ttext = promote_tests.read_text(encoding="utf-8", errors="replace")
        for fn in (
            "test_auto_promote_5c_writes_active_5c_root",
            "test_scheduler_nightly_all_horizons_default_on",
        ):
            if f"def {fn}" not in ttext:
                errors.append(f"tests/test_arch_competition_auto_promote.py: missing {fn}")
    return errors


_TRAINING_ANCHOR_ROSTER_MARKERS: tuple[tuple[str, str], ...] = (
    ("scheduler_user_tickers.py", "TRAINING_ANCHOR_TICKERS"),
    ("scheduler_user_tickers.py", "def resolve_ml_training_roster"),
    ("scheduler_user_tickers.py", "ED_ML_SCHEDULER_TRAINING_EXPAND"),
    ("ml_scheduler.py", "resolve_ml_training_roster"),
    ("scheduler_user_tickers.py", "require_ml_training_ticker_allowed"),
    ("train_all.py", "require_ml_training_ticker_allowed"),
    ("verify_active_models.py", "resolve_ml_training_roster"),
    ("training_outcome.py", "is_training_anchor_ticker"),
    ("arch_competition/scheduler_auto_promote_policy.py", "is_training_anchor_ticker"),
)

_TRAINING_ROSTER_BULK_LOAD_FILES: tuple[str, ...] = (
    "ml_scheduler.py",
    "train_all.py",
    "lstm_data.py",
    "transformer_train.py",
    "verify_active_models.py",
)


def check_training_anchor_roster_contract() -> list[str]:
    """AGENTS — ML train/promote/verify roster locked to SPY/QQQ/IWM unless expansion env set."""
    errors: list[str] = []
    for rel, needle in _TRAINING_ANCHOR_ROSTER_MARKERS:
        path = REPO_ROOT / rel
        if not path.is_file():
            errors.append(f"{rel}: missing (training anchor roster contract)")
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            errors.append(f"{rel}: cannot read for training anchor roster contract: {exc}")
            continue
        if needle not in text:
            errors.append(f"{rel}: missing training anchor roster marker {needle!r}")
    sched = REPO_ROOT / "scheduler_user_tickers.py"
    if sched.is_file():
        stext = sched.read_text(encoding="utf-8", errors="replace")
        if 'TRAINING_ANCHOR_TICKERS: tuple[str, ...] = ("SPY", "QQQ", "IWM")' not in stext:
            errors.append(
                "scheduler_user_tickers.py: TRAINING_ANCHOR_TICKERS must be exactly SPY, QQQ, IWM"
            )
    for rel in _TRAINING_ROSTER_BULK_LOAD_FILES:
        path = REPO_ROOT / rel
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if "load_user_scheduler_tickers_or_empty" in text and "resolve_ml_training_roster" not in text:
            errors.append(
                f"{rel}: bulk ticker load must use resolve_ml_training_roster (anchor roster authority)"
            )
    roster_tests = REPO_ROOT / "tests" / "test_scheduler_user_tickers_return_type.py"
    if roster_tests.is_file():
        rtext = roster_tests.read_text(encoding="utf-8", errors="replace")
        for fn in (
            "test_resolve_ml_training_roster_defaults_to_three_anchors",
            "test_resolve_ml_training_roster_expansion_includes_pinned_guests",
            "test_require_ml_training_ticker_allowed_rejects_guest_mega_cap",
        ):
            if f"def {fn}" not in rtext:
                errors.append(f"tests/test_scheduler_user_tickers_return_type.py: missing {fn}")
    agents = REPO_ROOT / "AGENTS.md"
    if agents.is_file():
        atext = agents.read_text(encoding="utf-8", errors="replace")
        if "check_training_anchor_roster_contract" not in atext:
            errors.append("AGENTS.md: missing check_training_anchor_roster_contract registry row")
    return errors


_UNIFIED_STACK_MONEY_PATH: tuple[str, ...] = (
    "ml_predict.py",
    "signals.py",
    "governed_stack_contract.py",
    "fusion_contract.py",
    "server.py",
    "market_state.py",
    "features/parallel_stack_schema.py",
    "arch_competition/stack_bundle_eval_v1.py",
)

_UNIFIED_STACK_CANONICAL_MARKERS: dict[str, tuple[str, ...]] = {
    "ml_predict.py": (
        "def run_unified_stack_ml_once",
        "def read_stack_layer_collapse_flags",
        "run_base_models_once = run_unified_stack_ml_once",
        "build_unified_stack_layer_output",
    ),
    "signals.py": (
        "run_unified_stack_ml_once(",
        "unified_stack_team_can_authorize",
        "mc_team_should_fail_closed",
    ),
    "governed_stack_contract.py": (
        "FEATURE_ABLATION_ML_STACK_LAYERS",
        "unified_stack_team_can_authorize",
        "count_unified_stack_ml_layers_available",
        "def classify_stack_health",
        "n_ml_layers_available",
        "MC_ML_LAYER_WEIGHT_XGBOOST",
    ),
    "features/parallel_stack_schema.py": (
        "class UnifiedStackLayerOutput",
        "def build_unified_stack_layer_output",
        "ParallelBaseModelOutput = UnifiedStackLayerOutput",
    ),
    "server.py": ("unified_stack_team_ok", "n_ml_layers_live"),
    "market_state.py": ("ml_layer_probs",),
    "fusion_contract.py": ("fusion_has_tradable_direction",),
    "arch_competition/stack_bundle_eval_v1.py": (
        "live_ablation_experiment_active",
        "unified_stack_bundle_relaxation_active",
    ),
}

_UNIFIED_STACK_VOCAB_ALLOWLIST_RELPATHS: frozenset[str] = frozenset(
    {
        "AGENTS.md",
        "tools/check_fix_everything_we_touch.py",
        "tests/test_check_fix_everything_we_touch.py",
    }
)

_UNIFIED_STACK_VOCAB_DOCS_PREFIXES: tuple[str, ...] = (
    "docs/",
    "governance/",
)

_UNIFIED_STACK_VOCAB_EXTRA_RELPATHS: tuple[str, ...] = (
    "tools/feature_curation_gate.py",
    "tools/build_feature_assignment_matrix_v2.py",
    "OPEN_ITEMS.md",
)

_UNIFIED_STACK_VOCAB_DOCS_EXCLUDE_PREFIXES: tuple[str, ...] = (
    "governance/archive/",
    "governance/register_slices/",
)

_UNIFIED_STACK_LEGACY_VOCAB_IN_DOCS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("base model(s) primary framing", re.compile(r"\bbase models?\b", re.IGNORECASE)),
    ("run_base_models_once", re.compile(r"\brun_base_models_once\b")),
    ("n_base_models_live", re.compile(r"\bn_base_models_live\b")),
    ("layer1_probs", re.compile(r"\blayer1_probs\b")),
    ("ParallelBaseModelOutput primary", re.compile(r"\bParallelBaseModelOutput\b")),
    ("three base models", re.compile(r"\bthree base models\b", re.IGNORECASE)),
)

_UNIFIED_STACK_BANNED_OPERATOR_PHRASES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("three base models", re.compile(r"\bthree base models\b", re.IGNORECASE)),
    ("Layer 1 (base models", re.compile(r"Layer\s+1\s*\(\s*base models", re.IGNORECASE)),
    ("base models run in parallel", re.compile(r"base models run in parallel", re.IGNORECASE)),
    ("no base tri-class", re.compile(r"\bno base tri-class\b", re.IGNORECASE)),
    ("separable base model", re.compile(r"\bseparable base model", re.IGNORECASE)),
    ("primary base model", re.compile(r"\bprimary base model", re.IGNORECASE)),
)

_UNIFIED_STACK_LEGACY_PRIMARY_DEFS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("def run_base_models_once", re.compile(r"^\s*def\s+run_base_models_once\s*\(", re.MULTILINE)),
    ("def read_base_collapse_flags", re.compile(r"^\s*def\s+read_base_collapse_flags\s*\(", re.MULTILINE)),
    ("class ParallelBaseModelOutput", re.compile(r"^\s*class\s+ParallelBaseModelOutput\s*\(", re.MULTILINE)),
    ("def build_parallel_base_output", re.compile(r"^\s*def\s+build_parallel_base_output\s*\(", re.MULTILINE)),
)

_UNIFIED_STACK_LEGACY_CALL_SITES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("run_base_models_once(", re.compile(r"(?<!=\s)run_base_models_once\s*\(")),
    ("read_base_collapse_flags(", re.compile(r"(?<!=\s)read_base_collapse_flags\s*\(")),
    ("build_parallel_base_output(", re.compile(r"(?<!=\s)build_parallel_base_output\s*\(")),
)


def _strip_deprecated_alias_lines(text: str) -> str:
    """Remove explicit deprecated-alias lines so legacy names there do not trip call-site bans."""
    kept: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            kept.append(line)
            continue
        if "deprecated alias" in stripped.lower():
            continue
        if re.match(
            r"^(run_base_models_once|read_base_collapse_flags|ParallelBaseModelOutput|"
            r"build_parallel_base_output|FEATURE_ABLATION_BASE_MODELS)\s*=",
            stripped,
        ):
            continue
        kept.append(line)
    return "\n".join(kept)


def check_unified_stack_docs_governance_vocabulary() -> list[str]:
    """docs/ + governance/ + ACTIVE_PROGRAM — canonical unified-stack vocabulary only (no frankenstein drift)."""
    errors: list[str] = []
    scan_paths: list[Path] = [REPO_ROOT / "ACTIVE_PROGRAM.md"]
    for extra in _UNIFIED_STACK_VOCAB_EXTRA_RELPATHS:
        scan_paths.append(REPO_ROOT / extra)
    for prefix in _UNIFIED_STACK_VOCAB_DOCS_PREFIXES:
        base = REPO_ROOT / prefix.rstrip("/")
        if not base.is_dir():
            continue
        scan_paths.extend(p for p in base.rglob("*.md") if p.is_file())
    for path in scan_paths:
        rel = path.relative_to(REPO_ROOT).as_posix()
        if rel in _UNIFIED_STACK_VOCAB_ALLOWLIST_RELPATHS:
            continue
        if any(rel.startswith(p) for p in _UNIFIED_STACK_VOCAB_DOCS_EXCLUDE_PREFIXES):
            continue
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        scan = _strip_deprecated_alias_lines(text)
        for label, pat in _UNIFIED_STACK_BANNED_OPERATOR_PHRASES:
            if pat.search(scan):
                errors.append(f"{rel}: banned operator phrase {label!r}")
        for label, pat in _UNIFIED_STACK_LEGACY_VOCAB_IN_DOCS:
            if pat.search(scan):
                errors.append(f"{rel}: legacy unified-stack vocabulary {label!r}")
    return errors


def check_unified_stack_canonical_vocabulary() -> list[str]:
    """Unified seven-layer team — canonical symbols required; legacy names only as deprecated aliases."""
    errors: list[str] = []
    errors.extend(check_unified_stack_docs_governance_vocabulary())
    for rel in _UNIFIED_STACK_MONEY_PATH:
        path = REPO_ROOT / rel
        if not path.is_file():
            errors.append(f"unified stack vocabulary: missing {rel}")
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for marker in _UNIFIED_STACK_CANONICAL_MARKERS.get(rel, ()):
            if marker not in text:
                errors.append(f"{rel}: missing canonical unified-stack marker {marker!r}")
        scan = _strip_deprecated_alias_lines(text)
        for label, pat in _UNIFIED_STACK_LEGACY_PRIMARY_DEFS:
            if pat.search(text):
                errors.append(
                    f"{rel}: legacy primary definition {label!r} — rename to canonical symbol; "
                    f"keep legacy name only as deprecated alias assignment"
                )
        if rel != "ml_predict.py":
            for label, pat in _UNIFIED_STACK_LEGACY_CALL_SITES:
                if pat.search(scan):
                    errors.append(
                        f"{rel}: legacy call site {label!r} — use canonical unified-stack symbol"
                    )
        for label, pat in _UNIFIED_STACK_BANNED_OPERATOR_PHRASES:
            if pat.search(scan):
                errors.append(f"{rel}: banned operator phrase {label!r} (full money-path scan)")
    return errors


def check_unified_stack_producer_language() -> list[str]:
    """Backward-compatible entry — canonical vocabulary lock supersedes header-only phrase scan."""
    return check_unified_stack_canonical_vocabulary()


def check_unified_stack_team_contract() -> list[str]:
    """Unified stack team gate — MC must not solo-green when ML team cannot authorize cards."""
    errors: list[str] = []
    for rel, marker in (
        ("governed_stack_contract.py", "unified_stack_team_can_authorize"),
        ("governed_stack_contract.py", "mc_team_should_fail_closed"),
        ("signals.py", "mc_team_should_fail_closed"),
        ("signals.py", "unified_stack_team_can_authorize"),
        ("signals.py", "blocked (unified_stack_team:"),
        ("fusion_contract.py", "fusion_has_tradable_direction"),
        ("server.py", "unified_stack_team_ok"),
    ):
        path = REPO_ROOT / rel
        if not path.is_file():
            errors.append(f"unified stack team: missing {rel}")
            continue
        if marker not in path.read_text(encoding="utf-8", errors="replace"):
            errors.append(f"{rel}: missing unified stack team marker {marker!r}")
    gsc = REPO_ROOT / "governed_stack_contract.py"
    if gsc.is_file():
        gt = gsc.read_text(encoding="utf-8", errors="replace")
        if "return \"PARTIAL\"" in gt or "return \"DEGRADED\"" in gt:
            errors.append(
                "governed_stack_contract.classify_stack_health: PARTIAL/DEGRADED solo-stack modes banned"
            )
    return errors


def check_live_ablation_experiment_wiring() -> list[str]:
    """Pre-train observe experiment — cards route via ED_LIVE_ABLATION_EXPERIMENT, not retrain-only strict active."""
    errors: list[str] = []
    sbe = REPO_ROOT / "arch_competition" / "stack_bundle_eval_v1.py"
    mp = REPO_ROOT / "ml_predict.py"
    ap = REPO_ROOT / "ACTIVE_PROGRAM.md"
    for path, markers in (
        (
            sbe,
            (
                "LIVE_ABLATION_EXPERIMENT_ENV",
                "live_ablation_experiment_active",
                "resolve_experiment_bundle_dir",
                "ablation_experiment_serve_masks_active",
                "ablation_primary_pass_authority_active",
                "primary_drop_group_ids_by_model_horizon",
                "unified_stack_bundle_relaxation_active",
            ),
        ),
        (
            REPO_ROOT / "tools" / "feature_curation_gate.py",
            (
                "stamp_primary_ablation_authority",
                "--ablation-stamp-primary-authority",
            ),
        ),
        (
            mp,
            (
                "live_ablation_experiment_active",
                "resolve_experiment_bundle_dir",
                "ED_LIVE_ABLATION_EXPERIMENT",
                "ablation_experiment_serve_masks_active",
            ),
        ),
        (
            ap,
            ("ED_LIVE_ABLATION_EXPERIMENT", "Pre-train card observe"),
            ),
    ):
        if not path.is_file():
            errors.append(f"live ablation experiment: missing {path.name}")
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for m in markers:
            if m not in text:
                errors.append(f"{path.name}: missing live ablation experiment marker {m!r}")
    return errors


# ── Repo-wide static audit — single source of truth (no whack-a-mole drift) ──
_REPO_WIDE_STATIC_CHECK_FUNCS: tuple[str, ...] = (
    "check_mvp_dataframe_ingress",
    "check_institutional_contract",
    "check_fusion_only_card_contract",
    "check_four_horizon_promotion_contract",
    "check_training_anchor_roster_contract",
    "check_mandatory_enforcement_registry",
    "check_promoted_agents_rules_mechanically_locked",
    "check_external_rule_tools_wired",
    "check_ablation_schwab_universe_contract",
    "check_ablation_seven_model_four_horizon_grid",
    "check_ablation_equal_layer_consumers",
    "check_ablation_single_authority",
    "check_ablation_full_stack_non_negotiable",
    "check_no_ablation_gate_bypass_in_money_path",
    "check_zero_bias_ablation_contract",
    "check_graphrag_fidelity_ablation_contract",
    "check_ablation_agnostic_ingest_contract",
    "check_unified_stack_team_contract",
    "check_live_ablation_experiment_wiring",
    "check_unified_stack_canonical_vocabulary",
    "check_feature_list_no_model_preassignment",
    "check_ablation_manifest_generator_no_model_preassignment",
    "check_full_stack_models_contract",
    "check_universal_code_quality_contract",
    "check_meet_or_exceed_cycle_documentation",
    "check_definition_of_done_for_fixes_contract",
    "check_agent_preload_contract",
    "check_branch_protection_proof",
    "check_required_status_checks",
    "check_governance_critical_files",
    "check_no_verify_resistance",
    "check_governance_self_protection",
    "check_governance_mutation_detection",
    "check_env_override_hardening",
    "check_reviewer_evidence_index",
    "check_objective_code_audit_documentation",
    "check_objective_code_audit_contract",
    "check_ablated_training_only",
    "check_encoder_cone_mechanical_lock",
    "check_governance_binding_contract",
    "check_tier1_engineering_standard",
    "check_v3_invariant_mechanical_registry",
    "check_institutional_signoff_contract",
    "check_ablation_denominator_vocabulary",
    "check_governance_archive_batch2_contract",
    "check_precommit_performance_contract",
    "check_repo_hygiene_policy",
    "check_source_control_hygiene",
    "check_prepush_fast_gate",
    "check_governance_generated_artifacts_clean",
    "check_ci_tooling_dependencies",
    "check_check_stack_rightsizing",
    "check_operator_trust_governance",
)

# Pre-commit staged / commit-msg locks (cannot run repo-wide without staged paths).
_STAGED_COMMIT_CHECK_FUNCS: tuple[str, ...] = (
    "check_upfront_mechanical_gate_stamp",
    "check_staged_rule_drift",
    "check_action_not_documentation",
    "check_storage_writer_has_consumer",
    "check_persistence_map_fresh",
    "check_persistence_writer_has_reader",
    "check_commit_message",
    "check_meet_or_exceed_signoff",
)

# Every AGENTS.md `[PROMOTED]` section → mechanical lock(s). Prose-only promotion is rejection-grade.
_PROMOTED_AGENTS_RULE_LOCKS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "World-class / institutional code gate",
        (
            "check_institutional_contract",
            "check_tier1_engineering_standard",
            "check_v3_invariant_mechanical_registry",
            "check_mandatory_enforcement_registry",
        ),
    ),
    ("Universal code quality", ("check_universal_code_quality_contract",)),
    ("Ablation universe", ("check_ablation_schwab_universe_contract",)),
    ("Full stack", ("check_full_stack_models_contract",)),
    ("Fusion-only horizon cards", ("check_fusion_only_card_contract",)),
    ("Training anchor roster", ("check_training_anchor_roster_contract",)),
    (
        "Ticker universality contract",
        (
            "external:tools/check_universal_ticker_lock.py",
            "external:tests/test_check_universal_ticker_lock.py",
        ),
    ),
    (
        "Repo-wide universality hardgate",
        (
            "external:tools/check_universal_ticker_lock.py",
            "external:tests/test_check_universal_ticker_lock.py",
        ),
    ),
    ("Ablation grid", ("check_ablation_seven_model_four_horizon_grid", "check_ablation_full_stack_non_negotiable", "check_ablation_denominator_vocabulary")),
    (
        "GraphRAG fidelity-first",
        ("check_graphrag_fidelity_ablation_contract", "check_ablation_agnostic_ingest_contract"),
    ),
    ("Encoder cone", ("check_encoder_cone_mechanical_lock", "external:tools/check_encoder_cone_tests.py")),
    (
        "Tier-1 Quantitative Engineering Standard",
        ("check_tier1_engineering_standard",),
    ),
    (
        "V3 invariant mechanical registry",
        ("check_v3_invariant_mechanical_registry",),
    ),
    (
        "Meet-or-Exceed Closure Cycle",
        ("check_institutional_signoff_contract", "check_meet_or_exceed_cycle_documentation", "check_meet_or_exceed_signoff"),
    ),
    (
        "Institutional sign-off contract",
        (
            "check_institutional_signoff_contract",
            "check_upfront_mechanical_gate_stamp",
            "check_ablation_denominator_vocabulary",
            "check_governance_archive_batch2_contract",
            "check_objective_code_audit_signoff",
            "check_meet_or_exceed_signoff",
        ),
    ),
    (
        "Objective",
        ("check_institutional_signoff_contract", "check_objective_code_audit_contract", "run_objective_code_audit"),
    ),
    (
        "Definition of Done for Fixes",
        ("check_definition_of_done_for_fixes_contract",),
    ),
    (
        "Agent preload enforcement",
        ("check_agent_preload_contract", "external:tools/check_agent_preload_contract.py"),
    ),
    ("Rule compliance", ("check_staged_rule_drift",)),
    ("Do not lie to the operator", ("check_commit_message", "external:tools/enforce_all_rules.py")),
    ("Fix everything we touch", ("check_paths", "external:tools/check_fix_everything_we_touch.py")),
    ("Code-first / no governance-only turn", ("check_action_not_documentation", "external:tests/test_governance_consolidation.py")),
    (
        "Storage-needs-consumer",
        ("check_storage_writer_has_consumer", "check_persistence_map_fresh", "check_persistence_writer_has_reader"),
    ),
    ("Self-governance quality loop", ("check_mandatory_enforcement_registry", "check_promoted_agents_rules_mechanically_locked")),
    ("File delete gatekeeper", ("check_commit_message",)),
    ("Banned tools", ("external:tools/check_no_grep_subprocess.py",)),
    ("No permission asks", ("external:tools/enforce_all_rules.py",)),
    ("Active agent posture + mutual gatekeeping", ("check_v4_memo", "external:tools/check_schwab_csv_first.py")),
    ("Banned phrases", ("check_staged_rule_drift", "external:tests/test_forbidden_phrases.py")),
    ("Closure definition + no-deferral", ("external:tools/check_no_deferral_language.py",)),
    ("No carried residuals", ("external:tools/check_no_deferral_language.py",)),
    (
        "Ablation contract",
        (
            "check_zero_bias_ablation_contract",
            "check_ablation_seven_model_four_horizon_grid",
            "check_graphrag_fidelity_ablation_contract",
        ),
    ),
    ("No new files when an existing one will do", ("check_promoted_agents_rules_mechanically_locked",)),
    ("Money-path module roster", ("external:tests/test_money_path_roster.py",)),
    ("Governance document hierarchy", ("check_governance_binding_contract",)),
    (
        "Clean as we touch",
        (
            "check_repo_hygiene_policy",
            "check_source_control_hygiene",
            "external:tools/build_repo_hygiene_inventory.py",
        ),
    ),
    (
        "check stack right-sizing",
        ("check_check_stack_rightsizing", "external:tools/build_check_stack_inventory.py"),
    ),
)

_EXTERNAL_TOOL_LOCKS: tuple[str, ...] = (
    "tools/check_no_deferral_language.py",
    "tools/check_no_grep_subprocess.py",
    "tools/check_encoder_cone_tests.py",
    "tools/check_schwab_csv_first.py",
    "tools/check_fix_everything_we_touch.py",
    "tools/check_agent_preload_contract.py",
    "tools/check_branch_protection_proof.py",
    "tools/check_required_status_checks.py",
    "tools/check_governance_critical_files.py",
    "tools/check_no_verify_resistance.py",
    "tools/check_governance_self_protection.py",
    "tools/verify_remote_enforcement.py",
    "tools/remote_enforcement_evidence.py",
    "tools/enforce_all_rules.py",
    "tools/check_source_control_hygiene.py",
    "tools/check_prepush_fast_gate.py",
    "tools/check_governance_generated_artifacts_clean.py",
    "tools/check_ci_tooling_dependencies.py",
)


def _agents_promoted_section_titles() -> list[str]:
    """Every `## … [PROMOTED]` heading in AGENTS.md (canonical rule inventory)."""
    agents = REPO_ROOT / "AGENTS.md"
    if not agents.is_file():
        return []
    titles: list[str] = []
    for line in agents.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.startswith("## ") or "[PROMOTED]" not in line:
            continue
        title = line[3:].split("[PROMOTED]")[0].strip().rstrip("`").strip()
        if title:
            titles.append(title)
    return titles


def _lock_id_wired(lock_id: str) -> bool:
    if lock_id.startswith("external:"):
        rel = lock_id.split(":", 1)[1]
        if rel.startswith("tests/"):
            return (REPO_ROOT / rel).is_file()
        return (REPO_ROOT / rel).is_file()
    if lock_id in _REPO_WIDE_STATIC_CHECK_FUNCS:
        return True
    if lock_id in _STAGED_COMMIT_CHECK_FUNCS:
        return True
    if lock_id in (
        "check_paths",
        "run_repo_wide_static_audit",
        "run_objective_code_audit",
        "run_situational_runtime_audits",
        "check_v4_memo",
        "check_objective_code_audit_signoff",
        "check_meet_or_exceed_signoff",
    ):
        checker = REPO_ROOT / "tools" / "check_fix_everything_we_touch.py"
        if not checker.is_file():
            return False
        text = checker.read_text(encoding="utf-8", errors="replace")
        return f"def {lock_id}(" in text
    return False


def check_encoder_cone_mechanical_lock() -> list[str]:
    """AGENTS § Encoder cone — documentation markers + external tool present."""
    errors: list[str] = []
    tool = REPO_ROOT / "tools" / "check_encoder_cone_tests.py"
    if not tool.is_file():
        errors.append("tools/check_encoder_cone_tests.py: missing (encoder cone lock)")
        return errors
    tools_dir = Path(__file__).resolve().parent
    if str(tools_dir) not in sys.path:
        sys.path.insert(0, str(tools_dir))
    import check_encoder_cone_tests as encoder_cone

    errors.extend(encoder_cone.check_encoder_cone_documentation())
    return errors


def check_external_rule_tools_wired() -> list[str]:
    """Every external enforcement tool exists and is wired in pre-commit or enforce_all_rules."""
    errors: list[str] = []
    for rel in _EXTERNAL_TOOL_LOCKS:
        if not (REPO_ROOT / rel).is_file():
            errors.append(f"{rel}: missing (external rule enforcement tool)")
    precommit = REPO_ROOT / ".pre-commit-config.yaml"
    pc = precommit.read_text(encoding="utf-8", errors="replace") if precommit.is_file() else ""
    for rel in (
        "tools/check_no_deferral_language.py",
        "tools/check_no_grep_subprocess.py",
        "tools/check_fix_everything_we_touch.py",
    ):
        if rel not in pc:
            errors.append(f".pre-commit-config.yaml: missing hook entry for {rel}")
    enforce = REPO_ROOT / "tools" / "enforce_all_rules.py"
    if enforce.is_file():
        et = enforce.read_text(encoding="utf-8", errors="replace")
        for flag in ("--enforce-static", "--enforce-all", "--stop-hook", "--code-quality", "--objective-audit"):
            if flag not in et:
                errors.append(f"enforce_all_rules.py: missing {flag} entrypoint")
    else:
        errors.append("tools/enforce_all_rules.py: missing")
    return errors


def check_repo_hygiene_policy() -> list[str]:
    """Phase 3I — repo hygiene inventory, backlog, and clean-as-we-touch policy."""
    from tools.check_repo_hygiene_policy import check_repo_hygiene_policy as _check

    return _check()


def check_source_control_hygiene() -> list[str]:
    """Local runtime artifacts must not appear as untracked clutter — .gitignore + audit."""
    from tools.check_source_control_hygiene import check_source_control_hygiene as _check

    return _check()


def check_prepush_fast_gate() -> list[str]:
    """Pre-push fast-fail policy — hook order + docs (not dirty-tree probe)."""
    from tools.check_prepush_fast_gate import check_prepush_fast_gate_policy as _check

    return _check()


def check_governance_generated_artifacts_clean() -> list[str]:
    """Generated governance JSON must match sources — check-only, no writes."""
    from tools.check_governance_generated_artifacts_clean import (
        check_governance_generated_artifacts_clean as _check,
    )

    return _check()


def check_ci_tooling_dependencies() -> list[str]:
    """CI / objective-audit governance tooling must be pinned and importable."""
    from tools.check_ci_tooling_dependencies import check_ci_tooling_dependencies as _check

    return _check()


def check_check_stack_rightsizing() -> list[str]:
    """Phase 3I — check stack inventory, tier policy, runtime budgets."""
    from tools.check_check_stack_rightsizing import check_check_stack_rightsizing as _check

    return _check()


def check_operator_trust_governance() -> list[str]:
    """Operator-trust stabilization artifacts, harnesses, passive-risk closure matrix."""
    from tools.check_operator_trust_governance import check_operator_trust_governance as _check

    return _check()


def check_precommit_performance_contract() -> list[str]:
    """Pre-commit tier policy — lightweight-only local pre-push, consolidation in CI.

    Phase 2B (2026-06-26): local pre-push is the two fast gates only
    (prepush-fast-gate -> generated-artifacts-clean-check). The repo-wide governance
    consolidation pytest suite is NOT a local pre-push hook — required CI 'pytest-full'
    owns it. The performance artifact records that move under ci_backed_suites.
    """
    errors: list[str] = []
    audit_py = REPO_ROOT / "tools" / "audit_precommit_performance.py"
    audit_json = REPO_ROOT / "governance" / "artifacts" / "PRECOMMIT_PERFORMANCE_AUDIT.json"
    profile_json = REPO_ROOT / "governance" / "artifacts" / "FIX_EVERYTHING_WE_TOUCH_PROFILE.json"
    audit_md = REPO_ROOT / "governance" / "docs" / "PRECOMMIT_PERFORMANCE_AUDIT.md"
    for path in (audit_py, audit_json, profile_json, audit_md):
        if not path.is_file():
            errors.append(f"{path.relative_to(REPO_ROOT).as_posix()}: missing (pre-commit performance audit)")
    precommit = REPO_ROOT / ".pre-commit-config.yaml"
    if not precommit.is_file():
        errors.append(".pre-commit-config.yaml: missing")
        return errors
    pc = precommit.read_text(encoding="utf-8", errors="replace")
    idx_static = pc.find("id: fix-everything-we-touch-full-static")
    if idx_static >= 0:
        rest = pc[idx_static:]
        next_hook = rest.find("\n      - id:", len("id: fix-everything-we-touch-full-static"))
        block = rest if next_hook < 0 else rest[:next_hook]
        if "pre-push" in block:
            errors.append(
                ".pre-commit-config.yaml: fix-everything-we-touch-full-static must not use "
                "stages: [pre-push] — repo-wide static is required CI objective-audit only"
            )

    # Phase 2B: the repo-wide consolidation pytest suite must NOT be a local pre-push
    # hook — required CI ('pytest-full') owns it. Its presence anywhere in the local
    # hook config means heavy coverage leaked back under the local budget.
    if pc.find("id: governance-consolidation-tests") >= 0:
        errors.append(
            ".pre-commit-config.yaml: governance-consolidation-tests must NOT be a local hook "
            "(Phase 2B: repo-wide pytest is required-CI 'pytest-full' only)"
        )
    idx_fast = pc.find("id: prepush-fast-gate")
    idx_art = pc.find("id: generated-artifacts-clean-check")
    if idx_fast < 0:
        errors.append(".pre-commit-config.yaml: missing prepush-fast-gate hook")
    if idx_art < 0:
        errors.append(".pre-commit-config.yaml: missing generated-artifacts-clean-check hook")
    if idx_fast >= 0 and idx_art >= 0:
        if not (idx_fast < idx_art):
            errors.append(
                ".pre-commit-config.yaml: pre-push hook order must be "
                "prepush-fast-gate → generated-artifacts-clean-check"
            )
    wf = REPO_ROOT / ".github" / "workflows" / "objective-audit.yml"
    if not wf.is_file():
        errors.append(".github/workflows/objective-audit.yml: missing (CI full-static authority)")
    elif "--objective-audit" not in wf.read_text(encoding="utf-8", errors="replace"):
        errors.append(
            ".github/workflows/objective-audit.yml: missing --objective-audit "
            "(required CI repo-wide static authority)"
        )
    if audit_json.is_file():
        try:
            audit = json.loads(audit_json.read_text(encoding="utf-8"))
            hook_ids = {h.get("id") for h in audit.get("hooks") or []}
            if "governance-consolidation-tests" in hook_ids:
                errors.append(
                    "PRECOMMIT_PERFORMANCE_AUDIT.json: governance-consolidation-tests must not be a "
                    "local hook row (Phase 2B: required-CI 'pytest-full' owns it)"
                )
            ci_backed = audit.get("ci_backed_suites") or {}
            gct_ci = ci_backed.get("governance-consolidation-tests")
            if not gct_ci:
                errors.append(
                    "PRECOMMIT_PERFORMANCE_AUDIT.json: missing ci_backed_suites["
                    "'governance-consolidation-tests'] (required-CI owner record)"
                )
            elif gct_ci.get("required_ci_check") != "pytest-full":
                errors.append(
                    "PRECOMMIT_PERFORMANCE_AUDIT.json: governance-consolidation-tests "
                    "required_ci_check must be 'pytest-full'"
                )
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"PRECOMMIT_PERFORMANCE_AUDIT.json: unreadable — {exc}")
    return errors


def check_promoted_agents_rules_mechanically_locked() -> list[str]:
    """AGENTS — every `[PROMOTED]` section must map to live mechanical lock(s); no prose-only rules."""
    errors: list[str] = []
    titles = _agents_promoted_section_titles()
    if not titles:
        errors.append("AGENTS.md: no [PROMOTED] sections found (rule inventory broken)")
        return errors

    matched_titles: set[str] = set()
    for section_key, lock_ids in _PROMOTED_AGENTS_RULE_LOCKS:
        if not any(section_key in t for t in titles):
            errors.append(
                f"promoted-rule manifest: section key {section_key!r} has no matching AGENTS [PROMOTED] heading"
            )
            continue
        for title in titles:
            if section_key in title:
                matched_titles.add(title)
        for lock_id in lock_ids:
            if not _lock_id_wired(lock_id):
                errors.append(
                    f"AGENTS [PROMOTED] {section_key!r}: mechanical lock {lock_id!r} missing or unwired"
                )

    for title in titles:
        if not any(key in title for key, _ in _PROMOTED_AGENTS_RULE_LOCKS):
            errors.append(
                f"AGENTS [PROMOTED] {title!r}: no entry in _PROMOTED_AGENTS_RULE_LOCKS — add mechanical lock(s)"
            )

    checker = REPO_ROOT / "tools" / "check_fix_everything_we_touch.py"
    if checker.is_file():
        ct = checker.read_text(encoding="utf-8", errors="replace")
        for fn in _REPO_WIDE_STATIC_CHECK_FUNCS:
            if f"def {fn}(" not in ct and fn not in ("check_paths", "run_repo_wide_static_audit", "run_objective_code_audit"):
                errors.append(f"repo-wide static audit lists missing function def {fn}()")
    return errors


def _scope_module():
    tools_dir = Path(__file__).resolve().parent
    if str(tools_dir) not in sys.path:
        sys.path.insert(0, str(tools_dir))
    import fix_everything_we_touch_scope as scope

    return scope


def _run_repo_wide_static_check_funcs(
    *,
    staged: set[str] | None = None,
    full_static: bool = False,
    profile: Any | None = None,
    use_cache: bool = True,
) -> list[str]:
    """Invoke repo-wide static locks — scoped/cached on pre-commit; full on --full-static / objective-audit."""
    scope = _scope_module()
    ProfileCollector = scope.ProfileCollector
    apply_cached_errors = scope.apply_cached_errors
    cache_covers_all_checks = scope.cache_covers_all_checks
    compute_cache_invalidation_sha256 = scope.compute_cache_invalidation_sha256
    load_disk_cache = scope.load_disk_cache
    resolve_precommit_check_funcs = scope.resolve_precommit_check_funcs
    run_check_funcs = scope.run_check_funcs
    save_disk_cache = scope.save_disk_cache

    st = staged if staged is not None else set()
    inv = compute_cache_invalidation_sha256(_REPO_WIDE_STATIC_CHECK_FUNCS)
    func_names = resolve_precommit_check_funcs(
        _REPO_WIDE_STATIC_CHECK_FUNCS,
        staged=st,
        full_static=full_static,
    )
    errors: list[str] = []
    prof = profile if isinstance(profile, ProfileCollector) else None

    if use_cache and not full_static:
        disk = load_disk_cache()
        if cache_covers_all_checks(disk, invalidation_sha256=inv, func_names=_REPO_WIDE_STATIC_CHECK_FUNCS):
            cached_errs = apply_cached_errors(disk, _REPO_WIDE_STATIC_CHECK_FUNCS)
            if prof is not None:
                prof.record(
                    "repo_wide_static_cache_hit",
                    0.0,
                    scope="cached",
                    files_scanned=len(st),
                    recommendation="Skip re-run when invalidation hash unchanged and last full pass green",
                    cached=True,
                )
            errors.extend(cached_errs)
            if st:
                t0 = time.perf_counter()
                sim_errors, _sim_warnings = audit_staged_python_simplicity(st)
                errors.extend(sim_errors)
                if prof is not None:
                    prof.record(
                        "audit_staged_python_simplicity",
                        time.perf_counter() - t0,
                        scope="staged",
                        files_scanned=len(st),
                    )
            return errors

    if prof is not None and not func_names and not full_static:
        prof.record(
            "repo_wide_static_skipped",
            0.0,
            scope="staged",
            files_scanned=len(st),
            recommendation="Fast path — no repo-wide checks required for staged scope",
        )

    if func_names:
        label = "repo" if full_static else "critical"
        fn_errors, results = run_check_funcs(
            func_names,
            globals(),
            profile=prof,
            scope_label=label,
            staged=st,
        )
        errors.extend(fn_errors)
        if full_static or is_governance_critical_commit(st):
            disk = load_disk_cache() or {}
            checkers = dict(disk.get("checkers") or {})
            checkers.update(results)
            save_disk_cache(
                {
                    "schema_version": 1,
                    "invalidation_sha256": inv,
                    "last_updated_utc": datetime.now(timezone.utc)
                    .replace(microsecond=0)
                    .isoformat(),
                    "checkers": checkers,
                }
            )

    if st:
        t0 = time.perf_counter()
        sim_errors, _sim_warnings = audit_staged_python_simplicity(st)
        errors.extend(sim_errors)
        if prof is not None:
            prof.record(
                "audit_staged_python_simplicity",
                time.perf_counter() - t0,
                scope="staged",
                files_scanned=len(st),
            )
    return errors


def is_governance_critical_commit(staged: set[str]) -> bool:
    return _scope_module().is_governance_critical_commit(staged)


# ── Tier 0 — Upfront mechanical gate (AGENTS § Institutional sign-off contract) ──
UPFRONT_GATE_STAMP_PATH = REPO_ROOT / ".cursor" / "upfront_mechanical_gate.json"
UPFRONT_GATE_MAX_AGE_SEC = 8 * 3600
_UPFRONT_GATE_BOOTSTRAP_PATHS: frozenset[str] = frozenset(
    {
        "tools/check_fix_everything_we_touch.py",
        "tools/enforce_all_rules.py",
        "tools/check_agent_preload_contract.py",
        "AGENTS.md",
        "CLAUDE.md",
        "governance/docs/AGENT_OPERATING_CONTRACT.md",
        ".cursor/rules/00-always.mdc",
        ".cursor/rules/000-agent-operating-contract.mdc",
        "tests/test_governance_consolidation.py",
        "tests/test_check_fix_everything_we_touch.py",
        "tests/test_agent_preload_contract.py",
    }
)


def _git_head_sha() -> str:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return ""
    if proc.returncode != 0:
        return ""
    return proc.stdout.strip()


def _upfront_gate_lock_set_sha256() -> str:
    payload = "|".join(_REPO_WIDE_STATIC_CHECK_FUNCS)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _staged_requires_upfront_gate(staged: set[str]) -> bool:
    if not staged:
        return False
    norms = {_normalize_staged_path(p) for p in staged}
    if norms <= _UPFRONT_GATE_BOOTSTRAP_PATHS:
        return False
    for norm in norms:
        if norm.startswith("tests/"):
            continue
        if norm.endswith(".py"):
            return True
        if norm.startswith("static/") or norm.startswith("templates/"):
            return True
    return False


def run_upfront_mechanical_gate(*, write_stamp: bool = True) -> dict:
    """Tier 0 — full repo static locks before first edit; stamp pins HEAD + lock-set hash."""
    head = _git_head_sha()
    lock_set = _upfront_gate_lock_set_sha256()
    errs = run_repo_wide_static_audit(staged=set())
    ok = not errs
    stamp = {
        "schema_version": 1,
        "git_sha": head,
        "utc_ts": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "exit_code": 0 if ok else 1,
        "command": "--upfront-gate",
        "lock_set_sha256": lock_set,
        "static_error_count": len(errs),
    }
    if write_stamp and ok:
        UPFRONT_GATE_STAMP_PATH.parent.mkdir(parents=True, exist_ok=True)
        UPFRONT_GATE_STAMP_PATH.write_text(json.dumps(stamp, indent=2) + "\n", encoding="utf-8")
    return {"ok": ok, "errors": errs, "stamp": stamp}


def check_upfront_mechanical_gate_stamp(staged: set[str] | None = None) -> list[str]:
    """Pre-commit fast-fail: production-path commits require fresh Tier 0 stamp on current HEAD."""
    st = staged if staged is not None else _git_staged_paths()
    if not _staged_requires_upfront_gate(st):
        return []

    if not UPFRONT_GATE_STAMP_PATH.is_file():
        return [
            "upfront gate: missing stamp — run "
            "python tools/enforce_all_rules.py --upfront-gate (exit 0) "
            "before staging production paths (AGENTS § Tier 0 — Upfront mechanical gate)"
        ]

    try:
        stamp = json.loads(UPFRONT_GATE_STAMP_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"upfront gate: stamp unreadable — {exc}"]

    errors: list[str] = []
    head = _git_head_sha()
    if stamp.get("exit_code") != 0:
        errors.append(
            "upfront gate: last --upfront-gate run failed — re-run after fixing static locks"
        )
    if stamp.get("git_sha") != head:
        errors.append(
            f"upfront gate: stamp git_sha {stamp.get('git_sha')!r} != HEAD {head!r} — "
            "re-run python tools/enforce_all_rules.py --upfront-gate on current tip"
        )
    if stamp.get("lock_set_sha256") != _upfront_gate_lock_set_sha256():
        errors.append(
            "upfront gate: static lock set changed since stamp — re-run --upfront-gate"
        )

    ts_raw = stamp.get("utc_ts") or ""
    try:
        ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - ts).total_seconds()
        if age > UPFRONT_GATE_MAX_AGE_SEC:
            errors.append(
                f"upfront gate: stamp age {int(age)}s exceeds {UPFRONT_GATE_MAX_AGE_SEC}s — "
                "re-run python tools/enforce_all_rules.py --upfront-gate"
            )
    except ValueError:
        errors.append(f"upfront gate: invalid utc_ts {ts_raw!r}")

    return errors


_MANDATORY_REGISTRY_CHECK_FUNCS: tuple[str, ...] = (
    "check_institutional_contract",
    "check_fusion_only_card_contract",
    "check_four_horizon_promotion_contract",
    "check_training_anchor_roster_contract",
    "check_meet_or_exceed_signoff",
    "check_universal_code_quality_contract",
    "check_ablation_schwab_universe_contract",
    "check_full_stack_models_contract",
    "check_zero_bias_ablation_contract",
    "check_ablation_agnostic_ingest_contract",
    "check_ablation_seven_model_four_horizon_grid",
    "check_ablation_full_stack_non_negotiable",
    "check_graphrag_fidelity_ablation_contract",
    "check_unified_stack_team_contract",
    "check_live_ablation_experiment_wiring",
    "check_unified_stack_canonical_vocabulary",
    "check_promoted_agents_rules_mechanically_locked",
    "check_external_rule_tools_wired",
    "check_encoder_cone_mechanical_lock",
    "check_governance_binding_contract",
    "check_tier1_engineering_standard",
    "check_v3_invariant_mechanical_registry",
    "check_institutional_signoff_contract",
    "check_ablation_denominator_vocabulary",
    "check_governance_archive_batch2_contract",
    "run_repo_wide_static_audit",
    "run_objective_code_audit",
)
_MANDATORY_REGISTRY_EXTERNAL_TOOLS: tuple[str, ...] = (
    "tools/check_no_deferral_language.py",
    "tools/check_no_grep_subprocess.py",
    "tools/check_encoder_cone_tests.py",
    "tools/check_schwab_csv_first.py",
    "tools/enforce_all_rules.py",
)


def check_institutional_signoff_contract() -> list[str]:
    """AGENTS § Institutional sign-off contract — uniform Cursor+Claude Tier A/B/C ladder + canonical block."""
    errors: list[str] = []
    agents = REPO_ROOT / "AGENTS.md"
    active = REPO_ROOT / "ACTIVE_PROGRAM.md"
    cursor_rule = REPO_ROOT / ".cursor" / "rules" / "00-always.mdc"
    enforce = REPO_ROOT / "tools" / "enforce_all_rules.py"

    if not agents.is_file():
        return ["AGENTS.md: missing (institutional sign-off contract)"]
    text = agents.read_text(encoding="utf-8", errors="replace")
    for needle in (
        "Institutional sign-off contract — uniform Cursor + Claude",
        "Canonical audit command ladder",
        "Tier 0",
        "Upfront mechanical gate",
        "--upfront-gate",
        "Tier A",
        "Tier B",
        "Tier C",
        "Canonical sign-off block",
        "AUDIT_LADDER:",
        "MIT_BAR:",
        "PEER_AUDIT:",
        "catalog_slots",
        "runnable_scored",
        "check_institutional_signoff_contract",
        "fix-as-we-find",
        "register / O-NN",
    ):
        if needle not in text:
            errors.append(f"AGENTS.md: missing institutional sign-off marker {needle!r}")

    if not active.is_file():
        errors.append("ACTIVE_PROGRAM.md: missing (institutional sign-off contract)")
    else:
        atext = active.read_text(encoding="utf-8", errors="replace")
        if "runnable_scored" not in atext and "catalog_slots" not in atext:
            if "Governance document hierarchy" not in atext:
                errors.append(
                    "ACTIVE_PROGRAM.md: missing governance hierarchy pointer or ablation denominator"
                )

    if cursor_rule.is_file():
        cr = cursor_rule.read_text(encoding="utf-8", errors="replace")
        for needle in ("Tier A", "objective-audit", "Institutional sign-off contract"):
            if needle not in cr:
                errors.append(f".cursor/rules/00-always.mdc: missing sign-off marker {needle!r}")
    else:
        errors.append(".cursor/rules/00-always.mdc: missing")

    if enforce.is_file():
        et = enforce.read_text(encoding="utf-8", errors="replace")
        if "--upfront-gate" not in et:
            errors.append("enforce_all_rules.py: missing --upfront-gate handler")
        if "Tier A (implementation)" not in et and "Tier A:" not in et:
            errors.append("enforce_all_rules.py: missing Tier A checklist marker")
    else:
        errors.append("tools/enforce_all_rules.py: missing")

    checker = REPO_ROOT / "tools" / "check_fix_everything_we_touch.py"
    checker_text = (
        checker.read_text(encoding="utf-8", errors="replace") if checker.is_file() else ""
    )
    if checker.is_file() and "def check_institutional_signoff_contract" not in checker_text:
        errors.append("check_fix_everything_we_touch.py: check_institutional_signoff_contract not defined")
    if checker.is_file() and "def check_upfront_mechanical_gate_stamp" not in checker_text:
        errors.append("check_fix_everything_we_touch.py: check_upfront_mechanical_gate_stamp not defined")
    if checker.is_file() and "def run_upfront_mechanical_gate" not in checker_text:
        errors.append("check_fix_everything_we_touch.py: run_upfront_mechanical_gate not defined")

    # ACTIVE_PROGRAM must point at AGENTS for sign-off law — not duplicate the full Tier ladder table.
    if active.is_file():
        atext = active.read_text(encoding="utf-8", errors="replace")
        tier_rows = atext.count("| **A — Implementation sign-off** |")
        if tier_rows > 0:
            errors.append(
                "ACTIVE_PROGRAM.md: duplicates Tier A/B/C ladder table — point to AGENTS § Institutional sign-off contract"
            )
        if "Institutional sign-off contract" not in atext and "institutional-signoff-contract" not in atext:
            errors.append(
                "ACTIVE_PROGRAM.md: missing pointer to AGENTS § Institutional sign-off contract"
            )

    hardening = REPO_ROOT / ".github" / "workflows" / "hardening.yml"
    if hardening.is_file():
        ht = hardening.read_text(encoding="utf-8", errors="replace")
        if "enforce_all_rules.py --enforce-static" not in ht:
            errors.append("hardening.yml: missing CI step python tools/enforce_all_rules.py --enforce-static")
    else:
        errors.append(".github/workflows/hardening.yml: missing (institutional CI gate)")
    return errors


_ABLATION_SLOT_NAMES: frozenset[str] = frozenset(
    {"catalog_slots", "manifest_in_cone", "runnable_scored"}
)
_ABLATION_BARE_COUNT_RE = re.compile(
    r"\b(?:7[,.]?840|2[,.]?632|1[,.]?092|1[,.]?288|\d{1,2},\d{3})\b.*\b(?:cells?|slots?|denominator)\b",
    re.IGNORECASE,
)


def check_ablation_denominator_vocabulary() -> list[str]:
    """Binding docs must cite catalog_slots | manifest_in_cone | runnable_scored — not bare cell counts."""
    errors: list[str] = []
    active = REPO_ROOT / "ACTIVE_PROGRAM.md"
    if not active.is_file():
        return ["ACTIVE_PROGRAM.md: missing (ablation denominator vocabulary)"]
    lines = active.read_text(encoding="utf-8", errors="replace").splitlines()
    in_glossary = False
    for i, line in enumerate(lines, start=1):
        if "### Ablation denominator glossary" in line or "Ablation denominator glossary" in line:
            in_glossary = True
        if in_glossary and line.startswith("## ") and "Ablation denominator" not in line:
            in_glossary = False
        if in_glossary:
            continue
        if not _ABLATION_BARE_COUNT_RE.search(line):
            continue
        window = "\n".join(lines[max(0, i - 3) : min(len(lines), i + 2)])
        if not any(slot in window for slot in _ABLATION_SLOT_NAMES):
            errors.append(
                f"ACTIVE_PROGRAM.md:{i}: bare ablation cell count without slot name "
                f"(catalog_slots | manifest_in_cone | runnable_scored)"
            )
    checker = REPO_ROOT / "tools" / "check_fix_everything_we_touch.py"
    if checker.is_file() and "def check_ablation_denominator_vocabulary" not in checker.read_text(
        encoding="utf-8", errors="replace"
    ):
        errors.append("check_fix_everything_we_touch.py: check_ablation_denominator_vocabulary not defined")
    return errors


def check_governance_archive_batch2_contract() -> list[str]:
    """REPO_CLEANUP_QUEUE batch 2 — C-bucket MDs are stubs at governance/ with archive bodies."""
    errors: list[str] = []
    worksheet = REPO_ROOT / "governance" / "consolidation" / "reconciliation_worksheet.json"
    if not worksheet.is_file():
        return ["governance/consolidation/reconciliation_worksheet.json: missing (archive batch 2)"]
    rows = [
        r
        for r in json.loads(worksheet.read_text(encoding="utf-8"))["rows"]
        if str(r.get("bucket", "")).startswith("C-")
    ]
    for row in rows:
        rel = row["path"].replace("\\", "/")
        stub_path = REPO_ROOT / rel
        if not stub_path.is_file():
            errors.append(f"{rel}: missing (C-bucket archive batch 2)")
            continue
        text = stub_path.read_text(encoding="utf-8", errors="replace")
        if not text.lstrip().startswith("> **Archived"):
            errors.append(f"{rel}: not an archive stub (batch 2 incomplete)")
            continue
        name = Path(rel).name
        if row["bucket"] == "C-superseded-schwab":
            archive = REPO_ROOT / "governance/archive/2026-Q2/superseded_schwab_coverage" / name
        else:
            archive = REPO_ROOT / "governance/archive/2026-Q2/governance_md" / name
        if not archive.is_file():
            errors.append(f"{rel}: archive body missing at {archive.relative_to(REPO_ROOT).as_posix()}")
        elif len(archive.read_text(encoding="utf-8", errors="replace")) < 80:
            errors.append(f"{rel}: archive body too short — likely stub not full text")
    queue = REPO_ROOT / "governance" / "REPO_CLEANUP_QUEUE.md"
    if queue.is_file() and "batch 2" in queue.read_text(encoding="utf-8", errors="replace"):
        if "batch 2 complete" not in queue.read_text(encoding="utf-8", errors="replace").lower():
            errors.append("governance/REPO_CLEANUP_QUEUE.md: batch 2 not marked complete")
    return errors


# ── Tier-1 Quality Standard + V3 invariant mechanical registry (AGENTS § promoted 2026-06-15) ──
TIER1_PRINCIPLE_IDS: tuple[str, ...] = tuple(f"T1-{i:02d}" for i in range(1, 25))

V3_INVARIANT_MECHANICAL_LOCKS: dict[str, tuple[str, ...]] = {
    "I-01": (
        "check_fusion_only_card_contract",
        "tests/test_ml_predict_fail_closed.py",
        "tests/test_prediction_engine_chunk1_fail_closed.py",
    ),
    "I-02": ("check_v3_i02_single_promotion_authority", "arch_competition/promotion_execution.py"),
    "I-03": ("check_v3_i03_causal_clock_contract", "time_et.py"),
    "I-04": ("check_v3_i03_causal_clock_contract", "time_et.py"),
    "I-05": ("check_encoder_cone_mechanical_lock", "tests/test_ml_feature_schema_parity.py"),
    "I-06": ("check_v3_i06_artifact_lineage", "arch_competition/promotion_execution.py"),
    "I-07": ("check_v3_i07_no_orphan_active_paths", "verify_active_models.py"),
    "I-08": (
        "check_v3_i08_output_schema_contract",
        "numeric_contract.py",
        "fusion_contract.py",
    ),
    "I-09": ("check_v3_i09_secrets_exclusion",),
    "I-10": ("check_v3_i10_training_identity", "arch_competition/audit.py"),
    "I-11": ("tests/test_arch_competition_eval_runner.py",),
    "I-12": ("check_v3_i12_oos_discipline", "arch_competition/stack_bundle_eval_v1.py"),
    "I-13": (
        "check_v3_i13_risk_supersedes_model",
        "position_sizing_policy.py",
        "call_engine.py",
    ),
    "I-14": ("check_v3_i14_attributable_change", "server.py"),
    "I-15": (
        "check_institutional_contract",
        "verify_active_models.py",
        "tools/live_diag_compare.py",
    ),
    "I-16": ("check_v3_i16_decision_explainability", "tools/live_diag_compare.py"),
    "I-17": ("tests/test_ml_predict_fail_closed.py", "check_v3_i17_deterministic_inference"),
    "I-18": ("check_v3_i18_capacity_bounded", "server.py"),
    "I-19": ("check_v3_i03_causal_clock_contract", "time_et.py"),
    "I-20": ("check_v3_i20_dependency_discipline", "requirements.txt"),
}

_V3_SEVERITY1: frozenset[str] = frozenset(
    {"I-01", "I-02", "I-05", "I-07", "I-15", "I-17", "I-19", "I-20"}
)

_SECRET_Literal_RE = re.compile(
    r"(?i)(api[_-]?key\s*=\s*['\"][^'\"]{8,}|secret\s*=\s*['\"][^'\"]{8,}|"
    r"password\s*=\s*['\"][^'\"]{4,}|aws[_-]?secret|sk-[a-zA-Z0-9]{20,})"
)


def _read_repo_text(rel: str) -> str:
    path = REPO_ROOT / rel.replace("\\", "/")
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _lock_target_exists(lock_id: str) -> bool:
    if lock_id.endswith(".py") or lock_id.startswith("tests/") or "/" in lock_id:
        return (REPO_ROOT / lock_id.replace("\\", "/")).is_file()
    if lock_id.startswith("check_") or lock_id.startswith("run_"):
        fn = globals().get(lock_id)
        return callable(fn)
    return (REPO_ROOT / lock_id).is_file()


def check_tier1_engineering_standard() -> list[str]:
    """AGENTS § Tier-1 Quantitative Engineering Standard — quality law above product law."""
    errors: list[str] = []
    agents = REPO_ROOT / "AGENTS.md"
    if not agents.is_file():
        return ["AGENTS.md: missing (Tier-1 engineering standard)"]
    text = agents.read_text(encoding="utf-8", errors="replace")
    for needle in (
        "Tier-1 Quantitative Engineering Standard",
        "Quality Standard vs Product law",
        "Product law (canonical list",
        "sits above product law",
        "check_tier1_engineering_standard",
        "Final directive (binding on every agent turn)",
        "Build as if this repository will manage institutional capital",
    ):
        if needle not in text:
            errors.append(f"AGENTS.md: missing Tier-1 marker {needle!r}")
    for pid in TIER1_PRINCIPLE_IDS:
        if f"**{pid}**" not in text:
            errors.append(f"AGENTS.md: missing Tier-1 principle {pid}")
    checker = REPO_ROOT / "tools" / "check_fix_everything_we_touch.py"
    if checker.is_file() and "def check_tier1_engineering_standard" not in checker.read_text(
        encoding="utf-8", errors="replace"
    ):
        errors.append("check_fix_everything_we_touch.py: check_tier1_engineering_standard not defined")
    return errors


def check_v3_i02_single_promotion_authority() -> list[str]:
    errors: list[str] = []
    rel = "arch_competition/promotion_execution.py"
    body = _read_repo_text(rel)
    if not body:
        return [f"{rel}: missing (V3 I-02 single promotion authority)"]
    for needle in (
        "execute_promotion_if_eligible",
        "governed_active_write_scope",
        "_governed_active_write_token",
    ):
        if needle not in body:
            errors.append(f"{rel}: missing I-02 marker {needle!r}")
    agents = _read_repo_text("AGENTS.md")
    if "execute_promotion_if_eligible" not in agents:
        errors.append("AGENTS.md: missing execute_promotion_if_eligible cite (I-02)")
    if "Auto-promote without governed executor" not in agents:
        errors.append("AGENTS.md: missing banned auto-promote pattern (I-02)")
    return errors


def check_v3_i03_causal_clock_contract() -> list[str]:
    errors: list[str] = []
    rel = "time_et.py"
    body = _read_repo_text(rel)
    if not body:
        return [f"{rel}: missing (V3 I-03/I-04/I-19 clock authority)"]
    for needle in (
        "Single source for production ET",
        "America/New_York",
        "RTH_START_MINS",
        "def now_et",
    ):
        if needle not in body:
            errors.append(f"{rel}: missing clock marker {needle!r}")
    return errors


def check_v3_i06_artifact_lineage() -> list[str]:
    errors: list[str] = []
    body = _read_repo_text("arch_competition/promotion_execution.py")
    if "validate_persisted_governed_artifacts_or_raise" not in body:
        errors.append(
            "promotion_execution.py: missing validate_persisted_governed_artifacts_or_raise (I-06 lineage)"
        )
    if "build_audit_record" not in body and "append_audit_record" not in body:
        errors.append("promotion_execution.py: missing promotion audit record wiring (I-06)")
    return errors


def check_v3_i07_no_orphan_active_paths() -> list[str]:
    errors: list[str] = []
    rel = "verify_active_models.py"
    if not (REPO_ROOT / rel).is_file():
        return [f"{rel}: missing (V3 I-07 orphan path guard)"]
    body = _read_repo_text(rel)
    if "models/active" not in body and "active_" not in body:
        errors.append(f"{rel}: must reference active model paths (I-07)")
    return errors


def check_v3_i08_output_schema_contract() -> list[str]:
    errors: list[str] = []
    for rel, needle in (
        ("numeric_contract.py", "float_finite_or_none"),
        ("fusion_contract.py", "fusion_is_authoritative"),
    ):
        body = _read_repo_text(rel)
        if not body:
            errors.append(f"{rel}: missing (V3 I-08 output schema)")
        elif needle not in body:
            errors.append(f"{rel}: missing I-08 marker {needle!r}")
    return errors


def check_v3_i09_secrets_exclusion() -> list[str]:
    errors: list[str] = []
    for rel in (
        "server.py",
        "signals.py",
        "call_engine.py",
        "ml_predict.py",
        "arch_competition/promotion_execution.py",
    ):
        body = _read_repo_text(rel)
        if not body:
            continue
        for i, line in enumerate(body.splitlines(), start=1):
            if line.strip().startswith("#"):
                continue
            if _SECRET_Literal_RE.search(line):
                errors.append(f"{rel}:{i}: suspected hardcoded secret (V3 I-09)")
    for env_name in (".env", "credentials.json", "secrets.json"):
        p = REPO_ROOT / env_name
        if not p.is_file():
            continue
        try:
            proc = subprocess.run(
                ["git", "ls-files", "--error-unmatch", env_name],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError:
            continue
        if proc.returncode == 0:
            errors.append(f"{env_name}: must not be git-tracked (V3 I-09)")
    return errors


def check_v3_i10_training_identity() -> list[str]:
    errors: list[str] = []
    audit = _read_repo_text("arch_competition/audit.py")
    if not audit:
        return ["arch_competition/audit.py: missing (V3 I-10 training identity)"]
    for needle in ("build_audit_record", "governance_audit_log_path"):
        if needle not in audit:
            errors.append(f"arch_competition/audit.py: missing I-10 marker {needle!r}")
    return errors


def check_v3_i12_oos_discipline() -> list[str]:
    errors: list[str] = []
    body = _read_repo_text("arch_competition/stack_bundle_eval_v1.py")
    if not body:
        return ["arch_competition/stack_bundle_eval_v1.py: missing (V3 I-12 OOS discipline)"]
    if not any(n in body.lower() for n in ("holdout", "embargo", "chronological")):
        errors.append(
            "stack_bundle_eval_v1.py: missing OOS/chronological marker (I-12) — "
            "expected holdout, embargo, or chronological"
        )
    return errors


def check_v3_i13_risk_supersedes_model() -> list[str]:
    errors: list[str] = []
    for rel, needles in (
        ("position_sizing_policy.py", ("size", "risk")),
        ("call_engine.py", ("wait", "block")),
    ):
        body = _read_repo_text(rel)
        if not body:
            errors.append(f"{rel}: missing (V3 I-13 risk supersedes model)")
            continue
        if not any(n.lower() in body.lower() for n in needles):
            errors.append(f"{rel}: missing I-13 risk gate markers {needles!r}")
    return errors


def check_v3_i14_attributable_change() -> list[str]:
    errors: list[str] = []
    body = _read_repo_text("server.py")
    if '"/api/build"' not in body and "'/api/build'" not in body:
        errors.append("server.py: missing /api/build (V3 I-14 attributable change)")
    if "git_sha" not in body:
        errors.append("server.py: missing git_sha on /api/build (V3 I-14)")
    return errors


def check_v3_i16_decision_explainability() -> list[str]:
    errors: list[str] = []
    body = _read_repo_text("tools/live_diag_compare.py")
    if "_summarize_full_stack_layers" not in body:
        errors.append(
            "live_diag_compare.py: missing _summarize_full_stack_layers (V3 I-16 explainability)"
        )
    return errors


def check_v3_i17_deterministic_inference() -> list[str]:
    errors: list[str] = []
    test = REPO_ROOT / "tests/test_ml_predict_fail_closed.py"
    if not test.is_file():
        return ["tests/test_ml_predict_fail_closed.py: missing (V3 I-17 deterministic inference)"]
    body = test.read_text(encoding="utf-8", errors="replace")
    if "fail" not in body.lower() and "closed" not in body.lower():
        errors.append("test_ml_predict_fail_closed.py: must exercise fail-closed inference (I-17)")
    return errors


def check_v3_i18_capacity_bounded() -> list[str]:
    errors: list[str] = []
    body = _read_repo_text("server.py")
    if "ThreadPoolExecutor" not in body:
        errors.append("server.py: missing ThreadPoolExecutor (V3 I-18 capacity bounded)")
    if "max_workers" not in body:
        errors.append("server.py: missing max_workers bounds (V3 I-18)")
    return errors


def check_v3_i20_dependency_discipline() -> list[str]:
    errors: list[str] = []
    req = REPO_ROOT / "requirements.txt"
    if not req.is_file():
        return ["requirements.txt: missing (V3 I-20 dependency discipline)"]
    lines = [ln.strip() for ln in req.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.startswith("#")]
    if not lines:
        errors.append("requirements.txt: empty (V3 I-20)")
    for ln in lines:
        if "*" in ln and "==" not in ln:
            errors.append(f"requirements.txt: wildcard dependency {ln!r} (V3 I-20)")
    agents = _read_repo_text("AGENTS.md")
    if "T1-15" not in agents or "Dependency discipline" not in agents:
        errors.append("AGENTS.md: missing Tier-1 dependency discipline (pairs with I-20)")
    return errors


def check_v3_invariant_mechanical_registry() -> list[str]:
    """AGENTS § V3 invariant mechanical registry — every I-01…I-20 wired + substance checks."""
    errors: list[str] = []
    agents = REPO_ROOT / "AGENTS.md"
    if not agents.is_file():
        return ["AGENTS.md: missing (V3 invariant mechanical registry)"]
    text = agents.read_text(encoding="utf-8", errors="replace")
    for needle in (
        "V3 invariant mechanical registry",
        "V3_INVARIANT_MECHANICAL_LOCKS",
        "check_v3_invariant_mechanical_registry",
        "Severity-1 invariants",
    ):
        if needle not in text:
            errors.append(f"AGENTS.md: missing V3 registry marker {needle!r}")

    expected_ids = [f"I-{i:02d}" for i in range(1, 21)]
    if set(V3_INVARIANT_MECHANICAL_LOCKS.keys()) != set(expected_ids):
        missing = set(expected_ids) - set(V3_INVARIANT_MECHANICAL_LOCKS.keys())
        extra = set(V3_INVARIANT_MECHANICAL_LOCKS.keys()) - set(expected_ids)
        if missing:
            errors.append(f"V3_INVARIANT_MECHANICAL_LOCKS: missing keys {sorted(missing)}")
        if extra:
            errors.append(f"V3_INVARIANT_MECHANICAL_LOCKS: unexpected keys {sorted(extra)}")

    for inv_id, locks in V3_INVARIANT_MECHANICAL_LOCKS.items():
        if f"**{inv_id}**" not in text:
            errors.append(f"AGENTS.md: V3 registry table missing row {inv_id}")
        for lock in locks:
            if lock not in text:
                errors.append(f"AGENTS.md: V3 row {inv_id} missing lock cite {lock!r} in registry table")
            if not _lock_target_exists(lock):
                errors.append(f"V3 {inv_id}: mechanical lock target missing or unwired: {lock!r}")

    substance_fns = (
        check_v3_i02_single_promotion_authority,
        check_v3_i03_causal_clock_contract,
        check_v3_i06_artifact_lineage,
        check_v3_i07_no_orphan_active_paths,
        check_v3_i08_output_schema_contract,
        check_v3_i09_secrets_exclusion,
        check_v3_i10_training_identity,
        check_v3_i12_oos_discipline,
        check_v3_i13_risk_supersedes_model,
        check_v3_i14_attributable_change,
        check_v3_i16_decision_explainability,
        check_v3_i17_deterministic_inference,
        check_v3_i18_capacity_bounded,
        check_v3_i20_dependency_discipline,
    )
    for fn in substance_fns:
        errors.extend(fn())

    for inv_id in _V3_SEVERITY1:
        if inv_id not in V3_INVARIANT_MECHANICAL_LOCKS:
            errors.append(f"V3 Severity-1 {inv_id} not in mechanical registry")

    wired_checks = (
        check_fusion_only_card_contract,
        check_encoder_cone_mechanical_lock,
        check_institutional_contract,
    )
    for fn in wired_checks:
        errors.extend(fn())

    return errors


def check_governance_binding_contract() -> list[str]:
    """AGENTS § Governance document hierarchy — binding stack markers + reconciliation inventory."""
    errors: list[str] = []
    agents = REPO_ROOT / "AGENTS.md"
    active = REPO_ROOT / "ACTIVE_PROGRAM.md"
    claude = REPO_ROOT / "CLAUDE.md"
    eng = REPO_ROOT / "governance" / "ENGINEERING_GATEKEEPING_POLICY.md"
    worksheet = REPO_ROOT / "governance" / "consolidation" / "reconciliation_worksheet.json"

    if not agents.is_file():
        return ["AGENTS.md: missing (governance binding contract)"]
    agents_text = agents.read_text(encoding="utf-8", errors="replace")
    for needle in (
        "Governance document hierarchy",
        "binding stack",
        "Tier-1 Quantitative Engineering Standard",
        "V3 invariant mechanical registry",
        "Promote-or-archive rule",
        "check_governance_binding_contract",
        "reconciliation_worksheet.json",
        "INSTITUTIONAL_STANDARD_V3.md",
    ):
        if needle not in agents_text:
            errors.append(f"AGENTS.md: missing governance hierarchy marker {needle!r}")

    if not active.is_file():
        errors.append("ACTIVE_PROGRAM.md: missing (governance binding contract)")
    else:
        active_text = active.read_text(encoding="utf-8", errors="replace")
        for needle in (
            "Governance reconciliation",
            "CURSOR_V4_AGENT_BRIEF.md",
            "Governance document hierarchy",
        ):
            if needle not in active_text:
                errors.append(f"ACTIVE_PROGRAM.md: missing governance reconciliation marker {needle!r}")

    if not claude.is_file():
        errors.append("CLAUDE.md: missing (governance binding contract)")
    else:
        claude_text = claude.read_text(encoding="utf-8", errors="replace")
        for needle in (
            "ENGINEERING GATEKEEPING",
            "Patch rejection",
            "Schwab-native first",
        ):
            if needle not in claude_text:
                errors.append(f"CLAUDE.md: missing engineering gatekeeping marker {needle!r}")

    if not eng.is_file():
        errors.append("governance/ENGINEERING_GATEKEEPING_POLICY.md: missing")
    else:
        eng_text = eng.read_text(encoding="utf-8", errors="replace")
        if "Binding authority:" not in eng_text or "CLAUDE.md" not in eng_text:
            errors.append(
                "governance/ENGINEERING_GATEKEEPING_POLICY.md: missing Binding authority redirect to CLAUDE.md"
            )

    if not worksheet.is_file():
        errors.append("governance/consolidation/reconciliation_worksheet.json: missing (reconciliation inventory)")
    return errors


def check_mandatory_enforcement_registry() -> list[str]:
    """AGENTS § Mandatory enforcement registry — every promoted row must have a live lock, not prose-only."""
    errors: list[str] = []
    agents = REPO_ROOT / "AGENTS.md"
    if not agents.is_file():
        return ["AGENTS.md: missing (mandatory enforcement registry)"]
    agents_text = agents.read_text(encoding="utf-8", errors="replace")
    if "Mandatory enforcement registry" not in agents_text:
        errors.append("AGENTS.md: missing § Mandatory enforcement registry")
    if "Fusion-only horizon cards" not in agents_text:
        errors.append("AGENTS.md: missing § Fusion-only horizon cards promoted section")
    if "check_fusion_only_card_contract()" not in agents_text:
        errors.append("AGENTS.md: registry missing check_fusion_only_card_contract() row")

    checker = REPO_ROOT / "tools" / "check_fix_everything_we_touch.py"
    if not checker.is_file():
        errors.append("tools/check_fix_everything_we_touch.py: missing")
        return errors
    checker_text = checker.read_text(encoding="utf-8", errors="replace")
    for fn in _MANDATORY_REGISTRY_CHECK_FUNCS:
        if f"def {fn}" not in checker_text:
            errors.append(f"check_fix_everything_we_touch.py: missing registry lock {fn}()")
    if "check_fusion_only_card_contract()" not in checker_text:
        errors.append("check_fix_everything_we_touch.py: check_fusion_only_card_contract not wired in check_paths")

    for rel in _MANDATORY_REGISTRY_EXTERNAL_TOOLS:
        path = REPO_ROOT / rel
        if not path.is_file():
            errors.append(f"{rel}: missing (mandatory registry external lock)")
            continue
        if rel.endswith("enforce_all_rules.py"):
            etext = path.read_text(encoding="utf-8", errors="replace")
            for flag in ("--stop-hook", "--code-quality", "--objective-audit", "--enforce-static"):
                if flag not in etext:
                    errors.append(f"enforce_all_rules.py: missing {flag} entrypoint")

    precommit = REPO_ROOT / ".pre-commit-config.yaml"
    if precommit.is_file():
        pc = precommit.read_text(encoding="utf-8", errors="replace")
        if "check_fix_everything_we_touch.py" not in pc:
            errors.append(".pre-commit-config.yaml: missing check_fix_everything_we_touch hook")
    else:
        errors.append(".pre-commit-config.yaml: missing")

    cursor_rule = REPO_ROOT / ".cursor" / "rules" / "00-always.mdc"
    if cursor_rule.is_file():
        cr = cursor_rule.read_text(encoding="utf-8", errors="replace")
        if "enforce_all_rules.py" not in cr:
            errors.append(".cursor/rules/00-always.mdc: missing enforce_all_rules.py cite (Cursor enforcement surface)")
    else:
        errors.append(".cursor/rules/00-always.mdc: missing")

    claude_settings = REPO_ROOT / ".claude" / "settings.json"
    if claude_settings.is_file():
        cs = claude_settings.read_text(encoding="utf-8", errors="replace")
        if "enforce_all_rules.py --stop-hook" not in cs:
            errors.append(".claude/settings.json: missing Stop hook for enforce_all_rules.py")
    return errors


def check_institutional_contract() -> list[str]:
    """AGENTS § World-class gate — mandatory registry rows must exist at repo tip."""
    errors: list[str] = []
    for rel, needle in INSTITUTIONAL_CONTRACT_MARKERS:
        path = REPO_ROOT / rel
        if not path.is_file():
            errors.append(f"{rel}: missing (institutional contract marker file)")
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            errors.append(f"{rel}: cannot read for institutional contract: {exc}")
            continue
        if needle not in text:
            errors.append(
                f"{rel}: missing institutional marker {needle!r} "
                f"(AGENTS § Mandatory enforcement registry)"
            )
    server = REPO_ROOT / "server.py"
    if server.is_file():
        try:
            stext = server.read_text(encoding="utf-8", errors="replace")
        except OSError:
            stext = ""
        for label, pat in INSTITUTIONAL_BANNED_SERVER_PATTERNS:
            if pat.search(stext):
                errors.append(f"server.py: {label}")
    index_html = REPO_ROOT / "static/index.html"
    if index_html.is_file():
        try:
            itext = index_html.read_text(encoding="utf-8", errors="replace")
        except OSError:
            itext = ""
        if "_lastSsePayloadAcceptedMs < SSE_POLL_SUPPRESS_MS" in itext:
            errors.append(
                "static/index.html: Tier C REST poll suppress must use _lastSseAnalyticsPayloadMs "
                "(quote SSE must not block analytics poll — UI_LATENCY_CONTRACT)"
            )
        if "await fetchJsonWithTimeout(url, { signal: fetchAbortSignal }, 120000)" in itext:
            errors.append(
                "static/index.html: fetchState must not await Tier C with 120s on ticker switch "
                "(use TIER-C-NONBLOCK-SWITCH + _fetchTierCRestAndApply force-gated timeout)"
            )
        if "_slowFetchAc && _slowFetchAc.abort()" in itext:
            errors.append(
                "static/index.html: Tier C timeout must not abort Tier A/B shared controller (UI_LATENCY_CONTRACT)"
            )
        if "ANALYTICS_PENDING_POLL_MS = 1500" in itext:
            errors.append(
                "static/index.html: UI_MAXIMIZE requires ANALYTICS_PENDING_POLL_MS <= 1000 (use 800)"
            )
        if "function renderTierCPartialAnalytics" not in itext:
            errors.append(
                "static/index.html: missing renderTierCPartialAnalytics (UI_MAXIMIZE partial chain paint)"
            )
        if "function _scheduleServerAnalyticsWarm" not in itext:
            errors.append(
                "static/index.html: missing _scheduleServerAnalyticsWarm (UI_MAXIMIZE server warm POST)"
            )
        if "triggerRefresh() { fetchState(true)" in itext:
            errors.append(
                "static/index.html: ticker switch must use fetchState(false); manualFullRefresh uses force"
            )
        if "live_quote" in itext and "_lastSseAnalyticsPayloadMs = Date.now()" in itext:
            live_idx = itext.find("live_quote")
            analytics_set = itext.find("_lastSseAnalyticsPayloadMs = Date.now()")
            if live_idx != -1 and analytics_set != -1:
                live_chunk = itext[live_idx : live_idx + 1200]
                if "_lastSseAnalyticsPayloadMs = Date.now()" in live_chunk:
                    errors.append(
                        "static/index.html: live_quote handler must not advance analytics poll suppress clock"
                    )
    return errors


VERDICT_LINE = re.compile(r"\bVERDICT:\s*(\S+)", re.IGNORECASE)
OBJECTIVE_LINE = re.compile(r"^OBJECTIVE:\s*\S", re.MULTILINE)
AUDIT_CLEAN_LINE = re.compile(r"^AUDIT:\s*CLEAN\b", re.MULTILINE | re.IGNORECASE)
MEET_OR_EXCEED_ALLOWED_VERDICTS = frozenset({"MET", "EXCEEDED"})

MEET_OR_EXCEED_BANNED_VERDICT_PHRASES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("partial completion verdict", re.compile(r"\b(?:mostly|partially)\s+(?:complete|meets?|met)\b", re.I)),
    ("meets with gaps verdict", re.compile(r"\bmeets?\s+with\s+gaps\b", re.I)),
    ("letter-grade partial verdict", re.compile(r"\bgrade:\s*[ABC][+-]", re.I)),
    ("explicit not-exceeded verdict", re.compile(r"\bdoes\s+not\s+exceed\b", re.I)),
    (
        "substandard completion verdict",
        re.compile(r"\b(?:substandard|good\s+enough)\b.*\b(?:complete|done|shipped)\b", re.I),
    ),
    (
        "scoped standard excuse",
        re.compile(
            r"\b(?:standard|verdict|cycle)\s+(?:met|applies|applicable)\s+(?:for|to)\s+(?:this|the)\s+"
            r"(?:slice|section|area|subsystem|epic|pr)\b",
            re.I,
        ),
    ),
    (
        "operator coherence slice scope-narrow",
        re.compile(r"\boperator\s+coherence\s+slice\b", re.I),
    ),
)

MEET_OR_EXCEED_UNIVERSAL_SCOPE_MARKERS: tuple[str, ...] = (
    "Scope — universal, not gated",
    "full repo",
    "one cycle, one verdict vocabulary",
)


def check_universal_code_quality_contract() -> list[str]:
    """AGENTS § Universal code quality — simplicity and institutional pride (full repo)."""
    errors: list[str] = []
    agents = REPO_ROOT / "AGENTS.md"
    if not agents.is_file():
        return ["AGENTS.md: missing (universal code quality contract)"]
    agents_text = agents.read_text(encoding="utf-8", errors="replace")
    for marker in (
        "Universal code quality — simplicity and institutional pride",
        "Simple when simple beats complication",
        "check_universal_code_quality_contract",
        "audit_staged_python_simplicity",
        "--code-quality",
        "Would an **MIT professor** deem this **high quality**",
    ):
        if marker not in agents_text:
            errors.append(f"AGENTS.md: missing universal code quality marker {marker!r}")

    active = REPO_ROOT / "ACTIVE_PROGRAM.md"
    if active.is_file():
        active_text = active.read_text(encoding="utf-8", errors="replace")
        if "check_universal_code_quality_contract" not in active_text:
            errors.append(
                "ACTIVE_PROGRAM.md: missing check_universal_code_quality_contract cite"
            )
        if "--code-quality" not in active_text:
            errors.append("ACTIVE_PROGRAM.md: missing --code-quality audit command cite")
    else:
        errors.append("ACTIVE_PROGRAM.md: missing (universal code quality program anchor)")

    checker = REPO_ROOT / "tools" / "check_fix_everything_we_touch.py"
    checker_text = checker.read_text(encoding="utf-8", errors="replace")
    for tok in ("check_universal_code_quality_contract()", "audit_staged_python_simplicity("):
        if tok not in checker_text:
            errors.append(f"check_fix_everything_we_touch.py: missing {tok} pre-commit wiring")

    enforce = REPO_ROOT / "tools" / "enforce_all_rules.py"
    if enforce.is_file():
        if "--code-quality" not in enforce.read_text(encoding="utf-8", errors="replace"):
            errors.append("enforce_all_rules.py: missing --code-quality audit flag")
    else:
        errors.append("enforce_all_rules.py: missing (universal code quality audit orchestrator)")

    return errors


_STAGED_SIMPLICITY_SKIP_PREFIXES = (
    "tests/",
    "governance/",
    "legacy/",
    "tests\\",
    "governance\\",
    "legacy\\",
)
_STAGED_SIMPLICITY_MAX_FUNCTION_LINES = 150


def audit_staged_python_simplicity(staged: set[str]) -> tuple[list[str], list[str]]:
    """Staged-file smells. Errors: duplicate defs (hard fail). Warnings: long functions (tripwire only)."""
    from collections import Counter

    errors: list[str] = []
    warnings: list[str] = []
    fn_def = re.compile(r"^def (\w+)\(", re.MULTILINE)
    for rel in sorted(staged):
        if not rel.endswith(".py"):
            continue
        if rel.startswith(_STAGED_SIMPLICITY_SKIP_PREFIXES):
            continue
        p = REPO_ROOT / rel
        if not p.is_file():
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            errors.append(f"{rel}: cannot read for simplicity audit: {exc}")
            continue

        names = fn_def.findall(text)
        dupes = sorted(n for n, c in Counter(names).items() if c > 1)
        if dupes:
            errors.append(
                f"{rel}: duplicate function definitions {dupes[:5]!r} — "
                f"consolidate (AGENTS § Universal code quality)"
            )

        for m in fn_def.finditer(text):
            start = m.start()
            next_def = fn_def.search(text, m.end())
            end = next_def.start() if next_def else len(text)
            body_lines = text[start:end].count("\n")
            if body_lines > _STAGED_SIMPLICITY_MAX_FUNCTION_LINES:
                warnings.append(
                    f"{rel}: function {m.group(1)!r} spans ~{body_lines} lines — "
                    f"review for split/simplify (>{_STAGED_SIMPLICITY_MAX_FUNCTION_LINES}; "
                    f"warning only — does not fail pre-commit)"
                )
                break

    return errors, warnings


def run_universal_code_quality_audit(*, staged: set[str] | None = None) -> dict:
    """Static + staged simplicity audit — run before every code sign-off (full repo)."""
    st = staged if staged is not None else _git_staged_paths()
    errors: list[str] = []
    warnings: list[str] = []
    errors.extend(check_universal_code_quality_contract())
    errors.extend(check_meet_or_exceed_cycle_documentation())
    sim_errors, sim_warnings = audit_staged_python_simplicity(st)
    errors.extend(sim_errors)
    warnings.extend(sim_warnings)
    return {
        "audit": "universal_code_quality",
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "staged_python_files": sorted(x for x in st if x.endswith(".py")),
    }


def check_agent_preload_contract() -> list[str]:
    """AGENTS § Agent preload — cross-agent operating contract surfaces."""
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from tools.check_agent_preload_contract import run_agent_preload_contract_check

    return run_agent_preload_contract_check()


def check_branch_protection_proof() -> list[str]:
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from tools.check_branch_protection_proof import run_branch_protection_proof_check

    return run_branch_protection_proof_check()


def check_required_status_checks() -> list[str]:
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from tools.check_required_status_checks import run_required_status_checks_check

    return run_required_status_checks_check()


def check_governance_critical_files() -> list[str]:
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from tools.check_governance_critical_files import run_governance_critical_files_check

    return run_governance_critical_files_check()


def check_no_verify_resistance() -> list[str]:
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from tools.check_no_verify_resistance import run_no_verify_resistance_check

    return run_no_verify_resistance_check()


def check_governance_self_protection() -> list[str]:
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from tools.check_governance_self_protection import run_governance_self_protection_check

    return run_governance_self_protection_check()


def check_governance_mutation_detection() -> list[str]:
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    errors: list[str] = []
    manifest = REPO_ROOT / "governance" / "artifacts" / "GOVERNANCE_ARTIFACT_MANIFEST.json"
    if not manifest.is_file():
        errors.append(
            "governance/artifacts/GOVERNANCE_ARTIFACT_MANIFEST.json: missing — run tools/_build_institutional_audit_phase3e.py"
        )
        return errors
    from tools.governance_mutation_detection import verify_governance_manifest

    result = verify_governance_manifest()
    if not result.get("ok"):
        if result.get("tampered"):
            errors.append(f"governance manifest tampered: {result['tampered']}")
        if result.get("missing"):
            errors.append(f"governance manifest missing files: {result['missing']}")
    return errors


def check_env_override_hardening() -> list[str]:
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from tools.check_env_override_hardening import run_env_override_hardening_check

    return run_env_override_hardening_check()


def check_reviewer_evidence_index() -> list[str]:
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from tools.check_reviewer_evidence_index import run_reviewer_evidence_index_check

    return run_reviewer_evidence_index_check()


def check_definition_of_done_for_fixes_contract() -> list[str]:
    """AGENTS § Definition of Done for Fixes — closed-loop fix workflow markers."""
    path = REPO_ROOT / "AGENTS.md"
    if not path.is_file():
        return ["AGENTS.md: missing (Definition of Done for Fixes)"]
    text = path.read_text(encoding="utf-8", errors="replace")
    errors: list[str] = []
    for marker in (
        "Definition of Done for Fixes",
        'id="definition-of-done-for-fixes"',
        "IDENTIFY → ROOT-CAUSE → PATCH → RERUN EXACT",
        "Remaining Known Gaps",
        "Do not substitute explanation for closure",
        "Exact failed test passes",
    ):
        if marker not in text:
            errors.append(f"AGENTS.md: Definition of Done missing marker {marker!r}")
    srv = REPO_ROOT / "server.py"
    if srv.is_file():
        st = srv.read_text(encoding="utf-8", errors="replace")
        for tok in (
            "_startup_analytics_executor",
            "_shutdown_analytics_executor",
            "_analytics_bg_shutdown",
            "ED_DISABLE_STARTUP_ANALYTICS_WARM",
        ):
            if tok not in st:
                errors.append(f"server.py: missing test-safe analytics lifecycle marker {tok!r}")
    else:
        errors.append("server.py: missing (analytics lifecycle guard for reviewer-clean tests)")
    return errors


def check_meet_or_exceed_cycle_documentation() -> list[str]:
    path = REPO_ROOT / "AGENTS.md"
    if not path.is_file():
        return ["AGENTS.md: missing (Meet-or-Exceed Closure Cycle)"]
    text = path.read_text(encoding="utf-8", errors="replace")
    if "Meet-or-Exceed Closure Cycle" not in text:
        return ["AGENTS.md: missing § Meet-or-Exceed Closure Cycle (operator binding)"]
    if "VERDICT: MET | EXCEEDED" not in text and "VERDICT: MET" not in text:
        return ["AGENTS.md: Meet-or-Exceed section missing required VERDICT block"]
    errors: list[str] = []
    for marker in MEET_OR_EXCEED_UNIVERSAL_SCOPE_MARKERS:
        if marker not in text:
            errors.append(
                f"AGENTS.md: Meet-or-Exceed missing universal-scope marker {marker!r} "
                f"(standard applies full repo — not gated to a slice)"
            )
    return errors


def check_meet_or_exceed_signoff(commit_msg_path: Path) -> list[str]:
    """AGENTS § Meet-or-Exceed — commit claims must not use partial verdict vocabulary."""
    if not commit_msg_path.is_file():
        return []
    text = commit_msg_path.read_text(encoding="utf-8", errors="replace")
    if not text.strip():
        return []
    if META_COMMIT_LINE.search(text) or RULE_DRIFT_META_LINE.search(text):
        return []
    errors: list[str] = []
    for label, pat in MEET_OR_EXCEED_BANNED_VERDICT_PHRASES:
        if pat.search(text):
            errors.append(
                f"commit message: banned partial sign-off phrase ({label!r}) — "
                f"use Meet-or-Exceed cycle until VERDICT: MET or EXCEEDED only (AGENTS.md)"
            )
    for m in VERDICT_LINE.finditer(text):
        verdict = (m.group(1) or "").strip().upper().rstrip(".")
        if verdict not in MEET_OR_EXCEED_ALLOWED_VERDICTS:
            errors.append(
                f"commit message: VERDICT must be MET or EXCEEDED only (got {verdict!r})"
            )
    errors.extend(check_objective_code_audit_signoff(commit_msg_path))
    return errors


def check_objective_code_audit_signoff(commit_msg_path: Path) -> list[str]:
    """AGENTS § Objective→Code→Audit — VERDICT requires OBJECTIVE + AUDIT: CLEAN."""
    if not commit_msg_path.is_file():
        return []
    text = commit_msg_path.read_text(encoding="utf-8", errors="replace")
    if not text.strip():
        return []
    if META_COMMIT_LINE.search(text) or RULE_DRIFT_META_LINE.search(text):
        return []
    if not VERDICT_LINE.search(text):
        return []
    errors: list[str] = []
    if not OBJECTIVE_LINE.search(text):
        errors.append(
            "commit message: VERDICT without OBJECTIVE: — state operator intent first "
            "(AGENTS § Objective→Code→Audit closure)"
        )
    if not AUDIT_CLEAN_LINE.search(text):
        errors.append(
            "commit message: VERDICT without AUDIT: CLEAN — run "
            "python tools/enforce_all_rules.py --objective-audit (exit 0) before sign-off"
        )
    return errors


OBJECTIVE_CODE_AUDIT_MARKERS: tuple[str, ...] = (
    "Objective → Code → Audit closure",
    "Institutional sign-off contract — uniform Cursor + Claude",
    "Upfront mechanical gate",
    "run_upfront_mechanical_gate",
    "check_upfront_mechanical_gate_stamp",
    "OBJECTIVE → CODE → AUDIT",
    "run_objective_code_audit",
    "run_repo_wide_static_audit",
    "run_situational_runtime_audits",
    "audit_ablation_placement_validity",
    "check_objective_code_audit_signoff",
    "check_institutional_signoff_contract",
    "Canonical audit command ladder",
    "--upfront-gate",
    "--objective-audit",
    "AUDIT: CLEAN",
)

OBJECTIVE_CODE_AUDIT_UNIVERSAL_SCOPE_MARKERS: tuple[str, ...] = (
    "Scope — universal, full repo",
    "every agent turn",
    "every deliverable",
    "situational runtime",
    "where the situation fits",
    "run_repo_wide_static_audit",
)

# Paths that trigger ablation placement runtime audit when staged (repo-wide rule, ML/ablation cone).
ABLATION_RUNTIME_PATH_TRIGGERS: tuple[str, ...] = (
    "arch_competition/",
    "arch_competition\\",
    "tools/feature_curation_gate.py",
    "ml_predict.py",
    "lstm_data.py",
    "lstm_model.py",
    "features/lstm_sequence_input.py",
    "transformer_train.py",
    "governance/artifacts/feature_ablation_manifest",
    "models/active/",
    "models/active\\",
    "models/active_5c/",
    "models/active_15c/",
    "models/active_60c/",
)


def _normalize_staged_path(path: str) -> str:
    return path.replace("\\", "/")


def situational_audit_applies(
    audit_id: str,
    path_triggers: tuple[str, ...],
    *,
    staged: set[str],
    force_all: bool = False,
) -> bool:
    """True when a situational runtime audit fits the current turn (AGENTS § situational table)."""
    if force_all:
        return True
    if staged:
        for raw in staged:
            norm = _normalize_staged_path(raw)
            if any(norm.startswith(t.replace("\\", "/")) or t.replace("\\", "/") in norm for t in path_triggers):
                return True
        return False
    if audit_id == "ablation_placement_validity":
        return (
            REPO_ROOT / "governance" / "artifacts" / "feature_ablation_manifest_leaf.json"
        ).is_file()
    return False


def run_repo_wide_static_audit(
    *,
    staged: set[str] | None = None,
    full_static: bool = True,
    force_fresh: bool = False,
) -> list[str]:
    """Repo-wide static locks — full strength for objective-audit / --enforce-static."""
    global _SESSION_STATIC_AUDIT_CACHE
    st = staged if staged is not None else set()
    cache_key = tuple(sorted(st))
    if _pytest_reuse_static_audit() and not force_fresh and _SESSION_STATIC_AUDIT_CACHE is not None:
        cached = _SESSION_STATIC_AUDIT_CACHE.get(cache_key)
        if cached is not None:
            return list(cached)

    errors = _run_repo_wide_static_check_funcs(
        staged=st,
        full_static=True,
        use_cache=False,
    )

    if _pytest_reuse_static_audit() and not force_fresh:
        if _SESSION_STATIC_AUDIT_CACHE is None:
            _SESSION_STATIC_AUDIT_CACHE = {}
        _SESSION_STATIC_AUDIT_CACHE[cache_key] = list(errors)
    return errors


def run_situational_runtime_audits(
    *,
    staged: set[str] | None = None,
    force_all: bool = False,
) -> dict:
    """Runtime probes that apply only where the touched cone / subsystem fits."""
    st = staged if staged is not None else _git_staged_paths()
    applied: list[str] = []
    skipped: list[str] = []
    runtime_errors: list[str] = []
    results: dict = {}

    ablation_applies = situational_audit_applies(
        "ablation_placement_validity",
        ABLATION_RUNTIME_PATH_TRIGGERS,
        staged=st,
        force_all=force_all,
    )
    if ablation_applies:
        applied.append("ablation_placement_validity")
        placement = audit_ablation_placement_validity()
        results["ablation_placement_validity"] = placement
        if not placement.get("ok"):
            runtime_errors.extend(placement.get("errors") or [])
    else:
        skipped.append("ablation_placement_validity")

    return {
        "applied_runtime_audits": applied,
        "skipped_runtime_audits": skipped,
        "runtime_errors": runtime_errors,
        "runtime_ok": not runtime_errors,
        "situational_results": results,
    }


def check_objective_code_audit_documentation() -> list[str]:
    """AGENTS § Objective→Code→Audit — prose + wiring markers must exist."""
    path = REPO_ROOT / "AGENTS.md"
    if not path.is_file():
        return ["AGENTS.md: missing (Objective→Code→Audit closure)"]
    text = path.read_text(encoding="utf-8", errors="replace")
    errors: list[str] = []
    if "Objective → Code → Audit closure" not in text:
        errors.append("AGENTS.md: missing § Objective→Code→Audit closure (operator binding)")
    for marker in OBJECTIVE_CODE_AUDIT_MARKERS:
        if marker not in text:
            errors.append(f"AGENTS.md: missing Objective→Code→Audit marker {marker!r}")
    for marker in OBJECTIVE_CODE_AUDIT_UNIVERSAL_SCOPE_MARKERS:
        if marker not in text:
            errors.append(
                f"AGENTS.md: Objective→Code→Audit missing universal-scope marker {marker!r} "
                f"(protocol applies full repo — situational runtime where cone fits)"
            )
    return errors


def check_objective_code_audit_contract() -> list[str]:
    """Static wiring for Objective→Code→Audit mechanical lock."""
    errors: list[str] = []
    errors.extend(check_objective_code_audit_documentation())

    checker = REPO_ROOT / "tools" / "check_fix_everything_we_touch.py"
    if checker.is_file():
        checker_text = checker.read_text(encoding="utf-8", errors="replace")
        for tok in (
            "def run_objective_code_audit(",
            "def run_repo_wide_static_audit(",
            "def run_situational_runtime_audits(",
            "def audit_ablation_placement_validity(",
            "def check_objective_code_audit_signoff(",
        ):
            if tok not in checker_text:
                errors.append(f"check_fix_everything_we_touch.py: missing {tok}")
    else:
        errors.append("check_fix_everything_we_touch.py: missing")

    enforce = REPO_ROOT / "tools" / "enforce_all_rules.py"
    if enforce.is_file():
        enforce_text = enforce.read_text(encoding="utf-8", errors="replace")
        if "--objective-audit" not in enforce_text:
            errors.append("enforce_all_rules.py: missing --objective-audit audit flag")
        if "--full-runtime" not in enforce_text:
            errors.append("enforce_all_rules.py: missing --full-runtime situational audit flag")
    else:
        errors.append("enforce_all_rules.py: missing")

    gate_py = REPO_ROOT / "tools" / "feature_curation_gate.py"
    if gate_py.is_file():
        gate_text = gate_py.read_text(encoding="utf-8", errors="replace")
        if "audit_ablation_placement_validity" not in gate_text:
            errors.append(
                "feature_curation_gate.py: missing audit_ablation_placement_validity in preflight"
            )
    return errors


def run_objective_code_audit(
    *,
    staged: set[str] | None = None,
    runtime: bool = True,
    full_runtime: bool = False,
    force_fresh_static: bool = False,
) -> dict:
    """Mandatory turn audit: repo-wide static locks + situational runtime where cone fits."""
    st = staged if staged is not None else _git_staged_paths()
    static_errors = run_repo_wide_static_audit(staged=st, force_fresh=force_fresh_static)

    out: dict = {
        "audit": "objective_code_audit",
        "scope": "full repo static; situational runtime where cone fits",
        "cycle": ["OBJECTIVE", "CODE", "AUDIT", "RECODE", "REAUDIT", "SUMMARIZE"],
        "static_ok": not static_errors,
        "static_errors": static_errors,
        "staged_paths": sorted(st),
    }

    if runtime:
        situational = run_situational_runtime_audits(staged=st, force_all=full_runtime)
        out["applied_runtime_audits"] = situational.get("applied_runtime_audits") or []
        out["skipped_runtime_audits"] = situational.get("skipped_runtime_audits") or []
        out["situational_results"] = situational.get("situational_results") or {}
        out["runtime_errors"] = situational.get("runtime_errors") or []
        out["runtime_ok"] = bool(situational.get("runtime_ok"))
    else:
        out["applied_runtime_audits"] = []
        out["skipped_runtime_audits"] = ["all (runtime disabled)"]
        out["situational_results"] = {}
        out["runtime_ok"] = True
        out["runtime_errors"] = []

    out["ok"] = out["static_ok"] and bool(out.get("runtime_ok"))
    out["audit_status"] = "CLEAN" if out["ok"] else "DEFECTS"
    return out


def check_paths(
    paths: list[Path],
    staged: set[str] | None = None,
    *,
    full_static: bool = False,
    profile: Any | None = None,
) -> list[str]:
    scope = _scope_module()
    ProfileCollector = scope.ProfileCollector

    staged = staged if staged is not None else _git_staged_paths()
    errors: list[str] = []
    prof = profile if isinstance(profile, ProfileCollector) else None

    memo_paths = [p for p in paths if p.is_file() and "SCHWAB_V4_REVIEW_MEMOS" in p.as_posix()]
    for memo_path in memo_paths:
        errors.extend(check_v4_memo(memo_path, staged))
        tools_dir = Path(__file__).resolve().parent
        if str(tools_dir) not in sys.path:
            sys.path.insert(0, str(tools_dir))
        import check_schwab_csv_first as schwab_guard

        errors.extend(schwab_guard.check_v4_memo_gatekeeper_csv(memo_path, REPO_ROOT))

    def _timed(name: str, fn: Callable[[], list[str]], scope: str = "staged") -> None:
        t0 = time.perf_counter()
        errors.extend(fn())
        if prof is not None:
            prof.record(name, time.perf_counter() - t0, scope=scope, files_scanned=len(staged))

    _timed("upfront_gate_stamp", lambda: check_upfront_mechanical_gate_stamp(staged))
    _timed("staged_rule_drift", lambda: check_staged_rule_drift(staged))
    _timed("action_not_documentation", lambda: check_action_not_documentation(staged))
    _timed("storage_writer_has_consumer", lambda: check_storage_writer_has_consumer(staged))
    _timed("persistence_map_fresh", lambda: check_persistence_map_fresh(staged))
    _timed("persistence_writer_has_reader", lambda: check_persistence_writer_has_reader(staged))

    t0 = time.perf_counter()
    errors.extend(
        _run_repo_wide_static_check_funcs(
            staged=staged,
            full_static=full_static,
            profile=prof,
            use_cache=not full_static,
        )
    )
    if prof is not None:
        prof.record(
            "repo_wide_static_aggregate",
            time.perf_counter() - t0,
            scope="repo" if full_static else "critical|cached",
            files_scanned=len(staged),
        )

    tools_dir = Path(__file__).resolve().parent
    if str(tools_dir) not in sys.path:
        sys.path.insert(0, str(tools_dir))
    import check_encoder_cone_tests as encoder_cone

    _timed("encoder_cone_tests", lambda: encoder_cone.check_encoder_cone_tests(staged))

    for path in paths:
        if path.name == "COMMIT_EDITMSG" or "--commit-msg" in path.as_posix():
            errors.extend(check_commit_message(path))
        elif path.is_file() and path.suffix == "" and "COMMIT_EDITMSG" in path.name:
            errors.extend(check_commit_message(path))

    return errors


ABLATED_TRAINING_ORCHESTRATOR = "tools/train_per_anchor_sequential.ps1"


def check_ablated_training_only() -> list[str]:
    """O-56 / AGENTS §Ablation contract: the production retrain orchestrator MUST train on the
    ablated data — full-feature is NOT a valid retrain target. Lock: the orchestrator sets
    ED_APPLY_ABLATION_SURVIVORS=1 and never disables it. Absent orchestrator = nothing to lock."""
    errors: list[str] = []
    p = REPO_ROOT / ABLATED_TRAINING_ORCHESTRATOR
    if not p.is_file():
        return errors
    enabled = False
    for line in p.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s.startswith("#") or "ED_APPLY_ABLATION_SURVIVORS" not in s or "=" not in s:
            continue
        val = s.split("=", 1)[1].split("#", 1)[0].strip().strip('"').strip("'").lower()
        if val in ("0", "false", "no", ""):
            errors.append(
                f"{ABLATED_TRAINING_ORCHESTRATOR}: ED_APPLY_ABLATION_SURVIVORS must be '1' — ablated "
                f"training is the only valid retrain target (AGENTS §Ablation contract); got {val!r}."
            )
        elif val == "1":
            enabled = True
    if not enabled and not errors:
        errors.append(
            f"{ABLATED_TRAINING_ORCHESTRATOR}: must set ED_APPLY_ABLATION_SURVIVORS=1 — train on the "
            "ablated data; full-feature is not a valid retrain target (AGENTS §Ablation contract)."
        )
    return errors


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    staged = _git_staged_paths()

    if args and args[0] == "--profile":
        scope = _scope_module()
        prof = scope.ProfileCollector()
        check_paths([], staged=staged, full_static=True, profile=prof)
        artifact = prof.to_artifact()
        scope.PROFILE_ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
        scope.PROFILE_ARTIFACT.write_text(json.dumps(artifact, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(artifact, indent=2))
        slow = sorted(artifact.get("subchecks") or [], key=lambda r: r.get("seconds") or 0, reverse=True)[:8]
        print("\nSlowest subchecks:", file=sys.stderr)
        for row in slow:
            print(f"  {row.get('seconds')}s  {row.get('name')}  ({row.get('scope')})", file=sys.stderr)
        return 0

    full_static = bool(args and args[0] == "--full-static")
    if full_static:
        args = args[1:]

    if args and args[0] == "--commit-msg":
        paths = [Path(a) for a in args[1:]]
    elif args:
        paths = [Path(a) for a in args]
    else:
        paths = [REPO_ROOT / p for p in staged]

    if len(args) == 1 and Path(args[0]).is_file() and Path(args[0]).name == "COMMIT_EDITMSG":
        paths = [Path(args[0])]

    errors: list[str] = []
    tools_dir = Path(__file__).resolve().parent
    if str(tools_dir) not in sys.path:
        sys.path.insert(0, str(tools_dir))
    import check_encoder_cone_tests as encoder_cone

    if paths and all(p.name == "COMMIT_EDITMSG" for p in paths if p.is_file()):
        for p in paths:
            errors.extend(check_commit_message(p))
            errors.extend(encoder_cone.check_encoder_cone_commit_claim(p.read_text(encoding="utf-8"), staged))
    else:
        errors.extend(check_paths(paths, staged=staged, full_static=full_static))
        for p in paths:
            if p.name == "COMMIT_EDITMSG":
                errors.extend(check_commit_message(p))
                errors.extend(
                    encoder_cone.check_encoder_cone_commit_claim(
                        p.read_text(encoding="utf-8"), staged
                    )
                )

    if errors:
        for err in errors:
            print(err, file=sys.stderr)
        print(
            "\ncheck_fix_everything_we_touch: land fix+test in the same commit; no banned/excuse "
            "phrases in commit or staged source. See AGENTS.md § Fix everything we touch and "
            "§ Rule compliance — zero drift.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
