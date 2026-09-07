#!/usr/bin/env python3
"""Credential / secret leak firewall on staged (and optional) text diffs.

OBSERVED (2026-07-25): operator-home paths already partially gated for
scoreboard evidence, but staged source can still land Bearer tokens, API
keys, or C:\\Users\\… literals that neither private-path scope nor ruff catch.
VALIDATED: regex suite unit-tested; scans `git diff --cached` only (what a
commit would publish). The scanner's own suite and this module are path-skipped
(injected payloads must live there). Other fixtures mark a line with
`# credential-leak-ok` or `# credential-leak-fixture-ok`.

    python tools/check_credential_leak.py
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

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
)


class StagedDiffUnreadable(RuntimeError):
    """`git diff --cached` did not run. An unread diff is not an empty diff."""


def _staged_text() -> str:
    """The staged diff, RAISING when git could not produce it.

    RC-529 (ported from #219's row 506; re-measured 2026-09-06 on ac3f78fb). This returned
    `p.stdout or ""` and never read returncode, so any failure of the child — a broken or
    locked index, a corrupt object, git absent from PATH under a different launch context —
    yielded an empty diff. An empty diff scans clean, so this BLOCKING pre-commit secrets gate
    would print its success line and let the commit through without having read a single byte
    of what was being committed. "I could not look" is not "there is nothing".
    """
    p = subprocess.run(
        ["git", "diff", "--cached", "--unified=0", "--no-color"],
        cwd=REPO,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if p.returncode != 0:
        raise StagedDiffUnreadable(
            f"git diff --cached exited {p.returncode}: "
            f"{((p.stderr or '').strip().splitlines() or [''])[0]}"
        )
    return p.stdout or ""


def _norm_path(path: str) -> str:
    """The ONE repo-relative spelling (RC-527). `lstrip("./")` used to live here and ate the
    leading dot of `.github/...`, so a dot-prefixed skip entry could never match."""
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    from tools.pretooluse_guard import normalize_repo_relative

    return normalize_repo_relative(path)


def find_credential_leaks(diff_text: str | None = None) -> list[str]:
    text = _staged_text() if diff_text is None else diff_text
    hits: list[str] = []
    current_file = "?"
    skip_file = False
    for line in text.splitlines():
        if line.startswith("+++ b/"):
            current_file = _norm_path(line[6:].strip() or "?")
            skip_file = current_file in _SKIP_PATHS
            continue
        if skip_file:
            continue
        if not line.startswith("+") or line.startswith("+++"):
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
        # RC-529: fail CLOSED. Reporting "clean" for a diff nobody read is the one outcome a
        # secrets gate must never produce.
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
        # BEDROCK 2026-09-06: ONE secrets-and-paths hook at the commit seam. The tracked-
        # evidence private-path scan (tools/check_private_paths.py) keeps its own module and
        # suite; this flag runs it in the same hook so the seam has one owner.
        if str(REPO) not in sys.path:
            sys.path.insert(0, str(REPO))
        from tools.check_private_paths import main as private_paths_main
        rc = max(rc, private_paths_main())
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
