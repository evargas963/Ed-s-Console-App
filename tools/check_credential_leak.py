#!/usr/bin/env python3
"""Credential / secret leak firewall on staged (and optional) text diffs.

Refuses Bearer tokens, API keys, private keys and operator-home paths (Windows, posix and Git
Bash spellings) in `git diff --cached` (what a commit would publish). The scanner's own suite
and this module are path-skipped
(injected payloads must live there). Other fixtures mark a line with
`# credential-leak-ok` or `# credential-leak-fixture-ok`.

    python tools/check_credential_leak.py
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_end_to_end import ToolError, _diff_path  # noqa: E402

REPO = Path(__file__).resolve().parents[1]

# Inline markers (any line carrying one is ignored).
_FIXTURE_MARKERS = ("credential-leak-ok", "credential-leak-fixture-ok")

# Paths that deliberately contain mock secrets for detector proof — never block.
_SKIP_PATHS = frozenset({
    "tests/test_credential_leak_v1.py",
    "tools/check_credential_leak.py",
})

SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # Require ≥16 token chars so prose like "Bearer token" in docs does not trip.
    ("bearer_token", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9\-._~+/]{16,}=*")),
    ("jwt_compact", re.compile(
        r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("generic_api_key_assign", re.compile(
        r"(?i)\b(api[_-]?key|secret[_-]?key|access[_-]?token|client[_-]?secret)\b\s*[:=]\s*"
        r"['\"][^'\"]{12,}['\"]")),
    ("pem_private_key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("windows_user_home", re.compile(
        r"[A-Za-z]:[\\/]+Users[\\/]+[A-Za-z0-9_.-]+", re.IGNORECASE)),
    ("posix_user_home", re.compile(r"(?<![\w<])/(?:home|Users)/[A-Za-z0-9_.-]+[\\/]")),
    ("git_bash_user_home", re.compile(r"(?<![\w<])/[A-Za-z]/Users/[A-Za-z0-9_.-]+[\\/]", re.IGNORECASE)),
)


class StagedDiffUnreadable(RuntimeError):
    """`git diff --cached` did not run. An unread diff is not an empty diff."""


def _staged_text(root: Path) -> str:
    """The staged diff, RAISING when git could not produce it.

    Any failure of git — a broken or locked index, a corrupt object, git absent from PATH —
    raises: an unread diff would scan clean and let the commit through unread. "I could not
    look" is not "there is nothing".
    """
    # core.quotePath=true: a quoted name is all escapes, whatever the repository's own setting.
    # --text, --no-textconv, --no-ext-diff: the bytes the commit publishes, whatever its attributes
    # or diff settings. Read as bytes: git ends a line only at a line feed.
    p = subprocess.run(
        ["git", "-c", "core.quotePath=true", "diff", "--cached", "--unified=0", "--no-color",
         "--text", "--no-textconv", "--no-ext-diff", "--src-prefix=a/", "--dst-prefix=b/"],
        cwd=root,
        capture_output=True,
    )
    if p.returncode != 0:
        raise StagedDiffUnreadable(
            f"git diff --cached exited {p.returncode}: "
            f"{(p.stderr.decode('utf-8', errors='replace').strip().splitlines() or [''])[0]}"
        )
    return p.stdout.decode("utf-8", errors="replace")


def find_credential_leaks(root: Path = REPO) -> list[str]:
    """Every secret or operator-home path on a line `root`'s staged diff adds."""
    text = _staged_text(root)
    hits: list[str] = []
    current_file = "?"
    skip_file = False
    header = False      # between a file's `diff --git` and its first hunk: an added line is not a header
    for line in text.split("\n"):
        if line.startswith("diff --git "):
            current_file, skip_file, header = "?", False, True
            continue
        if line.startswith("@@ "):
            header = False
            continue
        if header:
            if line.startswith("+++ ") and line != "+++ /dev/null":
                try:
                    current_file = _diff_path(line[len("+++ "):])
                except ToolError as e:
                    raise StagedDiffUnreadable(str(e)) from e
                skip_file = current_file in _SKIP_PATHS
            continue
        if skip_file or not line.startswith("+"):
            continue
        body = line[1:]
        if any(m in body for m in _FIXTURE_MARKERS):
            continue
        for label, pat in SECRET_PATTERNS:
            if pat.search(body):
                hits.append(f"{current_file}: {label}: {body.strip()[:120]}")
    return hits


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        hits = find_credential_leaks()
    except StagedDiffUnreadable as e:
        # Fail CLOSED: "clean" for a diff nobody read is the one outcome a secrets gate must
        # never produce.
        print("check_credential_leak: FAIL — the staged diff could not be read, so nothing "
              "was scanned:", file=sys.stderr)
        print(f"  {e}", file=sys.stderr)
        print("  This is NOT a clean result. Fix the repository state and commit again.",
              file=sys.stderr)
        return 1
    rc = 0
    if hits:
        print("check_credential_leak: FAIL — secrets or private paths in staged diff:")
        for h in hits[:40]:
            print(f"  {h}")
        if len(hits) > 40:
            print(f"  … and {len(hits) - 40} more")
        rc = 1
    else:
        print("check_credential_leak: PASS (staged diff clean)")
    if "--and-private-paths" in args:
        # ONE secrets-and-paths hook at the commit seam. The tracked-evidence private-path scan
        # (tools/check_private_paths.py) keeps its own module and suite; this flag runs it in
        # the same hook so the seam has one owner.
        if str(REPO) not in sys.path:
            sys.path.insert(0, str(REPO))
        from tools.check_private_paths import main as private_paths_main
        rc = max(rc, private_paths_main())
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
