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
    r"operator-as-catch|mechanical enforcement|commit-msg guard"
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
)
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
        if EVIDENCE_CITE.search(line):
            continue
        for label, pat in UNVERIFIED_CLAIM_PATTERNS:
            if pat.search(line):
                hits.append(
                    f"{path}:{line_no}: unverified-claim hit ({label}): {line.strip()[:200]!r} "
                    f"(AGENTS § Do not lie — cite tests/, @ SHA, or :line on same line)"
                )
    return hits


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
    if paths and all(p.name == "COMMIT_EDITMSG" for p in paths if p.is_file()):
        for p in paths:
            errors.extend(check_commit_message(p))
    else:
        errors.extend(check_paths(paths, staged=staged))
        # commit-msg file may also be passed alongside staged paths in some hooks
        for p in paths:
            if p.name == "COMMIT_EDITMSG":
                errors.extend(check_commit_message(p))

    if errors:
        for err in errors:
            print(err, file=sys.stderr)
        print(
            "\ncheck_fix_everything_we_touch: land fix+test in the same commit as the memo, "
            "or mark code edit landed / audit catch Closed. See AGENTS.md § Fix everything we touch.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
