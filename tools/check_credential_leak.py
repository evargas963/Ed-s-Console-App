#!/usr/bin/env python3
"""No credential or operator-home path is committed (AGENTS.md "Protect credentials"): the lines a
diff adds are scanned for Bearer tokens, JWTs, API keys, private keys, a Schwab token file's body,
a Schwab credential set with a value, and C:\\Users\\… or /home/… paths. The scanner's own suite
and this module are path-skipped (their payloads must live there). Other fixtures mark a line with
`# credential-leak-ok` or `# credential-leak-fixture-ok`.

    python tools/check_credential_leak.py                       # the staged diff (commit hook)
    python tools/check_credential_leak.py --base origin/main    # a pull request's diff (CI)
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
    # A Schwab token file's body (schwab_token.json): a token value of 32 or more token characters.
    # The placeholder of schwab_token.json.example ("<from OAuth — do not commit>") is not one.
    ("schwab_token_json", re.compile(
        r"[\"'](?:access_token|refresh_token|id_token)[\"']\s*:\s*[\"'][A-Za-z0-9._~+/@=-]{32,}[\"']")),
    # A Schwab credential set on its own line (.env, a .bat `set`, a shell `export`) with a value;
    # .env.example's empty, commented `# SCHWAB_API_KEY=` is not one.
    ("schwab_env_credential", re.compile(
        r"^\s*(?:export\s+|set\s+)?SCHWAB_(?:APP_SECRET|API_KEY)\s*=\s*[^\s#]", re.IGNORECASE)),
)


class StagedDiffUnreadable(RuntimeError):
    """The diff did not run. An unread diff is not an empty diff."""


def _staged_text(base: str | None = None) -> str:
    """The staged diff, or with `base` the pull request's diff (`base...HEAD`), RAISING when git
    could not produce it: an unread diff would scan clean."""
    p = subprocess.run(
        ["git", "diff", "--cached" if base is None else f"{base}...HEAD", "--unified=0", "--no-color"],
        cwd=REPO,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if p.returncode != 0:
        raise StagedDiffUnreadable(
            f"git diff {base or '--cached'} exited {p.returncode}: "
            f"{((p.stderr or '').strip().splitlines() or [''])[0]}"
        )
    return p.stdout or ""


def _norm_path(path: str) -> str:
    """The repository-relative spelling of `path`, a leading dot of a name (`.github/...`) kept."""
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    from tools.pretooluse_guard import normalize_repo_relative

    return normalize_repo_relative(path)


def find_credential_leaks(diff_text: str | None = None, base: str | None = None) -> list[str]:
    text = _staged_text(base) if diff_text is None else diff_text
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
    base = args[args.index("--base") + 1] if "--base" in args else None
    what = "staged diff" if base is None else f"diff {base}...HEAD"
    sys.stdout.reconfigure(encoding="utf-8")       # the messages and the lines found carry "—", "…"
    sys.stderr.reconfigure(encoding="utf-8")
    try:
        hits = find_credential_leaks(base=base)
    except StagedDiffUnreadable as e:
        print(f"check_credential_leak: FAIL — the {what} could not be read, so nothing "
              "was scanned:", file=sys.stderr)
        print(f"  {e}", file=sys.stderr)
        print("  This is NOT a clean result. Fix the repository state and commit again.",
              file=sys.stderr)
        return 1
    rc = 0
    if hits:
        print(f"check_credential_leak: FAIL — secrets or private paths in the {what}:")
        for h in hits[:40]:
            print(f"  {h}")
        if len(hits) > 40:
            print(f"  … and {len(hits) - 40} more")
        rc = 1
    else:
        print(f"check_credential_leak: PASS ({what} clean)")
    if "--and-private-paths" in args:
        # the private-path scan of tracked files runs in the same commit hook
        if str(REPO) not in sys.path:
            sys.path.insert(0, str(REPO))
        from tools.check_private_paths import main as private_paths_main
        rc = max(rc, private_paths_main())
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
