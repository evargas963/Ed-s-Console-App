"""Pre-commit guard: fail if a commit message or non-tracking file contains deferral language.

Authored 2026-05-24 after the operator's third call-out on the deferral pattern
(FIND-LIVEUI-6 paired-fix turn: Playwright spec was deferred with the rationale
"PYTEST-TO-CI gate" — a re-skinned version of every prior deferral).

Operator's rule (`feedback_no_audit_deferral_across_walks` memory): any small
fix without a real gate (telemetry / training-skew / unwalked-file /
accepted-as-designed) must land in the same commit. The deferral pattern shows
up first in language — "deferred", "TBD", "pending X", "follow-up commit",
"will land later", "next slice", "Phase N+1 paired-fix pending". This script
catches those phrases before they reach a remote.

Scope:
  - Commit message file (when wired as a `commit-msg` hook in pre-commit).
  - Staged source files (when wired as a normal `pre-commit` hook).

Allowlist (files where future-work tracking is legitimate, NOT deferral):
  - OPEN_ITEMS.md, ACTIVE_PROGRAM.md
  - governance/**/*.md
  - This script itself (so the rule documentation can list forbidden phrases).

Usage (manual): `python tools/check_no_deferral_language.py <paths...>` —
prints `file:line: matched <phrase>` to stderr-like stdout and exits non-zero
on any hit; exits zero otherwise. Pre-commit wiring is left to the operator
(see suggested `.pre-commit-config.yaml` block at the bottom of this docstring).

Suggested .pre-commit-config.yaml additions:

    - id: no-deferral-language-msg
      name: no deferral language in commit message
      entry: python tools/check_no_deferral_language.py
      language: system
      stages: [commit-msg]

    - id: no-deferral-language-files
      name: no deferral language in staged source files
      entry: python tools/check_no_deferral_language.py
      language: system
      types: [text]
      exclude: '^(OPEN_ITEMS\\.md|ACTIVE_PROGRAM\\.md|governance/.*|tools/check_no_deferral_language\\.py|.*memory/feedback_no_audit_deferral_across_walks\\.md)$'
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# Each pattern is compiled case-insensitive. Use word boundaries where the phrase
# is a single token; use anchored multi-word phrases where context matters.
#
# Quote-aware lookbehind/lookahead on verb forms ("deferred"/"deferring") lets a
# commit message or memory file quote the word for meta-discussion (e.g.,
# "operator caught X as 'deferred'") without triggering. The bare noun "deferral"
# is intentionally NOT caught — it's the concept name and appears in slug ids
# like "PROC-NO-DEFERRAL".
DEFERRAL_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "'deferred' scheduling phrasing (unquoted)",
        re.compile(
            r"(?<![\"'`])"
            r"(?:\b(?:extension|variant|spec|implementation|fix|work|promotion)\s+(?:is\s+)?deferred\b"
            r"|\bdeferred\s+(?:until|to|this|that|the)\b"
            r"|\(\s*deferred\s*\))"
            r"(?![\"'`])",
            re.IGNORECASE,
        ),
    ),
    ("'deferring' gerund (unquoted)", re.compile(r"(?<![\"'`])\bdeferring\b(?![\"'`])", re.IGNORECASE)),
    ("'TBD:' marker", re.compile(r"\bTBD\b\s*[:\-—]", re.IGNORECASE)),
    ("'pending <X>' deferral phrasing", re.compile(
        r"\bpending\s+(?:playwright|ci|operator\s+sign-?off|next\s+slice|follow-?up|"
        r"future\s+commit|paired[- ]fix|implementation|consumer|behavioral)\b",
        re.IGNORECASE,
    )),
    ("'follow-up commit/slice'", re.compile(r"\bfollow-?up\s+(?:commit|slice|paired[- ]fix|landing)\b", re.IGNORECASE)),
    ("'next slice will' / 'next commit will'", re.compile(
        r"\bnext\s+(?:slice|commit|turn|paired[- ]fix)\s+(?:will|lands|adds|covers|handles)\b",
        re.IGNORECASE,
    )),
    ("'future commit/slice/turn'", re.compile(
        r"\b(?:in|for|a)\s+(?:future|later)\s+(?:commit|slice|turn|paired[- ]fix)\b",
        re.IGNORECASE,
    )),
    ("'will land later/in a future <unit>'", re.compile(
        r"\bwill\s+land\s+(?:later|in\s+(?:a\s+)?(?:future|follow))",
        re.IGNORECASE,
    )),
    ("'Phase N paired-fix pending'", re.compile(
        r"Phase\s*\d+\s+paired[- ]fix\s+pending",
        re.IGNORECASE,
    )),
    ("'implementation pending' / 'consumer pending'", re.compile(
        r"\b(?:implementation|consumer|wire-?in|paired[- ]fix)\s+pending\b",
        re.IGNORECASE,
    )),
    ("'I'll <verb> later' / 'I'll commit it next'", re.compile(
        r"\bI(?:'ll| will)\s+(?:do|commit|land|add|wire|implement|finish)\s+(?:it|that|this|them)?\s*(?:later|next|in\s+a\s+follow)",
        re.IGNORECASE,
    )),
    ("'<verb> later' bare phrasing", re.compile(
        r"\b(?:land|ship|wire|implement|add|finish|cover)\s+(?:it\s+|this\s+|that\s+|them\s+)?later\b",
        re.IGNORECASE,
    )),
    ("'still pending' / 'currently pending' (scheduling)", re.compile(
        r"\b(?:still|currently)\s+pending\s+"
        r"(?:until|for|on|in|next|implementation|closure|fix|spec|paired|playwright|ci)\b",
        re.IGNORECASE,
    )),
    ("'behavioral/e2e/spec ... pending'", re.compile(
        r"\b(?:behavioral|e2e|spec|test)\s+\w*\s*\w*\s*pending\b",
        re.IGNORECASE,
    )),
    ("'can land later'", re.compile(
        r"\bcan\s+land\s+later\b",
        re.IGNORECASE,
    )),
)

# Paths (relative to repo root) where future-work tracking is the file's purpose.
ALLOWLIST_PATH_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(^|/)OPEN_ITEMS\.md$"),
    re.compile(r"(^|/)ACTIVE_PROGRAM\.md$"),
    re.compile(r"(^|/)MEMORY\.md$"),
    re.compile(r"(^|/)governance/"),
    re.compile(r"(^|/)tools/check_no_deferral_language\.py$"),
    re.compile(r"(^|/)tests/test_check_no_deferral_language\.py$"),
    re.compile(r"(^|/)tests/test_no_deferral_artifacts\.py$"),
    re.compile(r"(^|/)tests/"),
    re.compile(r"memory/feedback_no_audit_deferral_across_walks\.md$"),
    # `.git/COMMIT_EDITMSG` and other commit-msg paths are intentionally NOT
    # allowlisted — that's the primary site we want to gate.
)


def _path_is_allowlisted(path: Path) -> bool:
    s = path.as_posix()
    return any(pat.search(s) for pat in ALLOWLIST_PATH_PATTERNS)


def _scan_text(text: str) -> list[tuple[int, str, str]]:
    """Return (line_no, pattern_label, snippet) for every match."""
    hits: list[tuple[int, str, str]] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        if "[REAL-GATE:" in line:
            continue
        for label, pat in DEFERRAL_PATTERNS:
            m = pat.search(line)
            if m:
                hits.append((line_no, label, line.strip()[:200]))
    return hits


def check_path(path: Path) -> list[tuple[int, str, str]]:
    if _path_is_allowlisted(path):
        return []
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return _scan_text(text)


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        return 0
    failed = False
    for raw in args:
        path = Path(raw)
        for line_no, label, snippet in check_path(path):
            print(f"{path}:{line_no}: deferral-language hit ({label}): {snippet!r}")
            failed = True
    if failed:
        print(
            "\ncheck_no_deferral_language: deferral phrases detected. Either land the "
            "work in this commit (the operator rule per "
            "feedback_no_audit_deferral_across_walks) or move the future-work "
            "tracking row to OPEN_ITEMS.md / governance/ — those surfaces are "
            "allowlisted because they are the legitimate place for future work.",
            file=sys.stderr,
        )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
