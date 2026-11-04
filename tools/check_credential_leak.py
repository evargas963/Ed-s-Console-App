#!/usr/bin/env python3
"""Credential / secret leak firewall on the whole repository and on a change's history.

Refuses Bearer tokens, API keys, private keys and operator-home paths (Windows, posix and Git
Bash spellings) on any line of any tracked file (the index at commit, HEAD with --base), and on
any line `git diff --cached` adds (with --base, on any line any commit in `<base>..HEAD` adds,
since a line removed again later is still published in main's history), every file read as text
(what a commit would publish). No path and no line is skipped.

    python -m tools.check_credential_leak                       (pre-commit)
    python -m tools.check_credential_leak --base origin/main    (CI)
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

from tools.check_end_to_end import ToolError, _diff_path

REPO = Path(__file__).resolve().parents[1]

SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # Require ≥16 token chars so prose like "Bearer token" in docs does not trip.
    ("bearer_token", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9\-._~+/]{16,}=*")),
    (
        "jwt_compact",
        re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
    ),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    (
        "generic_api_key_assign",
        re.compile(
            r"(?i)\b(api[_-]?key|secret[_-]?key|access[_-]?token|client[_-]?secret)\b\s*[:=]\s*"
            r"['\"][^'\"]{12,}['\"]"
        ),
    ),
    ("pem_private_key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("windows_user_home", re.compile(r"[A-Za-z]:[\\/]+Users[\\/]+[A-Za-z0-9_.-]+", re.IGNORECASE)),
    ("posix_user_home", re.compile(r"(?<![\w<])/(?:home|Users)/[A-Za-z0-9_.-]+[\\/]")),
    (
        "git_bash_user_home",
        re.compile(r"(?<![\w<])/[A-Za-z]/Users/[A-Za-z0-9_.-]+[\\/]", re.IGNORECASE),
    ),
)


class DiffUnreadable(RuntimeError):
    """git could not produce the diff. An unread diff is not an empty diff."""


def _added_text(root: Path, base: str | None = None) -> str:
    """The staged diff, or with `base` every commit's diff in `base..HEAD` (a line one commit adds
    and a later one removes is still published in main's history), RAISING when git could not
    produce it.

    Any failure of git — a broken or locked index, a corrupt object, an unknown base, git absent
    from PATH — raises: an unread diff would scan clean and let the change through unread. "I
    could not look" is not "there is nothing".
    """
    # core.quotePath=true: a quoted name is all escapes, whatever the repository's own setting.
    # --text, --no-textconv, --no-ext-diff: the bytes the commit publishes, whatever its attributes
    # or diff settings. Read as bytes: git ends a line only at a line feed.
    # --diff-merges=remerge: a merge commit shows only what it adds beyond git's own merge of its
    # parents (a conflict resolved by hand), never the lines its other parent brings in.
    which = (
        ["log", "-p", "--diff-merges=remerge", "--format=", f"{base}..HEAD"]
        if base
        else ["diff", "--cached"]
    )
    p = subprocess.run(
        [
            "git",
            "-c",
            "core.quotePath=true",
            *which,
            "--unified=0",
            "--no-color",
            "--text",
            "--no-textconv",
            "--no-ext-diff",
            "--src-prefix=a/",
            "--dst-prefix=b/",
        ],
        cwd=root,
        capture_output=True,
    )
    if p.returncode != 0:
        raise DiffUnreadable(
            f"git {' '.join(which)} exited {p.returncode}: "
            f"{(p.stderr.decode('utf-8', errors='replace').strip().splitlines() or [''])[0]}"
        )
    return p.stdout.decode("utf-8", errors="replace")


def find_credential_leaks(root: Path = REPO, base: str | None = None) -> list[str]:
    """Every secret or operator-home path on a line `root`'s staged diff adds (with `base`, a line
    any commit in `base..HEAD` adds)."""
    text = _added_text(root, base)
    hits: list[str] = []
    current_file = "?"
    header = (
        False  # between a file's `diff --git` and its first hunk: an added line is not a header
    )
    for line in text.split("\n"):
        if line.startswith("diff --git "):
            current_file, header = "?", True
            continue
        if line.startswith("@@ "):
            header = False
            continue
        if header:
            if line.startswith("+++ ") and line != "+++ /dev/null":
                try:
                    current_file = _diff_path(line[len("+++ ") :])
                except ToolError as e:
                    raise DiffUnreadable(str(e)) from e
            continue
        if line.startswith("+"):
            hits.extend(_leaks(current_file, line[1:]))
    return hits


def _leaks(path: str, line: str) -> list[str]:
    return [
        f"{path}: {label}: {line.strip()[:120]}"
        for label, pat in SECRET_PATTERNS
        if pat.search(line)
    ]


def tree_leaks(root: Path = REPO, rev: str = "") -> list[str]:
    """Every secret or operator-home path on any line of any file `rev` tracks (the index when
    `rev` is empty), RAISING when git could not read it."""
    listed = subprocess.run(
        ["git", "ls-tree", "-r", "-z", "--name-only", rev] if rev else ["git", "ls-files", "-z"],
        cwd=root,
        capture_output=True,
    )
    if listed.returncode != 0:
        raise DiffUnreadable(f"git could not list the tracked files: exit {listed.returncode}")
    names = [n for n in listed.stdout.decode("utf-8", errors="replace").split("\0") if n]
    blobs = subprocess.run(
        ["git", "cat-file", "--batch"],
        cwd=root,
        input="".join(f"{rev}:{n}\n" for n in names).encode("utf-8"),
        capture_output=True,
    )
    if blobs.returncode != 0:
        raise DiffUnreadable(f"git could not read the tracked files: exit {blobs.returncode}")
    hits: list[str] = []
    out, at = blobs.stdout, 0
    for name in names:
        end = out.index(b"\n", at)
        head = out[at:end].split()
        if len(head) != 3:
            raise DiffUnreadable(f"git could not read {name}: {out[at:end]!r}")
        size = int(head[2])
        text = out[end + 1 : end + 1 + size].decode("utf-8", errors="replace")
        at = end + 1 + size + 1
        for line in text.split("\n"):
            hits.extend(_leaks(name, line))
    return hits


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Refuse secrets and operator-home paths a change adds")
    ap.add_argument("--base", help="read every commit of a pull request against this base (CI)")
    base = ap.parse_args(argv).base
    try:
        hits = tree_leaks(rev="HEAD" if base else "") + find_credential_leaks(base=base)
    except DiffUnreadable as e:
        # Fail CLOSED: "clean" for a diff nobody read is the one outcome a secrets gate must
        # never produce.
        print(
            "check_credential_leak: FAIL — the diff could not be read, so nothing was scanned:",
            file=sys.stderr,
        )
        print(f"  {e}", file=sys.stderr)
        print(
            "  This is NOT a clean result. Fix the repository state and run it again.",
            file=sys.stderr,
        )
        return 1
    rc = 0
    if hits:
        print("check_credential_leak: FAIL — secrets or private paths in the diff:")
        for h in hits[:40]:
            print(f"  {h}")
        if len(hits) > 40:
            print(f"  … and {len(hits) - 40} more")
        rc = 1
    else:
        print("check_credential_leak: PASS (every tracked file and the diff clean)")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
