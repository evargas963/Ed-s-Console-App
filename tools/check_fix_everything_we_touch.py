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
  python tools/check_fix_everything_we_touch.py              # staged files (pre-commit)
  python tools/check_fix_everything_we_touch.py path [path]  # explicit paths
  python tools/check_fix_everything_we_touch.py --commit-msg .git/COMMIT_EDITMSG
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MEMO_DIR = REPO_ROOT / "governance" / "SCHWAB_V4_REVIEW_MEMOS"

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
# Normative list lives in AGENTS.md; patterns here are the mechanical subset.
EXCUSE_PARTIAL_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("by design / works as designed", re.compile(r"\b(?:by\s+design|works\s+as\s+(?:designed|intended))\b", re.IGNORECASE)),
    ("policy by design", re.compile(r"\bpolicy\s+by\s+design\b", re.IGNORECASE)),
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


def check_persistence_map_fresh(staged: set[str]) -> list[str]:
    """Pass 2b — persistence_consumer_map.json must stay in sync with persistence sources.

    Triggers when commit stages any of db.py / calibration/writer.py /
    tools/audit_persistence_consumers.py. The map at
    governance/artifacts/persistence_consumer_map.json must also be staged
    in the same commit AND must match what the audit tool generates from the
    on-disk persistence sources.

    Failure modes blocked:
      1. Persistence source edited, map not re-staged -> "stale map".
      2. Persistence source edited, map staged but doesn't match -> "stale map content".

    The full content match runs the audit tool's --check mode. This catches
    drift between map and sources even when the operator remembered to stage
    the map but forgot to regenerate it.
    """
    triggers = [f for f in staged if f in PERSISTENCE_MAP_TRIGGER_FILES]
    if not triggers:
        return []

    errors: list[str] = []
    if PERSISTENCE_MAP_PATH not in staged:
        errors.append(
            f"{PERSISTENCE_MAP_PATH}: missing from commit but {', '.join(triggers)} staged. "
            f"Pass 2b — regenerate with `python tools/audit_persistence_consumers.py --stable-time` "
            f"and stage the result in the same commit."
        )
        return errors  # no point running --check if map isn't staged

    # Run the audit tool's --check against the working tree to confirm the staged
    # map matches what the tool would emit from current sources.
    audit_tool_path = REPO_ROOT / PERSISTENCE_AUDIT_TOOL
    if not audit_tool_path.is_file():
        return errors  # tool itself absent — can't run check
    try:
        proc = subprocess.run(
            [sys.executable, str(audit_tool_path), "--check"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        return errors + [f"{PERSISTENCE_MAP_PATH}: cannot run audit tool ({exc})"]
    if proc.returncode != 0:
        errors.append(
            f"{PERSISTENCE_MAP_PATH}: stale content vs persistence sources. "
            f"{proc.stderr.strip() or '(no detail)'}. "
            f"Pass 2b — regenerate with `python tools/audit_persistence_consumers.py --stable-time` "
            f"and re-stage."
        )
    return errors


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
    return errors


VERDICT_LINE = re.compile(r"\bVERDICT:\s*(\S+)", re.IGNORECASE)
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
    return errors


def check_paths(paths: list[Path], staged: set[str] | None = None) -> list[str]:
    staged = staged if staged is not None else _git_staged_paths()
    errors: list[str] = []

    memo_paths = [p for p in paths if p.is_file() and "SCHWAB_V4_REVIEW_MEMOS" in p.as_posix()]
    for memo_path in memo_paths:
        errors.extend(check_v4_memo(memo_path, staged))
        tools_dir = Path(__file__).resolve().parent
        if str(tools_dir) not in sys.path:
            sys.path.insert(0, str(tools_dir))
        import check_schwab_csv_first as schwab_guard

        errors.extend(schwab_guard.check_v4_memo_gatekeeper_csv(memo_path, REPO_ROOT))

    # Artifact-content rule (§Action-not-documentation): run once per commit on the full staged set.
    errors.extend(check_action_not_documentation(staged))
    # Storage-needs-consumer rule (§Storage-needs-consumer): block dormant writers at pre-commit.
    errors.extend(check_storage_writer_has_consumer(staged))
    # Pass 2b: persistence_consumer_map.json freshness when persistence sources staged.
    errors.extend(check_persistence_map_fresh(staged))
    # Pass 1b: new INSERTs must hit tables with readers OR a tracked REAL-GATE row.
    errors.extend(check_persistence_writer_has_reader(staged))
    errors.extend(check_mvp_dataframe_ingress())
    errors.extend(check_institutional_contract())
    errors.extend(check_meet_or_exceed_cycle_documentation())
    tools_dir = Path(__file__).resolve().parent
    if str(tools_dir) not in sys.path:
        sys.path.insert(0, str(tools_dir))
    import check_encoder_cone_tests as encoder_cone

    errors.extend(encoder_cone.check_encoder_cone_documentation())
    errors.extend(encoder_cone.check_encoder_cone_tests(staged))

    for path in paths:
        if path.name == "COMMIT_EDITMSG" or "--commit-msg" in path.as_posix():
            errors.extend(check_commit_message(path))
        elif path.is_file() and path.suffix == "" and "COMMIT_EDITMSG" in path.name:
            errors.extend(check_commit_message(path))

    return errors


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    staged = _git_staged_paths()

    if args and args[0] == "--commit-msg":
        paths = [Path(a) for a in args[1:]]
    elif args:
        paths = [Path(a) for a in args]
    else:
        paths = [REPO_ROOT / p for p in staged]

    # commit-msg hook passes a single file path as the only arg (no flag)
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
        errors.extend(check_paths(paths, staged=staged))
        # commit-msg file may also be passed alongside staged paths in some hooks
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
